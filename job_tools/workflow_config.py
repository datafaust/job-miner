"""Validated, versioned limits for each job source."""

import json
from dataclasses import dataclass
from pathlib import Path


CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "workflow_limits.json"


@dataclass(frozen=True)
class WorkflowLimits:
    greenhouse_jobs_per_run: int
    lever_jobs_per_run: int
    ashby_jobs_per_run: int
    remoteok_jobs_per_run: int
    remotive_jobs_per_run: int
    idealist_candidates_per_run: int
    idealist_jobs_per_run: int


def load_workflow_limits(path=CONFIG_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    required = set(WorkflowLimits.__dataclass_fields__)
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError(f"Workflow limits must contain exactly: {', '.join(sorted(required))}")
    for key, value in data.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{key} must be a positive integer")
    if data["idealist_jobs_per_run"] > data["idealist_candidates_per_run"]:
        raise ValueError("idealist_jobs_per_run cannot exceed idealist_candidates_per_run")
    return WorkflowLimits(**data)


LIMITS = load_workflow_limits()
