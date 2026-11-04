"""Verify batch pacing without GPU inference."""
import unittest
from unittest.mock import patch

from tests import test_fit_grader
from job_miner.cli import grade_batch as batch
from job_tools import job_history


class GradeBatchTests(unittest.TestCase):
    setUp = test_fit_grader.FitGraderTests.setUp
    save = test_fit_grader.FitGraderTests.save
    model_grade = staticmethod(test_fit_grader.FitGraderTests.model_grade)
    def test_limit_cooldown_and_unchanged_jobs(self):
        for index in range(12):
            self.save(f'job-{index:02}')
        with patch.object(
            batch.grade, 'request_grade', side_effect=lambda *args: self.model_grade()
        ) as request:
            self.assertEqual(batch.run_batch('model'), 0)
            self.assertEqual(request.call_count, 10)
            self.assertEqual(batch.run_batch('model'), 0)
            self.assertEqual(request.call_count, 10)
            with job_history._database() as connection:
                connection.execute('UPDATE fit_batch_state SET next_allowed = 0')
            self.assertEqual(batch.run_batch('model'), 0)
            self.assertEqual(request.call_count, 12)

    def test_time_budget_finishes_current_request(self):
        self.save('first')
        self.save('second')
        with patch.object(
            batch.time, 'monotonic', side_effect=[0, 301]
        ), patch.object(batch.grade, 'request_grade', side_effect=lambda *args: self.model_grade()) as request:
            self.assertEqual(batch.run_batch('model'), 0)
            self.assertEqual(request.call_count, 1)

    def test_failure_is_deferred_and_other_jobs_progress(self):
        self.save('first')
        self.save('second')
        with patch.object(
            batch.grade, 'request_grade', side_effect=[ValueError('bad grade'), self.model_grade()]
        ) as request:
            self.assertEqual(batch.run_batch('model'), 1)
            self.assertEqual(request.call_count, 2)
            with job_history._database() as connection:
                connection.execute('UPDATE fit_batch_state SET next_allowed = 0')
            self.assertEqual(batch.run_batch('model'), 0)
            self.assertEqual(request.call_count, 2)

    def test_monitor_flag_tracks_failed_and_successful_jobs_through_cooldown(self):
        self.save('first')
        self.save('second')
        with patch.object(batch, 'GradeMonitor') as factory, patch.object(
            batch.grade, 'request_grade', side_effect=[ValueError('bad grade'), self.model_grade()]
        ):
            monitor = factory.return_value
            self.assertEqual(batch.run_batch('model', monitor_gpu=True), 1)
            monitor.start.assert_called_once()
            monitor.stop.wait.assert_called_once_with(5)
            self.assertEqual(monitor.begin_job.call_count, 2)
            self.assertEqual(monitor.end_job.call_args_list[0].args, ('failed',))
            monitor.cooldown.assert_called_once_with(600)
            monitor.finish.assert_called_once_with(True)
            self.assertIsNone(batch.CURRENT_MONITOR.get())
            # Cron polls during cooldown without creating another monitor.
            batch.run_batch('model', monitor_gpu=True)
            factory.assert_called_once()

    def test_disabled_monitoring_and_empty_queue_do_not_create_monitor(self):
        with patch.object(batch, 'GradeMonitor') as factory:
            batch.run_batch('model', monitor_gpu=True)
            self.save('job')
            with patch.object(batch.grade, 'request_grade', return_value=self.model_grade()):
                batch.run_batch('model')
            factory.assert_not_called()
    def test_interrupted_monitored_run_flushes_without_waiting_for_cooldown(self):
        self.save('job')
        with patch.object(batch, 'GradeMonitor') as factory, patch.object(
            batch.grade, 'request_grade', side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(KeyboardInterrupt):
                batch.run_batch('model', monitor_gpu=True)
            monitor = factory.return_value
            monitor.cooldown.assert_not_called()
            monitor.finish.assert_called_once_with(False)
            self.assertIsNone(batch.CURRENT_MONITOR.get())

    def test_cli_monitor_flag_is_forwarded(self):
        with patch.object(batch, 'PROJECT_DIR', self.root), patch.object(batch, 'run_batch', return_value=0) as run:
            self.assertEqual(batch.main(['--model', 'model', '--monitor-gpu']), 0)
            run.assert_called_once_with('model', monitor_gpu=True)
