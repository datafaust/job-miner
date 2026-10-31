import unittest
import os
import subprocess
import sys
from pathlib import Path
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

    def test_noninteractive_cli_fails_without_inputs_instead_of_prompting(self):
        env = os.environ.copy()
        env["JOB_SEARCH_KEYWORDS"] = ""
        env["JOB_SEARCH_LOCATION"] = ""
        result = subprocess.run(
            [sys.executable, "main.py", "--keywords", "", "--location", ""],
            cwd=Path(__file__).resolve().parents[1], env=env, input="", text=True,
            capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Enter job keywords", result.stderr)
        self.assertNotIn("EOFError", result.stderr)


if __name__ == "__main__":
    unittest.main()
