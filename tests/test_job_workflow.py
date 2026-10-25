import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import JobCrew
from job_tools.greenhouse import MAX_GREENHOUSE_SUMMARIES


class JobWorkflowTests(unittest.TestCase):
    def setUp(self):
        log_directory = tempfile.TemporaryDirectory()
        self.addCleanup(log_directory.cleanup)
        self.summary_log = Path(log_directory.name) / "summary_attempts.jsonl"
        summary_log_patch = patch("main.SUMMARY_LOG_PATH", self.summary_log)
        summary_log_patch.start()
        self.addCleanup(summary_log_patch.stop)
        crewai_log_patch = patch("main.CREWAI_LOG_PATH", Path(log_directory.name) / "crewai_log.txt")
        crewai_log_patch.start()
        self.addCleanup(crewai_log_patch.stop)
        summary_patch = patch("main.record_ai_result")
        self.record_ai_result = summary_patch.start()
        self.addCleanup(summary_patch.stop)
        greenhouse_patch = patch("main.scrape_greenhouse")
        self.scrape_greenhouse = greenhouse_patch.start()
        self.scrape_greenhouse.return_value = []
        self.addCleanup(greenhouse_patch.stop)
        boards_patch = patch("main.load_greenhouse_boards", return_value=[{"company": "Stripe", "token": "stripe"}])
        boards_patch.start()
        self.addCleanup(boards_patch.stop)
        remote_patch = patch("main.fetch_remoteok_jobs", return_value=[])
        self.fetch_remoteok_jobs = remote_patch.start()
        self.addCleanup(remote_patch.stop)

    def test_unhelpful_model_output_cannot_replace_a_real_posting(self):
        candidates = [
            {
                "text": "Software Engineer (Early Career)\nExample Organization\nRemote",
                "link": "https://www.idealist.org/en/nonprofit-job/6965cacf0cf845ffaaae044a336111ec-software-engineer",
            },
            {
                "text": "Business Systems Engineer\nAnother Organization",
                "link": "https://www.idealist.org/en/nonprofit-job/f74488e68a154b1aa8e1e641f3d1dc38-engineer",
            },
        ]
        original_posting = "Software Engineer (Early Career)\nSalary: USD $72,000 - $82,000 / year"

        with patch("main.SearchTools") as search, patch("main.BrowserTools") as browser:
            search.search_idealist.run.return_value = json.dumps(candidates)
            browser.scrape_idealist_job_details.run.return_value = original_posting
            with patch(
                "main.Crew.kickoff",
                side_effect=["I cannot choose a job", "No further action is needed."],
            ):
                output = JobCrew("software engineer", "nyc", model="qwen2.5:1.5b").run()

        search.search_idealist.run.assert_called_once_with("software engineer", "nyc")
        self.scrape_greenhouse.assert_called_once_with("stripe")
        browser.scrape_idealist_job_details.run.assert_called_once_with(candidates[0]["link"])
        self.assertIn(candidates[0]["link"], output)
        self.assertIn(original_posting, output)
        self.assertIn("did not produce a job-specific summary", output)
        self.assertNotIn("No further action is needed", output)
        self.assertEqual(self.record_ai_result.call_args.args[3], "failed")
        attempts = [json.loads(line) for line in self.summary_log.read_text().splitlines()]
        self.assertEqual(attempts[0]["raw_output"], "No further action is needed.")
        self.assertIn("Expected first line", attempts[0]["reason"])
        self.assertEqual(attempts[0]["status"], "failed")

    def test_no_results_stops_before_scraping_or_ai_summary(self):
        with patch("main.SearchTools") as search, patch("main.BrowserTools") as browser:
            search.search_idealist.run.return_value = "[]"
            with patch("main.Crew") as crew:
                output = JobCrew("nonexistent role", "nyc").run()

        self.assertIn("No unprocessed Idealist jobs", output)
        self.scrape_greenhouse.assert_called_once_with("stripe")
        browser.scrape_idealist_job_details.run.assert_not_called()
        crew.assert_not_called()
        self.record_ai_result.assert_not_called()

    def test_remote_choice_reaches_both_sources(self):
        with patch("main.greenhouse_candidates", return_value=[]) as candidates, \
             patch("main.SearchTools") as search:
            self.scrape_greenhouse.return_value = [{"title": "Example"}]
            search.search_idealist.run.return_value = "[]"
            JobCrew("data analyst", "remote").run()

        candidates.assert_called_once_with([{"title": "Example"}], "data analyst", "Stripe", "remote")
        search.search_idealist.run.assert_called_once_with("data analyst", "remote")

    def test_remoteok_result_is_saved_and_summarized(self):
        job = {"id": "123", "position": "Data Analyst", "url": "https://remoteok.com/remote-jobs/123-data-analyst"}
        candidate = {"text": "Data Analyst\nExample\nRemote OK", "link": job["url"], "job": job}
        self.fetch_remoteok_jobs.return_value = [job]
        with patch("main.remoteok_candidates", return_value=[candidate]) as candidates, \
             patch("main.save_remoteok_job", return_value="Source: Remote OK\nOriginal posting") as save, \
             patch("main.SearchTools") as search, \
             patch("main.Crew.kickoff", return_value="SUMMARY: Data Analyst\nUseful summary"):
            search.search_idealist.run.return_value = "[]"
            output = JobCrew("data analyst", "remote").run()
        candidates.assert_called_once_with([job], "data analyst")
        save.assert_called_once_with(job)
        self.assertIn("Source: Remote OK", output)
        self.assertIn(job["url"], output)
        self.assertEqual(self.record_ai_result.call_args.args[0], job["url"])

    def test_scraped_posting_is_returned_if_organizer_fails(self):
        candidate = {
            "text": "Software Engineer\nExample Organization",
            "link": "https://www.idealist.org/en/nonprofit-job/6965cacf0cf845ffaaae044a336111ec-software-engineer",
        }
        with patch("main.SearchTools") as search, patch("main.BrowserTools") as browser:
            search.search_idealist.run.return_value = json.dumps([candidate])
            browser.scrape_idealist_job_details.run.return_value = "Actual job details"
            with patch("main.Crew.kickoff", side_effect=RuntimeError("model failed")):
                output = JobCrew("software engineer", "nyc").run()

        self.assertIn(candidate["link"], output)
        self.assertIn("Actual job details", output)
        self.assertIn("could not summarize", output)
        self.assertEqual(self.record_ai_result.call_args.args[3], "failed")
        attempt = json.loads(self.summary_log.read_text().splitlines()[0])
        self.assertIsNone(attempt["raw_output"])
        self.assertEqual(attempt["reason"], "CrewAI raised RuntimeError")
        self.assertIn("model failed", attempt["error"])

    def test_explicit_no_summary_needed_is_accepted(self):
        candidate = {
            "text": "Software Engineer (Early Career)\nExample Organization",
            "link": "https://www.idealist.org/en/nonprofit-job/6965cacf0cf845ffaaae044a336111ec-software-engineer",
        }
        decision = (
            "NO_SUMMARY_NEEDED: Software Engineer (Early Career)\n"
            "Reason: The posting already separates duties, qualifications, benefits, and application details."
        )
        with patch("main.SearchTools") as search, patch("main.BrowserTools") as browser:
            search.search_idealist.run.return_value = json.dumps([candidate])
            browser.scrape_idealist_job_details.run.return_value = "Actual job details"
            with patch("main.Crew.kickoff", return_value=decision):
                output = JobCrew("software engineer", "nyc").run()

        self.assertIn("No summary needed for Software Engineer (Early Career)", output)
        self.assertIn("already separates duties", output)
        self.assertIn("Actual job details", output)
        self.assertEqual(self.record_ai_result.call_args.args[3], "not_needed")
        attempt = json.loads(self.summary_log.read_text().splitlines()[0])
        self.assertEqual(attempt["raw_output"], decision)
        self.assertEqual(attempt["status"], "not_needed")

    def test_valid_summary_is_saved_with_the_selected_job_id(self):
        candidate = {
            "text": "Data Analyst\nExample Organization",
            "link": "https://www.idealist.org/en/nonprofit-job/8a10b7bd05454fe1b631295eb611de92-data-analyst",
        }
        summary = "SUMMARY: Data Analyst\nBuild dashboards."
        with patch("main.SearchTools") as search, patch("main.BrowserTools") as browser:
            search.search_idealist.run.return_value = json.dumps([candidate])
            browser.scrape_idealist_job_details.run.return_value = "Build dashboards and reports."
            with patch("main.Crew.kickoff", return_value=summary):
                output = JobCrew("data analyst", "nyc", model="qwen2.5:7b").run()

        self.assertIn(summary, output)
        self.record_ai_result.assert_called_once_with(
            candidate["link"], "Data Analyst", "qwen2.5:7b", "summarized", summary
        )

    def test_incomplete_no_summary_decision_is_rejected(self):
        candidate = {
            "text": "Software Engineer (Early Career)\nExample Organization",
            "link": "https://www.idealist.org/en/nonprofit-job/6965cacf0cf845ffaaae044a336111ec-software-engineer",
        }
        with patch("main.SearchTools") as search, patch("main.BrowserTools") as browser:
            search.search_idealist.run.return_value = json.dumps([candidate])
            browser.scrape_idealist_job_details.run.return_value = "Actual job details"
            with patch("main.Crew.kickoff", return_value="NO_SUMMARY_NEEDED: Software Engineer (Early Career)"):
                output = JobCrew("software engineer", "nyc").run()

        self.assertIn("did not produce a job-specific summary", output)
        self.assertNotIn("NO_SUMMARY_NEEDED:", output)
        self.assertEqual(self.record_ai_result.call_args.args[3], "failed")

    def test_greenhouse_result_is_summarized_even_without_idealist_results(self):
        job = {
            "id": 8172487,
            "title": "Software Engineer",
            "absolute_url": "https://stripe.com/jobs/search?gh_jid=8172487",
            "location": {"name": "Remote"},
            "content": "&lt;p&gt;Build services.&lt;/p&gt;",
        }
        self.scrape_greenhouse.return_value = [job]
        candidate = {"text": "Software Engineer\nStripe\nRemote", "link": job["absolute_url"], "job": job}
        with patch("main.greenhouse_candidates", return_value=[candidate]), \
             patch("main.save_greenhouse_job", return_value="Software Engineer\nBuild services.") as save, \
             patch("main.SearchTools") as search, \
             patch("main.BrowserTools") as browser, \
             patch("main.Crew.kickoff", return_value="SUMMARY: Software Engineer\nBuild services."):
            search.search_idealist.run.return_value = "[]"
            output = JobCrew("software engineer", "nyc").run()

        save.assert_called_once_with(job, board_token="stripe")
        self.record_ai_result.assert_called_once_with(
            job["absolute_url"], "Software Engineer", "openhermes", "summarized",
            "SUMMARY: Software Engineer\nBuild services.",
        )
        browser.scrape_idealist_job_details.run.assert_not_called()
        self.assertIn("SUMMARY: Software Engineer", output)
        self.assertIn("No unprocessed Idealist jobs", output)

    def test_configured_boards_continue_after_failure_and_save_with_correct_token(self):
        boards = [
            {"company": "Airbnb", "token": "airbnb"},
            {"company": "Figma", "token": "figma"},
            {"company": "GitHub", "token": "github"},
        ]
        jobs = {
            "figma": [{
                "id": 10, "title": "Software Engineer",
                "absolute_url": "https://boards.greenhouse.io/figma/jobs/10",
                "location": {"name": "Remote"}, "content": "<p>Build software.</p>",
            }],
            "github": [{
                "id": 20, "title": "Software Engineer",
                "absolute_url": "https://boards.greenhouse.io/github/jobs/20",
                "location": {"name": "Remote"}, "content": "<p>Build software.</p>",
            }],
        }

        def fetch(token):
            if token == "airbnb":
                raise ValueError("Invalid response")
            return jobs[token]

        with patch("main.load_greenhouse_boards", return_value=boards), \
             patch("main.greenhouse_candidates", side_effect=lambda items, query, company, location: [
                 {"text": f"{items[0]['title']}\n{company}\nRemote", "link": items[0]["absolute_url"],
                  "job": items[0], "match_type": "title"}
             ]), \
             patch("main.save_greenhouse_job", return_value="Original posting") as save, \
             patch("main.SearchTools") as search, \
             patch("main.Crew.kickoff", return_value="No summary"):
            self.scrape_greenhouse.side_effect = fetch
            search.search_idealist.run.return_value = "[]"
            JobCrew("software engineer", "nyc").run()

        self.assertEqual([call.args[0] for call in self.scrape_greenhouse.call_args_list],
                         ["airbnb", "figma", "github"])
        self.assertEqual([call.kwargs["board_token"] for call in save.call_args_list],
                         ["figma", "github"])
        self.assertEqual(self.record_ai_result.call_count, 2)

    def test_greenhouse_ai_summary_attempts_respect_cap(self):
        candidates = [
            {
                "text": f"Engineer {number}\nStripe\nRemote",
                "link": f"https://stripe.com/jobs/search?gh_jid={number}",
                "job": {"id": number, "title": f"Engineer {number}"},
            }
            for number in range(1, 8)
        ]
        with patch("main.greenhouse_candidates", return_value=candidates), \
             patch("main.save_greenhouse_job", return_value="Original posting") as save, \
             patch("main.SearchTools") as search, \
             patch("main.Crew.kickoff", return_value="No summary") as kickoff:
            search.search_idealist.run.return_value = "[]"
            output = JobCrew("engineer", "nyc").run()

        self.assertEqual(save.call_count, MAX_GREENHOUSE_SUMMARIES)
        self.assertEqual(kickoff.call_count, MAX_GREENHOUSE_SUMMARIES)
        self.assertEqual(self.record_ai_result.call_count, MAX_GREENHOUSE_SUMMARIES)
        self.assertNotIn(f"gh_jid={MAX_GREENHOUSE_SUMMARIES + 1}", output)
        self.assertIn("No unprocessed Idealist jobs", output)


if __name__ == "__main__":
    unittest.main()
