"""Fetch, match, and save public Lever postings."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests

from job_tools.greenhouse import _description_text
from job_tools.job_history import filter_unprocessed, is_processed, record_processed
from job_tools.location import greenhouse_matches_location
from job_tools.prospects import extract_and_save
from job_tools.relevance import is_relevant, role_profile, title_strength


BOARD_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "lever_boards.json"
MAX_LEVER_SUMMARIES = 2
USER_AGENT = "JobWatcher/1.0 (personal job search)"
STOP_WORDS = {"a", "an", "and", "at", "for", "in", "job", "jobs", "of", "or",
              "the", "to", "with", "looking", "work", "role", "position", "full", "time"}


def load_lever_boards(path=BOARD_CONFIG_PATH):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    config = "\n".join(line for line in lines if not line.lstrip().startswith("//"))
    boards = json.loads(re.sub(r",(?=\s*])", "", config))
    if not isinstance(boards, list):
        raise ValueError("Lever board config must be a list")
    seen = set()
    for board in boards:
        if not isinstance(board, dict) or not isinstance(board.get("company"), str) or not board["company"].strip():
            raise ValueError("Each Lever board needs a company name")
        site = board.get("site")
        if not isinstance(site, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", site):
            raise ValueError("Each Lever board needs a valid site slug")
        if not isinstance(board.get("eu", False), bool):
            raise ValueError("Lever board eu must be true or false")
        key = (site, board.get("eu", False))
        if key in seen:
            raise ValueError(f"Duplicate Lever board: {site}")
        seen.add(key)
    return boards


def fetch_lever_jobs(site, eu=False, timeout=30):
    if not isinstance(site, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", site):
        raise ValueError("Lever site must be a valid board slug")
    host = "api.eu.lever.co" if eu else "api.lever.co"
    response = requests.get(f"https://{host}/v0/postings/{site}",
                            params={"mode": "json"}, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    jobs = response.json()
    if not isinstance(jobs, list):
        raise ValueError("Lever returned a non-list feed")
    print(f"Lever fetch succeeded for {site}: found {len(jobs)} jobs.")
    return jobs


def _posting_url(job):
    url = job.get("hostedUrl") or job.get("applyUrl")
    parsed = urlsplit(url) if isinstance(url, str) else None
    if parsed and parsed.scheme == "https" and parsed.hostname in {"jobs.lever.co", "jobs.eu.lever.co"}:
        return url
    return None


def _description(job):
    plain = job.get("descriptionPlain")
    html = job.get("description")
    introduction = plain.strip() if isinstance(plain, str) and plain.strip() else (
        _description_text(html) if isinstance(html, str) and html.strip() else "")
    parts = [introduction]
    for section in job.get("lists") or []:
        if not isinstance(section, dict):
            continue
        heading = section.get("text")
        content = section.get("content")
        if isinstance(heading, str) and heading.strip():
            parts.append(heading.strip())
        if isinstance(content, str) and content.strip():
            parts.append(_description_text(content))
    additional = job.get("additionalPlain")
    if isinstance(additional, str) and additional.strip():
        parts.append(additional.strip())
    elif isinstance(job.get("additional"), str) and job["additional"].strip():
        parts.append(_description_text(job["additional"]))
    return "\n\n".join(part for part in parts if part)


def _location(job):
    categories = job.get("categories") or {}
    value = categories.get("location", "") if isinstance(categories, dict) else ""
    return value.strip() if isinstance(value, str) else ""


def _location_labels(job):
    categories = job.get("categories") or {}
    labels = categories.get("allLocations") if isinstance(categories, dict) else None
    if isinstance(labels, list):
        valid = [label.strip() for label in labels if isinstance(label, str) and label.strip()]
        if valid:
            return valid
    return [_location(job)]


def lever_candidates(jobs, query, company, location=None):
    terms = set(re.findall(r"[a-z0-9]+", query.casefold())) - STOP_WORDS
    if not terms:
        return []
    configured = role_profile(query) is not None
    title_ranked, description_ranked = [], []
    role_terms = terms - {"remote", "hybrid", "onsite", "on", "site"}
    for index, job in enumerate(jobs):
        if not isinstance(job, dict):
            continue
        title, url, description = job.get("text"), _posting_url(job), _description(job)
        location_name = _location(job)
        if not isinstance(title, str) or not title.strip() or not url or not description:
            continue
        if not is_relevant(query, title, description):
            continue
        match_locations = _location_labels(job)
        if str(job.get("workplaceType") or "").casefold() == "remote":
            match_locations = [f"Remote - {label}" if label else "Remote" for label in match_locations]
        if location is not None and not any(greenhouse_matches_location(
                {"location": {"name": label}}, location) for label in match_locations):
            continue
        categories = job.get("categories") or {}
        context = " ".join(str(categories.get(field) or "") for field in
                           ("location", "team", "department", "commitment"))
        title_matches = len(terms & set(re.findall(r"[a-z0-9]+", title.casefold())))
        context_matches = len(terms & set(re.findall(r"[a-z0-9]+", context.casefold())))
        candidate = {"text": f"{title}\n{company}\n{location_name}", "link": url, "job": job}
        if configured:
            candidate["match_type"] = "title"
            title_ranked.append((10 * title_strength(query, title) + title_matches,
                                 -index, candidate))
        elif title_matches:
            candidate["match_type"] = "title"
            title_ranked.append((3 * title_matches + context_matches, -index, candidate))
        elif role_terms:
            description_matches = len(role_terms & set(re.findall(r"[a-z0-9]+", description.casefold())))
            if description_matches >= min(2, len(role_terms)):
                candidate["match_type"] = "description"
                description_ranked.append((3 * description_matches + context_matches, -index, candidate))
    title_ranked.sort(reverse=True)
    title_candidates = filter_unprocessed([item[-1] for item in title_ranked])[:MAX_LEVER_SUMMARIES]
    if title_candidates:
        return title_candidates
    description_ranked.sort(reverse=True)
    return filter_unprocessed([item[-1] for item in description_ranked])[:MAX_LEVER_SUMMARIES]


def save_lever_job(job, site, company=None):
    if not isinstance(site, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", site):
        raise ValueError("Lever site must be a valid board slug")
    url = _posting_url(job)
    if not url:
        raise ValueError("Lever job has no valid source URL")
    if is_processed(url):
        raise ValueError("This Lever job was already processed")
    title, description = str(job.get("text") or "").strip(), _description(job)
    if not title or not description:
        raise ValueError("Lever job has no title or description")
    job_id = str(job.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        raise ValueError("Lever job has no valid ID")
    job_dir = Path("jobs")
    job_dir.mkdir(exist_ok=True)
    file_path = job_dir / f"JOB_lever_{site}_{job_id}.json"
    saved_job = dict(job)
    if company:
        saved_job["_job_watcher_company"] = company
    file_path.write_text(json.dumps(saved_job, ensure_ascii=False, indent=2), encoding="utf-8")
    record_processed(url, str(file_path))
    try:
        extract_and_save(url, str(file_path))
    except (OSError, ValueError, KeyError) as error:
        print(f"Could not extract prospective job fields for {url}: {error}")
    return (f"{title}\nLocation: {_location(job) or 'N/A'}\n"
            f"Workplace: {job.get('workplaceType') or 'N/A'}\n"
            f"Application URL: {job.get('applyUrl') or url}\nOriginal posting: {url}\n\n{description}")
