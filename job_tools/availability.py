"""Low-cost availability checks; uncertainty never counts as a closure."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from urllib.parse import urlsplit

import requests

from job_tools import job_history

LABELS = {"open": "Open", "possibly_closed": "Possibly closed", "closed": "Closed",
          "unknown": "Unknown", "unchecked": "Not checked"}
CONFIRM_AFTER = timedelta(hours=6)


def saved_jobs():
    with job_history._database() as db:
        rows = db.execute("""SELECT h.job_key, h.url, h.detail_file, a.checked_at
            FROM processed_jobs h LEFT JOIN job_availability a USING (job_key)
            WHERE h.hidden_at IS NULL""").fetchall()
    return [dict(zip(("job_key", "url", "detail_file", "checked_at"), row)) for row in rows]


def board_for(job):
    """Recover board identity from canonical URLs or our saved source filename."""
    parsed = urlsplit(job["url"])
    host = parsed.hostname
    parts = parsed.path.strip("/").split("/")
    if host in {"jobs.lever.co", "jobs.eu.lever.co"} and len(parts) >= 2:
        return ("lever_eu" if host == "jobs.eu.lever.co" else "lever", parts[0])
    if host == "jobs.ashbyhq.com" and len(parts) >= 2:
        return ("ashby", parts[0])
    if job["job_key"].startswith("greenhouse:"):
        match = re.fullmatch(r"JOB_greenhouse_(.+)_\d+\.json", Path(job["detail_file"]).name)
        if match:
            return ("greenhouse", match[1])
        if host in {"boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io"} and len(parts) >= 3:
            return ("greenhouse", parts[0])
    return None


def record_check(key, outcome, evidence, now=None):
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat()
    with job_history._database() as db:
        previous = db.execute("SELECT last_seen_open, missing_since FROM job_availability WHERE job_key = ?", (key,)).fetchone()
        last_open, missing = previous or (None, None)
        status = outcome
        if outcome == "open":
            last_open, missing = stamp, None
        elif outcome == "missing":
            missing = missing or stamp
            status = "closed" if now - datetime.fromisoformat(missing) >= CONFIRM_AFTER else "possibly_closed"
        else:
            # A failed/ambiguous check breaks consecutive missing observations.
            missing = None
        db.execute("""INSERT INTO job_availability
            (job_key, availability, checked_at, last_seen_open, missing_since, evidence)
            VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(job_key) DO UPDATE SET
            availability=excluded.availability, checked_at=excluded.checked_at,
            last_seen_open=excluded.last_seen_open, missing_since=excluded.missing_since,
            evidence=excluded.evidence""", (key, status, stamp, last_open, missing, evidence))
    return status


def observe_board(kind, board, ids):
    """Reuse an already fetched complete board, without additional requests."""
    ids = {str(value) for value in ids}
    for job in saved_jobs():
        if board_for(job) == (kind, board):
            posting_id = job["job_key"].rsplit(":", 1)[-1]
            record_check(job["job_key"], "open" if posting_id in ids else "missing",
                         "Present in board feed" if posting_id in ids else "Absent from complete board feed")


CLOSURE = re.compile(r"\b(?:this job is no longer (?:posted|available)|this position has been (?:filled|closed)|this job posting (?:has expired|is no longer available)|this job is no longer accepting applications)\b", re.I)


def check_page(job):
    try:
        response = requests.get(job["url"], timeout=15, headers={"User-Agent": "JobMiner/1.0 (personal job search)"})
        if response.status_code in {404, 410}:
            return record_check(job["job_key"], "missing", f"HTTP {response.status_code}")
        response.raise_for_status()
        # Ignore scripts and styles, which often contain unused closure messages.
        from job_tools.greenhouse import _description_text
        text = _description_text(re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", "", response.text, flags=re.I | re.S))
        if CLOSURE.search(text):
            return record_check(job["job_key"], "missing", "Explicit closure message on listing page")
        return record_check(job["job_key"], "unknown", "Page reachable; availability could not be verified")
    except requests.RequestException:
        return record_check(job["job_key"], "unknown", "Page request failed or was blocked")


def audit(force=False, pages=True):
    """Check each board once; skip checks fresher than 24 hours unless forced."""
    from job_tools.greenhouse import scrape_greenhouse
    from job_tools.lever import fetch_lever_jobs
    from job_tools.ashby import fetch_ashby_jobs
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    groups = defaultdict(list)
    for job in saved_jobs():
        if not force and job["checked_at"] and job["checked_at"] > cutoff:
            continue
        groups[board_for(job)].append(job)
    for target, jobs in groups.items():
        if target is None:
            if pages:
                for job in jobs:
                    if job["job_key"].startswith("local:"):
                        continue
                    check_page(job)
            continue
        kind, board = target
        try:
            if kind == "greenhouse":
                scrape_greenhouse(board)
            elif kind == "ashby":
                fetch_ashby_jobs(board)
            else:
                fetch_lever_jobs(board, eu=kind == "lever_eu")
        except (requests.RequestException, ValueError):
            for job in jobs:
                record_check(job["job_key"], "unknown", "Board request failed or returned an invalid feed")
    with job_history._database() as db:
        return dict(Counter(row[0] for row in db.execute("""SELECT COALESCE(a.availability, 'unchecked')
            FROM processed_jobs h LEFT JOIN job_availability a USING (job_key) WHERE h.hidden_at IS NULL""")))
