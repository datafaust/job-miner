import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_tools import job_history, prospects


class ProspectExtractionTests(unittest.TestCase):
    def test_greenhouse_uses_posted_date_not_update_date_and_does_not_guess_remote(self):
        job = {
            "title": "Analyst",
            "company_name": "Stripe",
            "location": {"name": "San Francisco"},
            "first_published": "2026-09-28T18:23:59-04:00",
            "updated_at": "2026-10-22T09:17:10-04:00",
            "content": "&lt;p&gt;Pay range: $90,000 - $120,000 per year.&lt;/p&gt;",
        }
        facts = prospects.extract_greenhouse(job)
        self.assertEqual(facts["posted_at"], job["first_published"])
        self.assertEqual(facts["salary_range"], "$90,000 - $120,000")
        self.assertEqual(facts["remote_status"], "unknown")

        job["location"] = {"name": "US-SF, US-Remote"}
        self.assertEqual(prospects.extract_greenhouse(job)["remote_status"], "remote")

    def test_idealist_uses_labelled_fields_and_keeps_relative_posting_age(self):
        source = (
            "NONPROFIT\nNew\nPublished 20 hours ago\nData Analyst\n"
            "Example Organization\nOn-site, Work must be performed in New York\n"
            "Salary:\nUSD $80,000 - $90,000 / year\nDescription\n"
            "Location: New York. Hybrid: 3 days/week in office."
        )
        facts = prospects.extract_idealist(source)
        self.assertEqual(facts["job_title"], "Data Analyst")
        self.assertEqual(facts["company"], "Example Organization")
        self.assertEqual(facts["salary_range"], "USD $80,000 - $90,000 / year")
        self.assertEqual(facts["posted_text"], "Published 20 hours ago")
        self.assertIsNone(facts["posted_at"])
        self.assertEqual(facts["remote_status"], "hybrid")

    def test_saved_source_is_upserted_and_exported_without_ai_summary(self):
        url = "https://stripe.com/jobs/search?gh_jid=8172487"
        job = {
            "title": "Software Engineer",
            "company_name": "Stripe",
            "absolute_url": url,
            "location": {"name": "Remote from the US"},
            "first_published": "2026-09-01T12:00:00-04:00",
            "content": "&lt;p&gt;Build services.&lt;/p&gt;",
        }
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "history.sqlite3"
            source_path = Path(directory) / "posting.json"
            source_path.write_text(json.dumps(job), encoding="utf-8")
            with patch.object(job_history, "HISTORY_DB_PATH", db_path):
                job_history.record_processed(url, str(source_path))
                prospects.extract_and_save(url, str(source_path))
                prospects.extract_and_save(url, str(source_path))
                rows = prospects.list_prospects()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["job_key"], "greenhouse:8172487")
        self.assertEqual(rows[0]["remote_status"], "remote")
        self.assertEqual(rows[0]["company"], "Stripe")
        self.assertIsNone(rows[0]["salary_range"])


if __name__ == "__main__":
    unittest.main()
