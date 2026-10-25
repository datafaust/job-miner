import argparse
import json
import os
import requests
import traceback
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path

from crewai import Crew
from dotenv import load_dotenv
from job_agents import JobAgents
from job_tasks import JobTasks
from job_tools.browser_tools import BrowserTools
from job_tools.greenhouse import MAX_GREENHOUSE_SUMMARIES, greenhouse_candidates, load_greenhouse_boards, save_greenhouse_job, scrape_greenhouse
from job_tools.job_history import job_key, record_ai_result, saved_ai_results
from job_tools.lever import MAX_LEVER_SUMMARIES, fetch_lever_jobs, lever_candidates, load_lever_boards, save_lever_job
from job_tools.location import normalize_search_location
from job_tools.remoteok import fetch_remoteok_jobs, remoteok_candidates, save_remoteok_job
from job_tools.remotive import fetch_remotive_jobs, remotive_candidates, save_remotive_job
from job_tools.search_tools import SearchTools

PROJECT_DIR = Path(__file__).resolve().parent
CREWAI_LOG_PATH = PROJECT_DIR / "crewai_log.txt"
SUMMARY_LOG_PATH = PROJECT_DIR / "summary_attempts.jsonl"


def resolve_search_inputs(keywords, location):
  """Use environment defaults for blank prompts, then require both values."""
  keywords = keywords.strip() or os.getenv("JOB_SEARCH_KEYWORDS", "").strip()
  location = location.strip() or os.getenv("JOB_SEARCH_LOCATION", "").strip()
  if not keywords:
    raise ValueError("Enter job keywords or set JOB_SEARCH_KEYWORDS")
  if not location:
    raise ValueError("Enter a location or set JOB_SEARCH_LOCATION")
  return keywords, normalize_search_location(location)


def log_summary_attempt(url, title, model, raw_output, status, reason, error=None):
  """Keep the model's original reply and our decision for local debugging."""
  entry = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "job_key": job_key(url),
    "url": url,
    "title": title,
    "model": model,
    "status": status,
    "reason": reason,
    "raw_output": raw_output,
    "error": error,
  }
  try:
    with SUMMARY_LOG_PATH.open("a", encoding="utf-8") as log_file:
      log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
  except OSError as log_error:
    print(f"Could not write summary debug log: {log_error}")


class JobCrew:

  def __init__(self, job_ask, location, model="openhermes"):
    self.job_ask = job_ask
    self.location = location
    self.model = model

  def run(self):
    agents = JobAgents(model=self.model)
    tasks = JobTasks()
    results = []

    candidate_groups = []
    for board in load_greenhouse_boards():
      try:
        jobs = scrape_greenhouse(board["token"])
      except (requests.RequestException, ValueError) as error:
        print(f"Greenhouse scrape failed for {board['company']} ({board['token']}): {error}")
        continue
      matches = greenhouse_candidates(jobs, self.job_ask, board["company"], self.location)
      candidate_groups.append([(match, board["token"]) for match in matches])

    selected_jobs = []
    seen_keys = set()
    for match_type in ("title", "description"):
      groups = [
        [(match, token) for match, token in group
         if match.get("match_type", "title") == match_type]
        for group in candidate_groups
      ]
      for row in zip_longest(*groups):
        for item in row:
          if item is None:
            continue
          match, token = item
          key = job_key(match["link"])
          if key not in seen_keys:
            selected_jobs.append((match, token))
            seen_keys.add(key)
          if len(selected_jobs) == MAX_GREENHOUSE_SUMMARIES:
            break
        if len(selected_jobs) == MAX_GREENHOUSE_SUMMARIES:
          break
      if len(selected_jobs) == MAX_GREENHOUSE_SUMMARIES:
        break

    if selected_jobs:
      for selected, token in selected_jobs:
        url = selected["link"]
        print(f"Selected Greenhouse job: {selected['job']['title']} ({url})")
        job_text = save_greenhouse_job(selected["job"], board_token=token)
        results.append(self._summarize_job(agents, tasks, selected, job_text))
    else:
      print("No matching unprocessed Greenhouse jobs found.")

    lever_groups = []
    for board in load_lever_boards():
      try:
        jobs = fetch_lever_jobs(board["site"], eu=board.get("eu", False))
      except (requests.RequestException, ValueError) as error:
        print(f"Lever fetch failed for {board['company']} ({board['site']}): {error}")
        continue
      matches = lever_candidates(jobs, self.job_ask, board["company"], self.location)
      lever_groups.append([(match, board["site"], board["company"]) for match in matches])

    selected_lever = []
    seen_keys = set()
    for match_type in ("title", "description"):
      groups = [[(match, site, company) for match, site, company in group
                 if match["match_type"] == match_type] for group in lever_groups]
      for row in zip_longest(*groups):
        for item in row:
          if item is None:
            continue
          match, site, company = item
          key = job_key(match["link"])
          if key not in seen_keys:
            selected_lever.append((match, site, company))
            seen_keys.add(key)
          if len(selected_lever) == MAX_LEVER_SUMMARIES:
            break
        if len(selected_lever) == MAX_LEVER_SUMMARIES:
          break
      if len(selected_lever) == MAX_LEVER_SUMMARIES:
        break

    if selected_lever:
      for selected, site, company in selected_lever:
        url = selected["link"]
        print(f"Selected Lever job: {selected['job']['text']} ({url})")
        job_text = save_lever_job(selected["job"], site=site, company=company)
        results.append(self._summarize_job(agents, tasks, selected, job_text))
    else:
      print("No matching unprocessed Lever jobs found.")

    if self.location == "remote":
      try:
        remote_jobs = fetch_remoteok_jobs()
        remote_matches = remoteok_candidates(remote_jobs, self.job_ask)
        for selected in remote_matches:
          url = selected["link"]
          print(f"Selected Remote OK job: {selected['job']['position']} ({url})")
          job_text = save_remoteok_job(selected["job"])
          results.append(self._summarize_job(agents, tasks, selected, job_text))
        if not remote_matches:
          print("No matching unprocessed Remote OK jobs found.")
      except (OSError, ValueError) as error:
        print(f"Remote OK search failed: {error}")

      try:
        remotive_jobs = fetch_remotive_jobs()
        remotive_matches = remotive_candidates(remotive_jobs, self.job_ask)
        for selected in remotive_matches:
          url = selected["link"]
          print(f"Selected Remotive job: {selected['job']['title']} ({url})")
          job_text = save_remotive_job(selected["job"])
          results.append(self._summarize_job(agents, tasks, selected, job_text))
        if not remotive_matches:
          print("No matching unprocessed Remotive jobs found.")
      except (OSError, ValueError) as error:
        print(f"Remotive search failed: {error}")

    search_results = json.loads(SearchTools.search_idealist.run(self.job_ask, self.location))
    if not search_results:
      results.append("No unprocessed Idealist jobs found for this search.")
      return "\n\n".join(results)

    selected = self._select_candidate(agents, tasks, search_results[:3], "Idealist")
    remaining = [selected] + [job for job in search_results[:3] if job["link"] != selected["link"]]
    for candidate in remaining:
      url = candidate["link"]
      job_text = BrowserTools.scrape_idealist_job_details.run(url, self.job_ask)
      if job_text is None:
        continue
      if not job_text or job_text.startswith("This Idealist job was already processed"):
        raise RuntimeError("The selected job could not be scraped.")
      print(f"Selected job: {candidate['text'].splitlines()[0]} ({url})")
      results.append(self._summarize_job(agents, tasks, candidate, job_text))
      break
    else:
      results.append("No relevant unprocessed Idealist jobs found for this search.")
    return "\n\n".join(results)

  def _select_candidate(self, agents, tasks, candidates, source):
    # The agent may recommend a candidate, but it cannot invent a new URL.
    if len(candidates) == 1:
      return candidates[0]
    listings = [{"text": job["text"], "link": job["link"]} for job in candidates]
    selection_task = tasks.identify_task(
      agents.job_selection_agent(), self.job_ask, listings, source
    )
    try:
      selection = str(Crew(
        agents=[selection_task.agent], tasks=[selection_task], verbose=True,
        output_log_file=str(CREWAI_LOG_PATH),
      ).kickoff())
    except Exception as error:
      print(f"Selection agent failed ({type(error).__name__}); using the first search result.")
      return candidates[0]
    matches = [job for job in candidates if job["link"] in selection]
    if len(matches) == 1:
      return matches[0]
    print("Selection agent did not identify one listed URL; using the first search result.")
    return candidates[0]

  def _summarize_job(self, agents, tasks, selected, job_text):
    url = selected["link"]
    organizer = agents.job_information_organizer()
    job_title = selected["text"].splitlines()[0].strip()
    gather_task = tasks.gather_task(organizer, job_text, url, job_title)
    raw_output = None
    error_detail = None
    try:
      raw_output = str(Crew(
        agents=[organizer], tasks=[gather_task], verbose=True,
        output_log_file=str(CREWAI_LOG_PATH),
      ).kickoff())
      summary = raw_output.strip()
      lines = [line.strip() for line in summary.splitlines() if line.strip()]
      skip_line = f"NO_SUMMARY_NEEDED: {job_title}"
      if (
        len(lines) == 2
        and lines[0] == skip_line
        and lines[1].startswith("Reason:")
        and lines[1][len("Reason:"):].strip()
        and "tool" not in lines[1].casefold()
      ):
        summary = f"No summary needed for {job_title}. {lines[1][len('Reason:'):].strip()}"
        summary_status = "not_needed"
        reason = "Model said the posting was already clear"
      elif len(lines) < 2 or lines[0] != f"SUMMARY: {job_title}":
        summary = "The selected model did not produce a job-specific summary."
        summary_status = "failed"
        if not lines:
          reason = "Empty model response"
        elif lines[0].startswith("NO_SUMMARY_NEEDED:"):
          reason = "NO_SUMMARY_NEEDED response did not have exactly two valid lines"
        elif lines[0] != f"SUMMARY: {job_title}":
          reason = f"Expected first line: SUMMARY: {job_title}"
        else:
          reason = "Summary body was missing"
      else:
        summary_status = "summarized"
        reason = "Valid job-specific summary"
    except Exception as error:
      print(f"Organizer agent failed ({type(error).__name__}); showing the original posting.")
      summary = "The selected model could not summarize this posting."
      summary_status = "failed"
      reason = f"CrewAI raised {type(error).__name__}"
      error_detail = traceback.format_exc()

    log_summary_attempt(url, job_title, self.model, raw_output, summary_status, reason, error_detail)

    record_ai_result(url, job_title, self.model, summary_status, summary)
    print(f"Saved AI result under job ID {job_key(url)} in job_history.sqlite3.")

    return (
      f"Source: {url}\n\nSearch listing:\n{selected['text']}\n\n"
      f"AI result:\n{summary}\n\nOriginal posting text:\n{job_text}"
    )

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="Find and organize Greenhouse, Lever, Remote OK, Remotive, and Idealist job postings.")
  parser.add_argument("--model", default="openhermes", help="Ollama model to use (default: openhermes)")
  parser.add_argument("--saved-summaries", action="store_true", help="Show saved AI results without searching")
  args = parser.parse_args()

  if args.saved_summaries:
    results = saved_ai_results()
    if not results:
      print("No AI results have been saved yet.")
    for key, title, model, status, result_text, saved_at, url, detail_file in results:
      source_credit = "Credit: Remotive\n" if url.startswith(("https://remotive.com/", "https://www.remotive.com/")) else ""
      print(
        f"{title} [{status}] — {saved_at}\n"
        f"Job ID: {key}\nModel: {model}\n{source_credit}Source: {url}\n"
        f"Original posting: {detail_file}\nAI result:\n{result_text}\n"
      )
    raise SystemExit(0)

  load_dotenv(PROJECT_DIR / ".env")
  print("## Welcome to Job Finder")
  print('-------------------------------')
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

  job_crew = JobCrew(job_ask, location, model=args.model)
  result = job_crew.run()
  print("\n\n########################")
  print("## Here are your jobs")
  print("########################\n")
  print(result)
