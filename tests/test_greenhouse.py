import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from job_tools import job_history, prospects
from job_tools.greenhouse import greenhouse_candidates, save_greenhouse_job, scrape_greenhouse


class GreenhouseTests(unittest.TestCase):
    def test_fetches_stripe_jobs_and_prints_success(self):
        jobs = [{"title": "Engineer", "content": "Full description"}]
        with patch("job_tools.greenhouse.requests.get") as get:
            get.return_value.json.return_value = {"jobs": jobs}
            output = io.StringIO()
            with redirect_stdout(output):
                result = scrape_greenhouse("stripe")

        get.assert_called_once_with(
            "https://boards-api.greenhouse.io/v1/boards/stripe/jobs",
            params={"content": "true"},
            timeout=30,
        )
        get.return_value.raise_for_status.assert_called_once_with()
        self.assertEqual(result, jobs)
        self.assertIn("Greenhouse scrape succeeded for stripe: found 1 jobs.", output.getvalue())

    def test_candidate_is_saved_with_original_listing_and_history(self):
        job = {
            "id": 8172487,
            "title": "Software Engineer",
            "absolute_url": "https://stripe.com/jobs/search?gh_jid=8172487",
            "location": {"name": "Remote"},
            "updated_at": "2026-10-22T09:16:14-04:00",
            "content": "&lt;p&gt;Build &amp;amp; maintain services.&lt;/p&gt;",
        }
        with tempfile.TemporaryDirectory() as directory:
            old_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with patch.object(job_history, "HISTORY_DB_PATH", Path(directory) / "history.sqlite3"):
                    self.assertEqual(greenhouse_candidates([job], "remote accountant"), [])
                    candidates = greenhouse_candidates([job], "remote software engineer")
                    self.assertEqual(len(candidates), 1)
                    text = save_greenhouse_job(candidates[0]["job"])
                    self.assertIn("Build & maintain services.", text)
                    self.assertIn(job["absolute_url"], text)
                    self.assertTrue(job_history.is_processed(job["absolute_url"]))
                    self.assertEqual(prospects.list_prospects()[0]["job_title"], "Software Engineer")
                    self.assertEqual(greenhouse_candidates([job], "software engineer"), [])
                    saved_file = Path("JOB_greenhouse_stripe_8172487.json")
                    self.assertEqual(json.loads(saved_file.read_text()), job)
                    with self.assertRaisesRegex(ValueError, "already processed"):
                        save_greenhouse_job(job)
            finally:
                os.chdir(old_cwd)

    def test_description_keywords_are_used_when_titles_do_not_match(self):
        title_match = {
            "id": 1, "title": "Python Developer",
            "absolute_url": "https://stripe.com/jobs/search?gh_jid=1",
            "location": {"name": "New York"},
            "content": "&lt;p&gt;Build systems.&lt;/p&gt;",
        }
        description_match = {
            "id": 2, "title": "Platform Engineer",
            "absolute_url": "https://stripe.com/jobs/search?gh_jid=2",
            "location": {"name": "Remote"},
            "content": "&lt;p&gt;Use Python to build developer tools.&lt;/p&gt;",
        }
        unrelated = {
            "id": 3, "title": "Account Manager",
            "absolute_url": "https://stripe.com/jobs/search?gh_jid=3",
            "location": {"name": "Remote"},
            "content": "&lt;p&gt;Support account teams.&lt;/p&gt;",
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(job_history, "HISTORY_DB_PATH", Path(directory) / "history.sqlite3"):
                jobs = [description_match, unrelated, title_match]
                self.assertEqual(
                    [candidate["job"] for candidate in greenhouse_candidates(jobs, "remote python developer")],
                    [title_match],
                )
                job_history.record_processed(title_match["absolute_url"], "saved.json")
                self.assertEqual(
                    [candidate["job"] for candidate in greenhouse_candidates(jobs, "remote python developer")],
                    [description_match],
                )

    def test_candidate_search_caps_greenhouse_results_at_five(self):
        jobs = [
            {
                "id": number,
                "title": "Software Engineer",
                "absolute_url": f"https://stripe.com/jobs/search?gh_jid={number}",
                "location": {"name": "Remote"},
                "content": "&lt;p&gt;Build services.&lt;/p&gt;",
            }
            for number in range(1, 8)
        ]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(job_history, "HISTORY_DB_PATH", Path(directory) / "history.sqlite3"):
                candidates = greenhouse_candidates(jobs, "software engineer")
        self.assertEqual([candidate["job"]["id"] for candidate in candidates], [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
