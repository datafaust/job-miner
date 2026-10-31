import unittest
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from job_tools import job_history
from job_tools.search_tools import SearchTools, idealist_search_url, idealist_shortlist
from job_tools.workflow_config import LIMITS


class SearchToolsTests(unittest.TestCase):
    def test_idealist_search_adds_passed_location_to_keyword_query(self):
        url = idealist_search_url("  data analyst  ", "nyc")
        self.assertEqual(urlsplit(url).path, "/en/jobs")
        self.assertEqual(parse_qs(urlsplit(url).query), {"q": ["data analyst New York City"]})
        remote = idealist_search_url("data analyst", "remote")
        self.assertEqual(
            parse_qs(urlsplit(remote).query),
            {"q": ["data analyst"], "locationType": ["REMOTE"]},
        )

    def test_idealist_search_requires_both_inputs(self):
        with self.assertRaisesRegex(ValueError, "keywords are required"):
            idealist_search_url(" ", "nyc")
        with self.assertRaisesRegex(ValueError, "location is required"):
            idealist_search_url("data analyst", " ")
        with self.assertRaisesRegex(ValueError, "nyc.*remote"):
            idealist_search_url("data analyst", "Boston")

    def test_idealist_shortlist_uses_configured_limit(self):
        results = list(range(10))
        with patch("job_tools.search_tools.LIMITS", replace(LIMITS, idealist_candidates_per_run=5)):
            self.assertEqual(idealist_shortlist(results), [0, 1, 2, 3, 4])

    def test_idealist_keeps_unconventional_titles_for_detail_review(self):
        url = "https://www.idealist.org/en/nonprofit-job/6965cacf0cf845ffaaae044a336111ec-operations-associate"
        listing = Mock(text="Operations Associate\nExample Org")
        listing.find_element.return_value.get_attribute.return_value = url
        driver = Mock()
        driver.find_elements.return_value = [listing]
        with tempfile.TemporaryDirectory() as directory:
            original_cwd = Path.cwd()
            try:
                os.chdir(directory)
                with patch.object(job_history, "HISTORY_DB_PATH", Path(directory) / "history.sqlite3"), \
                     patch("job_tools.search_tools.webdriver.Chrome", return_value=driver), \
                     patch("job_tools.search_tools.WebDriverWait"):
                    results = json.loads(SearchTools.search_idealist.run("data analyst", "nyc"))
                self.assertEqual([item["link"] for item in results], [url])
                self.assertEqual(json.loads(Path("output.json").read_text()), results)
                driver.quit.assert_called_once_with()
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
