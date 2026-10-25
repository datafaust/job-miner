"""Role-specific title and responsibility checks for configured searches."""

import json
import re
from functools import lru_cache
from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "related_keys.json"
START_HEADINGS = (
    "responsibilities", "what you'll do", "what you will do", "your responsibilities",
    "what you will be doing", "what you'll be doing", "duties", "day to day",
    "your impact", "about the role", "the role",
)
STOP_HEADINGS = (
    "qualifications", "requirements", "who you are", "what we're looking for",
    "what we are looking for", "what you bring", "what you'll bring",
    "your background", "skills", "experience", "minimum qualifications",
    "preferred qualifications", "nice to have", "benefits", "perks",
    "about us", "about the company", "compensation",
)


def normalize(value):
    """Match whole words while treating punctuation and hyphens as spaces."""
    return " ".join(re.findall(r"[a-z0-9]+", str(value).casefold()))


@lru_cache(maxsize=1)
def load_related_keys():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    required = {"primary_title_phrases", "related_title_phrases",
                "supporting_title_terms", "description_signals"}
    if not isinstance(config, dict):
        raise ValueError("Related keys config must be an object")
    for role, profile in config.items():
        if not isinstance(role, str) or not isinstance(profile, dict) or set(profile) != required:
            raise ValueError(f"Invalid related keys profile: {role}")
        for field, values in profile.items():
            if not isinstance(values, list) or not values or any(
                not isinstance(value, str) or not normalize(value) for value in values
            ):
                raise ValueError(f"Invalid related keys field: {role}.{field}")
    return config


def role_profile(query):
    """Use the longest configured role phrase found in the search request."""
    normalized_query = f" {normalize(query)} "
    roles = load_related_keys()
    matches = [role for role in roles if f" {normalize(role)} " in normalized_query]
    return roles[max(matches, key=len)] if matches else None


def _contains(text, phrase):
    return f" {normalize(phrase)} " in f" {normalize(text)} "


def title_may_match(query, title):
    """Screen listing titles before fetching Idealist details."""
    profile = role_profile(query)
    if profile is None:
        return True
    return title_strength(query, title) > 0


def title_strength(query, title):
    """Rank primary titles ahead of related phrases and broad title terms."""
    profile = role_profile(query)
    if profile is None:
        return 0
    for strength, field in ((3, "primary_title_phrases"),
                            (2, "related_title_phrases"),
                            (1, "supporting_title_terms")):
        if any(_contains(title, phrase) for phrase in profile[field]):
            return strength
    return 0


def _responsibility_text(description):
    """Prefer labeled duties and never count text after a qualification heading."""
    sections = []
    current = []
    before_stop = []
    in_duties = False
    found_heading = False
    intro_closed = False
    for raw_line in str(description).splitlines():
        line = raw_line.strip()
        heading = normalize(line.rstrip(":"))
        if len(heading) < 65 and any(heading == normalize(value) for value in START_HEADINGS):
            found_heading = True
            if current:
                sections.append(" ".join(current))
            current = []
            in_duties = True
        elif len(heading) < 65 and any(heading == normalize(value) for value in STOP_HEADINGS):
            if current:
                sections.append(" ".join(current))
            current = []
            in_duties = False
            intro_closed = True
        elif in_duties:
            current.append(line)
        elif not found_heading and not intro_closed:
            before_stop.append(line)
    if current:
        sections.append(" ".join(current))
    return " ".join(sections) if found_heading else " ".join(before_stop)


def is_relevant(query, title, description):
    """Primary title, or broader title plus two distinct duty signals."""
    profile = role_profile(query)
    if profile is None:
        return True
    strength = title_strength(query, title)
    if strength == 3:
        return True
    if not strength:
        return False
    duties = _responsibility_text(description)
    signals = {normalize(phrase) for phrase in profile["description_signals"]
               if _contains(duties, phrase)}
    return len(signals) >= 2
