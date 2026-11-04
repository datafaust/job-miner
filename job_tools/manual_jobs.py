"""Parse and save job descriptions pasted into the local browser."""

import hashlib
import json
import re
from pathlib import Path

from job_tools import job_history
from job_miner.paths import PROJECT_DIR


JOBS_DIR = PROJECT_DIR / "jobs"
FIELDS = ("job_title", "company", "salary_range", "posted_at", "posted_text", "remote_status", "location")



def _label(lines, *names):
    pattern = re.compile(r"^(?:" + "|".join(re.escape(name) for name in names) + r")\s*[:\-]\s*(.+)$", re.I)
    return next((match.group(1).strip() for line in lines if (match := pattern.match(line))), None)


def _optional_fact(value):
    if not value or value.strip().casefold() in {"n/a", "na", "none", "unknown", "not listed", "not provided"}:
        return None
    return value.strip()


def parse_posting(text):
    """Extract only explicit facts; leave uncertain fields empty."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Paste a job description before saving.")
    if len(text) > 100_000:
        raise ValueError("The job description is too long (maximum 100,000 characters).")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = _label(lines[:15], "job title", "position", "role", "title")
    if not title:
        title = next((line for line in lines[:10] if not re.match(
            r"^(company|location|salary|compensation|posted|date posted|work arrangement|job url|apply url)\s*[:\-]", line, re.I
        ) and not line.startswith(("http://", "https://")) and len(line) <= 160), None)
    title = _optional_fact(title)
    if not title:
        raise ValueError("Could not identify a job title. Add a line such as 'Job title: Data Analyst'.")
    company = _optional_fact(_label(lines[:20], "company", "organization", "employer"))
    if not company:
        match = re.match(r"^(.+?)\s+at\s+(.+)$", title, re.I)
        if match:
            title, company = match.group(1).strip(), match.group(2).strip()
    location = _optional_fact(_label(lines[:25], "location", "job location"))
    salary = _optional_fact(_label(lines[:30], "salary", "compensation", "pay range"))
    if not salary:
        from job_tools.salary import extract_salary
        result = extract_salary(text)
        salary = result["salary_range"] if result else None
    posted = _optional_fact(_label(lines[:30], "date posted", "posted", "publication date", "published"))
    posted_at = posted if posted and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ][\d:.+-]+Z?)?", posted) else None
    posted_text = posted if posted and not posted_at else None
    arrangement = _label(lines[:25], "work arrangement", "workplace type", "workplace", "remote status")
    signal = arrangement or location or ""
    if re.search(r"\bhybrid\b", signal, re.I):
        remote_status = "hybrid"
    elif re.search(r"\bremote\b", signal, re.I):
        remote_status = "remote"
    elif re.search(r"\b(?:on[ -]?site|in[ -]?person)\b", signal, re.I):
        remote_status = "on_site"
    else:
        remote_status = "unknown"
    return dict(job_title=title, company=company, salary_range=salary,
                posted_at=posted_at, posted_text=posted_text,
                remote_status=remote_status, location=location)


def save_posting(text, url=""):
    """Save the original paste and parsed facts as one new job."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Enter the original listing URL.")
    url = job_history.extract_job_url(url)
    facts = parse_posting(text)
    document = {"_job_miner_manual": True, "title": facts["job_title"],
                "url": url, "posting_text": text.strip(), "facts": facts}
    raw = (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    key = job_history.job_key(url)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    path = JOBS_DIR / f"JOB_manual_{hashlib.sha256(key.encode()).hexdigest()[:24]}.json"
    with job_history._database() as connection:
        if connection.execute("SELECT 1 FROM processed_jobs WHERE job_key = ?", (key,)).fetchone():
            raise ValueError("This job is already saved.")
        path.write_bytes(raw)
        try:
            connection.execute(
                "INSERT INTO processed_jobs (job_key, url, detail_file) VALUES (?, ?, ?)",
                (key, url, str(path)),
            )
            connection.execute(
                """INSERT INTO prospective_jobs
                   (job_key, job_title, company, salary_range, posted_at, posted_text, remote_status, location)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (key, *(facts[field] for field in FIELDS)),
            )
        except Exception:
            path.unlink(missing_ok=True)
            raise
    return key
