"""Shared search location choices and conservative Greenhouse matching."""

import re


NYC_LABEL = re.compile(
    r"\b(?:nyc|new york city|new york,\s*(?:ny|new york|us|usa)|"
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
REMOTE_WORD = re.compile(r"\bremote\b", re.IGNORECASE)
# Clear foreign-only restrictions should stay out; other remote labels are
# retained so an unfamiliar shorthand cannot hide a potentially eligible job.
FOREIGN_ONLY_REMOTE = re.compile(
    r"\b(?:canada|india|uk|united kingdom|london|ireland|dublin|germany|berlin|"
    r"poland|romania|europe|eu|emea|apac|australia|france|spain|portugal|"
    r"netherlands|brazil|mexico|singapore|japan|philippines|south africa|"
    r"united arab emirates|uae|israel)\b",
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
    """Match NYC labels and retain remote jobs without a foreign-only restriction."""
    location = normalize_search_location(location)
    field = job.get("location") or {}
    name = field.get("name", "") if isinstance(field, dict) else ""
    if not isinstance(name, str):
        return False
    name = name.strip()
    if location == "nyc":
        return name.casefold() == "new york" or bool(NYC_LABEL.search(name))
    if not REMOTE_WORD.search(name):
        return False
    if REMOTE_US.search(name) or REMOTE_NYC.search(name):
        return True
    return not FOREIGN_ONLY_REMOTE.search(name)
