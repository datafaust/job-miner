"""Browser search validation and enforced worker command, without live searches."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import job_web
import search_web_worker
from job_tools import search_web_tasks as tasks


class SearchWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.object(tasks, 'TASK_ROOT', self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = job_web.app.test_client()
        from uuid import uuid4
        self.task_id = str(uuid4())
        self.token = job_web.confirmation_signer.dumps({'search_id': self.task_id})

    def start(self, **values):
        return self.client.post('/search/start', data={
            'token': self.token, 'keywords': 'data analyst', 'location': 'nyc', **values})

    @patch('job_web.subprocess.Popen')
    def test_validation_and_duplicate_submission(self, popen):
        self.assertEqual(self.client.get('/search/new').status_code, 200)
        for values in ({'keywords': ' '}, {'location': ''}, {'location': 'Boston'},
                       {'keywords': 'x' * 301}, {'token': 'invalid'}):
            self.assertEqual(self.start(**values).status_code, 400)
        popen.assert_not_called()
        first = self.start()
        second = self.start()
        self.assertEqual(first.status_code, 302)
        self.assertEqual(first.location, second.location)
        popen.assert_called_once()
        self.assertIn(b'Search queued', self.client.get(first.location).data)

    @patch('job_web.subprocess.Popen', side_effect=OSError('cannot start'))
    def test_launch_failure_is_visible(self, popen):
        response = self.start()
        self.assertIn(b'Search failed', self.client.get(response.location).data)

    def test_worker_always_disables_summaries_and_records_result(self):
        task_dir = self.root / self.task_id
        task_dir.mkdir()
        for code, expected in ((0, 'completed'), (1, 'failed')):
            tasks.write_status(task_dir, dict(task_id=self.task_id, keywords='--model anything',
                                             location='remote', state='queued', created_at=tasks.now_utc()))
            with patch('search_web_worker.subprocess.run', return_value=Mock(returncode=code)) as run:
                search_web_worker.run(task_dir)
            command = run.call_args.args[0]
            self.assertIn('--no-summary', command)
            self.assertIn('--keywords=--model anything', command)
            self.assertEqual(tasks.read_status(task_dir)['state'], expected)
            self.assertIn(expected.encode(), self.client.get('/search/' + self.task_id).data)

    def test_missing_status_is_404(self):
        self.assertEqual(self.client.get('/search/' + self.task_id).status_code, 404)
        self.assertEqual(self.client.get('/search/not-a-uuid').status_code, 404)
