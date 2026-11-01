"""Persistent browser search requests (using the shared atomic status helpers)."""
from pathlib import Path

from job_tools.resume_web_tasks import now_utc, read_status, write_status

TASK_ROOT = Path(__file__).resolve().parent.parent / "generated_search_requests"
