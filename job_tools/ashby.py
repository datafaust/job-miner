"""Fetch, match, and save public Ashby job board postings."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests

from job_tools.greenhouse import _description_text
from job_tools.job_history import filter_unprocessed, is_processed, job_key, record_processed
from job_tools.location import greenhouse_matches_location
from job_tools.prospects import extract_and_save
from job_tools.relevance import is_relevant, role_profile, title_strength
from job_tools.workflow_config import LIMITS


BOARD_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "ashby_boards.json"
MAX_ASHBY_SUMMARIES = LIMITS.ashby_jobs_per_run
USER_AGENT = "JobWatcher/1.0 (personal job search)"
STOP_WORDS = {"a", "an", "and", "at", "for", "in", "job", "jobs", "of", "or",
              "the", "to", "with", "looking", "work", "role", "position", "full", "time"}


def _valid_board(board):
    return isinstance(board, str) and re.fullmatch(r"[A-Za-z0-9_-]+", board)


def load_ashby_boards(path=BOARD_CONFIG_PATH):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    config = "\n".join(line for line in lines if not line.lstrip().startswith("//"))
    boards = json.loads(re.sub(r",(?=\s*])", "", config))
    if not isinstance(boards, list):
        raise ValueError("Ashby board config must be a list")
    seen = set()
    for entry in boards:
        if not isinstance(entry, dict) or not isinstance(entry.get("company"), str) or not entry["company"].strip():
            raise ValueError("Each Ashby board needs a company name")
        board = entry.get("board")
        if not _valid_board(board):
            raise ValueError("Each Ashby board needs a valid board slug")
        if board.casefold() in seen:
            raise ValueError(f"Duplicate Ashby board: {board}")
        seen.add(board.casefold())
    return boards


def fetch_ashby_jobs(board, timeout=30):
    if not _valid_board(board):
        raise ValueError("Ashby board must be a valid board slug")
    response = requests.get(
        f"https://api.ashbyhq.com/posting-api/job-board/{board}",
        params={"includeCompensation": "true"},
        headers={"User-Agent": USER_AGENT}, timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    jobs = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(jobs, list):
        raise ValueError("Ashby returned a non-list job feed")
    print(f"Ashby fetch succeeded for {board}: found {len(jobs)} jobs.")
    return jobs


def _posting_url(job):
    url = job.get("jobUrl") or job.get("applyUrl")
    parsed = urlsplit(url) if isinstance(url, str) else None
    if parsed and parsed.scheme == "https" and parsed.hostname == "jobs.ashbyhq.com":
        return url
    return None


def _description(job):
    plain = job.get("descriptionPlain")
    if isinstance(plain, str) and plain.strip():
        return plain.strip()
    html = job.get("descriptionHtml")
    return _description_text(html) if isinstance(html, str) and html.strip() else ""


def _locations(job):
    locations = [(job.get("location"), job.get("address"))]
    for secondary in job.get("secondaryLocations") or []:
        if isinstance(secondary, dict):
            locations.append((secondary.get("location"), secondary.get("address")))
    for label, address in locations:
        postal = address.get("postalAddress") if isinstance(address, dict) else None
        yield (label.strip() if isinstance(label, str) else ""), (postal if isinstance(postal, dict) else {})


def _matches_location(job, location):
    workplace = str(job.get("workplaceType") or "").casefold()
    for label, postal in _locations(job):
        locality = str(postal.get("addressLocality") or "").casefold()
        region = str(postal.get("addressRegion") or "").casefold()
        country = str(postal.get("addressCountry") or "").casefold()
        if location == "nyc":
            if greenhouse_matches_location({"location": {"name": label}}, "nyc"):
                return True
            if re.search(r"\bnew york,\s*new york\b", label, re.IGNORECASE):
                return True
            if locality in {"new york", "new york city"} and region in {"", "ny", "new york"} and country in {"", "us", "usa", "united states"}:
                return True
        elif location == "remote" and workplace == "remote":
            # A remote role with a country or city restriction must still fit the
            # workflow's US/NYC remote choice.
            if greenhouse_matches_location({"location": {"name": label}}, "remote"):
                return True
            if label and greenhouse_matches_location({"location": {"name": f"Remote - {label}"}}, "remote"):
                return True
            if re.search(r"\bnew york,\s*new york\b", label, re.IGNORECASE):
                return True
            if locality in {"new york", "new york city"} and region in {"", "ny", "new york"} and country in {"", "us", "usa", "united states"}:
                return True
            if not label and not postal:
                return True
    return False


def ashby_candidates(jobs, query, company, location=None):
    terms = set(re.findall(r"[a-z0-9]+", query.casefold())) - STOP_WORDS
    if not terms:
        return []
    configured = role_profile(query) is not None
    role_terms = terms - {"remote", "hybrid", "onsite", "on", "site"}
    title_ranked, description_ranked = [], []
    for index, job in enumerate(jobs):
        if not isinstance(job, dict) or job.get("isListed") is False:
            continue
        title, url, description = job.get("title"), _posting_url(job), _description(job)
        if not isinstance(title, str) or not title.strip() or not url or not description:
            continue
        if location is not None and not _matches_location(job, location):
            continue
        if not is_relevant(query, title, description):
            continue
        location_name = str(job.get("location") or "")
        context = " ".join([location_name, str(job.get("department") or ""), str(job.get("team") or "")])
        title_matches = len(terms & set(re.findall(r"[a-z0-9]+", title.casefold())))
        context_matches = len(terms & set(re.findall(r"[a-z0-9]+", context.casefold())))
        candidate = {"text": f"{title}\n{company}\n{location_name}", "link": url, "job": job}
        if configured:
            candidate["match_type"] = "title"
            title_ranked.append((10 * title_strength(query, title) + title_matches, -index, candidate))
        elif title_matches:
            candidate["match_type"] = "title"
            title_ranked.append((3 * title_matches + context_matches, -index, candidate))
        elif role_terms:
            description_matches = len(role_terms & set(re.findall(r"[a-z0-9]+", description.casefold())))
            if description_matches >= min(2, len(role_terms)):
                candidate["match_type"] = "description"
                description_ranked.append((3 * description_matches + context_matches, -index, candidate))
    title_ranked.sort(reverse=True)
    title_candidates = filter_unprocessed([item[-1] for item in title_ranked])[:MAX_ASHBY_SUMMARIES]
    if title_candidates:
        return title_candidates
    description_ranked.sort(reverse=True)
    return filter_unprocessed([item[-1] for item in description_ranked])[:MAX_ASHBY_SUMMARIES]


def save_ashby_job(job, board, company=None):
    if not _valid_board(board):
        raise ValueError("Ashby board must be a valid board slug")
    url = _posting_url(job)
    if not url:
        raise ValueError("Ashby job has no valid source URL")
    if is_processed(url):
        raise ValueError("This Ashby job was already processed")
    title, description = str(job.get("title") or "").strip(), _description(job)
    if not title or not description:
        raise ValueError("Ashby job has no title or description")
    job_id = job_key(url).rsplit(":", 1)[-1]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        raise ValueError("Ashby job has no valid ID")
    job_dir = Path("jobs")
    job_dir.mkdir(exist_ok=True)
    file_path = job_dir / f"JOB_ashby_{board}_{job_id}.json"
    saved_job = dict(job)
    if company:
        saved_job["_job_watcher_company"] = company
    file_path.write_text(json.dumps(saved_job, ensure_ascii=False, indent=2), encoding="utf-8")
    record_processed(url, str(file_path))
    try:
        extract_and_save(url, str(file_path))
    except (OSError, ValueError, KeyError) as error:
        print(f"Could not extract prospective job fields for {url}: {error}")
    return (f"{title}\nLocation: {job.get('location') or 'N/A'}\n"
            f"Workplace: {job.get('workplaceType') or 'N/A'}\n"
            f"Published: {job.get('publishedAt') or 'N/A'}\n"
            f"Application URL: {job.get('applyUrl') or url}\nOriginal posting: {url}\n\n{description}")
