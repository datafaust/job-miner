"""Load a saved or local posting as the source text for resume tailoring."""

import hashlib
import json
from pathlib import Path

from job_tools.greenhouse import _description_text
from job_tools.job_history import job_key, saved_job
from job_tools.lever import _description as lever_description
from job_tools.ashby import _description as ashby_description


PROJECT_DIR = Path(__file__).resolve().parent.parent


def _required_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Posting is missing {field}")
    return value.strip()


def _optional_text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _json_posting(job):
    if not isinstance(job, dict):
        raise ValueError("Posting JSON must be an object")

    if "content" in job and "absolute_url" in job:
        title = _required_text(job.get("title"), "title")
        url = _optional_text(job.get("absolute_url"))
        description = _description_text(_required_text(job.get("content"), "content"))
        location = job.get("location") or {}
        location = location.get("name") if isinstance(location, dict) else None
        header = [title, _optional_text(job.get("company_name")), _optional_text(location)]
        source = "greenhouse"
    elif "jobUrl" in job and "title" in job:
        title = _required_text(job.get("title"), "title")
        url = _optional_text(job.get("jobUrl") or job.get("applyUrl"))
        description = ashby_description(job)
        header = [title, _optional_text(job.get("_job_watcher_company")), _optional_text(job.get("location"))]
        source = "ashby"
    elif "lists" in job or "descriptionPlain" in job or "hostedUrl" in job:
        title = _required_text(job.get("text"), "text")
        url = _optional_text(job.get("hostedUrl") or job.get("applyUrl"))
        description = lever_description(job)
        categories = job.get("categories") or {}
        location = categories.get("location") if isinstance(categories, dict) else None
        header = [title, _optional_text(job.get("_job_watcher_company")), _optional_text(location)]
        source = "lever"
    elif "position" in job:
        title = _required_text(job.get("position"), "position")
        url = _optional_text(job.get("url"))
        description = _description_text(_required_text(job.get("description"), "description"))
        header = [title, _optional_text(job.get("company")), _optional_text(job.get("location"))]
        source = "remoteok"
    elif "company_name" in job and "title" in job:
        title = _required_text(job.get("title"), "title")
        url = _optional_text(job.get("url"))
        description = _description_text(_required_text(job.get("description"), "description"))
        header = [title, _optional_text(job.get("company_name")), _optional_text(job.get("candidate_required_location"))]
        source = "remotive"
    else:
        raise ValueError("Unrecognized posting JSON format")

    description = _required_text(description, "description")
    text = "\n".join(part for part in header if part)
    if url:
        text += f"\nOriginal posting: {url}"
    return source, title, url, text + "\n\n" + description


def load_posting(path, *, source_url=None, source_title=None):
    """Return a normalized posting plus metadata from a source file."""
    path = Path(path).resolve()
    raw = path.read_bytes()
    if path.suffix.lower() == ".json":
        source, detected_title, detected_url, text = _json_posting(json.loads(raw.decode("utf-8")))
    elif path.suffix.lower() == ".txt":
        text = raw.decode("utf-8").strip()
        _required_text(text, "text")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        published = next((i for i, line in enumerate(lines) if line.startswith("Published ")), None)
        detected_title = lines[published + 1] if published is not None and len(lines) > published + 1 else lines[0]
        detected_url = None
        source = "idealist" if published is not None else "text"
    else:
        raise ValueError("Posting file must be .json or .txt")

    title = _required_text(source_title or detected_title, "title")
    if source_url and detected_url and job_key(source_url) != job_key(detected_url):
        raise ValueError("Provided job URL does not match the posting source URL")
    url = source_url or detected_url
    if url:
        # Use the same URL rules and stable key as job history.
        from job_tools.job_history import extract_job_url
        url = extract_job_url(url)
    source_hash = hashlib.sha256(raw).hexdigest()
    return {
        "source": source,
        "source_file": str(path),
        "source_sha256": source_hash,
        "title": title,
        "url": url,
        "job_id": job_key(url) if url else "local:" + source_hash[:16],
        "posting_text": text,
        "posting_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def load_saved_posting(key):
    row = saved_job(key)
    if row is None:
        raise ValueError(f"No saved posting found for job ID: {key}")
    url, detail_file = row
    path = Path(detail_file)
    if not path.is_absolute() and not path.exists():
        path = PROJECT_DIR / path
    result = load_posting(path, source_url=url)
    if result["job_id"] != key:
        raise ValueError(f"Saved posting ID does not match source URL: {key}")
    return result
