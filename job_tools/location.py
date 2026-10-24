"""Shared search location choices and conservative Greenhouse matching."""

import re


NYC_LABEL = re.compile(
    r"\b(?:nyc|new york city|new york,\s*(?:ny|us|usa)|"
    r"manhattan|brooklyn|queens|bronx|staten island)\b",
    re.IGNORECASE,
)
US = r"(?:us|u\.s\.|usa|united states)"
REMOTE_US = re.compile(
    rf"(?:\b{US}\b[\s()/,-]*remote\b|"
    rf"\bremote\b[\s()/,-]*(?:(?:in|from|for|within)\s+)?(?:the\s+)?{US}\b)",
    re.IGNORECASE,
)
REMOTE_NYC = re.compile(
    r"\bremote\b[\s()/,-]*(?:(?:in|from|for|within)\s+)?(?:the\s+)?"
    r"(?:nyc|new york city|new york,\s*ny)\b",
    re.IGNORECASE,
)


def normalize_search_location(value):
    """Recognize the two supported choices, including NYC aliases."""
    location = value.strip().casefold()
    if location in {"nyc", "new york", "new york city", "new york, ny"}:
        return "nyc"
    if location == "remote":
        return "remote"
    raise ValueError("Location must be nyc (or New York) or remote")


def greenhouse_matches_location(job, location):
    """Include only explicit NYC or US/NYC remote location labels."""
    location = normalize_search_location(location)
    field = job.get("location") or {}
    name = field.get("name", "") if isinstance(field, dict) else ""
    if not isinstance(name, str):
        return False
    name = name.strip()
    if location == "nyc":
        return bool(NYC_LABEL.search(name))
    return name.casefold() == "remote" or bool(
        REMOTE_US.search(name) or REMOTE_NYC.search(name)
    )
