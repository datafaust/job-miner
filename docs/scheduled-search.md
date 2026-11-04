# Scheduled job collection

Run `.venv/bin/python -m job_miner.cli.search_batch` from the repository root.
Use `--dry-run` to print commands without searching. The script reads the top-level
titles in `config/related_keys.json` each time it starts. Each title is searched
for `remote` and `nyc`, with Idealist sorted by both relevance and newest.
The sort option only affects Idealist; each invocation still searches all enabled
sources. Ten titles produce 40 searches per batch.

Scheduled collection uses `--no-summary`. Each search has a 900-second timeout,
configurable with `--timeout`. Failures are logged and the batch continues; its
exit status is nonzero if any searches failed. Previously processed postings are
handled by the existing search history.

`generated_search_requests/batch.lock` prevents overlapping batches, and the web
worker's `search.lock` serializes individual searches with web requests.
Logs are saved in `generated_search_requests/batch_logs/`. Remove old logs
periodically if disk usage grows.

Each batch records its start/end timestamps, status, saved-job counts, newly added
job IDs count, attempted/failed searches, and log path in the `search_runs` table
of `job_history.sqlite3`. The landing page shows the latest finished batch and
whether another is running. Counts include jobs saved by web searches during the
batch window. Interrupted batches are marked when the next batch starts; their
added-job count is unavailable. Existing logs are not backfilled into the table.

The installed user crontab runs once daily at 22:00 (10 p.m.), in the host's
America/New_York timezone (including daylight saving changes):

```cron
0 22 * * * cd /home/fausto/apps/job-miner && /home/fausto/apps/job-miner/.venv/bin/python -u -m job_miner.cli.search_batch >> /home/fausto/apps/job-miner/generated_search_requests/batch-cron.log 2>&1
```

Cron must be running and the host awake at that time. Inspect the schedule with
`crontab -l`; edit it with `crontab -e`. The CLI loads the repository's `.env`.

## Nightly availability audit

The installed user crontab also checks saved postings daily at 22:30 (10:30 p.m.)
in America/New_York, including daylight saving changes:

```cron
30 22 * * * cd /home/fausto/apps/job-miner && /usr/bin/flock -n /home/fausto/apps/job-miner/generated_search_requests/availability.lock /home/fausto/apps/job-miner/.venv/bin/python -u -m job_miner.cli.check_jobs --force >> /home/fausto/apps/job-miner/generated_search_requests/availability-cron.log 2>&1
```

`--force` ensures the evening audit runs even if earlier searches checked
those boards within the normal 24-hour cache window. `flock` prevents overlapping
scheduled audits. Results and request output append to
`generated_search_requests/availability-cron.log`. Missing postings still require
successful observations at least six hours apart before being marked closed.

## Nightly fit grading

The installed user crontab grades visible saved jobs daily at 23:00 (11 p.m.)
in America/New_York, including daylight saving changes:

```cron
0 23 * * * cd /home/fausto/apps/job-miner && /usr/bin/flock -n /home/fausto/apps/job-miner/generated_search_requests/grading.lock /home/fausto/apps/job-miner/.venv/bin/python -u -m job_miner.cli.grade --all --model qwen3.5-27b-16k:latest >> /home/fausto/apps/job-miner/generated_search_requests/grading-cron.log 2>&1
```

Uses the installed local Ollama model `qwen3.5-27b-16k:latest`. Ollama must be
running and the host awake. Jobs with unchanged postings, accomplishments, prompt
version, and model are skipped. Individual failures are logged and the batch
continues. `flock` prevents overlapping scheduled grading runs. Output appends to
`generated_search_requests/grading-cron.log`.

Each grading request sets Ollama's `keep_alive` to `0`, unloading the model
after the response so its prompt cache cannot accumulate across jobs. This adds
model loading time for each job. It reduces memory buildup between jobs but
does not guarantee that a single inference will fit in available RAM.
