"""Check the GUI worker's result and validation-failure status."""

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from job_tools import resume_web_tasks as tasks
from job_tools import resume_inputs
from resume_web_worker import SelectionCanceled, run


class ResumeWebWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task_dir = self.root / "task"
        self.task_dir.mkdir()
        tasks.write_status(self.task_dir, {
            "task_id": "test", "job_id": "greenhouse:123", "model": "qwen2.5:7b",
            "state": "queued", "created_at": tasks.now_utc(),
        })

    def test_validation_failure_reports_errors_and_no_selection(self):
        run_dir = self.root / "run"

        def prepare(posting, *, model, rewrite_mode):
            self.assertEqual((posting["job_id"], model, rewrite_mode),
                             ("greenhouse:123", "qwen2.5:7b", "none"))
            run_dir.mkdir()
            return run_dir

        def generate(path, *, on_progress):
            on_progress("Validating selection — attempt 2")
            (path / "validation_report.json").write_text(json.dumps({
                "valid": False, "errors": ["summary has too few words"]
            }), encoding="utf-8")
            raise ValueError("selection invalid")

        fake_cli = types.SimpleNamespace(prepare_run=prepare, generate_selection=generate)
        with patch.object(resume_inputs, "load_saved_posting", return_value={"job_id": "greenhouse:123"}), patch.dict(
            sys.modules, {"resume_cli": fake_cli}
        ):
            with self.assertRaises(ValueError):
                run(self.task_dir)
        status = tasks.read_status(self.task_dir)
        self.assertEqual(status["state"], "failed")
        self.assertIn("did not pass validation", status["message"])
        self.assertEqual(status["errors"], ["summary has too few words"])
        self.assertEqual(status["stage"], "Validating selection — attempt 2")
        self.assertNotIn("selection_file", status)

    def test_success_stops_at_review(self):
        status = tasks.read_status(self.task_dir)
        status["rewrite_mode"] = "targeted"
        tasks.write_status(self.task_dir, status)
        run_dir = self.root / "run"
        selection = self.root / "selection.json"

        def prepare(posting, *, model, rewrite_mode):
            self.assertEqual(rewrite_mode, "targeted")
            run_dir.mkdir()
            return run_dir

        def generate(path, *, on_progress):
            on_progress("Generating selection — attempt 1 of up to 2")
            self.assertEqual(tasks.read_status(self.task_dir)["stage"],
                             "Generating selection — attempt 1 of up to 2")
            on_progress("Building evidence report")
            selection.write_text("{}", encoding="utf-8")
            return selection

        fake_cli = types.SimpleNamespace(prepare_run=prepare, generate_selection=generate)
        with patch.object(resume_inputs, "load_saved_posting", return_value={"job_id": "greenhouse:123"}), patch.dict(
            sys.modules, {"resume_cli": fake_cli}
        ):
            run(self.task_dir)
        status = tasks.read_status(self.task_dir)
        self.assertEqual(status["state"], "ready_for_review")
        self.assertEqual(status["stage"], "Ready for review")
        self.assertEqual(status["selection_file"], str(selection))
        self.assertIn("Review it before rendering", status["message"])

    def test_canceled_worker_stays_canceled(self):
        run_dir = self.root / "run"

        def prepare(posting, *, model, rewrite_mode):
            run_dir.mkdir()
            return run_dir

        def generate(path, *, on_progress):
            on_progress("Generating selection — attempt 1 of up to 2")
            raise SelectionCanceled()

        fake_cli = types.SimpleNamespace(prepare_run=prepare, generate_selection=generate)
        with patch.object(resume_inputs, "load_saved_posting", return_value={"job_id": "greenhouse:123"}), patch.dict(
            sys.modules, {"resume_cli": fake_cli}
        ):
            run(self.task_dir)
        self.assertEqual(tasks.read_status(self.task_dir)["state"], "canceled")


if __name__ == "__main__":
    unittest.main()
