"""Telemetry correlation, missing sensors, summaries, and failure isolation."""
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_tools import grade_monitor as telemetry
from job_miner.cli import grade


class Reader:
    metadata = {'gpu_uuid': 'GPU-test', 'gpu_name': 'Test GPU', 'driver_version': 'test'}

    def sample(self):
        return {'power_w': 100, 'temperature_c': 60, 'gpu_util_pct': 80,
                'vram_used_mib': 1024, 'thermal_throttled': False}, {'fan_pct': 'Not Supported'}

    def close(self):
        pass


class MonitorTests(unittest.TestCase):
    def test_logs_correlate_gpu_jobs_and_ollama_without_prompt_content(self):
        with tempfile.TemporaryDirectory() as root:
            monitor = telemetry.GradeMonitor('test-model', root=root, reader_factory=Reader)
            # Exercise deterministic samples without creating a live thread.
            with patch.object(telemetry.threading.Thread, 'start'):
                monitor.start()
            monitor.thread = None
            monitor.sample()
            monitor.begin_job('job-1')
            monitor.sample()
            token = telemetry.CURRENT_MONITOR.set(monitor)
            try:
                telemetry.record_ollama_metrics({'eval_count': 10, 'eval_duration': 2_000_000_000,
                                                'response': 'private', 'thinking': 'private'})
            finally:
                telemetry.CURRENT_MONITOR.reset(token)
            monitor.end_job('graded')
            monitor.cooldown(0)
            monitor.sample()
            monitor.finish(True)
            monitor.reader.close()
            events = [json.loads(line) for line in (monitor.directory / 'events.jsonl').read_text().splitlines()]
            metric = next(row for row in events if row['event'] == 'ollama_result')
            self.assertEqual(metric['job_id'], 'job-1')
            self.assertEqual(metric['tokens_per_second'], 5)
            self.assertNotIn('response', metric)
            self.assertNotIn('thinking', metric)
            with (monitor.directory / 'gpu.csv').open() as handle:
                samples = list(csv.DictReader(handle))
            self.assertEqual([row['phase'] for row in samples], ['baseline', 'grading', 'cooldown'])
            self.assertIn('Not Supported', samples[1]['errors'])
            summary = json.loads((monitor.directory / 'summary.json').read_text())
            self.assertTrue(summary['completed'])
            self.assertEqual(summary['jobs'][0]['gpu']['power_w']['max'], 100)
            self.assertEqual(summary['grading']['samples_with_errors'], 1)

    def test_missing_nvml_still_records_events(self):
        with tempfile.TemporaryDirectory() as root:
            monitor = telemetry.GradeMonitor('model', root=root,
                reader_factory=lambda: (_ for _ in ()).throw(ImportError('missing NVML')))
            monitor.start()
            monitor.begin_job('job')
            monitor.end_job('failed', 'bad grade')
            monitor.finish(True)
            summary = json.loads((monitor.directory / 'summary.json').read_text())
            self.assertIsNone(summary['grading']['power_w'])
            self.assertIn('missing NVML', (monitor.directory / 'events.jsonl').read_text())

    def test_unwritable_log_directory_does_not_raise(self):
        with tempfile.TemporaryDirectory() as root:
            blocked = Path(root) / 'file'
            blocked.write_text('not a directory')
            monitor = telemetry.GradeMonitor('model', root=blocked, reader_factory=Reader)
            monitor.start()
            monitor.begin_job('job')
            monitor.end_job('graded')
            monitor.finish(True)

    def test_energy_excludes_missing_data_and_large_gaps(self):
        samples = [dict(elapsed_s=t, power_w=p, thermal_throttled=True) for t, p in
                   [(0, 100), (1, 200), (2, None), (20, 300)]]
        summary = telemetry.summarize(samples)
        self.assertAlmostEqual(summary['estimated_gpu_wh'], 150 / 3600)
        self.assertEqual(summary['energy_covered_seconds'], 1)
        self.assertEqual(summary['observed_thermal_throttling_seconds'], 2)

    def test_invalid_grade_retains_ollama_metrics(self):
        with patch.object(grade.requests, 'post') as post, patch.object(
            telemetry, 'CURRENT_MONITOR'
        ) as context:
            monitor = context.get.return_value
            post.return_value.json.return_value = {'response': 'invalid', 'eval_count': 12,
                                                    'eval_duration': 1_000_000_000}
            with self.assertRaises(json.JSONDecodeError):
                grade.request_grade('private prompt', 'model', {'A': 'evidence'})
            monitor.event.assert_called_once_with('ollama_result', eval_count=12,
                eval_duration=1_000_000_000, tokens_per_second=12)

    def test_retention_removes_old_raw_logs_but_keeps_summary(self):
        import os
        with tempfile.TemporaryDirectory() as root:
            old = Path(root) / '20200101T000000-1234abcd'
            old.mkdir()
            for name in ('gpu.csv', 'events.jsonl', 'summary.json'):
                path = old / name
                path.write_text('{}')
                os.utime(path, (0, 0))
            monitor = telemetry.GradeMonitor('model', root=root, reader_factory=Reader)
            with patch.object(telemetry.threading.Thread, 'start'):
                monitor.start()
            monitor.thread = None
            monitor.finish(True)
            monitor.reader.close()
            self.assertFalse((old / 'gpu.csv').exists())
            self.assertFalse((old / 'events.jsonl').exists())
            self.assertTrue((old / 'summary.json').exists())
