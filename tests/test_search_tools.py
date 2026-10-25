import unittest
from dataclasses import replace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from job_tools.search_tools import idealist_search_url, idealist_shortlist
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


if __name__ == "__main__":
    unittest.main()
