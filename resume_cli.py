#!/usr/bin/env python3
"""Generate a job-specific selection JSON with a local CrewAI/Ollama agent."""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from job_tools.resume_inputs import load_posting, load_saved_posting
from job_tools.resume_selection import (
    OLLAMA_CONTEXT_TOKENS, OLLAMA_NUM_PREDICT, OLLAMA_TIMEOUT_SECONDS,
    parse_selection, run_selection_agent, validate_selection,
)
from job_tools.resume_validation import SelectionValidationError, build_evidence_report, evidence_markdown


PROJECT_DIR = Path(__file__).resolve().parent
PROMPT_PATH = PROJECT_DIR / "RESUME_SELECTION_PROMPT.md"
INVENTORY_PATH = PROJECT_DIR / "master_accomplishments.yaml"
PROMPT_VERSION = "resume-selection-v1"


def prepare_run(posting, *, model, rewrite_mode, inventory_path=INVENTORY_PATH,
                prompt_path=PROMPT_PATH, output_dir=PROJECT_DIR / "generated_resume_runs"):
    """Write the exact posting and metadata that a later agent run will consume."""
    if not model.strip():
        raise ValueError("Model name cannot be blank")
    inventory_path = Path(inventory_path).resolve()
    prompt_path = Path(prompt_path).resolve()
    inventory_bytes = inventory_path.read_bytes()
    prompt_bytes = prompt_path.read_bytes()
    inventory_hash = hashlib.sha256(inventory_bytes).hexdigest()
    prompt_hash = hashlib.sha256(prompt_bytes).hexdigest()
    created_at = datetime.now(timezone.utc).isoformat()
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", posting["job_id"]).strip("_")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_dir = Path(output_dir).resolve() / slug / timestamp
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "posting.txt").write_text(posting["posting_text"], encoding="utf-8")
    (run_dir / "inventory.yaml").write_bytes(inventory_bytes)
    (run_dir / "prompt.md").write_bytes(prompt_bytes)
    manifest = {
        "contract_version": 1,
        "created_at": created_at,
        "job_id": posting["job_id"],
        "posting_url": posting["url"],
        "title": posting["title"],
        "source": posting["source"],
        "source_file": posting["source_file"],
        "source_sha256": posting["source_sha256"],
        "posting_sha256": posting["posting_sha256"],
        "inventory_file": str(inventory_path),
        "inventory_sha256": inventory_hash,
        "inventory_snapshot": "inventory.yaml",
        "model": model.strip(),
        "generation_config": {
            "num_ctx": OLLAMA_CONTEXT_TOKENS,
            "num_predict": OLLAMA_NUM_PREDICT,
            "timeout_seconds": OLLAMA_TIMEOUT_SECONDS,
            "temperature": 0,
        },
        "rewrite_mode": rewrite_mode,
        "prompt_version": PROMPT_VERSION,
        "prompt_file": str(prompt_path),
        "prompt_sha256": prompt_hash,
        "prompt_snapshot": "prompt.md",
        "status": "input_prepared",
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return run_dir


def generate_selection(run_dir, *, selection_dir=PROJECT_DIR / "generated_selections"):
    """Run the selector and save only parseable, source-linked selections."""
    run_dir = Path(run_dir)
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["validation_report"] = str(run_dir / "validation_report.json")
    validation = {"valid": False, "errors": [], "human_review_required": True}
    try:
        inventory = yaml.safe_load((run_dir / "inventory.yaml").read_text(encoding="utf-8"))
        if not isinstance(inventory, dict):
            raise ValueError("Inventory must be a YAML object")
        raw = run_selection_agent(
            (run_dir / "posting.txt").read_text(encoding="utf-8"),
            inventory,
            (run_dir / "prompt.md").read_text(encoding="utf-8"),
            model=manifest["model"],
            rewrite_mode=manifest["rewrite_mode"],
        )
        (run_dir / "selection_raw.txt").write_text(raw, encoding="utf-8")
        selection = parse_selection(raw)
        validate_selection(selection, inventory, rewrite_mode=manifest["rewrite_mode"])
        evidence = build_evidence_report(
            selection, inventory, (run_dir / "posting.txt").read_text(encoding="utf-8")
        )
        (run_dir / "evidence_report.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (run_dir / "evidence_report.md").write_text(evidence_markdown(evidence), encoding="utf-8")
        validation["valid"] = True
        validation["summary_word_count"] = len(selection["summary"]["text"].split())
        validation["claim_flags"] = sum(len(item["flags"]) for item in evidence["claim_reviews"])
        validation["skill_items_to_review"] = sum(
            len(item["unmatched_items"]) for item in evidence["skill_reviews"]
        )
        validation["requirements_without_leads"] = sum(
            not item["evidence_leads"] for item in evidence["requirements"]
        )
        selection_dir = Path(selection_dir).resolve()
        selection_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{run_dir.parent.name}_{run_dir.name}_selection.json"
        selection_path = selection_dir / filename
        selection_path.write_text(json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest["selection_file"] = str(selection_path)
        manifest["evidence_report"] = str(run_dir / "evidence_report.md")
        manifest["status"] = "selection_generated"
        return selection_path
    except Exception as error:
        manifest["status"] = "selection_failed"
        manifest["error"] = f"{type(error).__name__}: {error}"
        validation["valid"] = False
        validation["errors"] = error.errors if isinstance(error, SelectionValidationError) else [str(error)]
        raise
    finally:
        (run_dir / "validation_report.json").write_text(
            json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


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
