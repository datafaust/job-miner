"""Deterministic selection checks and review leads for a tailored resume."""

import re


REQUIRED_FIELDS = {"summary", "skills", "certifications", "experience", "projects", "education", "publications"}
ALLOWED_FIELDS = REQUIRED_FIELDS | {"name", "contact_line"}
TECHNOLOGIES = (
    "Python", "SQL", "R", "AWS", "Azure", "GCP", "Flask", "Docker", "Kubernetes",
    "Kafka", "Spark", "Airflow", "dbt", "Snowflake", "Tableau", "PostgreSQL",
    "Java", "Scala", "EHR", "HL7", "FHIR", "Power BI", "Looker",
)
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "in", "into", "is", "it", "of", "on", "or", "our", "that", "the", "their", "to",
    "using", "with", "you", "your", "years", "experience", "work", "role", "team",
    "ability", "skills", "strong", "knowledge", "required", "preferred",
}
HEADING_KINDS = {
    "responsibilities": "responsibility", "what you'll do": "responsibility",
    "what you’ll do": "responsibility", "duties": "responsibility",
    "minimum requirements": "required", "requirements": "required",
    "required qualifications": "required", "qualifications": "required",
    "who you are": "required", "what we're looking for": "required",
    "preferred qualifications": "preferred", "nice to have": "preferred",
    "bonus qualifications": "preferred",
}


class SelectionValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("; ".join(errors))


def _duplicates(items):
    return len(items) != len(set(items))


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def validation_errors(selection, inventory, *, rewrite_mode):
    """Collect all detectable renderer/schema problems without changing the selection."""
    errors = []
    if not isinstance(selection, dict):
        return ["Selection must be a JSON object"]
    missing = REQUIRED_FIELDS - selection.keys()
    unknown = selection.keys() - ALLOWED_FIELDS
    if missing:
        errors.append("Selection is missing fields: " + ", ".join(sorted(missing)))
    if unknown:
        errors.append("Selection has unsupported fields: " + ", ".join(sorted(unknown)))

    identity = inventory.get("identity", {})
    if "name" in selection and (not _text(selection["name"]) or
                                selection["name"].casefold() != str(identity.get("name", "")).casefold()):
        errors.append("name must match the inventory identity")
    if "contact_line" in selection and selection["contact_line"] != identity.get("contact_line_as_written"):
        errors.append("contact_line must match the inventory identity")

    summary = selection.get("summary")
    if not isinstance(summary, dict):
        errors.append("summary must be an object")
    else:
        if set(summary) - {"text", "source_ids"}:
            errors.append("summary has unsupported fields")
        summary_text = summary.get("text")
        if not _text(summary_text):
            errors.append("summary must contain nonempty text")
        else:
            count = len(summary_text.split())
            if not 45 <= count <= 70:
                errors.append(f"summary must be 45-70 words (found {count})")
            if "\n" in summary_text:
                errors.append("summary must be one paragraph")
            if "10+ years of experience" not in summary_text.casefold():
                errors.append("summary must contain '10+ years of experience'")
        source_ids = summary.get("source_ids")
        known = {item["id"] for item in inventory.get("summary_statements", [])}
        known.update(item["id"] for group in ("experience", "projects")
                     for role in inventory.get(group, []) for item in role.get("accomplishments", []))
        if not isinstance(source_ids, list) or not source_ids or any(
            not isinstance(item, str) or item not in known for item in source_ids
        ):
            errors.append("summary.source_ids must contain known accomplishment IDs")
        elif _duplicates(source_ids):
            errors.append("summary.source_ids contains duplicate IDs")
        if not isinstance(source_ids, list) or "SUM-001" not in source_ids:
            errors.append("summary.source_ids must include SUM-001")

    categories = {item["category"]: item["original_text"] for item in inventory.get("skills", [])}
    skills = selection.get("skills")
    if not isinstance(skills, list):
        errors.append("skills must be a list")
    else:
        selected_categories = []
        for index, item in enumerate(skills):
            if (not isinstance(item, dict) or not isinstance(item.get("category"), str)
                    or item["category"] not in categories or not _text(item.get("text"))):
                errors.append(f"skills[{index}] must use an inventory category and nonempty text")
            else:
                selected_categories.append(item["category"])
                if set(item) - {"category", "text"}:
                    errors.append(f"skills[{index}] has unsupported fields")
        if _duplicates(selected_categories):
            errors.append("skills contains duplicate categories")

    certifications = selection.get("certifications")
    permitted_certifications = {item["original_text"] for item in inventory.get("certifications", [])}
    if not isinstance(certifications, list) or any(
        not isinstance(item, str) or item not in permitted_certifications for item in certifications
    ):
        errors.append("certifications must exactly match inventory entries")
    elif _duplicates(certifications):
        errors.append("certifications contains duplicates")

    for group in ("experience", "projects"):
        entries = selection.get(group)
        if not isinstance(entries, list):
            errors.append(f"{group} must be a list")
            continue
        if group == "experience" and not entries:
            errors.append("experience must include at least one role")
        roles = {role["id"]: role for role in inventory.get(group, [])}
        positions = {role_id: index for index, role_id in enumerate(roles)}
        seen = set()
        previous_position = -1
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or entry["id"] not in roles:
                errors.append(f"{group}[{index}] contains an unknown role ID")
                continue
            role_id = entry["id"]
            if role_id in seen:
                errors.append(f"{group} contains duplicate role ID {role_id}")
            if positions[role_id] <= previous_position:
                errors.append(f"{group} roles must be in inventory order")
            seen.add(role_id)
            previous_position = positions[role_id]
            if set(entry) - {"id", "bullets", "bullet_overrides", "dates"}:
                errors.append(f"{group} {role_id} has unsupported fields")
            bullets = entry.get("bullets")
            allowed = {item["id"] for item in roles[role_id].get("accomplishments", [])}
            if not isinstance(bullets, list) or not bullets or any(
                not isinstance(item, str) or item not in allowed for item in bullets
            ):
                errors.append(f"{group} {role_id} has invalid bullet IDs")
                bullets = []
            elif _duplicates(bullets):
                errors.append(f"{group} {role_id} has duplicate bullet IDs")
            if group == "experience" and len(bullets) < (5 if role_id == "BAO" else 3):
                errors.append(f"{role_id} has too few bullets")
            if "dates" in entry:
                errors.append(f"{group} {role_id} has an unverified date override")
            overrides = entry.get("bullet_overrides", {})
            if not isinstance(overrides, dict) or set(overrides) - set(bullets) or any(
                not _text(text) for text in overrides.values()
            ):
                errors.append(f"{group} {role_id} has invalid bullet overrides")
            elif rewrite_mode == "none" and overrides:
                errors.append("bullet_overrides are not allowed in none mode")
            elif group == "projects" and overrides:
                errors.append("The current renderer does not support project bullet overrides")

    if not isinstance(selection.get("education"), bool):
        errors.append("education must be a boolean")
    publications = selection.get("publications")
    allowed_publications = {item["id"] for item in inventory.get("publications", [])}
    if not isinstance(publications, list) or any(
        not isinstance(item, str) or item not in allowed_publications for item in publications
    ):
        errors.append("publications must contain inventory IDs")
    elif _duplicates(publications):
        errors.append("publications contains duplicate IDs")
    return errors


def validate_selection(selection, inventory, *, rewrite_mode):
    errors = validation_errors(selection, inventory, rewrite_mode=rewrite_mode)
    if errors:
        raise SelectionValidationError(errors)


def _words(value):
    return {word for word in re.findall(r"[a-z][a-z0-9+#]*", value.casefold())
            if len(word) > 2 and word not in STOP_WORDS}


def _numbers(value):
    return set(re.findall(r"(?<!\w)(?:\$)?\d[\d,.]*\+?%?", value))


def _technology_terms(value):
    return {name for name in TECHNOLOGIES if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", value, re.I)}


def _source_texts(inventory):
    texts = {item["id"]: item["original_text"] for item in inventory.get("summary_statements", [])}
    for group in ("experience", "projects"):
        for role in inventory.get(group, []):
            texts.update({item["id"]: item["original_text"] for item in role.get("accomplishments", [])})
    return texts


def extract_requirements(posting_text):
    """Extract labelled posting lines without claiming to parse every requirement."""
    results = []
    kind = None
    for line in posting_text.splitlines():
        line = line.strip().lstrip("•*- ").strip()
        if not line:
            continue
        heading = line.rstrip(":").casefold()
        if heading in HEADING_KINDS:
            kind = HEADING_KINDS[heading]
            continue
        if kind and (heading in {"benefits", "about the team", "about us", "how to apply", "compensation"}):
            kind = None
        if kind and len(line) >= 20 and not line.lower().startswith("we're looking for someone"):
            results.append({"kind": kind, "text": line})
    return results


def _claim_flags(claim, evidence_text):
    flags = []
    tenure_scope = re.search(
        r"10\+ years of experience\s+(?:with|using|in|building)\s+([^,.]+)", claim, re.I
    )
    if tenure_scope and _technology_terms(tenure_scope.group(1)):
        flags.append("10+ years may be attached to a specific technology; verify scope")
    missing_numbers = sorted(_numbers(claim) - _numbers(evidence_text))
    if missing_numbers:
        flags.append("numbers absent from cited source: " + ", ".join(missing_numbers))
    missing_technologies = sorted(_technology_terms(claim) - _technology_terms(evidence_text))
    if missing_technologies:
        flags.append("technical terms absent from cited source: " + ", ".join(missing_technologies))
    overlap = _words(claim) & _words(evidence_text)
    if len(overlap) < 2:
        flags.append("little wording overlap with cited source; check meaning manually")
    return flags


def build_evidence_report(selection, inventory, posting_text):
    """Return review leads, never a claim that prose has been fact checked."""
    texts = _source_texts(inventory)
    selected_ids = [aid for group in ("experience", "projects") for role in selection[group]
                    for aid in role["bullets"]]
    requirements = []
    for requirement in extract_requirements(posting_text):
        terms = _words(requirement["text"])
        ranked = sorted(((len(terms & _words(texts[aid])), aid) for aid in selected_ids), reverse=True)
        leads = [{"source_id": aid, "source_text": texts[aid], "shared_terms": score}
                 for score, aid in ranked if score >= 2][:3]
        requirements.append({**requirement, "evidence_leads": leads,
                             "review_flag": "no selected evidence lead found" if not leads else None})

    summary = selection["summary"]
    source_ids = summary["source_ids"]
    summary_source = " ".join(texts[aid] for aid in source_ids)
    claim_reviews = [{"field": "summary.text", "source_ids": source_ids,
                      "claim": summary["text"], "source_text": summary_source,
                      "flags": _claim_flags(summary["text"], summary_source)}]
    for role in selection["experience"]:
        for aid, rewrite in role.get("bullet_overrides", {}).items():
            claim_reviews.append({"field": f"experience.{role['id']}.bullet_overrides.{aid}",
                                  "source_ids": [aid], "claim": rewrite,
                                  "source_text": texts[aid],
                                  "flags": _claim_flags(rewrite, texts[aid])})
    skill_sources = {item["category"]: item["original_text"] for item in inventory.get("skills", [])}
    skill_reviews = []
    for item in selection["skills"]:
        original = skill_sources[item["category"]]
        chosen = [term.strip() for term in re.split(r"[,;]", item["text"]) if term.strip()]
        unmatched = [term for term in chosen if term.casefold() not in original.casefold()]
        skill_reviews.append({"category": item["category"], "selected_text": item["text"],
                              "inventory_text": original, "unmatched_items": unmatched})
    return {
        "disclaimer": "Keyword overlap and source IDs are review leads, not proof of factual support.",
        "requirements": requirements,
        "claim_reviews": claim_reviews,
        "skill_reviews": skill_reviews,
        "human_review_required": True,
    }


def evidence_markdown(report):
    """Make the review leads readable without changing the selection artifact."""
    lines = ["# Resume evidence review", "", report["disclaimer"], "",
             "## Job requirements and selected evidence", ""]
    if not report["requirements"]:
        lines.extend(["No labelled requirement lines were extracted. Review the full posting manually.", ""])
    for number, item in enumerate(report["requirements"], 1):
        lines.extend([f"### {number}. {item['kind'].title()}", "", item["text"], ""])
        if item["evidence_leads"]:
            for lead in item["evidence_leads"]:
                lines.append(f"- **{lead['source_id']}** (shared terms: {lead['shared_terms']}): {lead['source_text']}")
        else:
            lines.append("- **Review flag:** No selected evidence lead found.")
        lines.append("")
    lines.extend(["## AI-authored claims to check", ""])
    for item in report["claim_reviews"]:
        lines.extend([f"### {item['field']}", "", f"Claim: {item['claim']}", "",
                      f"Cited IDs: {', '.join(item['source_ids'])}", "",
                      f"Source text: {item['source_text']}", ""])
        if item["flags"]:
            lines.extend(f"- **Review flag:** {flag}" for flag in item["flags"])
        else:
            lines.append("- No automatic flags. Confirm factual support manually.")
        lines.append("")
    lines.extend(["## Selected skills to check", ""])
    for item in report["skill_reviews"]:
        lines.extend([f"### {item['category']}", "", f"Selected: {item['selected_text']}", "",
                      f"Inventory: {item['inventory_text']}", ""])
        if item["unmatched_items"]:
            lines.append("Review flag: Items not found verbatim in category: " +
                         ", ".join(item["unmatched_items"]))
        else:
            lines.append("No unmatched skill items found by text comparison.")
        lines.append("")
    return "\n".join(lines)
