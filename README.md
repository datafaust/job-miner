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
python job_web.py
```

Search from the terminal without AI (no Ollama required):

```sh
python main.py --keywords "data analyst" --location nyc --no-summary
```

For an interactive search with AI summaries, run `python main.py`. Use `--model MODEL` to choose another installed Ollama model.

Grade saved jobs:

```sh
python fit_grader.py --all --model openhermes
```

Generate a resume selection using the Job ID from a saved posting's detail page, review the output, then render it:

```sh
python resume_cli.py --job-id <JOB_ID> --model openhermes --rewrite-mode none
python render_resume.py --selection <SELECTION_JSON> --template templates/resume-template.docx --output generated_resumes/resume.docx
```

See [the reference](docs/REFERENCE.md) for configuration, exports, storage, troubleshooting, and workflow details.
