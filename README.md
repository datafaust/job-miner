# Job Watcher

Job Watcher is an early job search prototype. Its current entry point asks for a job description, searches configured Greenhouse and Lever company boards, Remote OK and Remotive for remote searches, and [Idealist](https://www.idealist.org/), and uses CrewAI to choose and organize postings. Both agents use the same local Ollama model, `openhermes` by default. It prints the results in the terminal; it does not apply to jobs or run on a schedule.

## What happens during a run

1. [`main.py`](main.py) visits each board in [`config/greenhouse_boards.json`](config/greenhouse_boards.json) and fetches its jobs with full descriptions. The entered `nyc` or `remote` choice filters Greenhouse jobs by their published location labels before ranking. It ranks unprocessed title matches ahead of description matches, using location as a tie breaker. Candidates from different boards are taken in rounds, with **at most two Greenhouse jobs summarized per run** across all boards. This cap is set by `MAX_GREENHOUSE_SUMMARIES` in [`job_tools/greenhouse.py`](job_tools/greenhouse.py). A failed board request is reported, and the search continues through the remaining boards and Idealist.
2. Each processed Greenhouse job's complete API listing is saved as `jobs/JOB_greenhouse_<board-token>_<id>.json`. Its text is given to the organizer, and its Greenhouse ID is recorded in history. Other Greenhouse postings remain eligible for later runs.
   Lever boards run next with the same location choices and a separate cap of two summaries. Their saved API listings are `jobs/JOB_lever_<site>_<id>.json`.
3. For `nyc`, the Idealist search adds `New York City` to the keywords; this is a keyword preference, not a strict location filter. For `remote`, it uses Idealist's Remote location-type filter with the original keywords. The search reports how many listings it recovered and how many remain after filtering local history, writes the remaining listings to `output.json`, and returns up to three unprocessed listings.
4. The selection agent in [`job_agents.py`](job_agents.py) recommends one Idealist listing. The detail tool expands the posting, saves it as `jobs/JOB_idealist_<id>.txt`, and records it in history after scraping succeeds.
5. For each selected posting, the organizer receives the actual posting text and can write a summary or say that a summary is unnecessary. Its decision is saved in `job_history.sqlite3`. The terminal prints the source URL, search listing, decision, and original posting text.
6. A separate, rule-based extractor saves source-backed title, company, salary range, posting date or source age, work arrangement, and location in the `prospective_jobs` table. It runs when a posting is saved, independently of the AI summary.

All saved job files go into the main `jobs/` folder in the directory where you run the command. Greenhouse postings are `JOB_greenhouse_*.json`, Lever postings are `JOB_lever_*.json`, Remote OK postings are `JOB_remoteok_*.json`, Remotive postings are `JOB_remotive_*.json`, and Idealist postings are `JOB_idealist_*.txt`. The folder is created if needed, and these files are ignored by Git. The search snapshot `output.json` remains in the directory where you run the command. Idealist uses Selenium; Greenhouse, Lever, Remote OK, and Remotive use public APIs.

The Greenhouse board config has one `{"company": "Name", "token": "board-token"}` entry per company. Stripe, Airbnb, and Figma are currently active; the other 47 entries are retained as `//` commented lines. Uncomment a line to include that board in the next run, or comment an active line to skip it. Each run requests every active board in config order. The company name appears in search listings, while the token is used for the API request and saved filename. The loader accepts whole-line `//` comments and a trailing comma before the closing bracket.

### Lever searches

The workflow requests each board in [`config/lever_boards.json`](config/lever_boards.json) for both `nyc` and `remote` searches. Palantir is active by default. Add `{"company": "Name", "site": "board-slug"}` for a Lever board, or set `"eu": true` for a `jobs.eu.lever.co` board. Find the slug in the company's `jobs.lever.co/<slug>` URL. A failed board request does not stop the remaining sources. Lever jobs are filtered by location and ranked locally, with at most two unprocessed postings summarized per run across all Lever boards. Saved files include the complete API response plus `_job_watcher_company` for prospect extraction; the organizer receives the description, section lists, and additional text. Lever posting IDs are used for history, so apply links and posting links identify the same job.

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

`prospective_jobs` is the working list for a future document or spreadsheet. It has one row per saved posting and can be updated without duplicating jobs. Missing salary or remote information stays empty or `unknown`; a city name alone is not treated as on-site. Greenhouse uses its exact `first_published` timestamp for `posted_at`. Lever uses `createdAt`, `salaryRange`, `workplaceType`, and the board's configured company name. Remotive uses `publication_date`, `salary`, and `candidate_required_location` from its API. Idealist currently supplies only a relative label such as `Published 7 days ago`, saved as `posted_text`, so read it alongside `source_saved_at` rather than as a current age. `remote_status` is one of `remote`, `hybrid`, `on_site`, or `unknown`. Exported Lever and Remotive rows include source credit and the original URL.

To refresh facts from all existing source files and export the list as JSON:

```sh
python -m job_tools.prospects backfill
python -m job_tools.prospects export
```

The second command writes `prospective_jobs.json` in the current directory. It does not contact Google or run an AI agent. The extractor uses explicit source fields and labels; an AI extraction step can be added later for ambiguous postings, with its proposed values checked against the source before saving.

### Saved AI results

The `job_summaries` table in `job_history.sqlite3` stores one AI result per stable job ID, linked to the saved original posting. It records the title, model, result, timestamp, and whether the model produced a summary, judged one unnecessary, or failed. A later result for the same job ID replaces the earlier one. `output.json` remains a temporary search snapshot.

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

- Greenhouse and Lever each attempt summaries for at most two matching, unprocessed jobs per run. Idealist offers at most three unprocessed listings to the selection agent and processes one. Keyword matching may miss related roles that use different wording.
- Scraping relies on fixed Idealist page selectors, which can break when the site layout changes.
- The organizer agent has no tools of its own; it summarizes the scraped posting supplied by the workflow. Its summary should be checked against the original text printed below it.
- Automated tests cover job history and the workflow with mocked browser and model calls; a live search still depends on Idealist, Chrome, and Ollama.
- The old `trip_planner_archive/trip.py` and `crew_example.py` examples no longer set API keys in source. Supply `OPENAI_API_KEY` through your environment if you use those examples. The active job workflow uses Ollama and does not need that key.
