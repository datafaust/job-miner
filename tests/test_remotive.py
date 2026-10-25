import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from job_tools import job_history, prospects
from job_tools.remotive import fetch_remotive_jobs, remotive_candidates, save_remotive_job


JOB = {
    "id": 123, "title": "Python Engineer", "company_name": "Example",
    "url": "https://remotive.com/remote-jobs/software-dev/python-engineer-123",
    "description": "<p>Build Python services.</p>",
    "category": "Software Development", "candidate_required_location": "USA",
    "salary": "$100,000 - $120,000", "publication_date": "2026-10-20T00:00:00",
}


class RemotiveTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        db_patch = patch.object(job_history, "HISTORY_DB_PATH", self.directory / "history.sqlite3")
        db_patch.start()
        self.addCleanup(db_patch.stop)

    def test_fetch_caches_feed_and_passes_parameters(self):
        with patch("job_tools.remotive.requests.get") as get, patch("job_tools.remotive.time.time", return_value=100000):
            get.return_value.json.return_value = {"job-count": 2, "jobs": [JOB, {"bad": "record"}]}
            self.assertEqual(fetch_remotive_jobs(search="python", category="software-dev", limit=50), [JOB])
            self.assertEqual(fetch_remotive_jobs(search="python", category="software-dev", limit=50), [JOB])
        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs["params"], {"search": "python", "category": "software-dev", "limit": 50})
        with job_history._database() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM remotive_api_calls").fetchone()[0], 1)

    def test_failed_attempt_is_throttled_and_keeps_old_cache(self):
        with patch("job_tools.remotive.requests.get") as get, patch("job_tools.remotive.time.time") as now:
            get.return_value.json.return_value = {"jobs": [JOB]}
            now.return_value = 100000
            fetch_remotive_jobs()
            get.side_effect = requests.Timeout("network")
            now.return_value = 100000 + 6 * 3600
            self.assertEqual(fetch_remotive_jobs(), [JOB])
            now.return_value += 1
            self.assertEqual(fetch_remotive_jobs(), [JOB])
        self.assertEqual(get.call_count, 2)

    def test_global_gate_limits_requests_per_day(self):
        with patch("job_tools.remotive.requests.get") as get, patch("job_tools.remotive.time.time") as now:
            get.return_value.json.return_value = {"jobs": [JOB]}
            for index in range(4):
                now.return_value = 100000 + 32 * index
                fetch_remotive_jobs(search=f"term{index}")
            now.return_value += 32
            self.assertEqual(fetch_remotive_jobs(search="fifth"), [])
        self.assertEqual(get.call_count, 4)

    def test_local_match_history_and_attribution(self):
        jobs = [JOB, {**JOB, "id": 124, "title": "Accountant", "description": "Manage accounts.",
                      "url": "https://remotive.com/remote-jobs/finance/accountant-124"}]
        self.assertEqual([item["job"]["id"] for item in remotive_candidates(jobs, "python")], [123])
        old = Path.cwd()
        try:
            os.chdir(self.directory)
            text = save_remotive_job(JOB)
            self.assertIn("Source: Remotive", text)
            self.assertIn(JOB["url"], text)
            self.assertEqual(json.loads(Path("jobs/JOB_remotive_123.json").read_text()), JOB)
            facts = prospects.list_prospects()[0]
            self.assertEqual(facts["remote_status"], "remote")
            self.assertEqual(facts["salary_range"], JOB["salary"])
            self.assertEqual(facts["location"], "USA")
            self.assertEqual(facts["source"], "Remotive")
            self.assertEqual(remotive_candidates(jobs, "python"), [])
        finally:
            os.chdir(old)


if __name__ == "__main__":
    unittest.main()
