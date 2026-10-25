import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import requests

from job_tools import job_history, prospects
from job_tools.remoteok import fetch_remoteok_jobs, remoteok_candidates, save_remoteok_job


JOB = {
    "id": "123", "position": "Python Engineer", "company": "Example",
    "url": "https://remoteok.com/remote-jobs/123-python-engineer-example",
    "description": "<p>Build Python services.</p>", "tags": ["python"],
    "salary_min": 80000, "salary_max": 120000, "date": "2026-10-20T00:00:00+00:00",
}


class RemoteOKTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        db_patch = patch.object(job_history, "HISTORY_DB_PATH", self.directory / "history.sqlite3")
        db_patch.start()
        self.addCleanup(db_patch.stop)

    def test_fetch_caches_full_feed_and_records_one_call(self):
        with patch("job_tools.remoteok.requests.get") as get, patch("job_tools.remoteok.time.time", return_value=10000):
            get.return_value.json.return_value = [{"legal": "terms"}, JOB]
            self.assertEqual(fetch_remoteok_jobs(), [JOB])
            self.assertEqual(fetch_remoteok_jobs(), [JOB])
        get.assert_called_once()
        self.assertEqual(get.call_args.args[0], "https://remoteok.com/api")
        with job_history._database() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM remoteok_api_calls").fetchone()[0], 1)

    def test_failed_attempt_starts_cooldown_and_does_not_retry(self):
        with patch("job_tools.remoteok.requests.get", side_effect=requests.Timeout("network")):
            self.assertEqual(fetch_remoteok_jobs(), [])
        with patch("job_tools.remoteok.requests.get") as get:
            self.assertEqual(fetch_remoteok_jobs(), [])
            get.assert_not_called()

    def test_refreshes_after_ninety_minutes(self):
        with patch("job_tools.remoteok.requests.get") as get, patch("job_tools.remoteok.time.time") as now:
            get.return_value.json.return_value = [JOB]
            now.return_value = 10000
            fetch_remoteok_jobs()
            now.return_value = 10000 + 90 * 60 - 1
            fetch_remoteok_jobs()
            now.return_value = 10000 + 90 * 60
            fetch_remoteok_jobs()
        self.assertEqual(get.call_count, 2)

    def test_local_filter_salary_history_and_saved_attribution(self):
        jobs = [JOB, {**JOB, "id": "124", "position": "Accountant", "description": "<p>Manage accounts.</p>", "tags": [], "url": "https://remoteok.com/remote-jobs/124-accountant"}]
        self.assertEqual([item["job"]["id"] for item in remoteok_candidates(jobs, "python", 100000)], ["123"])
        old = Path.cwd()
        try:
            os.chdir(self.directory)
            text = save_remoteok_job(JOB)
            self.assertIn("Source: Remote OK", text)
            self.assertIn(JOB["url"], text)
            self.assertEqual(json.loads(Path("jobs/JOB_remoteok_123.json").read_text()), JOB)
            self.assertEqual(prospects.list_prospects()[0]["remote_status"], "remote")
            self.assertEqual(remoteok_candidates(jobs, "python"), [])
        finally:
            os.chdir(old)


if __name__ == "__main__":
    unittest.main()
