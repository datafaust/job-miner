"""Regression checks for module entry points and repository asset paths."""
import os
import subprocess
import sys
import tempfile
import unittest

from job_miner.paths import PROJECT_DIR


class PackageLayoutTests(unittest.TestCase):
    def test_command_modules_offer_help(self):
        for module in ('job_miner.cli.search', 'job_miner.cli.resume',
                       'job_miner.cli.grade', 'job_miner.cli.render', 'job_miner.web.app'):
            with self.subTest(module=module):
                result = subprocess.run(
                    [sys.executable, '-m', module, '--help'], cwd=PROJECT_DIR,
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('usage:', result.stdout)
                self.assertNotIn('RuntimeWarning', result.stderr)

    def test_assets_and_defaults_resolve_outside_repository_cwd(self):
        # Import inside a different cwd so this also catches cwd-based defaults.
        script = '''
import sys
from pathlib import Path
from job_miner.paths import PROJECT_DIR
from job_miner.resumes.workflow import INVENTORY_PATH, PROMPT_PATH
from job_miner.web.app import app
from job_tools.job_history import HISTORY_DB_PATH
from job_tools.search_web_tasks import TASK_ROOT as SEARCH_ROOT
from job_tools.resume_web_tasks import TASK_ROOT as RESUME_ROOT
from job_tools.workflow_config import CONFIG_PATH

assert PROJECT_DIR == Path(sys.argv[1])
assert INVENTORY_PATH == PROJECT_DIR / 'master_accomplishments.yaml'
assert PROMPT_PATH == PROJECT_DIR / 'RESUME_SELECTION_PROMPT.md'
assert INVENTORY_PATH.is_file() and PROMPT_PATH.is_file()
assert HISTORY_DB_PATH == PROJECT_DIR / 'job_history.sqlite3'
assert SEARCH_ROOT == PROJECT_DIR / 'generated_search_requests'
assert RESUME_ROOT == PROJECT_DIR / 'generated_resume_requests'
assert CONFIG_PATH == PROJECT_DIR / 'config' / 'workflow_limits.json'
assert CONFIG_PATH.is_file()
assert Path(app.template_folder) == PROJECT_DIR / 'templates'
assert Path(app.static_folder) == PROJECT_DIR / 'static'
assert app.test_client().get('/search/new').status_code == 200
static_file = next((PROJECT_DIR / 'static').glob('*.css'))
assert app.test_client().get('/static/' + static_file.name).status_code == 200
'''
        env = os.environ.copy()
        env['PYTHONPATH'] = str(PROJECT_DIR)
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, '-c', script, str(PROJECT_DIR)], cwd=directory,
                env=env, capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
