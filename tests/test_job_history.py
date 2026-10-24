import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_tools import job_history


class JobHistoryTests(unittest.TestCase):
    def test_extract_job_url_from_agent_listing(self):
        url = "https://www.idealist.org/en/nonprofit-job/6965cacf0cf845ffaaae044a336111ec-software-engineer"
        listing = {"text": "Software Engineer\nRemote", "link": url}
        self.assertEqual(job_history.extract_job_url(url), url)
        self.assertEqual(job_history.extract_job_url(listing), url)
        self.assertEqual(job_history.extract_job_url(json.dumps(listing)), url)
        self.assertEqual(
            job_history.extract_job_url(json.dumps(listing) + "\nThought: Choose the best job"),
            url,
        )

    def test_extract_job_url_rejects_missing_or_ambiguous_link(self):
        for value in ("Software Engineer", {"text": "Software Engineer"}, "https://a.example/job https://b.example/job"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                job_history.extract_job_url(value)

    def test_idealist_id_survives_slug_and_tracking_changes(self):
        job_id = "8a10b7bd05454fe1b631295eb611de92"
        first = f"https://www.idealist.org/en/nonprofit-job/{job_id}-analyst?source=search"
        renamed = f"https://idealist.org/en/nonprofit-job/{job_id}-senior-analyst"
        self.assertEqual(job_history.job_key(first), job_history.job_key(renamed))

    def test_urls_without_a_posting_id_ignore_tracking_parameters(self):
        first = "https://www.idealist.org/en/jobs/example?source=email"
        second = "https://idealist.org/en/jobs/example/?source=search#details"
        self.assertEqual(job_history.job_key(first), job_history.job_key(second))

    def test_greenhouse_id_in_stripe_url_distinguishes_jobs(self):
        first = "https://stripe.com/jobs/search?gh_jid=8172487&utm_source=example"
        same_job = "https://stripe.com/jobs/search?gh_jid=8172487"
        another = "https://stripe.com/jobs/search?gh_jid=8172488"
        self.assertEqual(job_history.job_key(first), job_history.job_key(same_job))
        self.assertNotEqual(job_history.job_key(first), job_history.job_key(another))

    def test_processed_jobs_are_excluded_across_database_connections(self):
        first = "https://www.idealist.org/en/nonprofit-job/8a10b7bd05454fe1b631295eb611de92-analyst"
        same_job = first + "?ref=latest"
        second = "https://www.idealist.org/en/nonprofit-job/bcf832329bee4e819069b2b0ccef02a6-analyst"
        results = [
            {"text": "Analyst", "link": first},
            {"text": "Analyst", "link": same_job},
            {"text": "Analyst", "link": second},
        ]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job_history.sqlite3"
            with patch.object(job_history, "HISTORY_DB_PATH", path):
                self.assertEqual(job_history.filter_unprocessed(results), [results[0], results[2]])
                self.assertFalse(job_history.is_processed(first))
                job_history.record_processed(first, "JOB_Analyst.txt")
                self.assertTrue(job_history.is_processed(same_job))
                self.assertEqual(job_history.filter_unprocessed(results), [results[2]])
                job_history.record_processed(same_job, "JOB_Analyst.txt")

            with sqlite3.connect(path) as connection:
                count = connection.execute("SELECT COUNT(*) FROM processed_jobs").fetchone()[0]
            self.assertEqual(count, 1)

    def test_ai_results_link_to_existing_history_and_can_be_updated(self):
        url = "https://www.idealist.org/en/nonprofit-job/8a10b7bd05454fe1b631295eb611de92-analyst"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job_history.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    """CREATE TABLE processed_jobs (
                        job_key TEXT PRIMARY KEY,
                        url TEXT NOT NULL,
                        detail_file TEXT NOT NULL,
                        processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )"""
                )

            with patch.object(job_history, "HISTORY_DB_PATH", path):
                job_history.record_processed(url, "JOB_analyst.txt")
                job_history.record_ai_result(url, "Analyst", "qwen2.5:7b", "summarized", "SUMMARY: Analyst\nSQL role")
                saved = job_history.saved_ai_results()
                self.assertEqual(len(saved), 1)
                self.assertEqual(saved[0][0], job_history.job_key(url))
                self.assertEqual(saved[0][3], "summarized")
                self.assertEqual(saved[0][4], "SUMMARY: Analyst\nSQL role")
                self.assertEqual(saved[0][6:], (url, "JOB_analyst.txt"))

                job_history.record_ai_result(url, "Analyst", "qwen2.5:7b", "not_needed", "No summary needed")
                saved = job_history.saved_ai_results()
                self.assertEqual(len(saved), 1)
                self.assertEqual(saved[0][3:5], ("not_needed", "No summary needed"))


if __name__ == "__main__":
    unittest.main()
