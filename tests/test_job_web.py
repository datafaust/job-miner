"""Exercise the saved-job browser with a temporary history and source files."""

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

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
