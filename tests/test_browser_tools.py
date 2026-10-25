import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from job_tools import job_history
from job_tools.browser_tools import BrowserTools


class BrowserToolsTests(unittest.TestCase):
    def test_irrelevant_idealist_posting_is_not_saved_or_marked_processed(self):
        url = "https://www.idealist.org/en/nonprofit-job/6965cacf0cf845ffaaae044a336111ec-financial-analyst"
        driver = Mock()
        driver.find_element.return_value.text = (
            "Financial Analyst\nResponsibilities\nReview budgets.\n"
            "Qualifications\nSQL and dashboards required."
        )
        driver.find_element.return_value.find_elements.return_value = []

        with tempfile.TemporaryDirectory() as directory:
            old_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with patch.object(job_history, "HISTORY_DB_PATH", Path(directory) / "history.sqlite3"), \
                     patch("job_tools.browser_tools.webdriver.Chrome", return_value=driver), \
                     patch("job_tools.browser_tools.WebDriverWait") as wait:
                    wait.return_value.until.return_value = Mock(text="Financial Analyst")
                    result = BrowserTools.scrape_idealist_job_details.run(url, "data analyst")
                    self.assertIsNone(result)
                    self.assertFalse(job_history.is_processed(url))
                self.assertFalse(Path("jobs").exists())
                driver.quit.assert_called_once_with()
            finally:
                os.chdir(old_cwd)

    def test_idealist_posting_is_saved_in_jobs_folder(self):
        url = (
            "https://www.idealist.org/en/nonprofit-job/"
            "6965cacf0cf845ffaaae044a336111ec-software-engineer"
        )
        posting = "Published 1 day ago\nSoftware Engineer\nExample Org\nRemote\nDetails"
        driver = Mock()
        driver.find_element.return_value.text = posting
        driver.find_element.return_value.find_elements.return_value = []
        title = Mock(text="Software Engineer")

        with tempfile.TemporaryDirectory() as directory:
            old_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with patch.object(job_history, "HISTORY_DB_PATH", Path(directory) / "history.sqlite3"), \
                     patch("job_tools.browser_tools.webdriver.Chrome", return_value=driver), \
                     patch("job_tools.browser_tools.WebDriverWait") as wait:
                    Path("output.json").write_text(json.dumps([
                        {"text": "Software Engineer", "link": url},
                        {"text": "Other job", "link": "https://example.com/other"},
                    ]), encoding="utf-8")
                    wait.return_value.until.return_value = title
                    result = BrowserTools.scrape_idealist_job_details.run(url)

                saved_file = Path("jobs/JOB_idealist_6965cacf0cf845ffaaae044a336111ec.txt")
                self.assertEqual(result, posting)
                self.assertEqual(saved_file.read_text(encoding="utf-8"), posting)
                self.assertEqual(
                    [row["link"] for row in json.loads(Path("output.json").read_text())],
                    ["https://example.com/other"],
                )
                with patch.object(job_history, "HISTORY_DB_PATH", Path(directory) / "history.sqlite3"):
                    with job_history._database() as connection:
                        detail_file = connection.execute(
                            "SELECT detail_file FROM processed_jobs WHERE job_key = ?",
                            (job_history.job_key(url),),
                        ).fetchone()[0]
                self.assertEqual(detail_file, str(saved_file))
                driver.quit.assert_called_once_with()
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
