import json
import tempfile
import unittest
from pathlib import Path

from job_tools.workflow_config import CONFIG_PATH, load_workflow_limits


class WorkflowConfigTests(unittest.TestCase):
    def test_loads_configured_limits(self):
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        data["idealist_candidates_per_run"] = 6
        data["idealist_jobs_per_run"] = 4
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "limits.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            limits = load_workflow_limits(path)
        self.assertEqual(limits.idealist_candidates_per_run, 6)
        self.assertEqual(limits.idealist_jobs_per_run, 4)

    def test_rejects_invalid_and_conflicting_limits(self):
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "limits.json"
            data["idealist_jobs_per_run"] = 0
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "positive integer"):
                load_workflow_limits(path)
            data["idealist_candidates_per_run"] = 3
            data["idealist_jobs_per_run"] = 4
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cannot exceed"):
                load_workflow_limits(path)


if __name__ == "__main__":
    unittest.main()
