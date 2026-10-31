<p align="center">
  <img src="assets/icon.png" alt="Job Miner icon" width="160">
</p>

# Job Miner

Job Miner is an early job search prototype. Its current entry point asks for a job description, searches configured company boards, the US Adzuna API when credentials are set, Remote OK and Remotive for remote searches, and [Idealist](https://www.idealist.org/), and uses CrewAI to choose and organize postings. Both agents use the same local Ollama model, `openhermes` by default. It prints the results in the terminal; it does not apply to jobs or run on a schedule.

## Browse saved jobs

The local job browser lists every saved posting, including jobs without extracted prospect facts or an AI summary. Click a row to read the saved posting, source details, and any AI result. Search by title or company, filter by source or work arrangement, and move through pages of 25 jobs.

```bash
python -m pip install "Flask>=3.1,<4" "requests>=2.31,<3"
python job_web.py
```

Open `http://127.0.0.1:5055` in your browser. The full `requirements.txt` also includes these dependencies. The browser reads `job_history.sqlite3` and the saved files referenced by it. A new checkout with no saved jobs shows an empty list. Styling is included locally, so the page does not need an internet connection. The browser binds to your computer only by default; stop it with Ctrl+C. Use `--port` to choose a different port.

On a posting page, choose an installed Ollama text-generation model and confirm to start a tailored resume selection. Install the full `requirements.txt` and start Ollama before using this action. The status page refreshes every five seconds, showing the current stage and elapsed time. A model call may take several minutes; a second attempt appears only when the first result needs repair. The page shows validation errors if selection fails. Use **Cancel selection** on that page to stop a long run; stopping the GUI alone leaves the separate worker running. Successful selections and evidence reports are saved under the existing generated directories for review; the GUI does not render a DOCX before that review. The GUI also keeps a link to recent attempts on each posting page.

## Resume selection

The separate resume workflow begins with `resume_cli.py`. It loads one saved posting or a local `.json`/`.txt` posting, then asks a local Ollama model through CrewAI to produce a job-specific selection JSON. It does not render a DOCX yet.

```bash
python resume_cli.py --job-id greenhouse:8172487 --model qwen2.5:7b --rewrite-mode light
python resume_cli.py --posting-file /path/to/posting.txt --job-title "Data Engineer" --job-url https://example.com/jobs/123 --model openhermes
```

`--job-id` accepts the stable IDs displayed by `python main.py --saved-summaries`; `--posting-file` accepts a saved source JSON or a plain text posting. For plain text, the first nonempty line is used as the title unless `--job-title` is supplied. A local posting without a URL receives a content-derived `local:` ID and a null URL. `--model` defaults to `openhermes`, as in `main.py`; `--rewrite-mode` accepts `none`, `light` (default), or `targeted`. The browser’s Bullet mode dropdown offers the same modes and defaults to No changes (`none`).

The selector requests an 8,192-token Ollama context and lets Ollama generate until the model stops (`num_predict=-1`). A 20-minute request timeout remains in place. These settings are recorded in each run manifest.

Each run creates `generated_resume_runs/<job-id>/<timestamp>/` with `posting.txt`, `inventory.yaml`, `prompt.md`, `manifest.json`, `validation_report.json`, and the raw model reply when available. The manifest records the source URL, title, job ID, source and posting hashes, inventory and prompt hashes, model, rewrite mode, prompt version, and generation status. Valid selections are saved to `generated_selections/<job-id>_<timestamp>_selection.json`. Those runs also get `evidence_report.json` and a readable `evidence_report.md` beside the manifest. Both directories are ignored by Git because they contain personal resume data and job postings.

Parsing or structural validation failures trigger one automatic repair attempt with the rejected response and specific errors. Each attempt retains `selection_raw_attempt_N.txt` and `validation_report_attempt_N.json`; `selection_raw.txt` contains the latest reply. Model request failures and evidence review flags do not trigger retries. If the repair also fails, no validated selection is saved.

Validation checks JSON shape, source IDs and ownership, ordering, duplicates, bullet minimums, summary length and `SUM-001`, skill categories, exact certification text, and unverified date overrides. Invalid output leaves its raw reply and all detected errors in the run directory; it does not produce a selection or DOCX. The direct `render_resume.py` entry point applies the same structural checks before opening the template. The evidence report extracts labelled job requirements and suggests selected accomplishment IDs based on shared words. It also flags new numbers, technical terms, technology-specific tenure, weak wording overlap in AI-authored prose, and skill items missing from their inventory category. These are leads for human review, not a factual proof or an AI score. Review the generated wording against the original inventory and posting before rendering.

## What happens during a run

1. [`main.py`](main.py) visits each board in [`config/greenhouse_boards.json`](config/greenhouse_boards.json) and fetches its jobs with full descriptions. The entered `nyc` or `remote` choice filters Greenhouse jobs by their published location labels before ranking. Configured roles also pass through the relevance check described below. Candidates from different boards are taken in rounds, with **at most two Greenhouse jobs summarized per run** across all boards by default. A failed board request is reported, and the search continues through the remaining boards and Idealist.
2. Each processed Greenhouse job's complete API listing is saved as `jobs/JOB_greenhouse_<board-token>_<id>.json`. Its text is given to the organizer, and its Greenhouse ID is recorded in history. Other Greenhouse postings remain eligible for later runs.
   Lever boards run next with the same location choices and a separate cap of two summaries. Their saved API listings are `jobs/JOB_lever_<site>_<id>.json`. Ashby boards in [`config/ashby_boards.json`](config/ashby_boards.json) then run with their own cap of two summaries; saved listings are `jobs/JOB_ashby_<board>_<id>.json`.
3. For `nyc`, the Idealist search adds `New York City` to the keywords; this is a keyword preference, not a strict location filter. For `remote`, it uses Idealist's Remote location-type filter with the original keywords. The search reports how many listings it recovered and how many remain after filtering local history, writes the remaining listings to `output.json`, and returns up to three unprocessed listings by default.
4. The selection agent in [`job_agents.py`](job_agents.py) recommends the first Idealist listing to process. The detail tool expands postings and checks configured-role relevance before saving them as `jobs/JOB_idealist_<id>.txt` and recording them in history. By default, the workflow saves one Idealist job per run; when configured to save more, it considers the rest of the shortlist in search order.
5. For each selected posting, the organizer receives the actual posting text and can write a summary or say that a summary is unnecessary. Its decision is saved in `job_history.sqlite3`. The terminal prints the source URL, search listing, decision, and original posting text.
6. A separate, rule-based extractor saves source-backed title, company, salary range, posting date or source age, work arrangement, and location in the `prospective_jobs` table. It runs when a posting is saved, independently of the AI summary.

All saved job files go into the main `jobs/` folder in the directory where you run the command. Greenhouse postings are `JOB_greenhouse_*.json`, Lever postings are `JOB_lever_*.json`, Ashby postings are `JOB_ashby_*.json`, Adzuna postings are `JOB_adzuna_*.json`, Remote OK postings are `JOB_remoteok_*.json`, Remotive postings are `JOB_remotive_*.json`, and Idealist postings are `JOB_idealist_*.txt`. The folder is created if needed, and these files are ignored by Git. The search snapshot `output.json` remains in the directory where you run the command. Idealist uses Selenium; the other sources use APIs.

### Workflow limits

Edit [`config/workflow_limits.json`](config/workflow_limits.json) to change per-run job caps. `idealist_candidates_per_run` controls how many filtered Idealist search results reach the selection step; `idealist_jobs_per_run` controls how many of that shortlist can be saved and summarized. Each API source, including Adzuna, has its own saved-job cap. Values must be positive integers, and Idealist's saved-job cap cannot exceed its candidate cap. The file is read when a Python run starts, so rerun the command after editing it. API request cooldowns are separate from these job caps.

### Role relevance

[`config/related_keys.json`](config/related_keys.json) defines relevance profiles for `data analyst`, `software engineer`, `ai engineer`, `data engineer`, and `applied ai` searches. A primary title phrase passes directly. A related title phrase or supporting title term needs at least two distinct description signals in the posting's responsibilities. Matching ignores case and punctuation and uses whole words. The filter prefers explicitly headed responsibility sections and excludes qualification sections; when no such headings exist, it checks the introductory description text. A description match without a title signal does not pass automatically.

For these configured roles, relevance is checked before per-source summary limits and before saving. Idealist listing titles are screened before details are opened, then the full posting is checked before persistence. Rejected postings are not marked processed, so changing the config can make them eligible on a later run. Search requests without a configured role keep the previous keyword matching behavior. Add a role profile to enable the stricter rule for that search.

The Greenhouse board config has one `{"company": "Name", "token": "board-token"}` entry per company. Uncomment a line to include that board in the next run, or comment an active line to skip it. Each run requests every active board in config order. The company name appears in search listings, while the token is used for the API request and saved filename. The loader accepts whole-line `//` comments and a trailing comma before the closing bracket.

Greenhouse, Lever, and Ashby board requests use a shared 0.25-second minimum interval and retry temporary network errors, HTTP 429, and common HTTP 5xx responses up to three attempts. A `Retry-After` header is honored when it asks for at most 30 seconds; longer waits leave that board failed so the run can continue. Set `JOB_BOARD_REQUEST_INTERVAL_SECONDS` in `.env` to change the interval (use `0` to disable it).

### Lever searches

The workflow requests each board in [`config/lever_boards.json`](config/lever_boards.json) for both `nyc` and `remote` searches. Palantir is active by default. Add `{"company": "Name", "site": "board-slug"}` for a Lever board, or set `"eu": true` for a `jobs.eu.lever.co` board. Find the slug in the company's `jobs.lever.co/<slug>` URL. A failed board request does not stop the remaining sources. Lever jobs are filtered by location and ranked locally, with at most two unprocessed postings summarized per run across all Lever boards. Saved files include the complete API response plus `_job_miner_company` for prospect extraction; the organizer receives the description, section lists, and additional text. Lever posting IDs are used for history, so apply links and posting links identify the same job.

Ashby boards are configured in [`config/ashby_boards.json`](config/ashby_boards.json); Ramp and Notion are active by default. Add `{"company": "Name", "board": "board-slug"}` using the slug from `jobs.ashbyhq.com/<board-slug>`. Each board is fetched once with compensation included. The workflow skips unlisted jobs, filters location locally, and ranks title matches before description matches using the entered keywords. For `nyc`, it checks primary and secondary locations, including structured city fields. For `remote`, it requires `workplaceType: Remote` and an explicit unrestricted, US, or NYC remote location; hybrid roles are excluded even when Ashby sets `isRemote: true`. Ambiguous and foreign-only remote locations are skipped. Ashby has no server-side keyword or location filters, and the current workflow only accepts `nyc` or `remote` as inputs. Adjust `ashby_jobs_per_run` in [`config/workflow_limits.json`](config/workflow_limits.json) to change its independent summary cap.

### Adzuna searches

Register at [Adzuna Developer](https://developer.adzuna.com/) and set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` in `.env` (see [`.env.example`](.env.example)). Without both, the workflow skips Adzuna. Each run makes one request for up to 50 recent US jobs, sorted by date. `nyc` searches use `where=New York, NY` and check the returned location label. `remote` searches include the `remote hybrid` keywords and require a remote or hybrid signal in the returned title, location, or description snippet. Adzuna has no dedicated remote flag, so check the source listing before relying on that classification. Two unprocessed jobs are saved by default; change `adzuna_jobs_per_run` to adjust this cap. The response contains only a description snippet, which is what the organizer receives. Saved listings and output credit [The Adzuna API](https://www.adzuna.com/) and preserve its redirect link. Predicted salaries are marked as Adzuna estimates in the prospect export. Adzuna API use is subject to its [terms and account limits](https://developer.adzuna.com/docs/terms_of_service).

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

### Manual job fit grading

After scraping jobs, run the fit grader separately with an installed local Ollama model:

```sh
python fit_grader.py --job 'greenhouse:123456' --model llama3.2
python fit_grader.py --all --model llama3.2
```

Use the **Job ID** on a saved job's detail page for `--job`. `--all` processes visible saved jobs and continues past individual failures. It skips a job when its posting, `master_accomplishments.yaml`, prompt version, and model match the stored grade; add `--force` to regrade. The command exits with status 1 if any job fails, making it suitable for a later cron run. Start Ollama and install the model before running it. The grader calls Ollama's local API directly; it does not run `main.py` or render a resume.

Grades are stored in `job_fit_grades` in `job_history.sqlite3`, with a score, strong/possible/weak tier, explanation, cited accomplishment IDs and source wording, model, timestamp, and input hashes. The saved-jobs page sorts by **Fit** by default; ungraded jobs appear last and retain saved-date order. You can still click any other header to sort by it. Open a job to review the requirements, evidence, and gaps behind its grade. Scores are a review aid and should be checked against the original posting, especially when a source provides only a description snippet.

### Saved AI results

The `job_summaries` table in `job_history.sqlite3` stores one AI result per stable job ID, linked to the saved original posting. It records the title, model, result, timestamp, and whether the model produced a summary, judged one unnecessary, or failed. A later result for the same job ID replaces the earlier one. Pass `--no-summary` to `main.py` to save jobs and prospect facts without running the organizer agent; these jobs have no `job_summaries` row and do not appear under `--saved-summaries`. Idealist's separate agent may still select among multiple search results. `output.json` remains a temporary search snapshot.

### Counts and history reset

At the end of each `main.py` search, the terminal shows how many new jobs, prospect rows, and AI results were saved to SQLite, with counts by source. It also shows cumulative database totals and the number of saved jobs missing prospect facts. The JSON export and Drive upload print row counts by source; only saved postings are included, not every search result.

To inspect totals or clear local history with a count of what was removed:

```sh
python -m job_tools.job_stats stats
python -m job_tools.job_stats reset
```

The reset removes the local history database, saved `jobs/JOB_*` postings, search/export snapshots, and run logs. It leaves the OAuth credentials and token in place. The Drive exporter preserves existing rows, so resetting local history does not clear the **Prospective jobs** worksheet.

To read saved results without starting a new search or Ollama session:

```sh
python main.py --saved-summaries
```

Only runs made after this change have saved AI results; earlier terminal output cannot be recovered from the database. The original Idealist text and Greenhouse JSON files remain in `jobs/` so you can compare any result with its source.

### Debug logs

Each CrewAI task is configured to append local execution events to `crewai_log.txt`, and each AI summary attempt appends one JSON record to `summary_attempts.jsonl` in the repository root. Both files are ignored by Git. The summary log includes the timestamp, job ID, model, raw AI reply, accepted status, validation reason, and any exception. This lets you inspect a rejected reply without relying on terminal scrollback. Existing failed results cannot be reconstructed; the logs begin with the next run. Already processed jobs are skipped, so rerunning the same request will select other unprocessed matches. CrewAI's hosted tracing is not enabled.

To inspect the latest summary decisions:

```sh
tail -n 10 summary_attempts.jsonl
```

## Set up

Run these commands from the repository root. Python 3.10 is a suitable version for the pinned dependencies in [`requirements.txt`](requirements.txt). On Intel macOS, CrewAI 1.9.3 is the newest release that installs with the available package wheels. CrewAI 1.10.0 and newer require LanceDB releases without an Intel macOS wheel.

```sh
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

The workflow also needs:

- **Ollama** running locally with the model you choose. Install Ollama, then run `ollama pull openhermes` for the default model, or substitute another model name in that command. Start the Ollama app, or use `ollama serve` if it is not already running. See the [Ollama quickstart](https://github.com/ollama/ollama/blob/main/docs/quickstart.mdx) and [`openhermes` model page](https://ollama.com/library/openhermes).
- **Chrome.** The active search and detail tools use Selenium Manager to find or download a ChromeDriver compatible with your installed browser. The first browser launch may need internet access to fetch the driver. The old `chromedriver-mac-x64/` directory is ignored by Git and is not used by the active tools. See [Selenium Manager](https://www.selenium.dev/documentation/selenium_manager/).
- **Internet access** to reach Idealist, Greenhouse, Lever, Remote OK, and Remotive.

## Run the job finder

With the virtual environment active and Ollama running:

```sh
python main.py
```

To use another installed Ollama model, pass its name. For example, after running `ollama pull llama3.2`:

```sh
python main.py --model llama3.2
```

Enter job keywords when prompted, then enter `nyc` (also accepts `New York`) or `remote`. Press Enter to use the defaults in `.env`: `JOB_SEARCH_KEYWORDS=data analyst` and `JOB_SEARCH_LOCATION=nyc`. A missing keyword or location with no environment default is an error. Other location values are rejected for now. Greenhouse considers explicit NYC labels for `nyc`, and plain `Remote` or explicitly US/NYC remote labels for `remote`; ambiguous or foreign-only remote labels are skipped. Neither choice changes the Greenhouse API request. Both agents use the selected model, then process matching postings and print the organized results. The run is interactive and may take time because it requests every configured board, uses a browser, and runs a local model.

## Other files

| File | Status |
| --- | --- |
| [`trip.py`](trip_planner_archive/trip.py) and [`trip_tasks.py`](trip_planner_archive/trip_tasks.py) | An unrelated trip planner prototype in `trip_planner_archive/`. `trip.py` cannot run as checked in because `trip_agents.py` is missing. |
| [`crew_example.py`](crew_example.py) | A separate CrewAI example about human rights research. Running it starts that example immediately. |
| [`search_tools.py`](search_tools.py) and [`scrape_job.py`](scrape_job.py) | Earlier standalone versions of the Idealist tools. Their example invocations are commented out; `main.py` uses the versions under `job_tools/`. |
| `docs/` | Local applicant documents; the current code does not read them. |

## Current limitations

- By default, Greenhouse and Lever each attempt summaries for at most two matching, unprocessed jobs per run. Idealist offers at most three unprocessed, title-relevant listings to the selection agent and processes one. Change these values in `config/workflow_limits.json`. The rule-based relevance check can miss roles with unusual titles or descriptions that lack clear responsibility text.
- Scraping relies on fixed Idealist page selectors, which can break when the site layout changes.
- The organizer agent has no tools of its own; it summarizes the scraped posting supplied by the workflow. Its summary should be checked against the original text printed below it.
- Automated tests cover job history and the workflow with mocked browser and model calls; a live search still depends on Idealist, Chrome, and Ollama.
- The old `trip_planner_archive/trip.py` and `crew_example.py` examples no longer set API keys in source. Supply `OPENAI_API_KEY` through your environment if you use those examples. The active job workflow uses Ollama and does not need that key.
