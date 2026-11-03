"""Availability evidence, confirmation delays, and board request reuse."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from job_tools import availability as a, job_history


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        patcher = patch.object(job_history, 'HISTORY_DB_PATH', Path(temp.name) / 'history.sqlite3')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.url = 'https://boards.greenhouse.io/acme/jobs/123'
        self.key = job_history.record_processed(self.url, 'jobs/JOB_greenhouse_acme_123.json')
        self.key = job_history.job_key(self.url)
        self.now = datetime(2026, 11, 2, tzinfo=timezone.utc)

    def state(self):
        with job_history._database() as db:
            return db.execute('SELECT availability, last_seen_open, missing_since FROM job_availability WHERE job_key=?', (self.key,)).fetchone()

    def test_confirmation_delay_and_reopening(self):
        a.record_check(self.key, 'open', 'feed', self.now)
        self.assertEqual(a.record_check(self.key, 'missing', 'feed', self.now), 'possibly_closed')
        self.assertEqual(a.record_check(self.key, 'missing', 'feed', self.now + timedelta(hours=1)), 'possibly_closed')
        self.assertEqual(a.record_check(self.key, 'missing', 'feed', self.now + timedelta(hours=6)), 'closed')
        self.assertEqual(self.state()[1], self.now.isoformat())
        self.assertEqual(a.record_check(self.key, 'open', 'feed', self.now + timedelta(hours=7)), 'open')
        self.assertIsNone(self.state()[2])

    def test_error_breaks_confirmation(self):
        a.record_check(self.key, 'missing', 'feed', self.now)
        a.record_check(self.key, 'unknown', 'blocked', self.now + timedelta(hours=7))
        self.assertEqual(a.record_check(self.key, 'missing', 'feed', self.now + timedelta(hours=8)), 'possibly_closed')

    def test_complete_feed_reused_and_scoped(self):
        other_url = 'https://boards.greenhouse.io/other/jobs/456'
        job_history.record_processed(other_url, 'jobs/JOB_greenhouse_other_456.json')
        a.observe_board('greenhouse', 'acme', [123])
        self.assertEqual(self.state()[0], 'open')
        with job_history._database() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM job_availability').fetchone()[0], 1)
        a.observe_board('greenhouse', 'acme', [])
        self.assertEqual(self.state()[0], 'possibly_closed')

    def test_one_fetch_per_board_and_daily_cache(self):
        job_history.record_processed('https://boards.greenhouse.io/acme/jobs/124', 'jobs/JOB_greenhouse_acme_124.json')
        def fetch(board):
            a.observe_board('greenhouse', board, [123, 124])
        with patch('job_tools.greenhouse.scrape_greenhouse', side_effect=fetch) as get:
            self.assertEqual(a.audit(pages=False), {'open': 2})
            a.audit(pages=False)
            get.assert_called_once_with('acme')

    def test_failed_board_marks_unknown(self):
        with patch('job_tools.greenhouse.scrape_greenhouse', side_effect=requests.Timeout):
            self.assertEqual(a.audit(pages=False), {'unknown': 1})

    def test_malformed_board_does_not_mark_missing(self):
        from job_tools.greenhouse import scrape_greenhouse
        with patch('job_tools.greenhouse.get_board') as get:
            get.return_value.json.return_value = {}
            with self.assertRaises(ValueError):
                scrape_greenhouse('acme')
        self.assertIsNone(self.state())

    def test_page_closure_and_ambiguous_success(self):
        job = a.saved_jobs()[0]
        with patch('job_tools.availability.requests.get') as get:
            get.return_value = Mock(status_code=200, text='<h1>This job is no longer posted</h1>')
            self.assertEqual(a.check_page(job), 'possibly_closed')
            get.return_value.text = '<script>This job is no longer posted</script><h1>Careers</h1>'
            self.assertEqual(a.check_page(job), 'unknown')
            get.return_value = Mock(status_code=404)
            self.assertEqual(a.check_page(job), 'possibly_closed')
            get.side_effect = requests.Timeout
            self.assertEqual(a.check_page(job), 'unknown')

    def test_web_status_and_filter(self):
        from job_miner.web.app import app
        a.record_check(self.key, 'missing', 'Absent from complete board feed', self.now)
        a.record_check(self.key, 'missing', 'Absent from complete board feed', self.now + timedelta(hours=6))
        client = app.test_client()
        response = client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Closed', response.data)
        self.assertIn(b'0 results', client.get('/?availability=hide_closed').data)
        with patch('job_miner.web.app._available_models', return_value=([], None)):
            detail = client.get('/jobs/' + self.key + '?availability=hide_closed')
        self.assertIn(b'Last checked', detail.data)
        self.assertIn(b'availability=hide_closed', detail.data)
