import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from job_tools import job_history, prospects
from job_tools.adzuna import adzuna_candidates, fetch_adzuna_jobs, save_adzuna_job


def listing(job_id="123", location="New York, NY", description="Analyze data and build dashboards."):
    return {
        "id": job_id,
        "title": "Data Analyst",
        "description": description,
        "redirect_url": f"https://www.adzuna.com/details/{job_id}?utm_source=search",
        "company": {"display_name": "Example"},
        "location": {"display_name": location, "area": ["US", "New York"]},
        "salary_min": 70000,
        "salary_max": 90000,
        "salary_is_predicted": True,
        "created": "2026-10-25T12:00:00Z",
    }


class AdzunaTests(unittest.TestCase):
    def test_fetch_uses_us_endpoint_and_search_location(self):
        response = Mock()
        response.json.return_value = {"results": [listing()]}
        with patch("job_tools.adzuna.requests.get", return_value=response) as get:
            self.assertEqual(fetch_adzuna_jobs("data analyst", "nyc", app_id="id", app_key="key"), [listing()])
            args, kwargs = get.call_args
            self.assertEqual(args[0], "https://api.adzuna.com/v1/api/jobs/us/search/1")
            self.assertEqual(kwargs["params"]["where"], "New York, NY")
            self.assertEqual(kwargs["params"]["results_per_page"], 50)
            self.assertEqual(kwargs["params"]["app_key"], "key")
            self.assertEqual(kwargs["timeout"], 30)
            response.raise_for_status.assert_called_once()
        with patch("job_tools.adzuna.requests.get", return_value=response) as get:
            fetch_adzuna_jobs("data analyst", "remote", app_id="id", app_key="key")
            self.assertEqual(get.call_args.kwargs["params"]["what_or"], "remote hybrid")
            self.assertNotIn("where", get.call_args.kwargs["params"])

    def test_missing_credentials_and_invalid_response(self):
        with patch.dict(os.environ, {"ADZUNA_APP_ID": "", "ADZUNA_APP_KEY": ""}), \
             self.assertRaisesRegex(ValueError, "ADZUNA_APP_ID"):
            fetch_adzuna_jobs("data analyst", "nyc")
        response = Mock()
        response.json.return_value = {"results": {}}
        with patch("job_tools.adzuna.requests.get", return_value=response), \
             self.assertRaisesRegex(ValueError, "non-list"):
            fetch_adzuna_jobs("data analyst", "nyc", app_id="id", app_key="key")

    def test_candidates_filter_location_and_processed_jobs(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(job_history, "HISTORY_DB_PATH", Path(directory) / "history.sqlite3"):
            nyc, other = listing(), listing("456", "Boston, MA")
            self.assertEqual([x["job"] for x in adzuna_candidates([nyc, other], "data analyst", "nyc")], [nyc])
            job_history.record_processed(nyc["redirect_url"], "saved.json")
            self.assertEqual(adzuna_candidates([nyc], "data analyst", "nyc"), [])
            remote = listing("789", "United States", "Remote data analysis and dashboards.")
            self.assertEqual([x["job"] for x in adzuna_candidates([remote, other], "data analyst", "remote")], [remote])

    def test_adzuna_http_redirect_and_stable_id(self):
        first = "http://www.adzuna.com/jobs/land/ad/123?v=abc"
        second = "https://www.adzuna.com/details/123?utm_source=api"
        self.assertEqual(job_history.job_key(first), "adzuna:123")
        self.assertEqual(job_history.job_key(first), job_history.job_key(second))
        self.assertEqual(job_history.job_source(job_history.job_key(first), first), "Adzuna")
        job = listing()
        job["redirect_url"] = first
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(job_history, "HISTORY_DB_PATH", Path(directory) / "history.sqlite3"):
            self.assertEqual(len(adzuna_candidates([job], "data analyst", "nyc")), 1)

    def test_save_records_listing_and_predicted_salary(self):
        job = listing()
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with patch.object(job_history, "HISTORY_DB_PATH", Path(directory) / "history.sqlite3"):
                    text = save_adzuna_job(job)
                    self.assertIn("Description snippet", text)
                    self.assertIn("The Adzuna API", text)
                    self.assertTrue(job_history.is_processed(job["redirect_url"]))
                    self.assertEqual(json.loads((Path("jobs") / "JOB_adzuna_123.json").read_text()), job)
                    row = prospects.list_prospects()[0]
                    self.assertEqual(row["source"], "Adzuna")
                    self.assertEqual(row["salary_range"], "$70,000 - $90,000 (Adzuna estimate)")
                    self.assertEqual(row["posted_at"], job["created"])
                    with self.assertRaisesRegex(ValueError, "already processed"):
                        save_adzuna_job(job)
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
