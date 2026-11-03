"""Persistent browser search requests (using the shared atomic status helpers)."""
from pathlib import Path

from job_tools.resume_web_tasks import now_utc, read_status, write_status
from job_miner.paths import PROJECT_DIR

TASK_ROOT = PROJECT_DIR / "generated_search_requests"
