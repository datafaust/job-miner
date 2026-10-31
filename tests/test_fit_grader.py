"""Exercise fit grading without requiring a live Ollama model."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fit_grader
from job_tools import job_history
from job_web import app


class FitGraderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        database_patch = patch.object(job_history, "HISTORY_DB_PATH", self.root / "history.sqlite3")
        database_patch.start()
        self.addCleanup(database_patch.stop)
        self.client = app.test_client()

    def save(self, name):
        url = f"https://example.org/jobs/{name}"
        path = self.root / f"{name}.txt"
        path.write_text(f"{name}\nBuild scalable data platforms with Python.", encoding="utf-8")
        job_history.record_processed(url, str(path))
        return job_history.job_key(url), path

    @staticmethod
    def model_grade(source_id="BAO-001"):
        return {"score": 82, "summary": "Strong platform engineering experience.",
                "requirements": [
                    {"requirement": "Scalable data platforms", "status": "match",
                     "evidence_ids": [source_id], "reason": "Built a scalable analytics platform."},
                    {"requirement": "Python", "status": "gap", "evidence_ids": [],
                     "reason": "The cited accomplishment does not prove this requirement."},
                ]}

    def test_single_job_persists_evidence_and_skips_unchanged_inputs(self):
        key, path = self.save("platform-engineer")
        with patch.object(fit_grader, "request_grade", side_effect=lambda *args: self.model_grade()) as model:
            self.assertEqual(fit_grader.main(["--job", key, "--model", "local-model"]), 0)
            self.assertEqual(fit_grader.main(["--job", key, "--model", "local-model"]), 0)
            self.assertEqual(model.call_count, 1)
            path.write_text("Platform engineer\nBuild Python APIs and pipelines.", encoding="utf-8")
            self.assertEqual(fit_grader.main(["--job", key, "--model", "local-model"]), 0)
            self.assertEqual(model.call_count, 2)
            self.assertEqual(fit_grader.main(["--job", key, "--model", "local-model", "--force"]), 0)
            self.assertEqual(model.call_count, 3)
        with job_history._database() as connection:
            self.assertEqual(connection.execute(
                "SELECT score, tier, model FROM job_fit_grades WHERE job_key = ?", (key,)
            ).fetchone(), (82, "strong", "local-model"))
        listing = self.client.get("/?sort=fit")
        self.assertIn(b"Strong", listing.data)
        self.assertIn(b"82", listing.data)
        detail = self.client.get(f"/jobs/{key}")
        self.assertIn(b"BAO-001", detail.data)
        self.assertIn(b"Built a scalable analytics platform", detail.data)

    def test_all_skips_hidden_and_invalid_citation_does_not_replace_grade(self):
        visible, _ = self.save("visible")
        hidden, _ = self.save("hidden")
        with job_history._database() as connection:
            connection.execute("UPDATE processed_jobs SET hidden_at = CURRENT_TIMESTAMP WHERE job_key = ?", (hidden,))
        with patch.object(fit_grader, "request_grade", return_value=self.model_grade()) as model:
            self.assertEqual(fit_grader.main(["--all", "--model", "local-model"]), 0)
            model.assert_called_once()
        with patch.object(fit_grader, "request_grade", return_value=self.model_grade("MADE-UP")):
            self.assertEqual(fit_grader.main(["--job", visible, "--model", "another-model"]), 1)
        with job_history._database() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM job_fit_grades").fetchone()[0], 1)
            self.assertEqual(connection.execute(
                "SELECT model FROM job_fit_grades WHERE job_key = ?", (visible,)
            ).fetchone()[0], "local-model")

    def test_model_schema_only_allows_inventory_ids(self):
        schema = fit_grader.grade_schema({"BAO-001": "Built a platform"})
        allowed = schema["properties"]["requirements"]["items"]["properties"]["evidence_ids"]["items"]["enum"]
        self.assertEqual(allowed, ["BAO-001"])

    def test_full_match_requires_named_tool_in_cited_evidence(self):
        grade = self.model_grade()
        grade["requirements"][0]["requirement"] = "Use SQL and BigQuery"
        grade = fit_grader.validate_grade(grade, {"BAO-001": "Built SQL pipelines"})
        fit_grader.check_named_tools(grade, {"BAO-001": "Built SQL pipelines"})
        self.assertEqual(grade["requirements"][0]["status"], "partial")
        self.assertIn("BigQuery", grade["requirements"][0]["reason"])

    def test_fit_sort_puts_highest_score_first_and_ungraded_last(self):
        high, _ = self.save("high-fit")
        low, _ = self.save("low-fit")
        self.save("ungraded")
        inventory_bytes = fit_grader.INVENTORY_PATH.read_bytes()
        inventory = fit_grader.yaml.safe_load(inventory_bytes)
        evidence = fit_grader.inventory_evidence(inventory)
        inventory_hash = hashlib.sha256(inventory_bytes).hexdigest()
        with patch.object(fit_grader, "request_grade", side_effect=lambda *args: self.model_grade()):
            fit_grader.grade_job(high, model="model", inventory=inventory,
                                 inventory_hash=inventory_hash, evidence=evidence)
        low_grade = self.model_grade()
        low_grade["score"] = 32
        with patch.object(fit_grader, "request_grade", return_value=low_grade):
            fit_grader.grade_job(low, model="model", inventory=inventory,
                                 inventory_hash=inventory_hash, evidence=evidence)
        page = self.client.get("/?sort=fit")
        self.assertEqual(page.status_code, 200)
        self.assertLess(page.data.index(b"high-fit"), page.data.index(b"low-fit"))
        self.assertLess(page.data.index(b"low-fit"), page.data.index(b"ungraded"))
        default_page = self.client.get("/")
        self.assertLess(default_page.data.index(b"high-fit"), default_page.data.index(b"low-fit"))


if __name__ == "__main__":
    unittest.main()
