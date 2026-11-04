"""Run a bounded fit-grading batch with persistent cooldown."""
import argparse
import fcntl
import hashlib
import sys
import time


from job_miner.cli import grade
from job_miner.paths import PROJECT_DIR
from job_tools import job_history
from job_tools.grade_monitor import CURRENT_MONITOR, GradeMonitor
from job_tools.resume_inputs import load_saved_posting

BATCH_SIZE = 10
ACTIVE_SECONDS = 300
COOLDOWN_SECONDS = 600
FAILURE_RETRY_SECONDS = 86400


def initialize_state():
    with job_history._database() as connection:
        connection.execute('''CREATE TABLE IF NOT EXISTS fit_batch_state (
            id INTEGER PRIMARY KEY CHECK (id = 1), next_allowed REAL NOT NULL)''')
        connection.execute('''CREATE TABLE IF NOT EXISTS fit_batch_failures (
            job_key TEXT PRIMARY KEY, retry_after REAL NOT NULL)''')


def run_batch(model, monitor_gpu=False):
    initialize_state()
    with job_history._database() as connection:
        row = connection.execute('SELECT next_allowed FROM fit_batch_state WHERE id = 1').fetchone()
        if row and time.time() < row[0]:
            print('Fit grading cooldown active; skipping.', flush=True)
            return 0
        jobs = connection.execute('''SELECT p.job_key FROM processed_jobs p
            LEFT JOIN job_fit_grades g USING (job_key)
            LEFT JOIN fit_batch_failures f USING (job_key)
            WHERE p.hidden_at IS NULL AND (f.retry_after IS NULL OR f.retry_after <= ?)
            ORDER BY (g.job_key IS NOT NULL), p.processed_at ASC, p.job_key''', (time.time(),)).fetchall()
    inventory_bytes = grade.INVENTORY_PATH.read_bytes()
    inventory = grade.yaml.safe_load(inventory_bytes)
    inventory_hash = hashlib.sha256(inventory_bytes).hexdigest()
    evidence = grade.inventory_evidence(inventory)
    attempted = failed = 0
    started = None
    monitor = token = None
    completed = False
    try:
        for (job_id,) in jobs:
            if attempted >= BATCH_SIZE or (started is not None and time.monotonic() - started >= ACTIVE_SECONDS):
                break
            try:
                # Filter unchanged jobs before spending an attempt.
                posting = load_saved_posting(job_id)
                with job_history._database() as connection:
                    previous = connection.execute('''SELECT model, posting_sha256,
                        inventory_sha256, prompt_version FROM job_fit_grades WHERE job_key = ?''',
                        (job_id,)).fetchone()
                if previous == (model, posting['posting_sha256'], inventory_hash, grade.PROMPT_VERSION):
                    continue
            except (OSError, ValueError) as error:
                print(f'{job_id}: cannot load posting: {error}', file=sys.stderr)
                with job_history._database() as connection:
                    connection.execute('INSERT OR REPLACE INTO fit_batch_failures VALUES (?, ?)',
                                       (job_id, time.time() + FAILURE_RETRY_SECONDS))
                failed += 1
                continue
            if started is None:
                if monitor_gpu:
                    monitor = GradeMonitor(model)
                    monitor.start()
                    monitor.event('batch_policy', batch_size=BATCH_SIZE, active_seconds=ACTIVE_SECONDS,
                                  cooldown_seconds=COOLDOWN_SECONDS, prompt_version=grade.PROMPT_VERSION,
                                  inventory_sha256=inventory_hash)
                    token = CURRENT_MONITOR.set(monitor)
                    # Keep the baseline outside the five-minute grading budget.
                    monitor.stop.wait(5)
                started = time.monotonic()
            attempted += 1
            # Reserve cooldown before inference too, so a killed worker cannot immediately restart.
            with job_history._database() as connection:
                connection.execute('INSERT OR REPLACE INTO fit_batch_state VALUES (1, ?)',
                                   (time.time() + 1200 + COOLDOWN_SECONDS,))
            if monitor:
                monitor.begin_job(job_id)
            try:
                status, result = grade.grade_job(job_id, model=model, inventory=inventory,
                    inventory_hash=inventory_hash, evidence=evidence)
                if monitor:
                    monitor.end_job(status)
                print(f'{job_id}: {status}' + (f" {result['score']} {result['tier']}" if result else ''), flush=True)
                with job_history._database() as connection:
                    connection.execute('DELETE FROM fit_batch_failures WHERE job_key = ?', (job_id,))
            except (OSError, ValueError, grade.requests.RequestException, grade.yaml.YAMLError) as error:
                if monitor:
                    monitor.end_job('failed', error=str(error))
                failed += 1
                print(f'{job_id}: failed: {error}', file=sys.stderr, flush=True)
                with job_history._database() as connection:
                    connection.execute('INSERT OR REPLACE INTO fit_batch_failures VALUES (?, ?)',
                                       (job_id, time.time() + FAILURE_RETRY_SECONDS))
        completed = True
    finally:
        try:
            if started is not None:
                with job_history._database() as connection:
                    connection.execute('INSERT OR REPLACE INTO fit_batch_state VALUES (1, ?)',
                                       (time.time() + COOLDOWN_SECONDS,))
        finally:
            if monitor:
                monitoring_completed = False
                try:
                    if completed:
                        monitor.cooldown(COOLDOWN_SECONDS)
                        monitoring_completed = True
                finally:
                    CURRENT_MONITOR.reset(token)
                    monitor.finish(monitoring_completed)
    print(f'Fit batch: {attempted} attempted; {failed} failed.', flush=True)
    return int(bool(failed))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--monitor-gpu', action='store_true',
                        help='Log GPU samples and job timings through grading and cooldown')
    args = parser.parse_args(argv)
    if not args.model.strip():
        parser.error('--model cannot be blank')
    directory = PROJECT_DIR / 'generated_search_requests'
    directory.mkdir(exist_ok=True)
    with (directory / 'grading.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another grading batch is active; skipping.')
            return 0
        try:
            return run_batch(args.model.strip(), monitor_gpu=args.monitor_gpu)
        except (OSError, ValueError, RuntimeError) as error:
            print(f'Fit batch stopped: {error}', file=sys.stderr)
            return 1


if __name__ == '__main__':
    sys.exit(main())
