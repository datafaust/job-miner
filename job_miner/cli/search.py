"""Search job boards from the terminal."""
import argparse
import os
import sys

from dotenv import load_dotenv

from job_miner.search.workflow import JobCrew, resolve_search_inputs
from job_tools.job_history import job_source, saved_ai_results
from job_tools.job_stats import format_run, snapshot
from job_miner.paths import PROJECT_DIR


def main(argv=None):
  parser = argparse.ArgumentParser(description="Find and organize Greenhouse, Lever, Ashby, Adzuna, Remote OK, Remotive, and Idealist job postings.")
  parser.add_argument("--model", default="openhermes", help="Ollama model to use (default: openhermes)")
  parser.add_argument("--no-summary", action="store_true", help="Save matching jobs without AI summaries")
  parser.add_argument("--keywords", help="Job search keywords (uses JOB_SEARCH_KEYWORDS if omitted)")
  parser.add_argument("--location", help="Search location: nyc or remote (uses JOB_SEARCH_LOCATION if omitted)")
  parser.add_argument("--idealist-sort", choices=("relevance", "newest"), default="relevance",
                      help="Idealist result order (default: relevance; use newest for scheduled runs)")
  parser.add_argument("--saved-summaries", action="store_true", help="Show saved AI results without searching")
  args = parser.parse_args(argv)

  if args.saved_summaries:
    results = saved_ai_results()
    if not results:
      print("No AI results have been saved yet.")
    for key, title, model, status, result_text, saved_at, url, detail_file in results:
      source_credit = "Credit: Remotive\n" if url.startswith(("https://remotive.com/", "https://www.remotive.com/")) else ""
      if job_source(key, url) == "Adzuna":
        source_credit = "Source: The Adzuna API (https://www.adzuna.com)\n"
      print(
        f"{title} [{status}] — {saved_at}\n"
        f"Job ID: {key}\nModel: {model}\n{source_credit}Source: {url}\n"
        f"Original posting: {detail_file}\nAI result:\n{result_text}\n"
      )
    raise SystemExit(0)

  load_dotenv(PROJECT_DIR / ".env")
  print("## Welcome to Job Finder")
  print('-------------------------------')
  if args.keywords is not None or args.location is not None or not sys.stdin.isatty():
    entered_keywords = args.keywords or ""
    entered_location = args.location or ""
  else:
    keyword_default = os.getenv("JOB_SEARCH_KEYWORDS", "").strip()
    location_default = os.getenv("JOB_SEARCH_LOCATION", "").strip()
    keyword_hint = f" [{keyword_default}]" if keyword_default else ""
    location_hint = f" [{location_default}]" if location_default else ""
    entered_keywords = input(f"What kind of job are you looking for?{keyword_hint}\n")
    entered_location = input(f"Location (nyc or remote)?{location_hint}\n")
  try:
    job_ask, location = resolve_search_inputs(entered_keywords, entered_location)
  except ValueError as error:
    parser.error(str(error))

  job_crew = JobCrew(job_ask, location, model=args.model, summarize=not args.no_summary,
                    idealist_sort=args.idealist_sort)
  before = snapshot()
  try:
    result = job_crew.run()
  except Exception:
    print("\n" + format_run(before, snapshot()))
    raise
  print("\n\n########################")
  print("## Here are your jobs")
  print("########################\n")
  print(result)
  print("\n" + format_run(before, snapshot()))


if __name__ == "__main__":
  main()
