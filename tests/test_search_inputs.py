import unittest
from unittest.mock import patch

from main import resolve_search_inputs


class SearchInputTests(unittest.TestCase):
    def test_blank_inputs_use_environment_defaults(self):
        with patch.dict("os.environ", {
            "JOB_SEARCH_KEYWORDS": "data analyst",
            "JOB_SEARCH_LOCATION": "nyc",
        }):
            self.assertEqual(resolve_search_inputs(" ", " "), ("data analyst", "nyc"))
            self.assertEqual(resolve_search_inputs("engineer", "remote"), ("engineer", "remote"))
            self.assertEqual(resolve_search_inputs("engineer", "New York"), ("engineer", "nyc"))

    def test_missing_keyword_or_location_errors(self):
        with patch.dict("os.environ", {
            "JOB_SEARCH_KEYWORDS": "",
            "JOB_SEARCH_LOCATION": "nyc",
        }):
            with self.assertRaisesRegex(ValueError, "Enter job keywords"):
                resolve_search_inputs("", "")
        with patch.dict("os.environ", {
            "JOB_SEARCH_KEYWORDS": "data analyst",
            "JOB_SEARCH_LOCATION": "",
        }):
            with self.assertRaisesRegex(ValueError, "Enter a location"):
                resolve_search_inputs("", "")
        with patch.dict("os.environ", {
            "JOB_SEARCH_KEYWORDS": "data analyst",
            "JOB_SEARCH_LOCATION": "Boston",
        }):
            with self.assertRaisesRegex(ValueError, "nyc.*remote"):
                resolve_search_inputs("", "")


if __name__ == "__main__":
    unittest.main()
