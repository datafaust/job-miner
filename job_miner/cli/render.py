"""Render a reviewed resume selection from the terminal."""
import argparse
import json
from pathlib import Path

import yaml

from job_miner.resumes.render import produce
from job_miner.paths import PROJECT_DIR


def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('--inventory',default=str(PROJECT_DIR / 'master_accomplishments.yaml'));ap.add_argument('--selection',default='selection.json');ap.add_argument('--template',default='resume-template.docx');ap.add_argument('--output',default='generated-resume.docx')
    x=ap.parse_args(argv)
    selection_path = Path(x.selection)
    if selection_path.parent == Path('.'):
        selection_path = PROJECT_DIR / 'generated_selections' / selection_path
    with open(x.inventory,encoding='utf-8') as f: inventory=yaml.safe_load(f)
    with selection_path.open(encoding='utf-8') as f: selection=json.load(f)
    output_path = produce(inventory,selection,x.template,x.output)
    print('Wrote', output_path)


if __name__ == "__main__":
    main()
