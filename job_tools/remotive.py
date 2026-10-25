"""Remotive feed, persisted request gate, and local job matching."""

import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from job_tools.greenhouse import _description_text
from job_tools.job_history import _database, filter_unprocessed, is_processed, record_processed
from job_tools.prospects import extract_and_save
from job_tools.workflow_config import LIMITS
from job_tools.relevance import is_relevant, role_profile, title_strength

API_URL = "https://remotive.com/api/remote-jobs"
USER_AGENT = "JobWatcher/1.0 (personal job search)"
REFRESH_SECONDS = 6 * 60 * 60
MIN_REQUEST_SPACING = 31
MAX_DAILY_REQUESTS = 4
MAX_REMOTIVE_SUMMARIES = LIMITS.remotive_jobs_per_run


def _valid_url(url):
    parsed = urlsplit(url) if isinstance(url, str) else None
    return (parsed is not None and parsed.scheme == "https"
            and parsed.hostname in {"remotive.com", "www.remotive.com"}
            and parsed.path.startswith("/remote-jobs/")
            and bool(parsed.path.removeprefix("/remote-jobs/").strip("/")))


def fetch_remotive_jobs(search=None, category=None, company_name=None, limit=None, timeout=30):
    """Fetch a cached Remotive feed, with at most four attempts per rolling day.

    The workflow calls this without filters and matches the full feed locally.
    Cache entries are scoped to the supplied API parameters. Failed attempts
    still consume a request slot; the last good response remains available.
    """
    params = {}
    for name, value in (("search", search), ("category", category), ("company_name", company_name)):
        if value:
            params[name] = value
    if limit is not None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("Remotive limit must be a positive integer")
        params["limit"] = limit
    cache_key = json.dumps(params, sort_keys=True)
    now = time.time()
    with _database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""CREATE TABLE IF NOT EXISTS remotive_api_calls (
            id INTEGER PRIMARY KEY, attempted_at REAL NOT NULL, status TEXT NOT NULL
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS remotive_feed_cache (
            cache_key TEXT PRIMARY KEY, fetched_at REAL NOT NULL, payload TEXT NOT NULL
        )""")
        cached = connection.execute(
            "SELECT fetched_at, payload FROM remotive_feed_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        latest = connection.execute("SELECT MAX(attempted_at) FROM remotive_api_calls").fetchone()[0]
        daily_count = connection.execute(
            "SELECT COUNT(*) FROM remotive_api_calls WHERE attempted_at > ?", (now - 86400,)
        ).fetchone()[0]
        if ((cached and now - cached[0] < REFRESH_SECONDS)
                or (latest is not None and now - latest < MIN_REQUEST_SPACING)
                or daily_count >= MAX_DAILY_REQUESTS):
            print("Remotive: using cached feed; API request gate is active.")
            return json.loads(cached[1]) if cached else []
        call_id = connection.execute(
            "INSERT INTO remotive_api_calls (attempted_at, status) VALUES (?, 'attempted')", (now,)
        ).lastrowid

    try:
        response = requests.get(API_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("Remotive returned an invalid jobs feed")
        jobs = [job for job in data["jobs"] if isinstance(job, dict)
                and job.get("id") is not None and _valid_url(job.get("url"))]
    except (requests.RequestException, ValueError) as error:
        with _database() as connection:
            connection.execute("UPDATE remotive_api_calls SET status = 'failed' WHERE id = ?", (call_id,))
        print(f"Remotive request failed: {error}")
        return json.loads(cached[1]) if cached else []

    with _database() as connection:
        connection.execute(
            """INSERT INTO remotive_feed_cache (cache_key, fetched_at, payload) VALUES (?, ?, ?)
               ON CONFLICT(cache_key) DO UPDATE SET fetched_at = excluded.fetched_at,
               payload = excluded.payload""",
            (cache_key, now, json.dumps(jobs, ensure_ascii=False)),
        )
        connection.execute("UPDATE remotive_api_calls SET status = 'success' WHERE id = ?", (call_id,))
    print(f"Remotive fetch succeeded: found {len(jobs)} jobs.")
    return jobs


def remotive_candidates(jobs, query):
    """Rank local matches, preferring titles, and skip processed jobs."""
    terms = set(re.findall(r"[a-z0-9]+", query.casefold())) - {
        "a", "an", "and", "at", "for", "in", "job", "jobs", "of", "or", "the", "to", "with",
        "looking", "work", "role", "position", "full", "time", "remote",
    }
    if not terms:
        return []
    configured = role_profile(query) is not None
    ranked = []
    for index, job in enumerate(jobs):
        if not isinstance(job, dict) or job.get("id") is None or not _valid_url(job.get("url")):
            continue
        title, description = job.get("title"), job.get("description")
        if not isinstance(title, str) or not title.strip() or not isinstance(description, str) or not description.strip():
            continue
        description_text = _description_text(description)
        if not is_relevant(query, title, description_text):
            continue
        title_matches = len(terms & set(re.findall(r"[a-z0-9]+", title.casefold())))
        context = " ".join((str(job.get("company_name") or ""),
                            str(job.get("category") or ""), description_text))
        other_matches = len(terms & set(re.findall(r"[a-z0-9]+", context.casefold())))
        if not configured and not title_matches and not other_matches:
            continue
        candidate = {"text": f"{title}\n{job.get('company_name') or ''}\nRemotive",
                     "link": job["url"], "job": job}
        ranked.append((bool(title_matches) or configured,
                       title_strength(query, title) if configured else title_matches,
                       other_matches, -index, candidate))
    ranked.sort(reverse=True)
    return filter_unprocessed([item[-1] for item in ranked])[:MAX_REMOTIVE_SUMMARIES]


def save_remotive_job(job):
    """Save the original API listing with its Remotive URL and attribution."""
    url = job["url"]
    if not _valid_url(url):
        raise ValueError("Remotive job has no valid source URL")
    if is_processed(url):
        raise ValueError("This Remotive job was already processed")
    title = str(job.get("title") or "").strip()
    description = _description_text(str(job.get("description") or ""))
    if not title or not description:
        raise ValueError("Remotive job has no title or description")
    job_dir = Path("jobs")
    job_dir.mkdir(exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(job["id"]))
    file_path = job_dir / f"JOB_remotive_{safe_id}.json"
    file_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    record_processed(url, str(file_path))
    try:
        extract_and_save(url, str(file_path))
    except (OSError, ValueError, KeyError) as error:
        print(f"Could not extract prospective job fields for {url}: {error}")
    return (f"{title}\n{job.get('company_name') or ''}\nSource: Remotive\n"
            f"Original posting: {url}\n\n{description}")
