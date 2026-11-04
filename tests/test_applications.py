"""Application reporting persists across requests and preserves list navigation."""
from datetime import date, timedelta
import sqlite3
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from tests import test_job_web
from job_miner.web import app as web
from job_tools import job_history


class ApplicationTests(unittest.TestCase):
    setUp = test_job_web.JobWebTests.setUp
    save_idealist = test_job_web.JobWebTests.save_idealist

    def report(self, key, status='applied', applied_on='2026-01-01', **context):
        token = web.confirmation_signer.dumps({'application_job': key})
        return self.client.post(f'/jobs/{key}/application', data={
            'token': token, 'status': status, 'applied_on': applied_on, **context})

    def test_mark_update_and_undo_survive_repeated_requests_and_collection(self):
        key = self.save_idealist('a' * 32, 'Data Engineer')
        page = self.client.get(f'/jobs/{key}')
        self.assertIn(b'Mark as applied', page.data)
        self.assertIn(b'type="date"', page.data)
        for _ in range(2):
            self.assertEqual(self.report(key).status_code, 302)
        with job_history._database() as connection:
            self.assertEqual(connection.execute('SELECT applied_on FROM processed_jobs').fetchone()[0], '2026-01-01')
        self.assertEqual(self.report(key, applied_on='2026-01-02').status_code, 302)
        url, path = job_history.saved_job(key)
        job_history.record_processed(url, path)
        detail = self.client.get(f'/jobs/{key}')
        self.assertIn(b'2026-01-02', detail.data)
        self.assertIn(b'Mark as not applied', detail.data)
        self.assertIn(b'Update date', detail.data)
        for _ in range(2):
            self.assertEqual(self.report(key, status='unapplied', applied_on='').status_code, 302)
        with job_history._database() as connection:
            self.assertIsNone(connection.execute('SELECT applied_on FROM processed_jobs').fetchone()[0])
        self.assertIn(b'Mark as applied', self.client.get(f'/jobs/{key}').data)

    def test_post_requires_valid_token_job_status_and_date(self):
        key = self.save_idealist('a' * 32, 'Data Engineer')
        route = f'/jobs/{key}/application'
        self.assertEqual(self.client.get(route).status_code, 404)
        self.assertEqual(self.client.post(route).status_code, 400)
        other = web.confirmation_signer.dumps({'application_job': 'other'})
        self.assertEqual(self.client.post(route, data={'token': other, 'status': 'unapplied'}).status_code, 400)
        self.assertEqual(self.report('unknown').status_code, 404)
        self.assertEqual(self.report(key, status='invalid').status_code, 400)
        for value in ('', 'invalid', '2026-02-30', '20260101', (date.today() + timedelta(days=1)).isoformat()):
            with self.subTest(value=value):
                self.assertEqual(self.report(key, applied_on=value).status_code, 400)
        with job_history._database() as connection:
            self.assertIsNone(connection.execute('SELECT applied_on FROM processed_jobs').fetchone()[0])

    def test_filters_sort_and_navigation_keep_application_context(self):
        first = self.save_idealist('a' * 32, 'Earlier Application')
        second = self.save_idealist('b' * 32, 'Later Application')
        third = self.save_idealist('c' * 32, 'Never Applied')
        self.report(first)
        self.report(second, applied_on='2026-01-02')
        applied = self.client.get('/?application=applied&sort=applied&order=desc')
        self.assertNotIn(b'Never Applied', applied.data)
        self.assertLess(applied.data.index(b'Later Application'), applied.data.index(b'Earlier Application'))
        self.assertIn(b'application=applied', applied.data)
        self.assertIn(b'<option value="applied" selected>', applied.data)
        unapplied = self.client.get('/?application=unapplied')
        self.assertIn(b'Never Applied', unapplied.data)
        self.assertNotIn(b'Earlier Application', unapplied.data)
        all_jobs = self.client.get('/?application=invalid&sort=applied&order=desc')
        self.assertIn(b'Never Applied', all_jobs.data)
        self.assertLess(all_jobs.data.index(b'Earlier Application'), all_jobs.data.index(b'Never Applied'))
        response = self.report(first, application='unapplied', availability='hide_closed', q='Application',
                               source='Idealist', remote='remote', page='2', sort='saved', order='asc')
        params = parse_qs(urlsplit(response.location).query)
        self.assertEqual(params['application'], ['unapplied'])
        self.assertEqual(params['availability'], ['hide_closed'])
        self.assertEqual(params['page'], ['2'])
        detail = self.client.get(response.location)
        self.assertIn(b'name="application" value="unapplied"', detail.data)
        self.assertIn(b'application=unapplied', detail.data)
        # Filtering happens before pagination; page links retain the filter.
        with patch.object(web, 'PAGE_SIZE', 1):
            page = self.client.get('/?application=applied')
            self.assertIn(b'Page 1 of 2', page.data)
            self.assertRegex(page.data, rb'application=applied[^\"]*page=2')

    def test_existing_database_adds_application_date_without_changing_rows(self):
        with sqlite3.connect(job_history.HISTORY_DB_PATH) as connection:
            connection.execute('''CREATE TABLE processed_jobs (
                job_key TEXT PRIMARY KEY, url TEXT NOT NULL, detail_file TEXT NOT NULL,
                processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, hidden_at TEXT)''')
            connection.execute("INSERT INTO processed_jobs (job_key, url, detail_file) VALUES ('old', 'https://example.org/job', 'old.txt')")
        for _ in range(2):
            with job_history._database() as connection:
                self.assertEqual(connection.execute('SELECT job_key, applied_on FROM processed_jobs').fetchone(), ('old', None))
