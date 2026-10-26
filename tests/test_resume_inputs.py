import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from job_tools import job_history
from job_tools.resume_inputs import load_posting, load_saved_posting
from resume_cli import main, prepare_run


class ResumeInputTests(unittest.TestCase):
    def test_saved_json_sources_keep_full_descriptions(self):
        cases = [
            ({"title": "Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/12",
              "location": {"name": "Remote"}, "content": "<p>Build APIs.</p><p>Test services.</p>"},
             "Build APIs.", "Test services."),
            ({"text": "Engineer", "hostedUrl": "https://jobs.lever.co/acme/abc",
              "descriptionPlain": "Build APIs.", "lists": [{"text": "Requirements", "content": "<p>Test services.</p>"}],
              "additionalPlain": "Work with data."}, "Requirements", "Work with data."),
            ({"position": "Engineer", "url": "https://remoteok.com/remote-jobs/12-engineer",
              "company": "Acme", "description": "<p>Build APIs.</p><p>Test services.</p>"},
             "Build APIs.", "Test services."),
            ({"title": "Engineer", "company_name": "Acme",
              "url": "https://remotive.com/remote-jobs/software-dev/engineer-12",
              "description": "<p>Build APIs.</p><p>Test services.</p>"},
             "Build APIs.", "Test services."),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "job.json"
            for job, first, second in cases:
                with self.subTest(job=job):
                    path.write_text(json.dumps(job), encoding="utf-8")
                    posting = load_posting(path)
                    self.assertIn(first, posting["posting_text"])
                    self.assertIn(second, posting["posting_text"])
                    self.assertEqual(posting["title"], "Engineer")
                    self.assertEqual(posting["posting_sha256"], hashlib.sha256(
                        posting["posting_text"].encode()).hexdigest())

    def test_saved_job_id_resolves_original_idealist_text(self):
        url = "https://www.idealist.org/en/nonprofit-job/6965cacf0cf845ffaaae044a336111ec-engineer"
        text = "NONPROFIT\nPublished 2 days ago\nEngineer\nAcme\nRemote\nFull posting body."
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "posting.txt"
            path.write_text(text, encoding="utf-8")
            with patch.object(job_history, "HISTORY_DB_PATH", root / "history.sqlite3"):
                job_history.record_processed(url, str(path))
                posting = load_saved_posting(job_history.job_key(url))
        self.assertEqual(posting["title"], "Engineer")
        self.assertEqual(posting["posting_text"], text)
        self.assertEqual(posting["url"], url)

    def test_cli_snapshots_sources_and_passes_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            posting_file = root / "job.txt"
            posting_file.write_text("Engineer\nBuild data systems.", encoding="utf-8")
            inventory = root / "inventory.yaml"
            inventory.write_text("experience: []\n", encoding="utf-8")
            prompt = root / "prompt.md"
            prompt.write_text("Prompt version 1", encoding="utf-8")
            posting = load_posting(posting_file)
            run_dir = prepare_run(posting, model="qwen2.5:7b", rewrite_mode="none",
                                  inventory_path=inventory, prompt_path=prompt,
                                  output_dir=root / "runs")
            manifest = json.loads((run_dir / "manifest.json").read_text())
            self.assertEqual(manifest["model"], "qwen2.5:7b")
            self.assertEqual(manifest["generation_config"]["num_predict"], -1)
            self.assertEqual(manifest["rewrite_mode"], "none")
            self.assertEqual(manifest["job_id"], posting["job_id"])
            self.assertEqual(manifest["inventory_sha256"], hashlib.sha256(inventory.read_bytes()).hexdigest())
            self.assertEqual((run_dir / "posting.txt").read_text(), posting["posting_text"])
            self.assertEqual((run_dir / "inventory.yaml").read_bytes(), inventory.read_bytes())
            self.assertEqual((run_dir / "prompt.md").read_bytes(), prompt.read_bytes())
            self.assertEqual((run_dir / "manifest.json").is_file(), True)

    def test_cli_rejects_unknown_job_id(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(job_history, "HISTORY_DB_PATH", Path(directory) / "history.sqlite3"):
                with self.assertRaises(SystemExit) as caught:
                    main(["--job-id", "greenhouse:missing", "--output-dir", directory])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
