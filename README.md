<p align="center">
  <img src="assets/icon.png" alt="Job Miner icon" width="160">
</p>

# Job Miner

Search job boards, browse saved postings locally, and use local Ollama models to summarize jobs, grade fit, and tailor resumes. Jobs and results are saved in SQLite.

## Setup

Run from the repository root with Python 3.10 and Chrome installed (Idealist searches use Selenium):

```sh
python3.10 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` to set default keywords and location (`nyc` or `remote`). Adzuna credentials and Google Drive settings are optional.

For AI features, install [Ollama](https://ollama.com/), start it with `ollama serve` (or the desktop app), and pull a model:

```sh
ollama pull openhermes
```

## Run

Activate the environment with `source .venv/bin/activate` and run commands from the repository root.

Start the web app, then open <http://127.0.0.1:5055> to search, browse jobs, and generate resumes:

```sh
python -m job_miner.web.app
```

Search from the terminal without AI (no Ollama required):

```sh
python -m job_miner.cli.search --keywords "data analyst" --location nyc --no-summary
```

For an interactive search with AI summaries, run `python -m job_miner.cli.search`. Use `--model MODEL` to choose another installed Ollama model.

List configured job categories from `config/related_keys.json`, or include all unique primary and related job titles:

```sh
python -m job_miner.cli.list_jobs
python -m job_miner.cli.list_jobs --all-titles
```

Grade saved jobs:

```sh
python -m job_miner.cli.grade --all --model openhermes
```

Generate a resume selection using the Job ID from a saved posting's detail page, review the output, then render it:

```sh
python -m job_miner.cli.resume --job-id <JOB_ID> --model openhermes --rewrite-mode none
python -m job_miner.cli.render --selection <SELECTION_JSON> --template templates/resume-template.docx --output generated_resumes/resume.docx
```

See [the reference](docs/REFERENCE.md) for configuration, exports, storage, troubleshooting, and workflow details.

## Code layout

`job_miner/` contains command entry points (`cli/`), search and resume workflows
(`search/`, `resumes/`), the Flask app (`web/`), and background workers (`workers/`).
`job_tools/` holds the existing board integrations, storage, and validation helpers;
`examples/` holds standalone examples. Shared repository paths live in
`job_miner/paths.py`. Templates, static assets, configuration, and generated data
remain in the repository root.

The former root Python scripts have moved. Use the `python -m` commands above
from the repository root; update any saved shell commands or scheduled jobs.

Run the automated tests without live job-board or Ollama calls:

```sh
python -m unittest discover -s tests
```
