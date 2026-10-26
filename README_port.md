# Resume Builder V1

A Python-based resume builder that uses ChatGPT to tailor resumes to specific job descriptions. ChatGPT selects and optionally rewrites accomplishments, while Python generates consistently formatted Word documents.

Uses **ChatGPT Projects, Python, and LibreOffice**. Microsoft Word is not required.

## Setup

### 1. Prepare your master resume

Create a Word document named `resume-master-accomplishments.docx` containing your complete professional history, including accomplishments, skills, education, certifications, and projects.

Include more detail than you would in a typical resume. This document serves as your source of truth.

### 2. Create a ChatGPT Project

Create a new ChatGPT Project and upload the following files to its sources:

- `resume-master-accomplishments.docx`
- `RESUME_TAILORING.md`
- `RESUME_VALIDATION.md`
- `GENERATE_YAML.md`

Review and customize the instruction files as needed.

### 3. Generate your YAML inventory

In your ChatGPT Project, prompt:

> Using `GENERATE_YAML.md`, convert my master resume into a downloadable `master_accomplishments.yaml` compatible with this project's resume builder.

Download the generated YAML into your local repository and upload it to your ChatGPT Project sources.

This YAML file stores your professional experience and accomplishments using unique identifiers, allowing ChatGPT to reference them consistently.

Whenever you update your master resume, regenerate the YAML using the same instructions.

### 4. Set up Python

Clone or download the repository and navigate to its directory.

Create and activate a virtual environment (macOS/Linux):

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install python-docx pyyaml
```

Install [LibreOffice](https://www.libreoffice.org/) if you want to edit generated resumes or export them to PDF.

### 5. Customize your resume template

Create the `templates` directory if it does not exist, and place `resume-template.docx` inside it:

```bash
mkdir -p templates
```

Open `templates/resume-template.docx` in LibreOffice or Microsoft Word and customize the fonts, margins, headings, and styles.

The Python renderer reads templates from this directory and creates the directory if it is missing. Keeping templates together will allow you to choose different resume layouts in the future by passing another template filename with `--template`.

## How It Works

The pipeline consists of four steps:

1. **Tailor:** Paste a job description into ChatGPT. Using `RESUME_TAILORING.md` and your YAML inventory, ChatGPT generates a job-specific `selection.json`.
2. **Generate:** Run the Python renderer with the selection JSON to create a formatted DOCX resume.
3. **Validate:** Upload the generated resume and job description to ChatGPT. Use `RESUME_VALIDATION.md` to evaluate job alignment, factual accuracy, and formatting.
4. **Submit:** Make any necessary adjustments, regenerate the resume, and export it to PDF if desired.

ChatGPT controls content selection and optional wording changes. Python handles document formatting.

Your original accomplishment inventory remains unchanged during tailoring.

## Generate a Resume

### 1. Create a job-specific selection

In your ChatGPT Project, prompt:

> Using `RESUME_TAILORING.md` and `master_accomplishments.yaml`, tailor my resume to the following job description. Use `bullet_rewrite_mode=light` and generate a downloadable `selection.json` compatible with `render_resume.py`.
>
> [PASTE JOB DESCRIPTION]

Create `generated_selections` in your local project directory if it does not exist, then download the generated JSON into that directory. The renderer looks there when you pass a selection filename.

```bash
mkdir -p generated_selections
```

Supported bullet rewriting modes:

- `none` — Preserve original accomplishment wording.
- `light` — Adjust wording and terminology without changing underlying facts (default).
- `targeted` — More extensive rewriting while preserving factual accuracy.

### 2. Generate the Word document

Run:

```bash
python render_resume.py \
  --inventory master_accomplishments.yaml \
  --selection generated_selections/selection.json \
  --template templates/resume-template.docx \
  --output resume.docx
```

The generated `generated_resumes/resume.docx` can be opened and edited in LibreOffice or Microsoft Word.

### 3. Export to PDF (optional)

Using LibreOffice:

```bash
libreoffice --headless \
  --convert-to pdf \
  --outdir generated_resumes \
  generated_resumes/resume.docx
```

On macOS, the LibreOffice executable may need to be called using its full installation path.

### 4. Validate your resume

Start a new ChatGPT conversation within the same Project and upload the generated resume.

Prompt:

> Using `RESUME_VALIDATION.md`, review this resume against the job description below. Score its quality, identify significant issues, and recommend only meaningful improvements. Do not modify the resume.
>
> [PASTE JOB DESCRIPTION]

Review the results, correct important issues, and regenerate if necessary.

The validation score is an editorial assessment, **not an actual ATS score or prediction of interview success**.

## Project Files

| File | Purpose |
|---|---|
| `resume-master-accomplishments.docx` | Complete source resume |
| `master_accomplishments.yaml` | Structured inventory of accomplishments |
| `GENERATE_YAML.md` | Instructions for generating/updating YAML |
| `RESUME_TAILORING.md` | Instructions for job-specific tailoring |
| `RESUME_VALIDATION.md` | Instructions for resume evaluation |
| `templates/` | Directory for reusable DOCX formatting templates |
| `templates/resume-template.docx` | Default resume formatting template |
| `render_resume.py` | Python resume generator |
| `generated_selections/example_selection.json` | Reference JSON structure for selections |
| `generated_selections/` | Local directory for downloaded job-specific selection JSON files |
| `generated_resumes/` | Directory created by the renderer for generated DOCX files |

Keep `generated_selections/example_selection.json` available as a schema reference when generating new job-specific selections.

## Notes

- Always review AI-generated resumes for factual accuracy.
- Never add qualifications or technologies you cannot substantiate.
- The renderer does not automatically guarantee a two-page resume.
- Update the YAML whenever you modify the master accomplishments document.
- Keep your personal resume data and generated application files private if publishing this repository publicly.
- Add `.venv/`, generated resumes, and private application selections to `.gitignore` to avoid accidentally committing them.
