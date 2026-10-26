import unittest
from unittest.mock import Mock, patch

import requests

from job_tools.board_http import get_board


class BoardHttpTests(unittest.TestCase):
    @patch("job_tools.board_http._interval", return_value=0)
    @patch("job_tools.board_http.time.sleep")
    @patch("job_tools.board_http.requests.get")
    def test_retries_429_using_retry_after(self, get, sleep, interval):
        throttled = Mock(status_code=429, headers={"Retry-After": "2"})
        success = Mock(status_code=200, headers={})
        get.side_effect = [throttled, success]
        self.assertIs(get_board("https://example.com/jobs", timeout=30), success)
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(2.0)

    @patch("job_tools.board_http._interval", return_value=0)
    @patch("job_tools.board_http.time.sleep")
    @patch("job_tools.board_http.random.uniform", return_value=0.5)
    @patch("job_tools.board_http.requests.get")
    def test_retries_timeout_then_stops(self, get, jitter, sleep, interval):
        get.side_effect = requests.Timeout("network")
        with self.assertRaises(requests.Timeout):
            get_board("https://example.com/jobs")
        self.assertEqual(get.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    @patch("job_tools.board_http._interval", return_value=0)
    @patch("job_tools.board_http.time.sleep")
    @patch("job_tools.board_http.requests.get")
    def test_does_not_retry_after_long_server_wait(self, get, sleep, interval):
        throttled = Mock(status_code=429, headers={"Retry-After": "120"})
        get.return_value = throttled
        self.assertIs(get_board("https://example.com/jobs"), throttled)
        get.assert_called_once()
        sleep.assert_not_called()

    @patch("job_tools.board_http._last_request_at", 10.0)
    @patch("job_tools.board_http._interval", return_value=0.25)
    @patch("job_tools.board_http.time.monotonic", return_value=10.0)
    @patch("job_tools.board_http.time.sleep")
    @patch("job_tools.board_http.requests.get")
    def test_spaces_requests(self, get, sleep, monotonic, interval):
        get.return_value = Mock(status_code=200, headers={})
        get_board("https://example.com/jobs")
        sleep.assert_called_once_with(0.25)


if __name__ == "__main__":
    unittest.main()
