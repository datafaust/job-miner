import requests
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from job_tools.job_history import filter_unprocessed, is_processed, job_key, record_processed
from job_tools.prospects import extract_and_save

MAX_GREENHOUSE_SUMMARIES = 5


class _DescriptionText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"br", "p", "div", "li", "h1", "h2", "h3", "h4", "ul", "ol"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "ul", "ol"}:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def _description_text(content):
    parser = _DescriptionText()
    parser.feed(html.unescape(content))
    return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())


def scrape_greenhouse(board_token="stripe"):
    """Fetch a Greenhouse board's jobs with their full descriptions."""
    response = requests.get(
        f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs",
        params={"content": "true"},
        timeout=30,
    )
    response.raise_for_status()
    jobs = response.json().get("jobs", [])
    print(f"Greenhouse scrape succeeded for {board_token}: found {len(jobs)} jobs.")
    return jobs


def greenhouse_candidates(jobs, query):
    """Find title matches, falling back to description keywords when needed."""
    terms = set(re.findall(r"[a-z0-9]+", query.casefold())) - {
        "a", "an", "and", "at", "for", "in", "job", "jobs", "of", "or", "the", "to", "with",
        "looking", "work", "role", "position", "full", "time",
    }
    if not terms:
        return []

    title_ranked = []
    description_jobs = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        title = job.get("title")
        url = job.get("absolute_url")
        content = job.get("content")
        if not isinstance(title, str) or not isinstance(url, str) or not isinstance(content, str):
            continue
        if not title.strip() or not content.strip():
            continue
        title_terms = set(re.findall(r"[a-z0-9]+", title.casefold()))
        location = job.get("location") or {}
        location_name = location.get("name", "") if isinstance(location, dict) else ""
        context_terms = set(re.findall(r"[a-z0-9]+", str(location_name).casefold()))
        candidate = {"text": f"{title}\nStripe\n{location_name}", "link": url, "job": job}
        title_matches = len(terms & title_terms)
        if title_matches:
            score = 3 * title_matches + len(terms & context_terms)
            title_ranked.append((score, candidate))
        else:
            description_jobs.append((candidate, context_terms, content))

    title_ranked.sort(key=lambda item: item[0], reverse=True)
    title_candidates = filter_unprocessed([candidate for _, candidate in title_ranked])[:MAX_GREENHOUSE_SUMMARIES]
    if title_candidates:
        return title_candidates

    # Descriptions contain boilerplate; require more than one keyword when the
    # request has several, and never count a location word as a role keyword.
    role_terms = terms - {"remote", "hybrid", "onsite", "on", "site"}
    if not role_terms:
        return []
    minimum_matches = min(2, len(role_terms))
    description_ranked = []
    for candidate, context_terms, content in description_jobs:
        content_terms = set(re.findall(r"[a-z0-9]+", _description_text(content).casefold()))
        matches = len(role_terms & content_terms)
        if matches >= minimum_matches:
            score = 3 * matches + len(terms & context_terms)
            description_ranked.append((score, candidate))

    description_ranked.sort(key=lambda item: item[0], reverse=True)
    return filter_unprocessed([candidate for _, candidate in description_ranked])[:MAX_GREENHOUSE_SUMMARIES]


def save_greenhouse_job(job, board_token="stripe"):
    """Save the API source listing, then record the posting in history."""
    url = job["absolute_url"]
    if is_processed(url):
        raise ValueError("This Greenhouse job was already processed")
    title = job["title"].strip()
    description = _description_text(job["content"])
    if not title or not description:
        raise ValueError("Greenhouse job has no title or description")

    safe_token = re.sub(r"[^A-Za-z0-9_-]", "_", board_token)
    job_id = job_key(url).removeprefix("greenhouse:")
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", job_id)
    job_dir = Path("jobs")
    job_dir.mkdir(exist_ok=True)
    file_path = job_dir / f"JOB_greenhouse_{safe_token}_{safe_id}.json"
    file_path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    record_processed(url, str(file_path))
    try:
        extract_and_save(url, str(file_path))
    except (OSError, ValueError, KeyError) as error:
        print(f"Could not extract prospective job fields for {url}: {error}")

    location = job.get("location") or {}
    location_name = location.get("name", "N/A") if isinstance(location, dict) else "N/A"
    return (
        f"{title}\nLocation: {location_name}\nUpdated: {job.get('updated_at', 'N/A')}\n"
        f"Application URL: {url}\n\n{description}"
    )
