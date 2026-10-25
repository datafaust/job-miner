import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_tools import job_history, prospects
from job_tools.lever import fetch_lever_jobs, lever_candidates, load_lever_boards, save_lever_job


def posting(id, location="New York, NY", workplace="on-site", title="Data Analyst"):
    return {
        "id": id, "text": title,
        "categories": {"location": location, "team": "Data"},
        "descriptionPlain": "Analyze data and build dashboards.",
        "hostedUrl": f"https://jobs.lever.co/palantir/{id}",
        "applyUrl": f"https://jobs.lever.co/palantir/{id}/apply",
        "workplaceType": workplace, "createdAt": 1720000000000,
        "salaryRange": {"min": 90000, "max": 120000, "currency": "USD", "interval": "year"},
    }


class LeverTests(unittest.TestCase):
    def test_board_config_and_endpoint(self):
        self.assertEqual(load_lever_boards(), [{"company": "Palantir", "site": "palantir"}])
        with patch("job_tools.lever.requests.get") as get:
            get.return_value.json.return_value = [posting("123")]
            self.assertEqual(len(fetch_lever_jobs("acme", eu=True)), 1)
        self.assertEqual(get.call_args.args[0], "https://api.eu.lever.co/v0/postings/acme")
        self.assertEqual(get.call_args.kwargs["params"], {"mode": "json"})

    def test_location_ranking_and_history(self):
        jobs = [posting("nyc"), posting("remote-us", "United States", "remote"),
                posting("remote-india", "India", "remote"),
                posting("multi", "Multiple Locations", "on-site")]
        jobs[-1]["categories"]["allLocations"] = ["London, UK", "New York, NY"]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(job_history, "HISTORY_DB_PATH", Path(directory) / "history.sqlite3"):
                self.assertEqual([c["job"]["id"] for c in lever_candidates(jobs, "data analyst", "Palantir", "nyc")], ["nyc", "multi"])
                self.assertEqual([c["job"]["id"] for c in lever_candidates(jobs, "data analyst", "Palantir", "remote")], ["remote-us"])
                job_history.record_processed(jobs[0]["hostedUrl"], "saved.json")
                self.assertEqual([c["job"]["id"] for c in lever_candidates(jobs, "data analyst", "Palantir", "nyc")], ["multi"])
        self.assertEqual(job_history.job_key(jobs[0]["hostedUrl"]),
                         job_history.job_key(jobs[0]["applyUrl"]))

    def test_save_and_extract(self):
        job = posting("abc123")
        job["lists"] = [{"text": "Requirements", "content": "<ul><li>SQL</li></ul>"}]
        job["additionalPlain"] = "Equal opportunity employer."
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with patch.object(job_history, "HISTORY_DB_PATH", Path(directory) / "history.sqlite3"):
                    text = save_lever_job(job, "palantir", "Palantir")
                    self.assertIn("Analyze data", text)
                    self.assertIn("Requirements", text)
                    self.assertIn("SQL", text)
                    self.assertIn("Equal opportunity employer", text)
                    path = Path("jobs/JOB_lever_palantir_abc123.json")
                    self.assertEqual(json.loads(path.read_text())["id"], "abc123")
                    prospect = prospects.list_prospects()[0]
                    self.assertEqual(prospect["company"], "Palantir")
                    self.assertEqual(prospect["salary_range"], "USD 90,000 - 120,000 / year")
                    self.assertEqual(prospect["source"], "Lever")
                    with self.assertRaisesRegex(ValueError, "already processed"):
                        save_lever_job(job, "palantir", "Palantir")
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
