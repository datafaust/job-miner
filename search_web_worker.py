"""Run browser searches serially, always without summarization."""
import fcntl
import subprocess
import sys
from pathlib import Path

from job_tools import search_web_tasks as tasks

PROJECT_DIR = Path(__file__).resolve().parent


def run(task_dir):
    task_dir = Path(task_dir)
    status = tasks.read_status(task_dir)
    try:
        # Searches share output files and history; serialize browser requests.
        with (task_dir.parent / "search.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            status.update(state="running", started_at=tasks.now_utc())
            tasks.write_status(task_dir, status)
            with (task_dir / "search.log").open("w", encoding="utf-8") as log:
                result = subprocess.run(
                    [sys.executable, "-u", str(PROJECT_DIR / "main.py"),
                     "--no-summary", "--keywords=" + status["keywords"],
                     "--location=" + status["location"]],
                    cwd=PROJECT_DIR, stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT, check=False,
                )
            status.update(
                state="completed" if result.returncode == 0 else "failed",
                message=("Search finished. Open saved jobs to see newly collected postings. "
                         "Some sources may have been skipped or returned no matches."
                         if result.returncode == 0 else
                         "Search failed. Check search.log in this search's request directory for details. "
                         "Any postings already collected remain saved."),
            )
    except Exception:
        status.update(state="failed", message="The search worker could not complete the search. Check worker.log for details.")
        raise
    finally:
        status["finished_at"] = tasks.now_utc()
        tasks.write_status(task_dir, status)


if __name__ == "__main__":
    run(sys.argv[1])
