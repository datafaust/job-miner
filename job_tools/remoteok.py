"""Remote OK feed, persisted request gate, and local job matching."""

import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from job_tools.greenhouse import _description_text
from job_tools.job_history import _database, filter_unprocessed, is_processed, job_key, record_processed
from job_tools.prospects import extract_and_save
from job_tools.workflow_config import LIMITS
from job_tools.relevance import is_relevant, role_profile, title_strength

API_URL = "https://remoteok.com/api"
USER_AGENT = "JobWatcher/1.0 (personal job search)"
REFRESH_SECONDS = 90 * 60
MAX_REMOTEOK_SUMMARIES = LIMITS.remoteok_jobs_per_run


def _valid_url(url):
    parsed = urlsplit(url) if isinstance(url, str) else None
    return parsed is not None and parsed.scheme == "https" and parsed.hostname in {"remoteok.com", "www.remoteok.com"} and bool(parsed.path.strip("/"))


def fetch_remoteok_jobs(timeout=30):
    """Fetch the full feed at most once per 90 minutes, reusing the last good feed.

    The attempt is committed before the HTTP call so failures and concurrent runs
    consume a slot too. A local SQLite database assumes a stable outbound IP.
    """
    now = time.time()
    with _database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("""CREATE TABLE IF NOT EXISTS remoteok_api_calls (
            id INTEGER PRIMARY KEY, attempted_at REAL NOT NULL, status TEXT NOT NULL
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS remoteok_feed_cache (
            id INTEGER PRIMARY KEY CHECK (id = 1), fetched_at REAL NOT NULL, payload TEXT NOT NULL
        )""")
        cached = connection.execute("SELECT payload FROM remoteok_feed_cache WHERE id = 1").fetchone()
        latest = connection.execute("SELECT MAX(attempted_at) FROM remoteok_api_calls").fetchone()[0]
        count = connection.execute(
            "SELECT COUNT(*) FROM remoteok_api_calls WHERE attempted_at > ?", (now - 3600,)
        ).fetchone()[0]
        if (latest is not None and now - latest < REFRESH_SECONDS) or count >= 10:
            print("Remote OK: using cached feed; API request gate is active.")
            return json.loads(cached[0]) if cached else []
        cursor = connection.execute(
            "INSERT INTO remoteok_api_calls (attempted_at, status) VALUES (?, 'attempted')", (now,)
        )
        call_id = cursor.lastrowid

    try:
        response = requests.get(API_URL, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError("Remote OK returned a non-list feed")
        jobs = [job for job in data if isinstance(job, dict) and job.get("id") and _valid_url(job.get("url"))]
    except (requests.RequestException, ValueError) as error:
        with _database() as connection:
            connection.execute("UPDATE remoteok_api_calls SET status = 'failed' WHERE id = ?", (call_id,))
        print(f"Remote OK request failed: {error}")
        return json.loads(cached[0]) if cached else []

    with _database() as connection:
        connection.execute(
            """INSERT INTO remoteok_feed_cache (id, fetched_at, payload) VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET fetched_at = excluded.fetched_at, payload = excluded.payload""",
            (now, json.dumps(jobs, ensure_ascii=False)),
        )
        connection.execute("UPDATE remoteok_api_calls SET status = 'success' WHERE id = ?", (call_id,))
    print(f"Remote OK fetch succeeded: found {len(jobs)} jobs.")
    return jobs


def remoteok_candidates(jobs, query, min_salary=0):
    """Match the cached feed locally and rank title matches first."""
    terms = set(re.findall(r"[a-z0-9]+", query.casefold())) - {
        "a", "an", "and", "at", "for", "in", "job", "jobs", "of", "or", "the", "to", "with",
        "looking", "work", "role", "position", "full", "time", "remote",
    }
    if not terms:
        return []
    configured = role_profile(query) is not None
    ranked = []
    for index, job in enumerate(jobs):
        if not isinstance(job, dict) or not job.get("id") or not _valid_url(job.get("url")):
            continue
        title = job.get("position")
        description = job.get("description")
        if not isinstance(title, str) or not title.strip() or not isinstance(description, str) or not description.strip():
            continue
        description_text = _description_text(description)
        if not is_relevant(query, title, description_text):
            continue
        try:
            salary_max = int(job.get("salary_max") or 0)
        except (TypeError, ValueError):
            salary_max = 0
        if min_salary > 0 and salary_max < min_salary:
            continue
        title_terms = set(re.findall(r"[a-z0-9]+", title.casefold()))
        other_text = " ".join((
            str(job.get("company") or ""),
            " ".join(str(tag) for tag in (job.get("tags") or [])),
            description_text,
        ))
        other_terms = set(re.findall(r"[a-z0-9]+", other_text.casefold()))
        title_matches = len(terms & title_terms)
        other_matches = len(terms & other_terms)
        if not configured and not title_matches and not other_matches:
            continue
        candidate = {
            "text": f"{title}\n{job.get('company') or ''}\nRemote OK",
            "link": job["url"], "job": job,
        }
        ranked.append((bool(title_matches) or configured,
                       title_strength(query, title) if configured else title_matches,
                       other_matches, -index, candidate))
    ranked.sort(reverse=True)
    return filter_unprocessed([item[-1] for item in ranked])[:MAX_REMOTEOK_SUMMARIES]


def save_remoteok_job(job):
    """Save the API listing and retain its Remote OK URL and attribution."""
    url = job["url"]
    if not _valid_url(url):
        raise ValueError("Remote OK job has no valid source URL")
    if is_processed(url):
        raise ValueError("This Remote OK job was already processed")
    title = str(job.get("position") or "").strip()
    description = _description_text(str(job.get("description") or ""))
    if not title or not description:
        raise ValueError("Remote OK job has no title or description")
    job_dir = Path("jobs")
    job_dir.mkdir(exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(job["id"]))
    file_path = job_dir / f"JOB_remoteok_{safe_id}.json"
    file_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    record_processed(url, str(file_path))
    try:
        extract_and_save(url, str(file_path))
    except (OSError, ValueError, KeyError) as error:
        print(f"Could not extract prospective job fields for {url}: {error}")
    return f"{title}\n{job.get('company') or ''}\nSource: Remote OK\nOriginal posting: {url}\n\n{description}"
