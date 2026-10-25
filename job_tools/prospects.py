"""Extract source-backed facts and export a prospective job list."""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from job_tools import job_history
from job_tools.job_stats import source_counts


SOURCE_DIR = Path(__file__).resolve().parent.parent
SALARY_RANGE = re.compile(
    r"(?:USD\s*)?\$[\d,]+(?:\.\d+)?\s*(?:-|–|—|to)\s*"
    r"(?:USD\s*)?\$[\d,]+(?:\.\d+)?(?:\s*/\s*(?:year|hour|month))?",
    re.IGNORECASE,
)


def _remote_status(location, description=""):
    label = location.casefold().strip()
    if label.startswith("hybrid") or re.search(r"\bhybrid\s*:", description, re.IGNORECASE):
        return "hybrid"
    if re.search(r"\bremote\b", label):
        return "remote"
    if label.startswith("on-site") or label.startswith("onsite"):
        return "on_site"
    return "unknown"


def extract_greenhouse(job):
    """Use API fields and only an unambiguous salary range from the posting."""
    from job_tools.greenhouse import _description_text

    location = job.get("location") or {}
    location_name = location.get("name", "").strip() if isinstance(location, dict) else ""
    description = _description_text(job.get("content") or "")
    ranges = {match.group().strip() for match in SALARY_RANGE.finditer(description)}
    return {
        "job_title": job["title"].strip(),
        "company": (job.get("company_name") or "").strip() or None,
        "salary_range": next(iter(ranges)) if len(ranges) == 1 else None,
        "posted_at": job.get("first_published") or None,
        "posted_text": None,
        "remote_status": _remote_status(location_name),
        "location": location_name or None,
    }


def extract_idealist(text):
    """Read labelled fields from a saved Idealist posting."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    published_index = next(
        (index for index, line in enumerate(lines) if line.startswith("Published ")),
        None,
    )
    if published_index is None or len(lines) <= published_index + 3:
        raise ValueError("Saved Idealist posting is missing its header")
    posted_text, title, company, location = lines[published_index:published_index + 4]
    salary = None
    for index, line in enumerate(lines[:-1]):
        if line == "Salary:":
            salary = lines[index + 1]
            break
    return {
        "job_title": title,
        "company": company,
        "salary_range": salary,
        "posted_at": None,
        "posted_text": posted_text,
        "remote_status": _remote_status(location, text),
        "location": location,
    }


def extract_remoteok(job):
    location = str(job.get("location") or "").strip()
    salary_min, salary_max = job.get("salary_min"), job.get("salary_max")
    salary = None
    if salary_min and salary_max:
        salary = f"${int(salary_min):,} - ${int(salary_max):,}"
    return {
        "job_title": str(job["position"]).strip(),
        "company": str(job.get("company") or "").strip() or None,
        "salary_range": salary,
        "posted_at": job.get("date") or None,
        "posted_text": None,
        "remote_status": "remote",
        "location": location or None,
    }


def extract_remotive(job):
    location = str(job.get("candidate_required_location") or "").strip()
    salary = str(job.get("salary") or "").strip()
    return {
        "job_title": str(job["title"]).strip(),
        "company": str(job.get("company_name") or "").strip() or None,
        "salary_range": salary or None,
        "posted_at": job.get("publication_date") or None,
        "posted_text": None,
        "remote_status": "remote",
        "location": location or None,
    }


def extract_lever(job):
    categories = job.get("categories") or {}
    location = str(categories.get("location") or "").strip() if isinstance(categories, dict) else ""
    salary_data = job.get("salaryRange") or {}
    salary = None
    if isinstance(salary_data, dict) and salary_data.get("min") is not None and salary_data.get("max") is not None:
        currency = str(salary_data.get("currency") or "").strip()
        interval = str(salary_data.get("interval") or "").strip()
        salary = f"{currency} {salary_data['min']:,} - {salary_data['max']:,}".strip()
        if interval:
            salary += f" / {interval}"
    created_at = job.get("createdAt")
    posted_at = None
    if isinstance(created_at, (int, float)) and not isinstance(created_at, bool):
        posted_at = datetime.fromtimestamp(created_at / 1000, timezone.utc).isoformat()
    workplace = str(job.get("workplaceType") or "").casefold()
    remote_status = {"remote": "remote", "hybrid": "hybrid", "on-site": "on_site", "onsite": "on_site"}.get(
        workplace, _remote_status(location))
    return {
        "job_title": str(job["text"]).strip(),
        "company": str(job.get("_job_watcher_company") or "").strip() or None,
        "salary_range": salary,
        "posted_at": posted_at,
        "posted_text": None,
        "remote_status": remote_status,
        "location": location or None,
    }


def extract_and_save(url, detail_file):
    """Extract facts from the saved source and upsert them by stable job ID."""
    path = Path(detail_file)
    if not path.is_absolute() and not path.exists():
        path = SOURCE_DIR / path
    if path.suffix == ".json":
        job = json.loads(path.read_text(encoding="utf-8"))
        if path.name.startswith("JOB_remoteok_"):
            facts = extract_remoteok(job)
        elif path.name.startswith("JOB_remotive_"):
            facts = extract_remotive(job)
        elif path.name.startswith("JOB_lever_"):
            facts = extract_lever(job)
        else:
            facts = extract_greenhouse(job)
    elif path.suffix == ".txt":
        facts = extract_idealist(path.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"Unsupported job source file: {path}")

    with job_history._database() as connection:
        connection.execute(
            """INSERT INTO prospective_jobs
               (job_key, job_title, company, salary_range, posted_at, posted_text,
                remote_status, location)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(job_key) DO UPDATE SET
                   job_title = excluded.job_title,
                   company = excluded.company,
                   salary_range = excluded.salary_range,
                   posted_at = excluded.posted_at,
                   posted_text = excluded.posted_text,
                   remote_status = excluded.remote_status,
                   location = excluded.location,
                   extracted_at = CURRENT_TIMESTAMP""",
            (job_history.job_key(url), *(facts[field] for field in (
                "job_title", "company", "salary_range", "posted_at", "posted_text",
                "remote_status", "location",
            ))),
        )
    return facts


def backfill():
    """Extract facts from every existing saved source posting."""
    with job_history._database() as connection:
        rows = connection.execute("SELECT url, detail_file FROM processed_jobs").fetchall()
    count = 0
    for url, detail_file in rows:
        try:
            extract_and_save(url, detail_file)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
            print(f"Could not extract {detail_file}: {error}")
            continue
        count += 1
    return count


def list_prospects():
    """Return rows ready for a future spreadsheet or document export."""
    with job_history._database() as connection:
        rows = connection.execute(
            """SELECT p.job_key, p.job_title, p.company, p.salary_range,
                      p.posted_at, p.posted_text, p.remote_status, p.location,
                      h.url, h.processed_at, p.extracted_at
               FROM prospective_jobs AS p
               JOIN processed_jobs AS h USING (job_key)
               ORDER BY h.processed_at DESC, p.job_key"""
        ).fetchall()
    fields = (
        "job_key", "job_title", "company", "salary_range", "posted_at",
        "posted_text", "remote_status", "location", "url", "source_saved_at",
        "extracted_at",
    )
    prospects = [dict(zip(fields, row)) for row in rows]
    for prospect in prospects:
        prospect["source"] = job_history.job_source(prospect["job_key"], prospect["url"])
    return prospects


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract or export saved job facts.")
    parser.add_argument("action", choices=("backfill", "export"))
    parser.add_argument("--output", default="prospective_jobs.json")
    args = parser.parse_args()
    if args.action == "backfill":
        print(f"Extracted {backfill()} saved jobs.")
    else:
        prospects = list_prospects()
        Path(args.output).write_text(
            json.dumps(prospects, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Exported {len(prospects)} jobs to {args.output}.")
        print(f"By source: {source_counts(row['source'] for row in prospects)}.")
