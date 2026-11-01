"""Exercise the saved-job browser with a temporary history and source files."""

import re
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import yaml
from docx import Document
import render_resume
import job_web
from job_tools import job_history
from job_tools import resume_web_tasks as tasks
from job_web import app

REAL_AVAILABLE_MODELS = job_web._available_models


class JobWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db_patch = patch.object(job_history, "HISTORY_DB_PATH", self.root / "history.sqlite3")
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.task_patch = patch.object(tasks, "TASK_ROOT", self.root / "requests")
        self.task_patch.start()
        self.addCleanup(self.task_patch.stop)
        self.model_patch = patch.object(job_web, "_available_models", return_value=(["qwen2.5:7b"], None))
        self.model_patch.start()
        self.addCleanup(self.model_patch.stop)
        self.client = app.test_client()

    def save_idealist(self, job_id, title, *, company="Acme", facts=True):
        url = f"https://www.idealist.org/en/nonprofit-job/{job_id}-{title.lower().replace(' ', '-')}"
        key = job_history.job_key(url)
        path = self.root / f"{job_id}.txt"
        path.write_text(f"NONPROFIT\nPublished 2 days ago\n{title}\n{company}\nFull posting body.", encoding="utf-8")
        job_history.record_processed(url, str(path))
        if facts:
            with job_history._database() as connection:
                connection.execute(
                    """INSERT INTO prospective_jobs
                       (job_key, job_title, company, remote_status, location, salary_range)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (key, title, company, "remote", "New York, NY", "$90,000–$110,000"),
                )
        return key

    def test_hide_job_preserves_history_and_artifacts(self):
        key = self.save_idealist("a" * 32, "Data Engineer", company="Hidden Company")
        other = self.save_idealist("b" * 32, "Research Analyst")
        listing = self.client.get("/")
        self.assertIn(b"data-hide-job", listing.data)
        token = job_web.confirmation_signer.dumps({"hide_job": key})
        route = f"/jobs/{key}/hide"
        self.assertEqual(self.client.get(route).status_code, 404)
        self.assertEqual(self.client.post(route).status_code, 400)
        wrong = job_web.confirmation_signer.dumps({"hide_job": other})
        self.assertEqual(self.client.post(route, data={"token": wrong}).status_code, 400)
        response = self.client.post(route, data={"token": token, "q": "Data", "page": "2"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("q=Data", response.location)
        self.assertIn("page=2", response.location)
        listing = self.client.get("/")
        self.assertNotIn(b"Data Engineer", listing.data)
        self.assertNotIn(b"Hidden Company", listing.data)
        self.assertIn(b"1 posting collected", listing.data)
        self.assertIn(b"Research Analyst", listing.data)
        url, detail_file = job_history.saved_job(key)
        self.assertTrue(Path(detail_file).is_file())
        self.assertTrue(job_history.is_processed(url))
        self.assertEqual(job_history.filter_unprocessed([{"link": url}]), [])
        self.assertEqual(self.client.get(f"/jobs/{key}").status_code, 200)
        self.assertEqual(self.client.post(route, data={"token": token}).status_code, 302)
        with job_history._database() as connection:
            self.assertIsNotNone(connection.execute(
                "SELECT hidden_at FROM processed_jobs WHERE job_key = ?", (key,)
            ).fetchone()[0])

    def test_existing_database_gets_visibility_column(self):
        import sqlite3
        with sqlite3.connect(job_history.HISTORY_DB_PATH) as connection:
            connection.execute("""CREATE TABLE processed_jobs (
                job_key TEXT PRIMARY KEY, url TEXT NOT NULL, detail_file TEXT NOT NULL,
                processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            connection.execute("INSERT INTO processed_jobs (job_key, url, detail_file) VALUES (?, ?, ?)",
                               ("old", "https://example.com/job", "old.txt"))
        with job_history._database() as connection:
            self.assertEqual(connection.execute(
                "SELECT job_key, hidden_at FROM processed_jobs"
            ).fetchone(), ("old", None))

    def test_empty_database_has_helpful_message(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No saved jobs yet", response.data)

    def test_all_saved_jobs_and_detail_even_without_optional_rows(self):
        first = self.save_idealist("a" * 32, "Data Engineer")
        second = self.save_idealist("b" * 32, "Research Analyst", facts=False)
        job_history.record_ai_result(
            "https://www.idealist.org/en/nonprofit-job/" + "a" * 32 + "-data-engineer",
            "Data Engineer", "local", "summarized", "Strong SQL role.",
        )

        listing = self.client.get("/")
        self.assertEqual(listing.status_code, 200)
        self.assertIn(b"Data Engineer", listing.data)
        self.assertIn(b"Research Analyst", listing.data)
        self.assertIn(b"2 postings collected", listing.data)

        detail = self.client.get(f"/jobs/{first}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"Full posting body.", detail.data)
        self.assertIn(b"Strong SQL role.", detail.data)
        self.assertIn(b"Original listing", detail.data)

        missing_facts = self.client.get(f"/jobs/{second}")
        self.assertEqual(missing_facts.status_code, 200)
        self.assertIn(b"Research Analyst", missing_facts.data)
        self.assertIn(b"Full posting body.", missing_facts.data)

    def test_search_filters_pagination_and_return_to_results(self):
        first = self.save_idealist("a" * 32, "Data Engineer", company="Northstar")
        self.save_idealist("b" * 32, "Research Analyst", company="Southstar", facts=False)
        for number in range(25):
            self.save_idealist(f"{number:032x}", f"Role {number}")

        page_two = self.client.get("/?page=2")
        self.assertEqual(page_two.status_code, 200)
        self.assertIn(b"Page 2 of 2", page_two.data)
        self.assertEqual(page_two.data.count(b'<tr data-href='), 2)

        filtered = self.client.get("/?q=northstar&source=Idealist&remote=remote")
        self.assertIn(b"Data Engineer", filtered.data)
        self.assertNotIn(b"Research Analyst", filtered.data)
        self.assertIn(b"1 result", filtered.data)

        detail = self.client.get(f"/jobs/{first}?q=northstar&source=Idealist&remote=remote&page=2")
        self.assertIn(b"q=northstar", detail.data)
        self.assertIn(b"page=2", detail.data)
        self.assertEqual(self.client.get("/jobs/unknown").status_code, 404)

    def test_sort_headers_order_dates_across_pages_and_keep_context(self):
        keys = []
        for number in range(27):
            key = self.save_idealist(f"{number:032x}", f"Role {number:02d}")
            keys.append(key)
            with job_history._database() as connection:
                connection.execute(
                    "UPDATE prospective_jobs SET posted_at = ? WHERE job_key = ?",
                    (f"2026-10-{number + 1:02d}T12:00:00Z", key),
                )
        with job_history._database() as connection:
            connection.execute("UPDATE prospective_jobs SET posted_at = NULL WHERE job_key = ?", (keys[0],))

        newest = self.client.get("/?sort=posted&order=desc")
        self.assertEqual(newest.status_code, 200)
        self.assertIn(b'aria-sort="descending"', newest.data)
        self.assertLess(newest.data.index(b"Role 26"), newest.data.index(b"Role 25"))
        self.assertNotIn(b"Role 00", newest.data)
        self.assertIn(b"sort=posted&amp;order=asc", newest.data)

        oldest = self.client.get("/?sort=posted&order=asc&page=2")
        self.assertIn(b"Role 00", oldest.data)  # Unknown dates remain last.
        self.assertIn(b"Role 26", oldest.data)
        self.assertIn(b"sort=posted&amp;order=asc", oldest.data)

        filtered = self.client.get("/?q=Role+02&sort=posted&order=asc")
        self.assertIn(b"Role 02", filtered.data)
        self.assertIn(b'name="sort" value="posted"', filtered.data)
        detail = self.client.get(f"/jobs/{keys[2]}?sort=posted&order=asc")
        self.assertIn(b"sort=posted", detail.data)
        self.assertIn(b'name="order" value="asc"', detail.data)

        by_title = self.client.get("/?sort=title&order=desc")
        self.assertLess(by_title.data.index(b"Role 26"), by_title.data.index(b"Role 25"))

    def test_posting_text_is_escaped(self):
        key = self.save_idealist("c" * 32, "Security Engineer")
        path = self.root / f"{'c' * 32}.txt"
        path.write_text("Published 1 day ago\nSecurity Engineer\n<script>alert(1)</script>", encoding="utf-8")
        response = self.client.get(f"/jobs/{key}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"&lt;script&gt;alert(1)&lt;/script&gt;", response.data)
        self.assertNotIn(b"<script>alert(1)</script>", response.data)

    def test_model_choice_requires_confirmation_and_starts_once(self):
        key = self.save_idealist("d" * 32, "Data Engineer")
        detail = self.client.get(f"/jobs/{key}")
        self.assertIn(b"Select a model", detail.data)
        self.assertIn(b"qwen2.5:7b", detail.data)

        invalid = self.client.post(f"/jobs/{key}/resume/confirm", data={"model": "not-installed"})
        self.assertEqual(invalid.status_code, 400)
        self.assertFalse(tasks.TASK_ROOT.exists())

        confirm = self.client.post(
            f"/jobs/{key}/resume/confirm", data={"model": "qwen2.5:7b", "q": "data"}
        )
        self.assertEqual(confirm.status_code, 200)
        self.assertIn(b"Confirm and start", confirm.data)
        self.assertFalse(tasks.TASK_ROOT.exists())
        token = re.search(rb'name="token" value="([^"]+)"', confirm.data).group(1).decode()

        with patch.object(job_web.subprocess, "Popen") as launch:
            started = self.client.post("/resume/start", data={"token": token})
            repeated = self.client.post("/resume/start", data={"token": token})
        self.assertEqual(started.status_code, 302)
        self.assertEqual(repeated.status_code, 302)
        launch.assert_called_once()
        task_id = started.location.rsplit("/", 1)[-1]
        status = tasks.read_status(tasks.TASK_ROOT / task_id)
        self.assertEqual(status["job_id"], key)
        self.assertEqual(status["model"], "qwen2.5:7b")
        self.assertEqual(status["state"], "queued")
        self.assertEqual(status["rewrite_mode"], "none")
        self.assertIn(b"Selection queued", self.client.get(started.location).data)
        self.assertIn(b"Recent selection attempts", self.client.get(f"/jobs/{key}").data)
        status.update(
            state="failed", message="A custom resume could not be made because the selection did not pass validation.",
            errors=["summary has too few words"],
        )
        tasks.write_status(tasks.TASK_ROOT / task_id, status)
        failed_page = self.client.get(started.location)
        self.assertIn(b"Custom resume could not be made", failed_page.data)
        self.assertIn(b"summary has too few words", failed_page.data)

    def test_bullet_modes(self):
        key = self.save_idealist("f" * 32, "Engineer")
        self.assertIn(b'<option value="none" selected>', self.client.get(f"/jobs/{key}").data)
        for mode in ("none", "light", "targeted"):
            confirm = self.client.post(f"/jobs/{key}/resume/confirm", data={
                "model": "qwen2.5:7b", "rewrite_mode": mode,
            })
            self.assertEqual(confirm.status_code, 200)
            token = re.search(rb'name="token" value="([^"]+)"', confirm.data).group(1).decode()
            with patch.object(job_web.subprocess, "Popen"):
                started = self.client.post("/resume/start", data={"token": token})
            task_id = started.location.rsplit("/", 1)[-1]
            self.assertEqual(tasks.read_status(tasks.TASK_ROOT / task_id)["rewrite_mode"], mode)
        self.assertEqual(self.client.post(f"/jobs/{key}/resume/confirm", data={
            "model": "qwen2.5:7b", "rewrite_mode": "invalid",
        }).status_code, 400)

    def test_render_download_and_validation_gate(self):
        from test_resume_selection import INVENTORY, SELECTION

        key = self.save_idealist("e" * 32, "Engineer")
        task_id = str(uuid4())
        task_dir = tasks.TASK_ROOT / task_id
        task_dir.mkdir(parents=True)
        (task_dir / "inventory.yaml").write_text(yaml.safe_dump(INVENTORY), encoding="utf-8")
        selection = task_dir / "selection.json"
        selection.write_text(json.dumps(SELECTION), encoding="utf-8")
        status = dict(task_id=task_id, job_id=key, model="qwen2.5:7b",
                      detail_url=f"/jobs/{key}", state="ready_for_review",
                      created_at=tasks.now_utc(), run_dir=str(task_dir),
                      selection_file=str(selection))
        tasks.write_status(task_dir, status)
        listing = self.client.get("/")
        self.assertIn(b"Resume Generated", listing.data)
        self.assertNotIn(b'aria-label="Resume generated"', listing.data)
        self.assertIn(b"Generate resume", self.client.get(f"/jobs/{key}").data)
        self.assertIn(b"Generate resume", self.client.get(f"/resume/{task_id}").data)
        token = job_web.confirmation_signer.dumps({"render_job": key})
        route = f"/resume/{task_id}/render"
        self.assertEqual(self.client.post(route).status_code, 400)
        with patch.object(render_resume, "__file__", str(self.root / "render_resume.py")):
            response = self.client.post(route, data={"token": token})
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment;", response.headers["Content-Disposition"])
            filename = re.search(r'filename=([^;]+)', response.headers["Content-Disposition"]).group(1).strip('"')
            self.assertRegex(filename, rf"^resume-\d{{8}}T\d{{12}}Z-{task_id}-[0-9a-f]{{32}}\.docx$")
            self.assertTrue((self.root / "generated_resumes" / filename).is_file())
            saved_status = tasks.read_status(task_dir)
            self.assertTrue(saved_status["resume_generated_at"])
            self.assertEqual(saved_status["resume_file"], str(self.root / "generated_resumes" / filename))
            self.assertIn(b'aria-label="Resume generated"', self.client.get("/").data)
            # Older renders have no status marker, but their filenames identify the request.
            with patch.object(tasks, "PROJECT_DIR", self.root):
                tasks.write_status(task_dir, status)
                self.assertIn(b'aria-label="Resume generated"', self.client.get("/").data)
                old_filename = self.root / "generated_resumes" / f"resume-{task_id}-{'a' * 32}.docx"
                (self.root / "generated_resumes" / filename).rename(old_filename)
                self.assertIn(b'aria-label="Resume generated"', self.client.get("/").data)
            document = Document(io.BytesIO(response.data))
            self.assertIn("Example Person", [p.text for p in document.paragraphs])
            response.close()
            selection.write_text("{}", encoding="utf-8")
            self.assertEqual(self.client.post(route, data={"token": token}).status_code, 422)
            selection.unlink()
            self.assertEqual(self.client.post(route, data={"token": token}).status_code, 422)
        status["state"] = "failed"
        tasks.write_status(task_dir, status)
        self.assertNotIn(b"Generate resume", self.client.get(f"/jobs/{key}").data)
        self.assertEqual(self.client.post(route, data={"token": token}).status_code, 409)
        self.assertEqual(self.client.post("/resume/invalid/render").status_code, 404)

    def test_installed_model_list_excludes_embedding_only_models(self):
        tags = Mock()
        tags.json.return_value = {"models": [{"name": "qwen2.5:7b"}, {"name": "nomic-embed-text:latest"}]}
        completion = Mock()
        completion.json.return_value = {"capabilities": ["completion"]}
        embedding = Mock()
        embedding.json.return_value = {"capabilities": ["embedding"]}
        with patch.object(job_web.requests, "get", return_value=tags), patch.object(
            job_web.requests, "post", side_effect=[completion, embedding]
        ):
            models, error = REAL_AVAILABLE_MODELS()
        self.assertIsNone(error)
        self.assertEqual(models, ["qwen2.5:7b"])

    def test_cancel_stops_the_matching_worker(self):
        task_id = str(uuid4())
        task_dir = tasks.TASK_ROOT / task_id
        task_dir.mkdir(parents=True)
        tasks.write_status(task_dir, {
            "task_id": task_id, "job_id": "greenhouse:123", "model": "qwen2.5:7b",
            "detail_url": "/", "state": "running", "created_at": tasks.now_utc(), "pid": 12345,
            "stage": "Generating selection — attempt 1 of up to 2",
            "stage_started_at": tasks.now_utc(),
        })
        running_page = self.client.get(f"/resume/{task_id}")
        self.assertIn(b"Current stage", running_page.data)
        self.assertIn(b"Generating selection", running_page.data)
        self.assertIn(b"Elapsed:", running_page.data)
        token = job_web.confirmation_signer.dumps({"cancel": task_id})
        process = Mock(returncode=0, stdout=f"python resume_web_worker.py {task_dir}")
        with patch.object(job_web.subprocess, "run", return_value=process), patch.object(job_web.os, "kill") as kill:
            response = self.client.post(f"/resume/{task_id}/cancel", data={"token": token})
        self.assertEqual(response.status_code, 302)
        kill.assert_called_once()
        self.assertEqual(tasks.read_status(task_dir)["state"], "canceled")
        self.assertIn(b"Selection canceled", self.client.get(f"/resume/{task_id}").data)


if __name__ == "__main__":
    unittest.main()
