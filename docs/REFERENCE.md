# Job Miner reference

Workflow, configuration, storage, and troubleshooting details for maintainers and agents. For setup and common commands, see the [README](../README.md).

## Browse saved jobs

From the repository root, with the virtual environment active:

```bash
python -m pip install -r requirements.txt
python -m job_miner.web.app
```

Open `http://127.0.0.1:5055`. Use `--port` to change the port; Ctrl+C stops the frontend. It reads saved postings from `job_history.sqlite3` and their source files; collect jobs with **New job search** or `job_miner/cli/search.py`. Browsing does not require Ollama. Styling is local, and the server binds to localhost by default.

- **New job search** beside the heading requires keywords and location (NYC or remote). Confirm with **Start search**. Browser searches always run `python -m job_miner.cli.search --no-summary`; the frontend cannot enable summarization. Idealist uses search order without calling Ollama. The status page shows a loading indicator and elapsed time, refreshing every five seconds. Use **View saved jobs** to see results. Searches continue in a separate worker if the page or frontend closes, and browser requests queue one at a time. Status and logs are saved under `generated_search_requests/`.
- Search titles/companies, filter source or work arrangement, and browse 25 jobs per page. Click a row for the saved posting, source details, and AI result.
- **Posted** shows the source date or saved relative label (e.g. “Published 2 days ago,” which does not update). **Saved (UTC)** shows the collection date. **Resume Generated** shows ✓ after a successful render.
- The trash icon asks for confirmation before hiding a job. Its database record and artifacts remain, so later searches still skip it. Hidden jobs are excluded from list counts; there is currently no restore control.
- Use the star on a saved job or its detail page to mark it as a favorite. Select **Favorites only** in the **Favorites** filter; combine it with **Not applied** to see important jobs still awaiting an application. Click the filled star to remove the favorite.
- On a job's detail page, **Application status** lets you choose an application date (today by default) and **Mark as applied**. You can update the date or **Mark as not applied** to undo it. Dates are saved locally and must be on or before today. The saved-jobs table shows the status/date, supports sorting by **Application**, and filters by **All jobs**, **Not applied**, or **Applied**. Application tracking does not require Ollama.
- To create a resume, start Ollama, open a posting, choose an installed text-generation model and **Bullet mode**, then confirm. **No changes** (default) preserves bullets; **Light edits** adjusts phrasing; **Targeted edits** allows more restructuring while preserving facts.
- The selection status page refreshes every five seconds and shows progress, errors, and **Cancel selection**. Stopping the frontend does not stop its separate selection worker. Recent attempts appear on the posting page.
- After validation, review the selection/evidence files at the displayed paths; browser editing is not implemented. Click **Generate resume** on the posting or successful selection page to render and download a Word document using `templates/resume-template.docx`. Rendering needs no model call.

Each render saves a new file under `generated_resumes/` with the same download filename: `resume-<UTC timestamp>-<selection task ID>-<unique render ID>.docx`. Existing documents are retained. Selection inputs and reports remain under `generated_resume_runs/` and `generated_selections/`.

## Resume selection

The separate resume workflow begins with `job_miner/cli/resume.py`. It loads one saved posting or a local `.json`/`.txt` posting, then asks a local Ollama model through CrewAI to produce a job-specific selection JSON. It produces a selection JSON for review; render it separately with `job_miner/cli/render.py`.

```bash
python -m job_miner.cli.resume --job-id greenhouse:8172487 --model qwen2.5:7b --rewrite-mode light
python -m job_miner.cli.resume --posting-file /path/to/posting.txt --job-title "Data Engineer" --job-url https://example.com/jobs/123 --model openhermes
```

`--job-id` accepts the stable IDs displayed by `python -m job_miner.cli.search --saved-summaries`; `--posting-file` accepts a saved source JSON or a plain text posting. For plain text, the first nonempty line is used as the title unless `--job-title` is supplied. A local posting without a URL receives a content-derived `local:` ID and a null URL. `--model` defaults to `openhermes`, as in `job_miner/cli/search.py`; `--rewrite-mode` accepts `none`, `light` (default), or `targeted`. The browser’s Bullet mode dropdown offers the same modes and defaults to No changes (`none`).

The selector requests an 8,192-token Ollama context and lets Ollama generate until the model stops (`num_predict=-1`). A 20-minute request timeout remains in place. These settings are recorded in each run manifest.

Each run creates `generated_resume_runs/<job-id>/<timestamp>/` with `posting.txt`, `inventory.yaml`, `prompt.md`, `manifest.json`, `validation_report.json`, and the raw model reply when available. The manifest records the source URL, title, job ID, source and posting hashes, inventory and prompt hashes, model, rewrite mode, prompt version, and generation status. Valid selections are saved to `generated_selections/<job-id>_<timestamp>_selection.json`. Those runs also get `evidence_report.json` and a readable `evidence_report.md` beside the manifest. Both directories are ignored by Git because they contain personal resume data and job postings.

Parsing or structural validation failures trigger one automatic repair attempt with the rejected response and specific errors. Each attempt retains `selection_raw_attempt_N.txt` and `validation_report_attempt_N.json`; `selection_raw.txt` contains the latest reply. Model request failures and evidence review flags do not trigger retries. If the repair also fails, no validated selection is saved.

Validation checks JSON shape, source IDs and ownership, ordering, duplicates, bullet minimums, summary length and `SUM-001`, skill categories, exact certification text, and unverified date overrides. Invalid output leaves its raw reply and all detected errors in the run directory; it does not produce a selection or DOCX. The direct `job_miner/cli/render.py` entry point applies the same structural checks before opening the template. The evidence report extracts labelled job requirements and suggests selected accomplishment IDs based on shared words. It also flags new numbers, technical terms, technology-specific tenure, weak wording overlap in AI-authored prose, and skill items missing from their inventory category. These are leads for human review, not a factual proof or an AI score. Review the generated wording against the original inventory and posting before rendering.

## What happens during a run

1. [`job_miner/cli/search.py`](../job_miner/cli/search.py) visits each board in [`config/greenhouse_boards.json`](../config/greenhouse_boards.json) and fetches its jobs with full descriptions. The entered `nyc` or `remote` choice filters Greenhouse jobs by their published location labels before ranking. Configured roles also pass through the relevance check described below. Candidates from different boards are taken in rounds, with **at most two Greenhouse jobs summarized per run** across all boards by default. A failed board request is reported, and the search continues through the remaining boards and Idealist.
2. Each processed Greenhouse job's complete API listing is saved as `jobs/JOB_greenhouse_<board-token>_<id>.json`. Its text is given to the organizer, and its Greenhouse ID is recorded in history. Other Greenhouse postings remain eligible for later runs.
   Lever boards run next with the same location choices and a separate cap of two summaries. Their saved API listings are `jobs/JOB_lever_<site>_<id>.json`. Ashby boards in [`config/ashby_boards.json`](../config/ashby_boards.json) then run with their own cap of two summaries; saved listings are `jobs/JOB_ashby_<board>_<id>.json`.
3. For `nyc`, the Idealist search adds `New York City` to the keywords; this is a keyword preference, not a strict location filter. For `remote`, it uses Idealist's Remote location-type filter with the original keywords. The search defaults to Best Match; `--idealist-sort newest` puts recently posted jobs first. It reports how many listings it recovered and how many remain after filtering local history, writes the remaining listings to `output.json`, and returns up to 1,000 unprocessed listings with the current configuration.
4. The selection agent in [`job_miner/search/agents.py`](../job_miner/search/agents.py) recommends the first Idealist listing to process. With `--no-summary`, the workflow skips that agent and uses search order. The detail tool expands postings and checks configured-role relevance before saving them as `jobs/JOB_idealist_<id>.txt` and recording them in history. With the current configuration, the workflow saves up to 1,000 Idealist jobs per run, considering the rest of the shortlist in search order.
5. For each selected posting, the organizer receives the actual posting text and can write a summary or say that a summary is unnecessary. Its decision is saved in `job_history.sqlite3`. The terminal prints the source URL, search listing, decision, and original posting text.
6. A separate, rule-based extractor saves source-backed title, company, salary range, posting date or source age, work arrangement, and location in the `prospective_jobs` table. It runs when a posting is saved, independently of the AI summary.

All saved job files go into the main `jobs/` folder in the directory where you run the command. Greenhouse postings are `JOB_greenhouse_*.json`, Lever postings are `JOB_lever_*.json`, Ashby postings are `JOB_ashby_*.json`, Adzuna postings are `JOB_adzuna_*.json`, Remote OK postings are `JOB_remoteok_*.json`, Remotive postings are `JOB_remotive_*.json`, and Idealist postings are `JOB_idealist_*.txt`. The folder is created if needed, and these files are ignored by Git. The search snapshot `output.json` remains in the directory where you run the command. Idealist uses Selenium; the other sources use APIs.

### Workflow limits

Edit [`config/workflow_limits.json`](../config/workflow_limits.json) to change per-run job caps. `idealist_candidates_per_run` controls how many filtered Idealist search results reach the workflow; `idealist_jobs_per_run` controls how many of that shortlist can be saved and summarized. Each API source, including Adzuna, has its own saved-job cap. Values must be positive integers, and Idealist's saved-job cap cannot exceed its candidate cap. The file is read when a Python run starts, so rerun the command after editing it. API request cooldowns are separate from these job caps.

### Role relevance

[`config/related_keys.json`](../config/related_keys.json) defines relevance profiles for configured role searches. A primary title phrase passes directly. A related title phrase or supporting title term needs at least two distinct description signals in the posting's responsibilities. A title with no configured title signal needs three distinct responsibility signals. Matching ignores case and punctuation and uses whole words. The filter prefers explicitly headed responsibility sections and excludes qualification sections; when no such headings exist, it checks the introductory description text.

For these configured roles, relevance is checked before per-source summary limits and before saving. Idealist opens returned listings and checks the full posting before persistence. Rejected postings are not marked processed, so changing the config can make them eligible on a later run. Search requests without a configured role keep the previous keyword matching behavior. Add a role profile to enable the stricter rule for that search.

The Greenhouse board config has one `{"company": "Name", "token": "board-token"}` entry per company. Uncomment a line to include that board in the next run, or comment an active line to skip it. Each run requests every active board in config order. The company name appears in search listings, while the token is used for the API request and saved filename. The loader accepts whole-line `//` comments and a trailing comma before the closing bracket.

Greenhouse, Lever, and Ashby board requests use a shared 0.25-second minimum interval and retry temporary network errors, HTTP 429, and common HTTP 5xx responses up to three attempts. A `Retry-After` header is honored when it asks for at most 30 seconds; longer waits leave that board failed so the run can continue. Set `JOB_BOARD_REQUEST_INTERVAL_SECONDS` in `.env` to change the interval (use `0` to disable it).

### Lever searches

The workflow requests each board in [`config/lever_boards.json`](../config/lever_boards.json) for both `nyc` and `remote` searches. Palantir is active by default. Add `{"company": "Name", "site": "board-slug"}` for a Lever board, or set `"eu": true` for a `jobs.eu.lever.co` board. Find the slug in the company's `jobs.lever.co/<slug>` URL. A failed board request does not stop the remaining sources. Lever jobs are filtered by location and ranked locally, with at most two unprocessed postings summarized per run across all Lever boards. Saved files include the complete API response plus `_job_miner_company` for prospect extraction; the organizer receives the description, section lists, and additional text. Lever posting IDs are used for history, so apply links and posting links identify the same job.

Ashby boards are configured in [`config/ashby_boards.json`](../config/ashby_boards.json); Ramp and Notion are active by default. Add `{"company": "Name", "board": "board-slug"}` using the slug from `jobs.ashbyhq.com/<board-slug>`. Each board is fetched once with compensation included. The workflow skips unlisted jobs, filters location locally, and ranks title matches before description matches using the entered keywords. For `nyc`, it checks primary and secondary locations, including structured city fields. For `remote`, it requires `workplaceType: Remote` and an explicit unrestricted, US, or NYC remote location; hybrid roles are excluded even when Ashby sets `isRemote: true`. Ambiguous and foreign-only remote locations are skipped. Ashby has no server-side keyword or location filters, and the current workflow only accepts `nyc` or `remote` as inputs. Adjust `ashby_jobs_per_run` in [`config/workflow_limits.json`](../config/workflow_limits.json) to change its independent summary cap.

### Adzuna searches

Register at [Adzuna Developer](https://developer.adzuna.com/) and set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` in `.env` (see [`.env.example`](../.env.example)). Without both, the workflow skips Adzuna. Each run requests up to two pages of 50 recent US jobs, sorted by date; a short first page ends the search, and a failed second page leaves the first page available. `nyc` searches use `where=New York, NY` and check the returned location label. `remote` searches include the `remote hybrid` keywords and require a remote or hybrid signal in the returned title, location, or description snippet. Adzuna has no dedicated remote flag, so check the source listing before relying on that classification. The `adzuna_jobs_per_run` limit controls how many unprocessed matches are saved. The response contains only a description snippet, which is what the organizer receives. Saved listings and output credit [The Adzuna API](https://www.adzuna.com/) and preserve its redirect link. Predicted salaries are marked as Adzuna estimates in the prospect export. Adzuna API use is subject to its [terms and account limits](https://developer.adzuna.com/docs/terms_of_service).

### Remote OK searches

When the selected location is `remote`, the workflow also searches the [Remote OK public feed](https://remoteok.com/faq). It fetches the full feed and filters keywords locally, then saves and summarizes up to two unprocessed matches. Selected API listings are stored as `jobs/JOB_remoteok_<id>.json`. Their output includes “Remote OK” credit and a link to the original Remote OK posting.

The `remoteok_api_calls` table in `job_history.sqlite3` records every outbound attempt, including failures. The `remoteok_feed_cache` table holds the latest successful full feed. A new request is allowed after 90 minutes; runs during the cooldown search the cached feed. The gate also enforces at most 10 attempted requests in a rolling hour. This assumes a stable outbound IP and that this program is the only Remote OK client using it. Without a cached feed, a run during cooldown returns no Remote OK jobs.

### Remotive searches

For `remote` searches, the workflow also fetches the [Remotive public API](https://remotive.com/api/remote-jobs) without filters and matches keywords locally. It saves and summarizes up to two unprocessed jobs per run. Each selected listing is saved as `jobs/JOB_remotive_<id>.json`, and displayed results credit Remotive and link to the original posting. Remotive listings are delayed by 24 hours at the source. Do not republish these jobs to another job board.

The `remotive_api_calls` table records outbound attempts, including failures; `remotive_feed_cache` stores successful responses by API parameter set. The request gate reuses a feed for six hours, keeps requests at least 31 seconds apart, and allows at most four attempts per rolling 24 hours. A failed request falls back to the last cached response for those parameters. Without a cached response, a gated or failed request returns no jobs. This assumes this program is the only Remotive client using the same outbound IP. The optional `search`, `category`, `company_name`, and `limit` arguments are available on `fetch_remotive_jobs` for direct use; each parameter set has a separate cache entry but shares the request gate.

### Job history

Processed jobs are stored in `job_history.sqlite3` in the repository root. The history survives later runs and is ignored by Git. Keys use the stable Idealist posting ID, Greenhouse `gh_jid`, or Lever posting ID; otherwise they use the URL's host and path without tracking parameters. Titles alone are not unique.

`output.json` remains a snapshot of the latest search's unprocessed results and is overwritten on the next search. A job is not added to the history merely because it appeared in search results. If a detail scrape fails or the agent does not choose that job, it remains eligible for a later run. The detail tool also checks the history before opening a previously processed URL. Keep a copy of `job_history.sqlite3` if you need to carry the history to another machine.

The existing `output.json` is not imported into the history, because it contains search results that may never have been scraped. History tracking starts when a detail scrape succeeds with this version of the code.

### Prospective job list

`prospective_jobs` is the working list for a future document or spreadsheet. It has one row per saved posting and can be updated without duplicating jobs. Missing salary or remote information stays empty or `unknown`; a city name alone is not treated as on-site. Greenhouse uses its exact `first_published` timestamp for `posted_at`. Lever uses `createdAt`, `salaryRange`, `workplaceType`, and the board's configured company name. Remotive uses `publication_date`, `salary`, and `candidate_required_location` from its API. Idealist currently supplies only a relative label such as `Published 7 days ago`, saved as `posted_text`, so read it alongside `source_saved_at` rather than as a current age. `remote_status` is one of `remote`, `hybrid`, `on_site`, or `unknown`. Exported rows include a source label and the original URL.

To refresh facts from all existing source files and export the list as JSON:

```sh
python -m job_tools.prospects backfill
python -m job_tools.prospects export
```

The second command writes `prospective_jobs.json` in the current directory. It does not contact Google or run an AI agent. The extractor uses explicit source fields and labels; an AI extraction step can be added later for ambiguous postings, with its proposed values checked against the source before saving.

To add a job by hand, open the local saved-jobs browser (`python -m job_miner.web.app`) and click **Add job**. In the popup, enter the original listing URL and paste the posting. Lines such as `Job title:`, `Company:`, `Location:`, `Salary:`, and `Date posted:` help the parser identify facts. The full paste is saved for the detail page and resume tailoring. Unclear or missing facts remain empty; work arrangement is `unknown` unless the posting explicitly identifies it. A duplicate listing URL will not create another row.

#### Add jobs to a worksheet in Google Drive

Install the dependencies in `requirements.txt`, then enable both the [Google Drive API](https://developers.google.com/workspace/drive/api/quickstart/python) and [Google Sheets API](https://developers.google.com/workspace/sheets/api/quickstart/python) in a Google Cloud project. Configure the OAuth consent screen, add your Google account as a test user if the app is External and in testing, and create a **Desktop app OAuth client**. Download its JSON to `credentials.json` in this repository. This is an OAuth client ID and secret, not an API key; an API key cannot update your private Drive files. This command uses the [Drive `drive` scope](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) so it can access an existing file you created yourself. Keep the client JSON and saved token private.

To use an existing Google Sheet or `.xlsx` file in Drive, copy the file ID from its URL (`https://docs.google.com/spreadsheets/d/FILE_ID/edit` or `https://drive.google.com/file/d/FILE_ID/view`). To create a new Google Sheet on the first export, leave `GOOGLE_DRIVE_FILE_ID` empty. Set these values in `.env`:

```dotenv
GOOGLE_DRIVE_FILE_ID=FILE_ID
GOOGLE_OAUTH_CLIENT_SECRETS_FILE=credentials.json
GOOGLE_OAUTH_TOKEN_FILE=.google_drive_token.json
```

Then run:

```sh
python -m job_tools.prospects export
python -m job_tools.drive_export
```

The first upload opens a browser for Google sign-in and saves the OAuth token locally for later runs. If no file ID is configured, or Google returns 404 for the configured ID, it creates a Google Sheet named **Job Miner** and saves its ID to `.env`. The exporter creates the **Prospective jobs** tab if missing. Later exports keep existing rows and add only jobs whose stable job key or URL is not already present. Existing job rows, manual notes, and other tabs remain in place; an empty JSON export does not clear the sheet. For an Excel `.xlsx` file, the exporter downloads and reuploads the workbook only when it has new jobs or needs to create the tab. Your JSON export and Drive upload are separate commands, so rerun both to publish new jobs. Use the same Google account that owns or can edit the target file.

Scheduled grading uses bounded batches and a cooldown, with optional
`--monitor-gpu` usage logs (currently enabled in cron);
see [scheduled-search.md](scheduled-search.md#paced-fit-grading). Manual commands
below bypass those controls.

### Manual job fit grading

On a job detail page, choose **Run fit grade** and confirm the popup. A detached
worker grades that one job with `qwen3.5-27b-16k:latest`; this explicitly reruns
inference even if the stored grade is unchanged. A successful grade replaces the
previous assessment; failures preserve it. The progress page refreshes every five
seconds and links back to the posting with your list filters intact. Closing the
page does not cancel the request. Duplicate submissions reuse the same request,
and a job with a queued/running request shows **View grading progress**.

Browser requests share the scheduled grader's lock and persisted cooldown, waiting
for any active grading/cooldown before starting and reserving a ten-minute
cooldown afterward. They do not change power or temperature limits. Browser
requests currently do not enable GPU sampling; `--monitor-gpu` remains an option
for the scheduled batch CLI. Request status and worker output are stored under
`generated_search_requests/fit_grades/<request-id>/`.


After scraping jobs, run the fit grader separately with an installed local Ollama model:

```sh
python -m job_miner.cli.grade --job 'greenhouse:123456' --model llama3.2
python -m job_miner.cli.grade --all --model llama3.2
```

Use the **Job ID** on a saved job's detail page for `--job`. `--all` processes visible saved jobs and continues past individual failures. It skips a job when its posting, `master_accomplishments.yaml`, prompt version, and model match the stored grade; add `--force` to regrade. The command exits with status 1 if any job fails, making it suitable for a later cron run. Start Ollama and install the model before running it. The grader calls Ollama's local API directly; it does not run `job_miner/cli/search.py` or render a resume.

Grades are stored in `job_fit_grades` in `job_history.sqlite3`, with a score, strong/possible/weak tier, explanation, cited accomplishment IDs and source wording, model, timestamp, and input hashes. The saved-jobs page sorts by **Fit** by default; ungraded jobs appear last and retain saved-date order. You can still click any other header to sort by it. Open a job to review the requirements, evidence, and gaps behind its grade. Scores are a review aid and should be checked against the original posting, especially when a source provides only a description snippet.

### Saved AI results

The `job_summaries` table in `job_history.sqlite3` stores one AI result per stable job ID, linked to the saved original posting. It records the title, model, result, timestamp, and whether the model produced a summary, judged one unnecessary, or failed. A later result for the same job ID replaces the earlier one. Pass `--no-summary` to `job_miner/cli/search.py` to save jobs and prospect facts without running the organizer agent; these jobs have no `job_summaries` row and do not appear under `--saved-summaries`. Idealist uses search order without calling the selection agent in this mode. `output.json` remains a temporary search snapshot.

### Counts and history reset

At the end of each `job_miner/cli/search.py` search, the terminal shows how many new jobs, prospect rows, and AI results were saved to SQLite, with counts by source. It also shows cumulative database totals and the number of saved jobs missing prospect facts. The JSON export and Drive upload print row counts by source; only saved postings are included, not every search result.

To inspect totals or clear local history with a count of what was removed:

```sh
python -m job_tools.job_stats stats
python -m job_tools.job_stats reset
```

The reset removes the local history database, saved `jobs/JOB_*` postings, search/export snapshots, and run logs. It leaves the OAuth credentials and token in place. The Drive exporter preserves existing rows, so resetting local history does not clear the **Prospective jobs** worksheet.

To read saved results without starting a new search or Ollama session:

```sh
python -m job_miner.cli.search --saved-summaries
```

Only runs made after this change have saved AI results; earlier terminal output cannot be recovered from the database. The original Idealist text and Greenhouse JSON files remain in `jobs/` so you can compare any result with its source.

### Debug logs

Each CrewAI task is configured to append local execution events to `crewai_log.txt`, and each AI summary attempt appends one JSON record to `summary_attempts.jsonl` in the repository root. Both files are ignored by Git. The summary log includes the timestamp, job ID, model, raw AI reply, accepted status, validation reason, and any exception. This lets you inspect a rejected reply without relying on terminal scrollback. Existing failed results cannot be reconstructed; the logs begin with the next run. Already processed jobs are skipped, so rerunning the same request will select other unprocessed matches. CrewAI's hosted tracing is not enabled.

To inspect the latest summary decisions:

```sh
tail -n 10 summary_attempts.jsonl
```

## Current limitations

- Idealist searches only the first results page and passes up to 1,000 unprocessed listings to the workflow, saving up to 1,000 relevant jobs with the current configuration. Change these values in `config/workflow_limits.json`. The rule-based relevance check can miss roles with unusual titles or descriptions that lack clear responsibility text.
- Scraping relies on fixed Idealist page selectors, which can break when the site layout changes.
- The organizer agent has no tools of its own; it summarizes the scraped posting supplied by the workflow. Its summary should be checked against the original text printed below it.
- Automated tests cover job history and the workflow with mocked browser and model calls; a live search still depends on Idealist, Chrome, and Ollama.
- The old `trip_planner_archive/trip.py` and `examples/crew_example.py` examples no longer set API keys in source. Supply `OPENAI_API_KEY` through your environment if you use those examples. The active job workflow uses Ollama and does not need that key.

### Fill missing salaries from saved descriptions

Run `.venv/bin/python -m job_tools.salary` to preview proposed salaries as JSON
lines with job IDs and supporting source excerpts. Add `--apply` to save them.
The command only fills blank salaries in existing fact rows and leaves company,
application status, favorites, and other fields untouched. Repeating it is safe.
Descriptions that cannot be read are reported; uncertain matches remain empty.

The same text extractor runs automatically when board ingestion or a manually
pasted posting has no salary. It preserves source wording, regional ranges,
currencies, and pay periods without annualizing or using a model. Existing saved
salaries take precedence during fact re-extraction. The preview/apply output can
be redirected to a JSONL file for an audit trail. Backfill reads locally saved
postings and does not fetch missing descriptions from the internet.

Salary display on the job list and detail page uses a shared formatter: explicit
New York/NYC ranges take priority, followed by US-wide ranges. Canadian and other
identified foreign ranges are omitted. When US regional applicability is unclear,
short region labels remain visible. Currency codes and pay periods are retained
when stated; missing periods are not inferred or annualized. Salary sorting uses
the displayed range. The original salary evidence remains unchanged in SQLite.
