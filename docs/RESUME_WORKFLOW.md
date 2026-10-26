# Resume workflow: implementation and test record

Last reviewed: **2026-10-25**. This document records the resume work discussed and tested in this repository so future agents can distinguish implemented behavior from proposed work. The saved job used for live tests was Stripe's **Strategy & Analytics Business Partner Analyst**, job ID `greenhouse:8079783`.

## What was brought into the repository

The earlier resume builder used ChatGPT to choose accomplishments and optionally rewrite bullets, then Python to render a Word document. The local workflow keeps that division of labor: a CrewAI agent using a local Ollama model produces a **selection JSON**; `render_resume.py` fills `templates/resume-template.docx` from that selection and `master_accomplishments.yaml`. The agent does not generate the DOCX. This is a separate workflow that starts with a saved job or local posting, rather than an automatic continuation of the job search in `main.py`.

Source and policy material: `resume-master-accomplishments.docx`, `master_accomplishments.yaml`, `README_port.md`, `RESUME_TAILORING.md`, `GENERATE_YAML.md`, `resume-prompt`, `example_selection.json`, and `RESUME_SELECTION_PROMPT.md`. The YAML was supplied for this work; no YAML extraction was needed. Its `source.filename` now reads `resume-master-accomplishments.docx`. Treat `master_accomplishments.yaml` as the candidate fact inventory and `example_selection.json` as a schema example, not a selection to copy for every job.

The resume dependencies added to `requirements.txt` are `PyYAML>=6,<7` and `python-docx>=1.1,<2`; CrewAI with LiteLLM was already used by the job workflow.

## Current path through the code

1. `resume_cli.py` accepts `--job-id` **or** `--posting-file`, `--model`, and `--rewrite-mode {none,light,targeted}`. Saved IDs resolve through the job history database. The posting loader normalizes saved Greenhouse, Lever, Remote OK, Remotive, and Idealist data or a local JSON/text posting into full posting text. It does not intentionally shorten the job description for the model.
2. Each attempt gets a timestamped `generated_resume_runs/<job-id>/<timestamp>/` directory. `posting.txt`, `inventory.yaml`, and `prompt.md` are copied input snapshots for that attempt. `manifest.json` records the job ID, URL, title, source and posting hashes, inventory and prompt hashes, model, rewrite mode, prompt version, generation settings, and result paths. The full inventory is saved; the agent receives a compact view that drops extraction metadata while retaining source wording and IDs.
3. `job_tools/resume_selection.py` asks one CrewAI agent to return a renderer-compatible JSON object. The local Ollama model is passed with `--model`, as in `main.py`. Current settings are `num_ctx=8192`, `num_predict=-1` (generate until the model stops), temperature `0`, and a 1,200-second timeout. `selection_raw.txt` retains the reply when one is returned.
4. `job_tools/resume_selection.py` parses the model reply as JSON, then `job_tools/resume_validation.py` checks the selection contract: allowed fields, role order, ID ownership, duplicate IDs, bullet minimums, skill categories, exact certification wording, a 45–70-word summary containing `10+ years of experience` and citing `SUM-001`, and prohibited unverified date overrides. `none` mode prohibits bullet overrides. Failed checks save errors in `validation_report.json` and produce no final selection or DOCX.
5. A valid selection is written to `generated_selections/<job-id>_<timestamp>_selection.json`. The same attempt also writes `evidence_report.json` and `.md`. These list labelled posting requirements, possible selected accomplishment leads based on shared words, and heuristic flags for AI-authored summary/rewrite claims and selected skills. **A lead is not proof of support.** `human_review_required` remains true even when structural validation passes.
6. After review, `render_resume.py` can turn the selection into a DOCX. It repeats structural validation before opening the template. It does not judge job fit or factual meaning. `generated_resume_runs/`, `generated_selections/`, and `generated_resumes/` are ignored by Git because they may contain personal information and application materials.

Example generation command:

```bash
.venv/bin/python resume_cli.py \
  --job-id greenhouse:8079783 \
  --model qwen2.5:14b \
  --rewrite-mode none
```

## Tests and observed results

The focused automated suite was run on **2026-10-25** with `.venv/bin/python -m unittest tests.test_resume_inputs tests.test_resume_selection`: **14 tests passed**. The suite uses mocked model replies; it checks input normalization and snapshots, model parameter forwarding, validation errors, evidence heuristics, failed-run retention, selection output location, and the renderer's structural gate. It does not establish semantic job fit or live model reliability. Its expected unknown-job-ID case prints an argparse error during the passing run.

Live attempts for `greenhouse:8079783` show why parse/schema success and tailoring quality should be assessed separately:

| Run ID (UTC) | Model / mode | Observed result |
| --- | --- | --- |
| `20261025T172021008520Z` | `qwen2.5:1.5b` / `none` | Failed to parse: incomplete fenced JSON response. This run predates removal of the reply cap; it does not isolate model capability as the cause. |
| `20261025T173027524256Z` | `qwen2.5:1.5b` / `none` | With `num_predict=-1`, failed structural validation, including invalid bullet IDs and too few bullets. Removing the cap alone did not make its selection valid. |
| `20261025T173454793790Z` | `qwen2.5:7b` / `none` | Returned parseable JSON but failed the summary rule: 34 words instead of 45–70. |
| `20261025T234517215721Z` | `qwen2.5:14b` / `none` | Passed structural validation with zero errors. Saved a 58-word summary, selection JSON, and evidence reports. No rewrite overrides were used. |

The 14b run's `validation_report.json` says `valid: true`, `claim_flags: 0`, `skill_items_to_review: 0`, `requirements_without_leads: 8`, and `human_review_required: true`. The eight count includes a generic introductory requirement sentence, so it is not a count of eight confirmed missing qualifications. The model selected all eight BAO Systems bullets and five each from the two NYC Taxi & Limousine Commission roles. It omitted Urban Upbound entirely, although that role contains the clearest banking and financial-outcomes work for this posting. Its summary emphasizes software engineering and cloud platforms more than strategy and operations. Some evidence leads are semantically weak: a driver income calculator is not proof of Financial Crimes forecasting. The output is structurally usable but was **not approved as a well-tailored final resume**, and this review did not render a DOCX.

For reproduction, inspect the ignored local artifacts under `generated_resume_runs/greenhouse_8079783/20261025T234517215721Z/` and `generated_selections/greenhouse_8079783_20261025T234517215721Z_selection.json`. The run manifest records prompt version `resume-selection-v1`, the precise hashes, and the model settings. Generated artifacts may be absent from another checkout because they are ignored by Git.

## Conclusions and next work

- Keep deterministic schema/source checks as the hard validity gate. They answer whether a selection can safely be rendered, not whether it is the best selection for a posting.
- Add a **separate substantive validation step** before rendering. It should assess requirement coverage and evidence strength against the full posting and both selected and unselected inventory items, check that rewritten claims stay within source facts, and flag weak or omitted evidence. Report findings and source IDs for human review; do not silently invent or insert experience. In particular, review whether Urban Upbound should be represented for this Stripe job.
- Make the reviewer model independently configurable. `qwen2.5:14b` is a reasonable local baseline to test against this known run; a different or more capable reviewer could catch mistakes the selector repeats. No model-based reviewer or comparative reviewer test exists yet.
- Improve the evidence extractor so introductory text is not counted as a requirement and distinguish lexical matches from semantic support. Consider explicit outcomes for missing, weak, and strong evidence, with citations checked against the original inventory wording.
- Review a selection manually before invoking `render_resume.py`; then inspect the rendered DOCX's content and layout. There has been no documented end-to-end render or scored resume-quality test for the 14b run.

The legacy `README_port.md` describes a ChatGPT validation step and mentions `RESUME_VALIDATION.md`; that file is not present in this repository. It is background for a future validation design, not an implemented local agent.
