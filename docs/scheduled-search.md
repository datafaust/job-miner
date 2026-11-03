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

The installed user crontab runs at 08:00 and 15:00 daily, in the host's
America/New_York timezone (including daylight saving changes):

```cron
0 8,15 * * * cd /home/fausto/apps/job-miner && /home/fausto/apps/job-miner/.venv/bin/python -u -m job_miner.cli.search_batch >> /home/fausto/apps/job-miner/generated_search_requests/batch-cron.log 2>&1
```

Cron must be running and the host awake at those times. Inspect the schedule with
`crontab -l`; edit it with `crontab -e`. The CLI loads the repository's `.env`.
