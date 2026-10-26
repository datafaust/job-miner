# Resume tailoring instructions (v1.2)

## Purpose and inputs
Generate a job-specific **selection JSON** for `render_resume.py` using:
1. The complete job description supplied by the user.
2. `master_accomplishments.yaml` as the only source for the candidate's employment history, skills, credentials, projects, and accomplishments.
3. `example_selection.json` as a **schema reference**, not as a fixed content selection.

Deliver a downloadable `<company>_<role>_selection.json` file, plus a short human-readable rationale and any important evidence gaps. Do not generate a DOCX unless explicitly requested.

## Content and integrity rules
- Do not invent experience, results, metrics, technologies, education, certifications, or clearances.
- Only select accomplishment IDs that exist under the corresponding role or project in the YAML. The renderer uses the original YAML wording unless a job-specific `bullet_overrides` entry is present. Keep `experience[].bullets` and `projects[].bullets` as lists of source IDs, never prose.
- Preserve the existing role IDs and their order, normally newest first; do not change job titles, employers, or location.
- The professional summary and permitted `bullet_overrides` are the only AI-authored resume prose. Write a factual single paragraph of approximately 45–70 words, oriented toward the posting. Supply IDs of summary statements and/or experience/project accomplishments supporting the paragraph in `summary.source_ids`. These IDs are a traceability aid, not proof by themselves. Review factual support explicitly.
- **Mandatory professional-summary positioning:** Include the exact phrase **`10+ years of experience`** in `summary.text` for every application. Place it in the opening sentence whenever possible. This refers to the candidate's **overall professional experience across data, analytics, and software-related roles**, not to tenure in any single programming language, framework, platform, industry specialty, or responsibility. `SUM-001` and the chronological employment record support the broad claim. Always include `SUM-001` among `summary.source_ids` when using this phrase.
- **Safe wording:** "Senior Data & Software Engineer with 10+ years of experience across data engineering, analytics, and software development, specializing in Python, SQL, and cloud-based data platforms." Tailor the specializations according to the posting and the YAML; this example is not mandatory prose.
- **Avoid false specificity:** Do not write "10+ years of Flask experience," "10+ years building AWS systems," "10+ years in EHR integration," or "10+ years as a software engineer" unless that exact duration and scope are independently supported. Do not conflate years of overall experience with years of experience in one technology. This policy authorizes emphasis on the documented broad tenure, **not fabricated tenure or qualifications**.
- Source summary statements `SUM-001` through `SUM-007` remain as-is in YAML; do not render them as bullets for the default output.
- For skill entries, use the exact category labels found in YAML. In `text`, choose truthful, relevant items from that category. Preserve the source terminology rather than inventing tool proficiency. No requirement to retain all skill groups.
- Use only certifications/approvals supported by YAML. Do not represent Public Trust as a security clearance or claim an approval is active; include only where genuinely relevant and accurately worded.
- Omit optional projects, publications, or sections if irrelevant.
- Use relevant keywords naturally, but do not insert missing requirements as if the candidate has them. Report those as gaps separately.
- Do not infer precise employment end dates: BAO's source date says 'Present' and should be manually updated/verified when appropriate. Use `experience[].dates` only if the user has provided verified dates.
- Do not add explanation, confidence scores, comments, trailing commas, or markdown code fences inside the JSON artifact.

## Priorities
The primary audience is senior/lead data engineering, analytics engineering, and data-platform software engineering roles; selectively, engineering management and applied-AI application development. Prioritize concrete hands-on engineering, technical scope, quantifiable outcomes, and impact over keyword saturation.

- Senior Data Engineer: Python, SQL, ETL, data quality, schema/database design, scalable data platforms, AWS.
- Analytics Engineer: SQL/data modeling, KPIs, analytics products, automated reporting, data validation, stakeholders.
- Data Platform / Backend Engineer: Python, Flask, APIs, microservices, cloud services, testing, Docker, CI/CD.
- Applied AI Engineer: demonstrated AI chatbot/RAG integration, LLM-enabled applications, the Cosmo project when relevant; no unsupported model-training claims.
- Engineering manager: credible historical team leadership combined with recent hands-on engineering; do not overstate current people management.

## Resume balance, minimum bullets, and page length
**Human readability and a convincing representation of career history matter as much as keyword targeting.** Do not over-prune experience merely to maximize match keywords or force a two-page document.

### Required minimums
- **Every experience role included in `experience` must have at least 3 meaningful, nonredundant accomplishment bullets.** This includes older positions such as Urban Upbound. Never output a role with only 1–2 bullets.
- BAO: aim for **5–7** bullets (minimum 4 only if explicitly overridden by the user; default minimum is 5).
- TLC Director: aim for **4–5** bullets (minimum 3).
- TLC Manager: aim for **4–5** bullets (minimum 3).
- Urban Upbound: **3** bullets if included; either include the role with 3 relevant bullets or omit it if the target resume intentionally excludes that older experience. Do not omit earlier employment merely because it is less relevant without considering continuity of work history.
- Independent projects are optional and **not subject to the 3-bullet rule**: use 1–3 strong bullets for a clearly relevant project, or omit it. A one-bullet project is acceptable because it is not an employment role.
- No filler, invented facts, duplicate accomplishments, or near-identical bullets to satisfy a minimum; if a minimum cannot be met honestly, explicitly flag the conflict for review rather than breaking it silently.

### Length and ordering
- Start with one 45–70-word professional summary and about 4–6 relevant skills categories.
- **Two pages is a preferred target, not a hard constraint.** A balanced, readable three-page resume is better than a two-page resume that removes important evidence, leaves a position visually underdeveloped, or uses tiny fonts/tight spacing.
- Optimize space in this order: remove redundant skills and irrelevant optional sections; tighten verbose bullets with factual light rewrites; reduce excess bullets from roles **only while respecting minimums**; then accept a third page or flag the tradeoff for user review.
- Prefer a coherent chronological progression: recent platform engineering first, earlier database/ETL and leadership work next, less recent experience with a reasonable but shorter treatment.
- Education: include by default. Publications: include when relevant.
- The renderer does not automatically enforce PDF page count. When possible, inspect the LibreOffice-exported PDF for page count and stranded headings/one-bullet positions.

## Output schema: match `render_resume.py` exactly
```json
{
  "name": "Fausto Lopez",
  "contact_line": "(646) 639-3360 | FaustoLopez110@gmail.com",
  "summary": {
    "source_ids": ["SUM-001", "BAO-001"],
    "text": "One factual, tailored summary paragraph."
  },
  "skills": [
    {"category": "Programming & Scripting", "text": "Python, SQL, R"}
  ],
  "certifications": ["AWS Certified Developer – Associate (Earned: 03/2025)"],
  "experience": [
    {"id": "BAO", "bullets": ["BAO-001", "BAO-002", "BAO-003", "BAO-007", "BAO-008"], "bullet_overrides": {}},
    {"id": "TLC-DIR", "bullets": ["TLC-DIR-001", "TLC-DIR-002", "TLC-DIR-003", "TLC-DIR-006"]},
    {"id": "TLC-MGR", "bullets": ["TLC-MGR-001", "TLC-MGR-002", "TLC-MGR-003", "TLC-MGR-005"]}
  ],
  "projects": [],
  "education": true,
  "publications": []
}
```
All displayed IDs above are *examples only*; select based on the actual job description. The `bullets` lists contain source IDs, not rewritten prose. An optional `bullet_overrides` object maps selected source IDs to approved tailored wording when the local renderer supports this extension. Keep `bullet_rewrite_mode` as an AI instruction, not a setting that makes Python rewrite text automatically. If a role is omitted, it will be omitted from the document.

## Validation checklist before delivering JSON
1. JSON parses successfully; all required arrays/objects have the expected shape.
2. Every summary `source_id` exists in YAML.
3. Every experience and project accomplishment ID belongs to its selected role/project.
4. Every publication ID exists.
5. Every selected skill/certification is supported by YAML and worded accurately.
6. Summary claims can be substantiated from referenced source text or other relevant YAML entries; unsupported claims are removed.
6a. `summary.text` contains the literal phrase `10+ years of experience` (case-insensitive); `SUM-001` appears in `summary.source_ids`; the phrase clearly refers to broad professional experience, **not** 10+ years in a specific framework, technology, or specialty.
7. Confirm every included employment role has at least 3 substantive bullets, and BAO has at least 5 by default. Flag any exception explicitly.
8. Summarize 3–5 particularly relevant job requirements and the chosen corresponding evidence in the *chat response*, not the JSON.
9. Call out important gaps separately; do not hide them by inventing bullet points.
10. If tools can run the renderer, generate a test DOCX and inspect exported PDF page count; if not, clearly say layout hasn't been checked.

## Example user request
"Use RESUME_TAILORING.md and master_accomplishments.yaml to tailor my resume to the job description below. Generate a downloadable `<company>_<role>_selection.json` compatible with render_resume.py. Keep factual claims traceable to the YAML. Give a short match rationale and list any notable gaps. Job description: [PASTE FULL POSTING]"

## Render command
```bash
python render_resume.py \
  --inventory master_accomplishments.yaml \
  --selection generated_selections/company_role_selection.json \
  --template templates/resume-template.docx \
  --output company_role_resume.docx
```

## Known limitations
- The renderer does not itself compose the summary; the AI supplies `summary.text`.
- The renderer does not fact-check freeform text or detect unsupported keywords in skill and certification strings.
- The renderer does not auto-fit to two pages or auto-export PDF.
- Name in the JSON overrides name in YAML; keep it in desired title case.
- Revisit source employment dates before final submission.

## Bullet rewriting policy
- **none:** use original YAML bullets unchanged.
- **light (default):** reorder phrasing, improve clarity, and use technically accurate terms appearing in the posting without adding facts.
- **targeted:** more extensive restructuring for role relevance, but every underlying claim must remain supported.
- Keep original bullet IDs in `bullets`; write any changed prose in `bullet_overrides` keyed by those IDs. Never edit the master YAML to suit one employer.
- Preserve factual scope, technologies, ownership, metrics, and outcomes. Do not invent EHR, HL7/FHIR, Java/Scala, Kafka, or other experience simply because a posting names it.
- Prefer the original bullet if a rewrite adds no value. Don't combine unrelated accomplishments into misleading claims.
- List unsupported requirements separately as gaps.
- The mode guides the AI only; `render_resume.py` renders supplied overrides and does not generate prose itself. Confirm the local renderer implements `bullet_overrides` before depending on them.
