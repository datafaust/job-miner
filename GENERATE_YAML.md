# Master Accomplishments YAML Generation

Using `resume-master-accomplishments.docx` as the authoritative source, generate or update `master_accomplishments.yaml` for the automated resume-tailoring pipeline.

### Requirements

1. **Preserve original wording** of all accomplishments, skills, summaries, certifications, education, and projects. Do not rewrite, embellish, or invent information.
2. **Maintain the existing YAML schema** so the file remains compatible with `render_resume.py` and `RESUME_TAILORING.md`.
3. **Preserve existing IDs** (e.g., `BAO-001`, `TLC-MGR-009`, `SUM-001`). Assign new, unique IDs only to newly added accomplishments.
4. **Synchronize changes** from the Word document, including additions, modifications, and deletions. Do not silently discard existing information.
5. **Preserve metadata** such as technology tags, competencies, and target roles when applicable. Update suggested metadata for new accomplishments.
6. **Validate the output** for YAML syntax, unique IDs, required fields, and compatibility with the Python renderer.
7. **Report changes** made since the previous version, including any ambiguities requiring manual review.

### Deliverable

Produce a downloadable `master_accomplishments.yaml` ready to replace the existing file in the GitHub repository.

Treat the Word document as the factual source of truth and the existing YAML as the structural reference. Do not alter other project files unless explicitly requested.