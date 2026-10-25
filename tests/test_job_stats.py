import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_tools import job_history, job_stats


class JobStatsTests(unittest.TestCase):
    def test_run_summary_counts_new_jobs_and_missing_prospects_by_source(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "history.sqlite3"
            with patch.object(job_history, "HISTORY_DB_PATH", db_path):
                before = job_stats.snapshot()
                job_history.record_processed(
                    "https://www.idealist.org/en/nonprofit-job/6965cacf0cf845ffaaae044a336111ec-engineer",
                    "jobs/idealist.txt",
                )
                job_history.record_processed(
                    "https://stripe.com/jobs/search?gh_jid=123", "jobs/greenhouse.json"
                )
                with job_history._database() as connection:
                    connection.execute(
                        "INSERT INTO prospective_jobs (job_key, job_title, remote_status) VALUES (?, ?, ?)",
                        ("idealist:6965cacf0cf845ffaaae044a336111ec", "Engineer", "remote"),
                    )
                job_history.record_ai_result(
                    "https://stripe.com/jobs/search?gh_jid=123", "Engineer", "model",
                    "summarized", "Summary",
                )
                after = job_stats.snapshot()
        report = job_stats.format_run(before, after)
        self.assertIn("2 saved jobs; 1 prospect rows; 1 AI results", report)
        self.assertIn("Greenhouse 1", report)
        self.assertIn("Idealist 1", report)
        self.assertIn("Saved jobs missing prospect facts: 1", report)

    def test_reset_reports_cleared_jobs_and_keeps_oauth_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs = root / "jobs"
            jobs.mkdir()
            posting = jobs / "JOB_idealist_example.txt"
            posting.write_text("posting", encoding="utf-8")
            token = root / ".google_drive_token.json"
            token.write_text("private token", encoding="utf-8")
            with patch.object(job_history, "HISTORY_DB_PATH", root / "job_history.sqlite3"), \
                 patch.object(job_stats, "PROJECT_DIR", root):
                job_history.record_processed(
                    "https://www.idealist.org/en/nonprofit-job/6965cacf0cf845ffaaae044a336111ec-engineer",
                    str(posting),
                )
                report = job_stats.reset_history()
                self.assertFalse((root / "job_history.sqlite3").exists())
            self.assertIn("Cleared 1 saved jobs", report)
            self.assertIn("Idealist 1", report)
            self.assertFalse(posting.exists())
            self.assertTrue(token.exists())


if __name__ == "__main__":
    unittest.main()
