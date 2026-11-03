"""Collect every configured job title in a finite, cron-friendly batch."""
import argparse
import fcntl
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime

from job_miner.paths import PROJECT_DIR
from job_tools import search_runs


def search_commands(titles):
    for title in titles:
        for location in ("remote", "nyc"):
            for sort in ("relevance", "newest"):
                yield [sys.executable, "-u", "-m", "job_miner.cli.search",
                       "--no-summary", "--keywords", title, "--location", location,
                       "--idealist-sort", sort]


def run_search(command, log, timeout):
    # Kill the whole process group on timeout, including browser subprocesses.
    with subprocess.Popen(command, cwd=PROJECT_DIR, stdin=subprocess.DEVNULL,
                          stdout=log, stderr=subprocess.STDOUT,
                          start_new_session=True) as process:
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            print(f"Search timed out after {timeout} seconds", file=log, flush=True)
            return 124


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print commands without searching")
    parser.add_argument("--timeout", type=int, default=900, help="Seconds allowed per search (default: 900)")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    titles = json.loads((PROJECT_DIR / "config/related_keys.json").read_text())
    if not isinstance(titles, dict) or not titles or any(not title.strip() for title in titles):
        parser.error("related_keys.json must be a nonempty object with nonblank title keys")
    commands = list(search_commands(titles))
    if args.dry_run:
        for command in commands:
            print(shlex.join(command))
        return 0

    request_dir = PROJECT_DIR / "generated_search_requests"
    request_dir.mkdir(exist_ok=True)
    with (request_dir / "batch.lock").open("a") as batch_lock:
        try:
            fcntl.flock(batch_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another scheduled batch is active; skipping.")
            return 0
        log_dir = request_dir / "batch_logs"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".log")
        print(f"Batch log: {log_path}", flush=True)
        failures = 0
        with log_path.open("w", encoding="utf-8", buffering=1) as log:
            started = time.monotonic()
            print(f"Started {datetime.now().isoformat()}: {len(commands)} searches", file=log)
            run_id, before = search_runs.start_run(log_path)
            attempted = 0
            aborted = True
            try:
                for index, command in enumerate(commands, 1):
                    # Use the web worker's lock per search, allowing web requests between searches.
                    with (request_dir / "search.lock").open("a") as search_lock:
                        fcntl.flock(search_lock, fcntl.LOCK_EX)
                        print(f"\n[{index}/{len(commands)}] {datetime.now().isoformat()} {shlex.join(command)}", file=log)
                        search_started = time.monotonic()
                        attempted += 1
                        try:
                            code = run_search(command, log, args.timeout)
                        except OSError as error:
                            print(f"Could not launch search: {error}", file=log)
                            code = 1
                        failures += code != 0
                        print(f"Exit {code}; duration {time.monotonic() - search_started:.1f}s", file=log)
                aborted = False
            finally:
                added = search_runs.finish_run(run_id, before, attempted, failures, aborted)
                print(f"Run {run_id}: {added} jobs added during this batch", file=log)
            summary = (f"Finished {datetime.now().isoformat()}: {len(commands) - failures} succeeded, "
                       f"{failures} failed; duration {time.monotonic() - started:.1f}s")
            print(summary, file=log)
            print(summary)
        return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
