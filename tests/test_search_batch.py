"""Exercise batch failures and locking without fetching job boards."""
import fcntl
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_miner.cli import search_batch
from job_tools import job_history, search_runs


class SearchBatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "config").mkdir()
        (self.root / "config/related_keys.json").write_text(json.dumps({"data analyst": {}}))
        patcher = patch.object(search_batch, "PROJECT_DIR", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        database_patch = patch.object(job_history, "HISTORY_DB_PATH", self.root / "history.sqlite3")
        database_patch.start()
        self.addCleanup(database_patch.stop)

    @patch.object(search_batch, "run_search", side_effect=[1, 0, 124, 0])
    def test_failures_do_not_stop_remaining_searches(self, run):
        self.assertEqual(search_batch.main([]), 1)
        self.assertEqual(run.call_count, 4)
        combinations = {(call.args[0][-3], call.args[0][-1]) for call in run.call_args_list}
        self.assertEqual(combinations, {("remote", "relevance"), ("remote", "newest"),
                                       ("nyc", "relevance"), ("nyc", "newest")})
        log = next((self.root / "generated_search_requests/batch_logs").glob("*.log"))
        self.assertIn("2 succeeded, 2 failed", log.read_text())
        latest, running = search_runs.latest_runs()
        self.assertFalse(running)
        self.assertEqual(latest["status"], "partial_failure")
        self.assertEqual(latest["searches_attempted"], 4)
        self.assertEqual(latest["searches_failed"], 2)

    @patch.object(search_batch, "run_search")
    def test_existing_batch_is_skipped(self, run):
        folder = self.root / "generated_search_requests"
        folder.mkdir()
        with (folder / "batch.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(search_batch.main([]), 0)
        run.assert_not_called()
        self.assertEqual(search_runs.latest_runs(), (None, False))

    def test_new_ids_are_counted_even_when_old_jobs_are_deleted(self):
        job_history.record_processed("https://example.com/old", "old.txt")
        run_id, before = search_runs.start_run("batch.log")
        with job_history._database() as connection:
            connection.execute("DELETE FROM processed_jobs")
        job_history.record_processed("https://example.com/new", "new.txt")
        self.assertEqual(search_runs.finish_run(run_id, before, 4, 0), 1)
        latest, running = search_runs.latest_runs()
        self.assertEqual((latest["jobs_before"], latest["jobs_after"]), (1, 1))
        self.assertEqual(latest["status"], "completed")

    def test_abandoned_run_is_interrupted_on_next_start(self):
        search_runs.start_run("old.log")
        search_runs.start_run("new.log")
        latest, running = search_runs.latest_runs()
        self.assertTrue(running)
        self.assertEqual(latest["status"], "interrupted")
        self.assertIsNone(latest["jobs_added"])

    @patch.object(search_batch, "run_search", side_effect=RuntimeError("unexpected"))
    def test_unexpected_error_finalizes_run(self, run):
        with self.assertRaises(RuntimeError):
            search_batch.main([])
        latest, running = search_runs.latest_runs()
        self.assertFalse(running)
        self.assertEqual(latest["status"], "failed")

    def test_timeout_stops_child_process(self):
        import sys
        with (self.root / "timeout.log").open("w") as log:
            self.assertEqual(search_batch.run_search(
                [sys.executable, "-c", "import time; time.sleep(30)"], log, 0.1), 124)


if __name__ == "__main__":
    unittest.main()
