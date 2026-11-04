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

The installed user crontab also checks saved postings daily at 23:00 (11 p.m.)
in America/New_York, including daylight saving changes:

```cron
0 23 * * * cd /home/fausto/apps/job-miner && /usr/bin/flock -n /home/fausto/apps/job-miner/generated_search_requests/availability.lock /home/fausto/apps/job-miner/.venv/bin/python -u -m job_miner.cli.check_jobs --force >> /home/fausto/apps/job-miner/generated_search_requests/availability-cron.log 2>&1
```

`--force` ensures the evening audit runs even if earlier searches checked
those boards within the normal 24-hour cache window. `flock` prevents overlapping
scheduled audits. Results and request output append to
`generated_search_requests/availability-cron.log`. Missing postings still require
successful observations at least six hours apart before being marked closed.

## Paced fit grading

The user crontab polls every minute:

```cron
* * * * * cd /home/fausto/apps/job-miner && /home/fausto/apps/job-miner/.venv/bin/python -u -m job_miner.cli.grade_batch --model qwen3.5-27b-16k:latest --monitor-gpu >> /home/fausto/apps/job-miner/generated_search_requests/grading-cron.log 2>&1
```

The worker takes `generated_search_requests/grading.lock` internally; do not wrap
it in another flock on that path. Each batch attempts at most 10 grades and stops
starting requests after 300 seconds, letting the current request finish. SQLite
persists a 600-second cooldown after completion. Polling adds up to one minute.
A killed worker leaves a conservative reservation of the 1,200-second request
timeout plus cooldown from its last request start.

Visible never-graded jobs go first, then previously graded jobs, oldest saved first.
Unchanged inputs/model/prompt are skipped without consuming an attempt. Failed
jobs are deferred 24 hours, including if their inputs change during that interval.
Ollama must be running; each request retains `keep_alive: 0` to unload afterward.

The worker does not change GPU power or temperature limits and requires no sudo
permission.

Manual `job_miner.cli.grade --job` / `--all` retain their original behavior and
bypass batch pacing.

### Optional GPU monitoring

`--monitor-gpu` enables a background thread in the batch process using the
read-only NVIDIA NVML API (`nvidia-ml-py`, included in `requirements.txt`). Remove
that flag from the cron command to disable monitoring; no service or `.env`
change is required. Power and temperature settings are never modified.

A monitor starts only when the batch finds a job needing inference. It records a
five-second baseline before starting the grading time budget, samples GPU 0 about
once per second, and continues through the full ten-minute cooldown. The process
holds `grading.lock` throughout, so cron polls during that period exit immediately.
Without the flag, the worker exits after grading and SQLite still enforces the
same cooldown. Manual `job_miner.cli.grade` commands do not enable monitoring.

Each monitored batch creates a UTC timestamp/unique-ID directory under
`generated_search_requests/grading_logs/`, containing:

- `gpu.csv`: UTC timestamps, monotonic elapsed seconds, batch/job IDs, phase,
  power draw/limit, core temperature, utilization, VRAM used/total, fan percentage,
  SM/memory clocks, thermal/power throttling flags, and sensor errors.
- `events.jsonl`: batch policy and GPU identity/driver, job start/end and status,
  errors, Ollama load/prompt/generation durations (nanoseconds), token counts and
  generation tokens/second, and cooldown boundaries. Prompts, generated grades,
  and thinking text are not logged.
- `summary.json`: overall, grading-only, cooldown, and per-job statistics, estimated
  GPU watt-hours and measurement coverage, thermal throttling time, job durations,
  and temperatures near 1, 5, and 10 minutes of cooldown.

Raw CSV/events older than 30 days are removed when a new monitored batch starts;
summaries are retained. Logs flush after each record so interrupted runs preserve
samples/events; a forcibly killed process may leave no summary. Graceful Python
exceptions produce an incomplete summary and preserve the cooldown deadline.

Unavailable sensors are null/blank with errors rather than zero. Missing NVML or
log I/O errors are reported without preventing grading. Measurements describe the
whole GPU, including other applications, and one-second sampling misses brief
spikes. Watt-hours use trapezoidal integration over observed intervals up to five
seconds; missing samples and interval boundaries limit per-job estimates. Energy
per successful grade includes energy spent on failed attempts in the same batch.
