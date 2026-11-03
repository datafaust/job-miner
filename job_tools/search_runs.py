"""Persist scheduled batch outcomes in the existing job history database."""
import sqlite3
from datetime import datetime, timezone

from job_tools.job_history import _database


def now():
    return datetime.now(timezone.utc).isoformat()


def start_run(log_path):
    """Call only while holding the batch lock; older running rows are abandoned."""
    with _database() as connection:
        connection.execute("UPDATE search_runs SET status='interrupted', finished_at=? "
                           "WHERE status='running'", (now(),))
        before = {row[0] for row in connection.execute("SELECT job_key FROM processed_jobs")}
        cursor = connection.execute(
            "INSERT INTO search_runs (started_at, status, jobs_before, log_path) "
            "VALUES (?, 'running', ?, ?)", (now(), len(before), str(log_path)))
        return cursor.lastrowid, before


def finish_run(run_id, before, attempted, failed, aborted=False):
    with _database() as connection:
        after = {row[0] for row in connection.execute("SELECT job_key FROM processed_jobs")}
        status = ('failed' if aborted or (attempted and failed == attempted) else
                  'partial_failure' if failed else 'completed')
        added = len(after - before)
        connection.execute(
            "UPDATE search_runs SET finished_at=?, status=?, jobs_after=?, jobs_added=?, "
            "searches_attempted=?, searches_failed=? WHERE id=?",
            (now(), status, len(after), added, attempted, failed, run_id))
        return added


def latest_runs():
    with _database() as connection:
        connection.row_factory = sqlite3.Row
        latest = connection.execute(
            "SELECT * FROM search_runs WHERE status != 'running' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        running = connection.execute(
            "SELECT 1 FROM search_runs WHERE status='running' LIMIT 1"
        ).fetchone()
        return dict(latest) if latest else None, bool(running)
