"""Persistent history, AI results, and structured facts for job postings."""

import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


HISTORY_DB_PATH = Path(__file__).resolve().parent.parent / "job_history.sqlite3"
IDEALIST_ID = re.compile(r"^([0-9a-f]{32})(?:-|$)", re.IGNORECASE)
URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>}]+")


def extract_job_url(value):
    """Accept a URL or a search result object passed by an agent."""
    if isinstance(value, dict):
        candidate = value.get("link") or value.get("url")
    elif isinstance(value, str):
        raw = value.strip()
        try:
            payload, _ = json.JSONDecoder().raw_decode(raw)
        except json.JSONDecodeError:
            payload = None

        if isinstance(payload, dict):
            candidate = payload.get("link") or payload.get("url")
        elif isinstance(payload, str):
            candidate = payload
        else:
            urls = URL_IN_TEXT.findall(raw)
            candidate = urls[0].rstrip(".,;)]") if len(urls) == 1 else None
    else:
        candidate = None

    if not isinstance(candidate, str):
        raise ValueError("Provide one absolute job URL or a listing with a link field")

    parsed = urlsplit(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Provide one absolute job URL or a listing with a link field")
    return candidate


def job_key(url):
    """Use stable posting IDs where available, else a URL without tracking data."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host:
        raise ValueError("Job URL must be absolute")

    if host == "idealist.org":
        for segment in parsed.path.split("/"):
            match = IDEALIST_ID.match(segment)
            if match:
                return "idealist:" + match.group(1).lower()

    if host == "adzuna.com" or host.endswith(".adzuna.com"):
        match = re.search(r"/(?:jobs/land/ad|details)/(\d+)(?:/|$)", parsed.path)
        if match:
            return "adzuna:" + match.group(1)

    greenhouse_ids = parse_qs(parsed.query).get("gh_jid", [])
    if len(greenhouse_ids) == 1 and greenhouse_ids[0].isdigit():
        return "greenhouse:" + greenhouse_ids[0]

    if host.endswith("greenhouse.io"):
        match = re.search(r"/jobs/(\d+)(?:/|$)", parsed.path)
        if match:
            return "greenhouse:" + match.group(1)

    if host in {"jobs.lever.co", "jobs.eu.lever.co"}:
        segments = parsed.path.strip("/").split("/")
        if len(segments) >= 2 and re.fullmatch(r"[A-Za-z0-9_-]+", segments[1]):
            return "lever:" + segments[1]

    if host == "jobs.ashbyhq.com":
        segments = parsed.path.strip("/").split("/")
        if len(segments) >= 2 and re.fullmatch(r"[0-9a-fA-F-]{36}", segments[1]):
            return "ashby:" + segments[0].casefold() + ":" + segments[1].lower()

    return "url:" + host + (parsed.path.rstrip("/") or "/")


def job_source(key, url):
    """Name a saved posting's source from its stable key or original URL."""
    if key.startswith("idealist:"):
        return "Idealist"
    if key.startswith("greenhouse:"):
        return "Greenhouse"
    if key.startswith("lever:"):
        return "Lever"
    if key.startswith("ashby:"):
        return "Ashby"
    if key.startswith("adzuna:"):
        return "Adzuna"
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if host == "adzuna.com" or host.endswith(".adzuna.com"):
        return "Adzuna"
    if host == "remoteok.com":
        return "Remote OK"
    if host == "remotive.com":
        return "Remotive"
    return "Other"


@contextmanager
def _database():
    connection = sqlite3.connect(HISTORY_DB_PATH, timeout=30)
    try:
        with connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS processed_jobs (
                    job_key TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    detail_file TEXT NOT NULL,
                    processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    hidden_at TEXT
                )"""
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(processed_jobs)")}
            if "hidden_at" not in columns:
                connection.execute("ALTER TABLE processed_jobs ADD COLUMN hidden_at TEXT")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS job_summaries (
                    job_key TEXT PRIMARY KEY REFERENCES processed_jobs(job_key),
                    title TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('summarized', 'not_needed', 'failed')),
                    result_text TEXT NOT NULL,
                    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS prospective_jobs (
                    job_key TEXT PRIMARY KEY REFERENCES processed_jobs(job_key),
                    job_title TEXT NOT NULL,
                    company TEXT,
                    salary_range TEXT,
                    posted_at TEXT,
                    posted_text TEXT,
                    remote_status TEXT NOT NULL CHECK
                        (remote_status IN ('remote', 'hybrid', 'on_site', 'unknown')),
                    location TEXT,
                    extracted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            yield connection
    finally:
        connection.close()


def filter_unprocessed(results):
    """Keep only listings that have not been scraped, once per posting ID."""
    with _database() as connection:
        processed = {
            row[0] for row in connection.execute("SELECT job_key FROM processed_jobs")
        }

    unprocessed = []
    for result in results:
        link = result.get("link")
        if not link:
            continue
        key = job_key(link)
        if key not in processed:
            unprocessed.append(result)
            processed.add(key)
    return unprocessed


def is_processed(url):
    with _database() as connection:
        return connection.execute(
            "SELECT 1 FROM processed_jobs WHERE job_key = ?", (job_key(url),)
        ).fetchone() is not None


def record_processed(url, detail_file):
    """Mark a job only after its detail text has been saved successfully."""
    with _database() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO processed_jobs (job_key, url, detail_file) VALUES (?, ?, ?)",
            (job_key(url), url, detail_file),
        )


def saved_job(key):
    """Return the original URL and source file for one saved posting ID."""
    with _database() as connection:
        return connection.execute(
            "SELECT url, detail_file FROM processed_jobs WHERE job_key = ?", (key,)
        ).fetchone()


def record_ai_result(url, title, model, status, result_text):
    """Save the displayed AI result for a previously scraped posting."""
    if status not in {"summarized", "not_needed", "failed"}:
        raise ValueError(f"Unknown AI result status: {status}")

    with _database() as connection:
        connection.execute(
            """INSERT INTO job_summaries (job_key, title, model, status, result_text)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(job_key) DO UPDATE SET
                   title = excluded.title,
                   model = excluded.model,
                   status = excluded.status,
                   result_text = excluded.result_text,
                   saved_at = CURRENT_TIMESTAMP""",
            (job_key(url), title, model, status, result_text),
        )


def saved_ai_results():
    """Return saved AI results with their source posting details, newest first."""
    with _database() as connection:
        return connection.execute(
            """SELECT s.job_key, s.title, s.model, s.status, s.result_text,
                      s.saved_at, p.url, p.detail_file
               FROM job_summaries AS s
               JOIN processed_jobs AS p USING (job_key)
               ORDER BY s.saved_at DESC, s.job_key"""
        ).fetchall()
