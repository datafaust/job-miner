"""Run one GUI-requested selection outside the Flask request lifecycle."""

import json
import os
import signal
import sys
from pathlib import Path

from job_tools.resume_web_tasks import now_utc, read_status, write_status


class SelectionCanceled(Exception):
    pass


def run(task_dir):
    task_dir = Path(task_dir)
    status = read_status(task_dir)
    status.update(state="running", started_at=now_utc(), pid=os.getpid())
    write_status(task_dir, status)
    signal.signal(signal.SIGTERM, lambda _signum, _frame: _raise_canceled())

    def set_stage(stage):
        current = read_status(task_dir)
        if current.get("state") == "canceled":
            raise SelectionCanceled()
        current.update(stage=stage, stage_started_at=now_utc())
        write_status(task_dir, current)
        status.update(current)

    run_dir = None
    try:
        from job_tools.resume_inputs import load_saved_posting
        from resume_cli import generate_selection, prepare_run

        set_stage("Loading saved posting")
        posting = load_saved_posting(status["job_id"])
        set_stage("Preparing resume inputs")
        run_dir = prepare_run(posting, model=status["model"], rewrite_mode="light")
        status["run_dir"] = str(run_dir)
        write_status(task_dir, status)
        selection_path = generate_selection(run_dir, on_progress=set_stage)
        if read_status(task_dir).get("state") == "canceled":
            raise SelectionCanceled()
        status.update(
            state="ready_for_review", finished_at=now_utc(),
            stage="Ready for review",
            selection_file=str(selection_path),
            validation_report=str(run_dir / "validation_report.json"),
            evidence_report=str(run_dir / "evidence_report.md"),
            message="Selection passed structural validation. Review it before rendering a resume.",
        )
        write_status(task_dir, status)
    except SelectionCanceled:
        status = read_status(task_dir)
        status.update(state="canceled", finished_at=now_utc(), message="Selection canceled by user.")
        write_status(task_dir, status)
    except Exception as error:
        errors = []
        if run_dir is not None:
            report_path = run_dir / "validation_report.json"
            if report_path.is_file():
                try:
                    errors = json.loads(report_path.read_text(encoding="utf-8")).get("errors", [])
                except (OSError, ValueError):
                    pass
                status["validation_report"] = str(report_path)
        validation_failure = isinstance(error, ValueError) and bool(errors)
        if not errors:
            errors = [f"{type(error).__name__}: {error}"]
        status.update(
            state="failed", finished_at=now_utc(), errors=errors,
            message=(
                "A custom resume could not be made because the selection did not pass validation."
                if validation_failure else
                "A custom resume could not be made. The selection workflow failed."
            ),
        )
        write_status(task_dir, status)
        raise


def _raise_canceled():
    raise SelectionCanceled()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python resume_web_worker.py TASK_DIR")
    run(sys.argv[1])
