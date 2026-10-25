import unittest
from unittest.mock import patch

from job_tools.greenhouse import greenhouse_candidates
from job_tools.lever import lever_candidates
from job_tools.remoteok import remoteok_candidates
from job_tools.remotive import remotive_candidates
from job_tools.relevance import is_relevant, title_may_match


class RelevanceTests(unittest.TestCase):
    def test_primary_title_passes_without_description_signals(self):
        self.assertTrue(is_relevant("data analyst", "Senior Data Analyst", "Help the team."))
        self.assertTrue(is_relevant("software engineer", "Full-Stack Engineer", "Build services."))

    def test_broad_title_requires_two_distinct_duty_signals(self):
        self.assertFalse(is_relevant("data analyst", "Financial Analyst", "Use SQL and SQL."))
        self.assertTrue(is_relevant(
            "data analyst", "Financial Analyst", "Responsibilities\nUse SQL and build dashboards."
        ))
        self.assertFalse(is_relevant(
            "data analyst", "Financial Analyst",
            "Review budgets.\nQualifications\nSQL and dashboards required."
        ))
        self.assertFalse(is_relevant(
            "data analyst", "Financial Analyst",
            "Responsibilities\nReview budgets.\nQualifications\nSQL and dashboards required."
        ))

    def test_description_only_and_partial_word_do_not_pass(self):
        self.assertFalse(is_relevant("data analyst", "Program Manager", "Analyze data with SQL."))
        self.assertFalse(title_may_match("data analyst", "Psychoanalyst"))

    def test_unconfigured_queries_keep_existing_matching(self):
        self.assertTrue(is_relevant("python developer", "Developer", "Python"))

    def test_all_api_sources_reject_irrelevant_jobs_before_caps(self):
        irrelevant = "SQL and dashboards are listed as qualifications."
        relevant = "Responsibilities\nUse SQL and build dashboards."
        greenhouse_jobs = [
            {"title": "Accountant", "absolute_url": "https://example.com/1",
             "content": f"<p>{irrelevant}</p>"},
            {"title": "Business Analyst", "absolute_url": "https://example.com/2",
             "content": f"<p>{relevant}</p>"},
        ]
        lever_jobs = [
            {"text": "Accountant", "hostedUrl": "https://jobs.lever.co/example/1",
             "descriptionPlain": irrelevant},
            {"text": "Business Analyst", "hostedUrl": "https://jobs.lever.co/example/2",
             "descriptionPlain": relevant},
        ]
        remoteok_jobs = [
            {"id": "1", "position": "Accountant", "url": "https://remoteok.com/remote-jobs/1",
             "description": irrelevant},
            {"id": "2", "position": "Business Analyst", "url": "https://remoteok.com/remote-jobs/2",
             "description": relevant},
        ]
        remotive_jobs = [
            {"id": 1, "title": "Accountant", "url": "https://remotive.com/remote-jobs/1",
             "description": irrelevant},
            {"id": 2, "title": "Business Analyst", "url": "https://remotive.com/remote-jobs/2",
             "description": relevant},
        ]
        for module in ("greenhouse", "lever", "remoteok", "remotive"):
            with patch(f"job_tools.{module}.filter_unprocessed", side_effect=lambda jobs: jobs):
                if module == "greenhouse":
                    candidates = greenhouse_candidates(greenhouse_jobs, "data analyst")
                elif module == "lever":
                    candidates = lever_candidates(lever_jobs, "data analyst", "Example")
                elif module == "remoteok":
                    candidates = remoteok_candidates(remoteok_jobs, "data analyst")
                else:
                    candidates = remotive_candidates(remotive_jobs, "data analyst")
            self.assertEqual([candidate["job"] for candidate in candidates],
                             [{"greenhouse": greenhouse_jobs, "lever": lever_jobs,
                               "remoteok": remoteok_jobs, "remotive": remotive_jobs}[module][1]])

    def test_related_title_can_pass_without_literal_query_words(self):
        description = "Responsibilities\nWrite code and build applications."
        jobs = {
            "greenhouse": {"title": "Web Developer", "absolute_url": "https://example.com/3",
                           "content": description},
            "lever": {"text": "Web Developer", "hostedUrl": "https://jobs.lever.co/example/3",
                      "descriptionPlain": description},
            "remoteok": {"id": "3", "position": "Web Developer",
                         "url": "https://remoteok.com/remote-jobs/3", "description": description},
            "remotive": {"id": 3, "title": "Web Developer",
                         "url": "https://remotive.com/remote-jobs/3", "description": description},
        }
        for source, job in jobs.items():
            with patch(f"job_tools.{source}.filter_unprocessed", side_effect=lambda results: results):
                if source == "greenhouse":
                    matches = greenhouse_candidates([job], "software engineer")
                elif source == "lever":
                    matches = lever_candidates([job], "software engineer", "Example")
                elif source == "remoteok":
                    matches = remoteok_candidates([job], "software engineer")
                else:
                    matches = remotive_candidates([job], "software engineer")
            self.assertEqual(len(matches), 1, source)


if __name__ == "__main__":
    unittest.main()
