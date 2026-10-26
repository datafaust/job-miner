"""Summaries of saved jobs and a counted reset of local job history."""

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from job_tools import job_history


PROJECT_DIR = Path(__file__).resolve().parent.parent
SOURCES = ("Greenhouse", "Lever", "Ashby", "Adzuna", "Remote OK", "Remotive", "Idealist", "Other")


@dataclass(frozen=True)
class HistorySnapshot:
    processed: dict[str, str]
    prospects: set[str]
    summaries: dict[str, str]


def snapshot():
    """Read the current database state, keyed by stable posting ID."""
    with job_history._database() as connection:
        processed = {
            key: job_history.job_source(key, url)
            for key, url in connection.execute("SELECT job_key, url FROM processed_jobs")
        }
        prospects = {key for (key,) in connection.execute("SELECT job_key FROM prospective_jobs")}
        summaries = dict(connection.execute("SELECT job_key, status FROM job_summaries"))
    return HistorySnapshot(processed, prospects, summaries)


def source_counts(sources):
    counts = Counter(sources)
    return ", ".join(f"{source} {counts[source]}" for source in SOURCES if source != "Other" or counts[source])


def format_totals(state):
    missing = len(state.processed.keys() - state.prospects)
    return (
        f"Database totals: {len(state.processed)} saved jobs, "
        f"{len(state.prospects)} prospects, {len(state.summaries)} AI results.\n"
        f"By source: {source_counts(state.processed.values())}.\n"
        f"Saved jobs missing prospect facts: {missing}."
    )


def format_run(before, after):
    new_keys = after.processed.keys() - before.processed.keys()
    new_prospects = after.prospects - before.prospects
    new_summaries = after.summaries.keys() - before.summaries.keys()
    statuses = Counter(after.summaries[key] for key in new_summaries)
    return (
        "Run summary\n"
        f"Added to database: {len(new_keys)} saved jobs; "
        f"{len(new_prospects)} prospect rows; {len(new_summaries)} AI results "
        f"(summarized {statuses['summarized']}, "
        f"not needed {statuses['not_needed']}, failed {statuses['failed']}).\n"
        f"New jobs by source: {source_counts(after.processed[key] for key in new_keys)}.\n"
        f"New prospects by source: {source_counts(after.processed[key] for key in new_prospects)}.\n"
        + format_totals(after)
    )


def reset_history():
    """Delete only known generated job history files, then report what was cleared."""
    before = snapshot()
    saved_files = [path for path in (PROJECT_DIR / "jobs").glob("JOB_*") if path.is_file()]
    files = set(PROJECT_DIR.glob("job_history.sqlite3*"))
    files.update(PROJECT_DIR / name for name in (
        "prospective_jobs.json", "output.json", "crewai_log.txt", "summary_attempts.jsonl"
    ))
    files.update(saved_files)
    removed = 0
    for path in files:
        if path.is_file():
            path.unlink()
            removed += 1
    return (
        "History reset\n"
        f"Cleared {len(before.processed)} saved jobs, {len(before.prospects)} prospect rows, "
        f"{len(before.summaries)} AI results, and {len(saved_files)} saved posting files.\n"
        f"Cleared jobs by source: {source_counts(before.processed.values())}.\n"
        f"Removed {removed} generated files; OAuth credentials and token were kept."
    )


def main():
    parser = argparse.ArgumentParser(description="Show job history counts or clear local history.")
    parser.add_argument("action", nargs="?", choices=("stats", "reset"), default="stats")
    args = parser.parse_args()
    print(reset_history() if args.action == "reset" else format_totals(snapshot()))


if __name__ == "__main__":
    main()
