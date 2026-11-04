"""Manual grading confirmation, request deduplication, pacing, and persistence."""
import unittest
import fcntl
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from tests import test_job_web, test_fit_grader
from job_miner.web import app as web
from job_miner.workers import grade as worker
from job_tools import grade_web_tasks as tasks, job_history


class GradeWebTests(unittest.TestCase):
    save_idealist = test_job_web.JobWebTests.save_idealist

    def setUp(self):
        test_job_web.JobWebTests.setUp(self)
        task_patch = patch.object(tasks, 'TASK_ROOT', self.root / 'requests' / 'fit_grades')
        task_patch.start()
        self.addCleanup(task_patch.stop)
        self.key = self.save_idealist('a' * 32, 'Data Engineer')

    def token(self, key=None):
        return web.confirmation_signer.dumps({'grade_job': key or self.key, 'task_id': str(uuid4())})

    def start(self, token=None, **context):
        return self.client.post(f'/jobs/{self.key}/grade', data={'token': token or self.token(), **context})

    def test_button_tokens_and_start_preserve_context_and_launch_once(self):
        detail = self.client.get(f'/jobs/{self.key}?application=unapplied&q=Data&page=2')
        self.assertIn(b'Run fit grade', detail.data)
        self.assertIn(b'data-run-fit-grade', detail.data)
        self.assertIn(b'data-confirm-message=', detail.data)
        token = self.token()
        with patch.object(web.subprocess, 'Popen') as launch:
            response = self.start(token, application='unapplied', q='Data', page='2')
            self.assertEqual(response.status_code, 302)
            again = self.start(token)
            self.assertEqual(again.location, response.location)
            other_tab = self.start()
            self.assertEqual(other_tab.location, response.location)
            launch.assert_called_once()
            self.assertIn('job_miner.workers.grade', launch.call_args.args[0])
            self.assertTrue(launch.call_args.kwargs['start_new_session'])
        task_id = response.location.rsplit('/', 1)[-1]
        task = tasks.read_status(tasks.TASK_ROOT / task_id)
        self.assertEqual(task['model'], tasks.DEFAULT_MODEL)
        params = parse_qs(urlsplit(task['detail_url']).query)
        self.assertEqual(params['application'], ['unapplied'])
        self.assertEqual(params['page'], ['2'])
        pending = self.client.get(response.location)
        self.assertIn(b'content="5"', pending.data)
        self.assertIn(b'Waiting for any active fit grading', pending.data)
        self.assertIn(b'View grading progress', self.client.get(f'/jobs/{self.key}').data)

    def test_invalid_token_job_and_posting_never_launch_worker(self):
        route = f'/jobs/{self.key}/grade'
        with patch.object(web.subprocess, 'Popen') as launch:
            self.assertEqual(self.client.post(route).status_code, 400)
            self.assertEqual(self.start(self.token('other')).status_code, 400)
            missing = 'unknown'
            self.assertEqual(self.client.post(f'/jobs/{missing}/grade', data={'token': self.token(missing)}).status_code, 404)
            with patch.object(web, 'load_saved_posting', side_effect=ValueError('missing posting')):
                self.assertEqual(self.start().status_code, 400)
            launch.assert_not_called()
        self.assertEqual(self.client.get('/fit-grade/not-a-uuid').status_code, 404)
        self.assertEqual(self.client.get('/fit-grade/' + str(uuid4())).status_code, 404)

    def test_launch_failure_is_visible_and_allows_retry(self):
        with patch.object(web.subprocess, 'Popen', side_effect=OSError('launch failed')):
            response = self.start()
        self.assertIn(b'The grading worker could not start', self.client.get(response.location).data)
        self.assertIn(b'Run fit grade', self.client.get(f'/jobs/{self.key}').data)

    def queued_task(self):
        with patch.object(web.subprocess, 'Popen'):
            response = self.start()
        return tasks.TASK_ROOT / response.location.rsplit('/', 1)[-1]

    def test_worker_forces_regrade_persists_result_and_enforces_cooldown(self):
        task_dir = self.queued_task()
        def grade_under_lock(*args):
            # A scheduled grader opening the same file must be excluded during inference.
            with (tasks.TASK_ROOT.parent / 'grading.lock').open('a') as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return test_fit_grader.FitGraderTests.model_grade()
        with patch.object(worker.grade, 'request_grade', side_effect=grade_under_lock) as model:
            worker.run(task_dir)
            model.assert_called_once()
            # Relaunching the same completed task must not perform inference again.
            worker.run(task_dir)
            model.assert_called_once()
            task = tasks.read_status(task_dir)
            self.assertEqual(task['state'], 'completed')
            self.assertEqual(task['score'], 82)
            with job_history._database() as connection:
                self.assertEqual(connection.execute('SELECT score FROM job_fit_grades').fetchone()[0], 82)
                self.assertGreater(connection.execute('SELECT next_allowed FROM fit_batch_state').fetchone()[0], worker.time.time())
                connection.execute('UPDATE fit_batch_state SET next_allowed = 0')
            second = self.queued_task()
            worker.run(second)
            self.assertEqual(model.call_count, 2)  # Unchanged input still explicitly regrades.
        status_page = self.client.get('/fit-grade/' + task['task_id'])
        self.assertIn(b'82/100', status_page.data)
        self.assertNotIn(b'http-equiv="refresh"', status_page.data)

    def test_worker_waits_for_cooldown_and_failure_preserves_previous_grade(self):
        first = self.queued_task()
        with patch.object(worker.grade, 'request_grade', side_effect=lambda *args: test_fit_grader.FitGraderTests.model_grade()):
            worker.run(first)
        second = self.queued_task()
        def finish_cooldown(seconds):
            self.assertGreater(seconds, 0)
            with job_history._database() as connection:
                connection.execute('UPDATE fit_batch_state SET next_allowed = 0')
        with patch.object(worker.time, 'sleep', side_effect=finish_cooldown) as sleep, patch.object(
            worker.grade, 'request_grade', side_effect=ValueError('Invalid model response')
        ):
            worker.run(second)
            sleep.assert_called_once()
        status = tasks.read_status(second)
        self.assertEqual(status['state'], 'failed')
        self.assertEqual(status['error'], 'Invalid model response')
        with job_history._database() as connection:
            self.assertEqual(connection.execute('SELECT score FROM job_fit_grades').fetchone()[0], 82)
            self.assertIsNotNone(connection.execute('SELECT retry_after FROM fit_batch_failures').fetchone())
        self.assertIn(b'Any previous grade is preserved', self.client.get('/fit-grade/' + status['task_id']).data)

    def test_dead_worker_is_reported_and_can_be_retried(self):
        task_dir = self.queued_task()
        status = tasks.read_status(task_dir)
        status.update(pid=999999999, state='running')
        tasks.write_status(task_dir, status)
        with patch.object(tasks.os, 'kill', side_effect=ProcessLookupError):
            response = self.client.get('/fit-grade/' + status['task_id'])
        self.assertIn(b'The grading worker stopped', response.data)
        self.assertEqual(tasks.read_status(task_dir)['state'], 'failed')
