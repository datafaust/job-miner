import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_tools import job_history, prospects
from job_tools.ashby import ashby_candidates, fetch_ashby_jobs, load_ashby_boards, save_ashby_job
from job_tools.resume_inputs import load_posting


def posting(identifier, location="Remote (US)", workplace="Remote"):
    return {
        "id": identifier, "title": "Data Analyst", "location": location,
        "workplaceType": workplace, "isRemote": workplace in {"Remote", "Hybrid"},
        "isListed": True, "descriptionPlain": "Analyze data with SQL.",
        "jobUrl": f"https://jobs.ashbyhq.com/ramp/{identifier}",
        "applyUrl": f"https://jobs.ashbyhq.com/ramp/{identifier}/application",
        "publishedAt": "2026-10-26T00:00:00Z",
        "compensation": {"scrapeableCompensationSalarySummary": "$90K - $120K"},
    }


class AshbyTests(unittest.TestCase):
    def test_fetch_and_config(self):
        self.assertEqual(load_ashby_boards()[0], {"company": "Ramp", "board": "ramp"})
        with patch("job_tools.ashby.requests.get") as get:
            get.return_value.json.return_value = {"jobs": [posting("a" * 36)]}
            self.assertEqual(len(fetch_ashby_jobs("ramp")), 1)
        self.assertEqual(get.call_args.args[0], "https://api.ashbyhq.com/posting-api/job-board/ramp")
        self.assertEqual(get.call_args.kwargs["params"], {"includeCompensation": "true"})
        with self.assertRaisesRegex(ValueError, "non-list"):
            with patch("job_tools.ashby.requests.get") as get:
                get.return_value.json.return_value = {"jobs": {}}
                fetch_ashby_jobs("ramp")

    def test_location_listed_and_history(self):
        ids = ["1" * 36, "2" * 36, "3" * 36, "4" * 36]
        remote_us = posting(ids[0])
        hybrid = posting(ids[1], "New York, New York", "Hybrid")
        hybrid["secondaryLocations"] = [{"location": "San Francisco", "address": {}}]
        nyc_secondary = posting(ids[2], "San Francisco, CA", "OnSite")
        nyc_secondary["secondaryLocations"] = [{"location": "New York, New York", "address": {
            "postalAddress": {"addressLocality": "New York", "addressRegion": "New York", "addressCountry": "United States"}}}]
        hidden = posting(ids[3])
        hidden["isListed"] = False
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(job_history, "HISTORY_DB_PATH", Path(directory) / "history.sqlite3"):
                self.assertEqual([c["job"] for c in ashby_candidates(
                    [remote_us, hybrid, nyc_secondary, hidden], "data analyst", "Ramp", "remote")], [remote_us])
                self.assertEqual([c["job"] for c in ashby_candidates(
                    [remote_us, hybrid, nyc_secondary, hidden], "data analyst", "Ramp", "nyc")], [hybrid, nyc_secondary])
                job_history.record_processed(remote_us["jobUrl"], "saved.json")
                self.assertEqual(ashby_candidates([remote_us], "data analyst", "Ramp", "remote"), [])
        self.assertEqual(job_history.job_key(remote_us["jobUrl"]), job_history.job_key(remote_us["applyUrl"]))

    def test_save_prospect_and_resume_input(self):
        job = posting("a" * 36)
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with patch.object(job_history, "HISTORY_DB_PATH", Path(directory) / "history.sqlite3"):
                    text = save_ashby_job(job, "ramp", "Ramp")
                    self.assertIn("Analyze data with SQL", text)
                    path = Path("jobs/JOB_ashby_ramp_" + "a" * 36 + ".json")
                    saved = json.loads(path.read_text())
                    self.assertEqual(saved["_job_watcher_company"], "Ramp")
                    fact = prospects.list_prospects()[0]
                    self.assertEqual((fact["source"], fact["remote_status"], fact["salary_range"]),
                                     ("Ashby", "remote", "$90K - $120K"))
                    resume = load_posting(path)
                    self.assertEqual(resume["source"], "ashby")
                    self.assertIn("Analyze data with SQL", resume["posting_text"])
                    with self.assertRaisesRegex(ValueError, "already processed"):
                        save_ashby_job(job, "ramp", "Ramp")
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
