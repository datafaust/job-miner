"""Favorites persist and combine with application filters."""
import unittest
from tests import test_job_web
from job_miner.web import app as web
from job_tools import job_history


class FavoriteTests(unittest.TestCase):
    setUp = test_job_web.JobWebTests.setUp
    save_idealist = test_job_web.JobWebTests.save_idealist

    def test_favorite_filter_and_unfavorite(self):
        key = self.save_idealist('a' * 32, 'Important Job')
        other = self.save_idealist('b' * 32, 'Other Job')
        route = f'/jobs/{key}/favorite'
        token = web.confirmation_signer.dumps({'favorite_job': key})
        self.assertEqual(self.client.post(route, data={'is_favorite': '1'}).status_code, 400)
        wrong = web.confirmation_signer.dumps({'favorite_job': other})
        self.assertEqual(self.client.post(route, data={'token': wrong, 'is_favorite': '1'}).status_code, 400)
        self.assertEqual(self.client.post(route, data={'token': token, 'is_favorite': 'bad'}).status_code, 400)
        response = self.client.post(route, data={'token': token, 'is_favorite': '1', 'return_to': 'list', 'favorite': '1', 'application': 'unapplied'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('favorite=1', response.location)
        listing = self.client.get(response.location).data
        self.assertIn(b'Important Job', listing)
        self.assertNotIn(b'Other Job', listing)
        self.assertIn(b'aria-pressed="true"', listing)
        detail = self.client.get(f'/jobs/{key}?favorite=1&application=unapplied').data
        self.assertIn(b'name="favorite" value="1"', detail)
        self.assertIn(b'aria-pressed="true"', detail)
        with job_history._database() as connection:
            connection.execute("UPDATE processed_jobs SET applied_on = '2026-01-01' WHERE job_key = ?", (key,))
        self.assertNotIn(b'Important Job', self.client.get('/?favorite=1&application=unapplied').data)
        self.assertIn(b'Important Job', self.client.get('/?favorite=1&application=applied').data)
        for _ in range(2):
            self.assertEqual(self.client.post(route, data={'token': token, 'is_favorite': '0'}).status_code, 302)
        self.assertNotIn(b'Important Job', self.client.get('/?favorite=1').data)
        self.assertIn(b'Important Job', self.client.get('/').data)

    def test_unknown_job(self):
        token = web.confirmation_signer.dumps({'favorite_job': 'missing'})
        self.assertEqual(self.client.post('/jobs/missing/favorite', data={'token': token, 'is_favorite': '1'}).status_code, 404)
