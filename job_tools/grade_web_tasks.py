"""Persistent manual fit-grading requests started from a job detail page."""
import os
from pathlib import Path

from job_miner.paths import PROJECT_DIR
from job_tools.resume_web_tasks import now_utc, read_status, write_status, recent_for_job

TASK_ROOT = PROJECT_DIR / 'generated_search_requests/fit_grades'
DEFAULT_MODEL = 'qwen3.5-27b-16k:latest'
ACTIVE_STATES = {'queued', 'running'}


def read_task(task_dir):
    status = read_status(task_dir)
    if status.get('state') in ACTIVE_STATES and status.get('pid'):
        try:
            os.kill(status['pid'], 0)
        except ProcessLookupError:
            status.update(state='failed', finished_at=now_utc(),
                          message='The grading worker stopped before finishing. You can try again.')
            write_status(task_dir, status)
    return status


def latest_for_job(job_id):
    matches = recent_for_job(job_id, root=TASK_ROOT, limit=1)
    return read_task(TASK_ROOT / matches[0]['task_id']) if matches else None
