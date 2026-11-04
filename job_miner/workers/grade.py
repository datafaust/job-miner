"""Run one requested fit grade, sharing the scheduled grader's lock and cooldown."""
import fcntl
import hashlib
import os
from pathlib import Path
import sys
import time

from job_miner.cli import grade, grade_batch
from job_tools import grade_web_tasks as tasks
from job_tools import job_history


def run(task_dir):
    task_dir = Path(task_dir)
    # Protect against accidentally launching the same request more than once.
    with (task_dir / 'worker.lock').open('a') as request_lock:
        try:
            fcntl.flock(request_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        status = tasks.read_status(task_dir)
        if status['state'] not in tasks.ACTIVE_STATES:
            return
        status['pid'] = os.getpid()
        tasks.write_status(task_dir, status)
        attempted = False
        try:
            grade_batch.initialize_state()
            with (task_dir.parent.parent / 'grading.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                # Hold the shared lock while waiting so a scheduled batch cannot jump ahead.
                while True:
                    with job_history._database() as connection:
                        row = connection.execute('SELECT next_allowed FROM fit_batch_state WHERE id = 1').fetchone()
                    remaining = row[0] - time.time() if row else 0
                    if remaining <= 0:
                        break
                    time.sleep(min(remaining, 30))
                status.update(state='running', started_at=tasks.now_utc(),
                              message='Grading this job. This may take several minutes.')
                tasks.write_status(task_dir, status)
                try:
                    inventory_bytes = grade.INVENTORY_PATH.read_bytes()
                    inventory = grade.yaml.safe_load(inventory_bytes)
                    with job_history._database() as connection:
                        connection.execute('INSERT OR REPLACE INTO fit_batch_state VALUES (1, ?)',
                            (time.time() + 1200 + grade_batch.COOLDOWN_SECONDS,))
                    attempted = True
                    _, result = grade.grade_job(status['job_id'], model=status['model'],
                        inventory=inventory, inventory_hash=hashlib.sha256(inventory_bytes).hexdigest(),
                        evidence=grade.inventory_evidence(inventory), force=True)
                    with job_history._database() as connection:
                        connection.execute('DELETE FROM fit_batch_failures WHERE job_key = ?', (status['job_id'],))
                    status.update(state='completed', score=result['score'], tier=result['tier'],
                                  message='Fit grade saved. Open the job to review the assessment.')
                finally:
                    if attempted:
                        with job_history._database() as connection:
                            connection.execute('INSERT OR REPLACE INTO fit_batch_state VALUES (1, ?)',
                                               (time.time() + grade_batch.COOLDOWN_SECONDS,))
        except Exception as error:
            status.update(state='failed', message='Fit grading failed. Any previous grade is preserved.', error=str(error))
            if attempted:
                with job_history._database() as connection:
                    connection.execute('INSERT OR REPLACE INTO fit_batch_failures VALUES (?, ?)',
                                       (status['job_id'], time.time() + grade_batch.FAILURE_RETRY_SECONDS))
        finally:
            status['finished_at'] = tasks.now_utc()
            tasks.write_status(task_dir, status)


if __name__ == '__main__':
    run(sys.argv[1])
