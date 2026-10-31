"""Search US Adzuna listings and save selected API records."""

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests

from job_tools.job_history import filter_unprocessed, is_processed, record_processed
from job_tools.location import NYC_LABEL
from job_tools.prospects import extract_and_save
from job_tools.relevance import is_relevant, role_profile, title_strength
from job_tools.workflow_config import LIMITS


MAX_ADZUNA_SUMMARIES = LIMITS.adzuna_jobs_per_run
USER_AGENT = "JobMiner/1.0 (personal job search)"
STOP_WORDS = {"a", "an", "and", "at", "for", "in", "job", "jobs", "of", "or",
              "the", "to", "with", "looking", "work", "role", "position", "full", "time"}


def fetch_adzuna_jobs(query, location, *, app_id=None, app_key=None, timeout=30):
    """Fetch up to two pages of recent jobs, stopping after a short page."""
    app_id = app_id or os.getenv("ADZUNA_APP_ID")
    app_key = app_key or os.getenv("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise ValueError("Set ADZUNA_APP_ID and ADZUNA_APP_KEY to enable Adzuna")
    if location not in {"nyc", "remote"}:
        raise ValueError("Adzuna location must be nyc or remote")
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": query,
        "results_per_page": 50,
        "max_days_old": 30,
        "sort_by": "date",
    }
    if location == "nyc":
        params["where"] = "New York, NY"
    else:
        params["what_or"] = "remote hybrid"
    jobs = []
    for page in (1, 2):
        try:
            response = requests.get(
                f"https://api.adzuna.com/v1/api/jobs/us/search/{page}",
                params=params,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            page_jobs = data.get("results") if isinstance(data, dict) else None
            if not isinstance(page_jobs, list):
                raise ValueError("Adzuna returned a non-list job feed")
        except (requests.RequestException, ValueError) as error:
            if page == 1:
                raise
            status = getattr(getattr(error, "response", None), "status_code", None)
            detail = f"HTTP {status}" if status else type(error).__name__
            print(f"Adzuna page 2 failed ({detail}); keeping page 1 results.")
            break
        jobs.extend(page_jobs)
        if len(page_jobs) < params["results_per_page"]:
            break
    print(f"Adzuna search succeeded: found {len(jobs)} jobs.")
    return jobs


def _posting_url(job):
    url = job.get("redirect_url")
    parsed = urlsplit(url) if isinstance(url, str) else None
    if parsed and parsed.scheme in {"http", "https"} and parsed.hostname and (parsed.hostname == "adzuna.com" or parsed.hostname.endswith(".adzuna.com")):
        return url
    return None


def _location(job):
    field = job.get("location") or {}
    name = field.get("display_name") if isinstance(field, dict) else None
    return name.strip() if isinstance(name, str) else ""


def adzuna_candidates(jobs, query, location):
    """Keep relevant US listings with an explicit location or remote signal."""
    if location not in {"nyc", "remote"}:
        raise ValueError("Adzuna location must be nyc or remote")
    terms = set(re.findall(r"[a-z0-9]+", query.casefold())) - STOP_WORDS
    if not terms:
        return []
    configured = role_profile(query) is not None
    ranked = []
    for index, job in enumerate(jobs):
        if not isinstance(job, dict):
            continue
        title, url = job.get("title"), _posting_url(job)
        description = job.get("description")
        if not isinstance(title, str) or not title.strip() or not url or not isinstance(description, str):
            continue
        if not description.strip() or not is_relevant(query, title, description):
            continue
        place = _location(job)
        if location == "nyc":
            if not NYC_LABEL.search(place):
                continue
        elif not re.search(r"\b(remote|hybrid)\b", " ".join((title, place, description)), re.I):
            continue
        title_matches = len(terms & set(re.findall(r"[a-z0-9]+", title.casefold())))
        if not configured and not title_matches:
            continue
        company = job.get("company") or {}
        company_name = company.get("display_name", "") if isinstance(company, dict) else ""
        candidate = {
            "text": f"{title}\n{company_name}\n{place}\nSource: The Adzuna API",
            "link": url, "job": job,
        }
        ranked.append((10 * title_strength(query, title) + title_matches, -index, candidate))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return filter_unprocessed([item[2] for item in ranked])[:MAX_ADZUNA_SUMMARIES]


def save_adzuna_job(job):
    """Persist the API listing and extract its structured prospect facts."""
    url = _posting_url(job)
    if not url:
        raise ValueError("Adzuna job has no valid redirect URL")
    if is_processed(url):
        raise ValueError("This Adzuna job was already processed")
    title = str(job.get("title") or "").strip()
    description = str(job.get("description") or "").strip()
    job_id = str(job.get("id") or "")
    if not title or not description or not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        raise ValueError("Adzuna job needs an ID, title, and description snippet")
    job_dir = Path("jobs")
    job_dir.mkdir(exist_ok=True)
    path = job_dir / f"JOB_adzuna_{job_id}.json"
    path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    record_processed(url, str(path))
    try:
        extract_and_save(url, str(path))
    except (OSError, ValueError, KeyError) as error:
        print(f"Could not extract prospective job fields for {url}: {error}")
    company = job.get("company") or {}
    company_name = company.get("display_name", "N/A") if isinstance(company, dict) else "N/A"
    return (f"Source: The Adzuna API (https://www.adzuna.com)\n"
            f"{title} at {company_name}\nLocation: {_location(job) or 'N/A'}\n"
            f"Posted: {job.get('created') or 'N/A'}\n"
            f"Adzuna listing: {url}\n"
            f"Description snippet (full description unavailable from this API):\n{description}")
