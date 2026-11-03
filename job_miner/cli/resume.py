"""Generate a resume selection from the terminal."""
import argparse
import json
from pathlib import Path

from job_miner.resumes.workflow import INVENTORY_PATH, generate_selection, prepare_run
from job_tools.resume_inputs import load_posting, load_saved_posting
from job_miner.paths import PROJECT_DIR


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate a resume selection JSON for one job posting.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--job-id", help="Stable ID from job history, e.g. greenhouse:8172487")
    source.add_argument("--posting-file", type=Path, help="Local .json or .txt job posting")
    parser.add_argument("--job-url", help="Source URL for a local posting without one")
    parser.add_argument("--job-title", help="Title override for a local posting")
    parser.add_argument("--model", default="openhermes", help="Ollama model for selection (default: openhermes)")
    parser.add_argument("--rewrite-mode", choices=("none", "light", "targeted"), default="light")
    parser.add_argument("--inventory", type=Path, default=INVENTORY_PATH)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_DIR / "generated_resume_runs")
    parser.add_argument("--selection-dir", type=Path, default=PROJECT_DIR / "generated_selections")
    args = parser.parse_args(argv)
    if args.job_id and (args.job_url or args.job_title):
        parser.error("--job-url and --job-title apply only to --posting-file")
    try:
        posting = (load_saved_posting(args.job_id) if args.job_id else
                   load_posting(args.posting_file, source_url=args.job_url, source_title=args.job_title))
        run_dir = prepare_run(posting, model=args.model, rewrite_mode=args.rewrite_mode,
                              inventory_path=args.inventory, output_dir=args.output_dir)
    except (OSError, ValueError, json.JSONDecodeError, UnicodeError) as error:
        parser.error(str(error))
    print(f"Prepared resume input: {run_dir}", flush=True)
    try:
        selection_path = generate_selection(run_dir, selection_dir=args.selection_dir)
    except Exception as error:
        parser.exit(1, f"Selection generation failed; see {run_dir}: {type(error).__name__}: {error}\n")
    print(f"Wrote selection: {selection_path}")
    print(f"Evidence review: {run_dir / 'evidence_report.md'}")
    print("Review the selection and evidence report before rendering a resume.")
    return selection_path


if __name__ == "__main__":
    main()
