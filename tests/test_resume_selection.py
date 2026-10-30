import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_tools.resume_selection import parse_selection, validate_selection
from job_tools.resume_validation import build_evidence_report, validation_errors
from resume_cli import generate_selection, prepare_run


INVENTORY = {
    "identity": {"name": "Example Person", "contact_line_as_written": "person@example.com"},
    "summary_statements": [{"id": "SUM-001", "original_text": "10+ years across data roles"}],
    "skills": [{"category": "Programming", "original_text": "Python, SQL"}],
    "certifications": [],
    "experience": [{"id": "BAO", "employer": "Example", "location": "Remote",
                    "title": "Engineer", "dates_as_written": "2020-Present",
                    "accomplishments": [{"id": f"BAO-00{i}", "original_text": f"Result {i}"}
                                        for i in range(1, 6)]}],
    "projects": [], "education": [], "publications": [],
}
SELECTION = {
    "summary": {"source_ids": ["SUM-001", "BAO-001"],
                "text": ("Engineer with 10+ years of experience across data roles, building reliable systems "
                         "and delivering useful results for colleagues and partners. The work spans "
                         "technical implementation, careful analysis, and clear communication with "
                         "stakeholders. This background supports practical problem solving, responsible "
                         "delivery, and collaboration on complex data projects while keeping the "
                         "original accomplishments and their documented scope intact.")},
    "skills": [{"category": "Programming", "text": "Python, SQL"}],
    "certifications": [],
    "experience": [{"id": "BAO", "bullets": [f"BAO-00{i}" for i in range(1, 6)]}],
    "projects": [], "education": True, "publications": [],
}


class ResumeSelectionTests(unittest.TestCase):
    def test_accepts_renderer_selection_and_rejects_unknown_bullet(self):
        validate_selection(SELECTION, INVENTORY, rewrite_mode="light")
        bad = json.loads(json.dumps(SELECTION))
        bad["experience"][0]["bullets"][0] = "BAO-999"
        with self.assertRaisesRegex(ValueError, "invalid bullet IDs"):
            validate_selection(bad, INVENTORY, rewrite_mode="light")

    def test_none_mode_rejects_overrides(self):
        bad = json.loads(json.dumps(SELECTION))
        bad["experience"][0]["bullet_overrides"] = {"BAO-001": "Changed"}
        with self.assertRaisesRegex(ValueError, "none mode"):
            validate_selection(bad, INVENTORY, rewrite_mode="none")

    def test_collects_multiple_schema_errors(self):
        bad = json.loads(json.dumps(SELECTION))
        bad["summary"]["text"] = "10+ years of experience"
        bad["summary"]["source_ids"].append("SUM-001")
        bad["certifications"] = ["Invented certification"]
        bad["skills"][0]["category"] = ["Programming"]
        bad["experience"][0]["bullets"][1] = "BAO-001"
        bad["experience"][0]["dates"] = "2020-2025"
        errors = validation_errors(bad, INVENTORY, rewrite_mode="light")
        self.assertGreaterEqual(len(errors), 5)
        self.assertTrue(any("45-70 words" in error for error in errors))
        self.assertTrue(any("duplicate" in error for error in errors))
        self.assertTrue(any("unverified date" in error for error in errors))
        self.assertTrue(any("certifications" in error for error in errors))
        self.assertTrue(any("skills[0]" in error for error in errors))

    def test_requirement_leads_and_unverified_rewrite_flags(self):
        inventory = json.loads(json.dumps(INVENTORY))
        inventory["experience"][0]["accomplishments"][0]["original_text"] = "Build reliable SQL data systems"
        selection = json.loads(json.dumps(SELECTION))
        selection["experience"][0]["bullet_overrides"] = {
            "BAO-001": "Built Kafka systems serving 900 teams"
        }
        selection["skills"][0]["text"] = "Python, Kafka"
        report = build_evidence_report(
            selection, inventory,
            "Responsibilities\nBuild reliable SQL data systems for partners\n"
            "Minimum requirements\nExpertise with Kafka and distributed systems",
        )
        self.assertEqual(report["requirements"][0]["evidence_leads"][0]["source_id"], "BAO-001")
        self.assertEqual(report["requirements"][1]["review_flag"], "no selected evidence lead found")
        flags = report["claim_reviews"][1]["flags"]
        self.assertTrue(any("900" in flag for flag in flags))
        self.assertTrue(any("Kafka" in flag for flag in flags))
        self.assertEqual(report["skill_reviews"][0]["unmatched_items"], ["Kafka"])

    def test_flags_technology_specific_tenure_for_review(self):
        selection = json.loads(json.dumps(SELECTION))
        selection["summary"]["text"] = selection["summary"]["text"].replace(
            "across data roles", "with Python across data roles"
        )
        report = build_evidence_report(selection, INVENTORY, "Requirements\nBuild data systems")
        self.assertTrue(any("10+ years" in flag for flag in report["claim_reviews"][0]["flags"]))

    def test_valid_output_writes_generated_selections_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = root / "master.yaml"
            import yaml
            inventory.write_text(yaml.safe_dump(INVENTORY), encoding="utf-8")
            policy = root / "policy.md"
            policy.write_text("Use source IDs.", encoding="utf-8")
            posting = {"job_id": "local:abc", "url": None, "title": "Engineer", "source": "text",
                       "source_file": str(root / "job.txt"), "source_sha256": "abc",
                       "posting_sha256": "def", "posting_text": "Engineer\nBuild systems."}
            run_dir = prepare_run(posting, model="qwen2.5:7b", rewrite_mode="light",
                                  inventory_path=inventory, prompt_path=policy,
                                  output_dir=root / "runs")
            stages = []
            with patch("resume_cli.run_selection_agent", return_value=json.dumps(SELECTION)) as agent:
                selection_path = generate_selection(
                    run_dir, selection_dir=root / "generated_selections", on_progress=stages.append
                )
            self.assertEqual(agent.call_count, 1)
            self.assertIn("Generating selection — attempt 1 of up to 2", stages)
            self.assertIn("Validating selection — attempt 1", stages)
            self.assertEqual(stages[-1], "Saving validated selection")
            self.assertEqual(agent.call_args.kwargs["model"], "qwen2.5:7b")
            self.assertEqual(selection_path.parent.name, "generated_selections")
            self.assertEqual(json.loads(selection_path.read_text()), SELECTION)
            self.assertEqual(json.loads((run_dir / "manifest.json").read_text())["status"],
                             "selection_generated")
            self.assertTrue((run_dir / "evidence_report.md").is_file())
            self.assertTrue(json.loads((run_dir / "validation_report.json").read_text())["valid"])

    def test_invalid_output_preserves_raw_and_does_not_write_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            import yaml
            (root / "inventory.yaml").write_text(yaml.safe_dump(INVENTORY), encoding="utf-8")
            (root / "policy.md").write_text("Policy", encoding="utf-8")
            posting = {"job_id": "local:abc", "url": None, "title": "Engineer", "source": "text",
                       "source_file": str(root / "job.txt"), "source_sha256": "abc",
                       "posting_sha256": "def", "posting_text": "Engineer\nBuild systems."}
            run_dir = prepare_run(posting, model="qwen2.5:7b", rewrite_mode="light",
                                  inventory_path=root / "inventory.yaml", prompt_path=root / "policy.md",
                                  output_dir=root / "runs")
            with patch("resume_cli.run_selection_agent", return_value="not JSON") as agent:
                with self.assertRaises(json.JSONDecodeError):
                    generate_selection(run_dir, selection_dir=root / "generated_selections")
            self.assertEqual(agent.call_count, 2)
            self.assertEqual((run_dir / "selection_raw.txt").read_text(), "not JSON")
            self.assertEqual(json.loads((run_dir / "manifest.json").read_text())["status"],
                             "selection_failed")
            self.assertFalse((root / "generated_selections").exists())
            self.assertFalse(json.loads((run_dir / "validation_report.json").read_text())["valid"])

    def test_failed_schema_validation_retains_all_errors_and_raw_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            import yaml
            (root / "inventory.yaml").write_text(yaml.safe_dump(INVENTORY), encoding="utf-8")
            (root / "policy.md").write_text("Policy", encoding="utf-8")
            posting = {"job_id": "local:abc", "url": None, "title": "Engineer", "source": "text",
                       "source_file": str(root / "job.txt"), "source_sha256": "abc",
                       "posting_sha256": "def", "posting_text": "Engineer\nBuild systems."}
            run_dir = prepare_run(posting, model="qwen2.5:1.5b", rewrite_mode="light",
                                  inventory_path=root / "inventory.yaml", prompt_path=root / "policy.md",
                                  output_dir=root / "runs")
            bad = json.loads(json.dumps(SELECTION))
            bad["summary"]["text"] = "10+ years of experience"
            bad["experience"][0]["dates"] = "2020-2025"
            raw = json.dumps(bad)
            with patch("resume_cli.run_selection_agent", return_value=raw):
                with self.assertRaises(ValueError):
                    generate_selection(run_dir, selection_dir=root / "generated_selections")
            report = json.loads((run_dir / "validation_report.json").read_text())
            self.assertEqual((run_dir / "selection_raw.txt").read_text(), raw)
            self.assertFalse(report["valid"])
            self.assertGreaterEqual(len(report["errors"]), 2)
            self.assertFalse((root / "generated_selections").exists())

    def test_repairs_parse_and_validation_failures_once(self):
        import yaml
        bad = json.loads(json.dumps(SELECTION))
        bad["summary"]["text"] = "10+ years of experience"
        for rejected in ("not JSON", json.dumps(bad)):
            with self.subTest(rejected=rejected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "inventory.yaml").write_text(yaml.safe_dump(INVENTORY), encoding="utf-8")
                (root / "policy.md").write_text("Use source IDs.", encoding="utf-8")
                posting = {"job_id": "local:abc", "url": None, "title": "Engineer", "source": "text",
                           "source_file": str(root / "job.txt"), "source_sha256": "abc",
                           "posting_sha256": "def", "posting_text": "Engineer\nBuild systems."}
                run_dir = prepare_run(posting, model="qwen3:14b", rewrite_mode="none",
                                      inventory_path=root / "inventory.yaml", prompt_path=root / "policy.md",
                                      output_dir=root / "runs")
                with patch("resume_cli.run_selection_agent",
                           side_effect=[rejected, json.dumps(SELECTION)]) as agent:
                    stages = []
                    result = generate_selection(
                        run_dir, selection_dir=root / "selections", on_progress=stages.append
                    )
                self.assertEqual(agent.call_count, 2)
                self.assertIn("Generating selection — attempt 2 of up to 2", stages)
                feedback = agent.call_args.args[2]
                first_report = json.loads((run_dir / "validation_report_attempt_1.json").read_text())
                self.assertFalse(first_report["valid"])
                self.assertIn(rejected, feedback)
                for error in first_report["errors"]:
                    self.assertIn(error, feedback)
                self.assertEqual((run_dir / "selection_raw_attempt_1.txt").read_text(), rejected)
                self.assertTrue(json.loads((run_dir / "validation_report_attempt_2.json").read_text())["valid"])
                self.assertEqual(json.loads(result.read_text()), SELECTION)
                self.assertEqual(json.loads((run_dir / "manifest.json").read_text())["attempts"], 2)

    def test_renderer_rejects_invalid_selection_before_opening_template(self):
        from render_resume import produce
        bad = json.loads(json.dumps(SELECTION))
        bad["experience"][0]["bullets"][0] = "BAO-999"
        with patch("render_resume.Document") as document:
            with self.assertRaises(ValueError):
                produce(INVENTORY, bad, "unused.docx", "unused.docx")
        document.assert_not_called()

    def test_parse_fenced_json(self):
        self.assertEqual(parse_selection('```json\n{"education": true}\n```'), {"education": True})
        with self.assertRaisesRegex(ValueError, "incomplete fenced JSON"):
            parse_selection('```json\n{"education": true')


if __name__ == "__main__":
    unittest.main()
