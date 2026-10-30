"""Small persistent status files for resume selections started from the GUI."""

import json
from datetime import datetime, timezone
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
TASK_ROOT = PROJECT_DIR / "generated_resume_requests"


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def write_status(task_dir, status):
    task_dir = Path(task_dir)
    path = task_dir / "status.json"
    temporary = task_dir / "status.json.tmp"
    temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_status(task_dir):
    return json.loads((Path(task_dir) / "status.json").read_text(encoding="utf-8"))


def recent_for_job(job_id, *, root=None, limit=5):
    root = Path(root or TASK_ROOT)
    if not root.is_dir():
        return []
    matches = []
    for task_dir in root.iterdir():
        if not task_dir.is_dir():
            continue
        try:
            status = read_status(task_dir)
        except (OSError, ValueError):
            continue
        if status.get("job_id") == job_id:
            matches.append(status)
    return sorted(matches, key=lambda item: item.get("created_at", ""), reverse=True)[:limit]
