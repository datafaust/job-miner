"""Local browser for saved jobs and reviewed resume-selection requests."""

import argparse
import json
import math
import os
import secrets
import signal
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import requests
import yaml
from flask import Flask, abort, redirect, render_template, request, send_file, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from job_tools import job_history
from job_tools import resume_web_tasks as tasks
from job_tools.resume_inputs import load_saved_posting
from render_resume import produce


PAGE_SIZE = 25
PROJECT_DIR = Path(__file__).resolve().parent
app = Flask(__name__)
confirmation_signer = URLSafeTimedSerializer(secrets.token_bytes(32), salt="resume-selection")


def _available_models():
    """Return installed Ollama text-generation models and a displayable error."""
    try:
        response = requests.get("http://127.0.0.1:11434/api/tags", timeout=3)
        response.raise_for_status()
        models = response.json().get("models", [])
        names = []
        for item in models:
            name = item.get("name") if isinstance(item, dict) else None
            if not isinstance(name, str) or not name:
                continue
            try:
                shown = requests.post(
                    "http://127.0.0.1:11434/api/show", json={"model": name}, timeout=3
                )
                shown.raise_for_status()
                capabilities = shown.json().get("capabilities")
            except (requests.RequestException, ValueError):
                capabilities = None
            if capabilities is None or "completion" in capabilities:
                names.append(name)
        return sorted(set(names), key=str.casefold), None
    except (requests.RequestException, ValueError, AttributeError, TypeError) as error:
        return [], f"Could not reach local Ollama: {error}. Start Ollama and reload this page."


def _job(job_id):
    return next((item for item in _saved_jobs() if item["job_key"] == job_id), None)


def _detail_url(job_id, values):
    return url_for(
        "job_detail", job_id=job_id,
        q=values.get("q", ""), source=values.get("source", ""),
        remote=values.get("remote", ""), page=values.get("page", "1"),
    )


def _elapsed_text(start_text, end_text=None):
    if not start_text:
        return None
    try:
        started = datetime.fromisoformat(start_text)
        ended = datetime.fromisoformat(end_text) if end_text else datetime.now(timezone.utc)
        seconds = max(0, int((ended - started).total_seconds()))
    except (TypeError, ValueError):
        return None
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {seconds}s" if hours else f"{minutes}m {seconds}s"


def _saved_jobs():
    """Include every saved posting, even when extraction or AI work failed."""
    with job_history._database() as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT h.job_key, h.url, h.processed_at, h.hidden_at,
                      p.job_title, p.company, p.location, p.remote_status,
                      p.salary_range, p.posted_at, p.posted_text,
                      s.title AS summary_title, s.status AS summary_status,
                      s.result_text AS summary_text, s.saved_at AS summary_saved_at
               FROM processed_jobs AS h
               LEFT JOIN prospective_jobs AS p USING (job_key)
               LEFT JOIN job_summaries AS s USING (job_key)
               ORDER BY h.processed_at DESC, h.job_key"""
        ).fetchall()

    jobs = []
    for row in rows:
        job = dict(row)
        job["source"] = job_history.job_source(job["job_key"], job["url"])
        job["title"] = job["job_title"] or job["summary_title"]
        if not job["title"]:
            try:
                job["title"] = load_saved_posting(job["job_key"])["title"]
            except (OSError, ValueError, KeyError, UnicodeError):
                job["title"] = "Untitled posting"
        job["remote_status"] = job["remote_status"] or "unknown"
        jobs.append(job)
    return jobs


def _list_state():
    query = request.args.get("q", "").strip()
    source = request.args.get("source", "").strip()
    remote = request.args.get("remote", "").strip()
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    return query, source, remote, page


@app.get("/")
def job_list():
    all_jobs = [job for job in _saved_jobs() if job["hidden_at"] is None]
    query, source, remote, page = _list_state()
    sources = sorted({job["source"] for job in all_jobs})
    if source not in sources:
        source = ""
    if remote not in {"remote", "hybrid", "on_site", "unknown"}:
        remote = ""

    filtered = [
        job for job in all_jobs
        if (not query or query.casefold() in
            f"{job['title']} {job['company'] or ''}".casefold())
        and (not source or job["source"] == source)
        and (not remote or job["remote_status"] == remote)
    ]
    page_count = max(1, math.ceil(len(filtered) / PAGE_SIZE))
    page = min(page, page_count)
    start = (page - 1) * PAGE_SIZE
    visible_jobs = filtered[start:start + PAGE_SIZE]
    return render_template(
        "job_list.html", jobs=visible_jobs,
        hide_tokens={job["job_key"]: confirmation_signer.dumps({"hide_job": job["job_key"]})
                     for job in visible_jobs},
        total=len(filtered), saved_total=len(all_jobs), sources=sources,
        q=query, source=source, remote=remote, page=page,
        page_count=page_count,
        resume_job_ids=tasks.jobs_with_generated_resumes(),
    )


@app.post("/jobs/<path:job_id>/hide")
def job_hide(job_id):
    try:
        data = confirmation_signer.loads(request.form.get("token", ""), max_age=3600)
        if data.get("hide_job") != job_id:
            abort(400)
    except (BadSignature, SignatureExpired):
        abort(400, "Reload the job list and try again.")
    with job_history._database() as connection:
        result = connection.execute(
            "UPDATE processed_jobs SET hidden_at = COALESCE(hidden_at, CURRENT_TIMESTAMP) WHERE job_key = ?",
            (job_id,),
        )
        if result.rowcount == 0:
            abort(404)
    return redirect(url_for(
        "job_list", q=request.form.get("q", ""), source=request.form.get("source", ""),
        remote=request.form.get("remote", ""), page=request.form.get("page", "1"),
    ))


@app.get("/jobs/<path:job_id>")
def job_detail(job_id):
    job = _job(job_id)
    if job is None:
        abort(404)
    try:
        posting = load_saved_posting(job_id)
    except (OSError, ValueError, KeyError, UnicodeError) as error:
        posting = None
        posting_error = str(error)
    else:
        posting_error = None
    query, source, remote, page = _list_state()
    back_url = url_for("job_list", q=query, source=source, remote=remote, page=page)
    models, model_error = _available_models()
    return render_template(
        "job_detail.html", job=job, posting=posting,
        posting_error=posting_error, back_url=back_url,
        models=models, model_error=model_error,
        recent_attempts=tasks.recent_for_job(job_id),
        render_token=confirmation_signer.dumps({"render_job": job_id}),
        q=query, source=source, remote=remote, page=page,
    )


@app.post("/jobs/<path:job_id>/resume/confirm")
def resume_confirm(job_id):
    job = _job(job_id)
    if job is None:
        abort(404)
    model = request.form.get("model", "")
    rewrite_mode = request.form.get("rewrite_mode", "none")
    if rewrite_mode not in {"none", "light", "targeted"}:
        abort(400, "Choose a valid bullet mode.")
    models, model_error = _available_models()
    detail_url = _detail_url(job_id, request.form)
    if model_error or model not in models:
        return render_template(
            "resume_error.html", detail_url=detail_url,
            message=model_error or "Select an installed text-generation model.",
        ), 400
    try:
        load_saved_posting(job_id)
    except (OSError, ValueError, KeyError, UnicodeError) as error:
        return render_template(
            "resume_error.html", detail_url=detail_url,
            message=f"The saved posting could not be opened: {error}",
        ), 400
    task_id = str(uuid4())
    token = confirmation_signer.dumps({
        "task_id": task_id, "job_id": job_id, "model": model,
        "rewrite_mode": rewrite_mode,
        "detail_url": detail_url,
    })
    return render_template(
        "resume_confirm.html", job=job, model=model,
        rewrite_mode=rewrite_mode,
        token=token, detail_url=detail_url,
    )


@app.post("/resume/start")
def resume_start():
    try:
        data = confirmation_signer.loads(request.form.get("token", ""), max_age=900)
        task_id = str(UUID(data["task_id"]))
        job_id, model = data["job_id"], data["model"]
        rewrite_mode = data.get("rewrite_mode", "none")
        if rewrite_mode not in {"none", "light", "targeted"}:
            abort(400)
    except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
        abort(400, "Confirmation expired. Choose a model again from the job page.")
    if _job(job_id) is None:
        abort(404)
    models, model_error = _available_models()
    if model_error or model not in models:
        return render_template(
            "resume_error.html", detail_url=data["detail_url"],
            message=model_error or "The selected model is no longer installed.",
        ), 400

    task_dir = tasks.TASK_ROOT / task_id
    try:
        task_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        return redirect(url_for("resume_status", task_id=task_id))
    status = {
        "task_id": task_id, "job_id": job_id, "model": model,
        "rewrite_mode": rewrite_mode,
        "detail_url": data["detail_url"], "state": "queued",
        "created_at": tasks.now_utc(),
    }
    tasks.write_status(task_dir, status)
    try:
        with (task_dir / "worker.log").open("w", encoding="utf-8") as log:
            subprocess.Popen(
                [sys.executable, str(PROJECT_DIR / "resume_web_worker.py"), str(task_dir)],
                cwd=PROJECT_DIR, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except OSError as error:
        status.update(
            state="failed", finished_at=tasks.now_utc(),
            message="A custom resume could not be made. The selection worker could not start.",
            errors=[str(error)],
        )
        tasks.write_status(task_dir, status)
    return redirect(url_for("resume_status", task_id=task_id))


@app.get("/resume/<task_id>")
def resume_status(task_id):
    try:
        task_id = str(UUID(task_id))
        status = tasks.read_status(tasks.TASK_ROOT / task_id)
    except (ValueError, OSError, KeyError):
        abort(404)
    cancel_token = confirmation_signer.dumps({"cancel": task_id})
    return render_template(
        "resume_status.html", task=status, cancel_token=cancel_token,
        render_token=confirmation_signer.dumps({"render_job": status["job_id"]}),
        elapsed=_elapsed_text(status.get("started_at") or status.get("created_at"),
                              status.get("finished_at")),
        stage_elapsed=_elapsed_text(status.get("stage_started_at"),
                                    status.get("finished_at")),
    )


@app.post("/resume/<task_id>/render")
def resume_render(task_id):
    try:
        task_id = str(UUID(task_id))
        status = tasks.read_status(tasks.TASK_ROOT / task_id)
    except (ValueError, OSError, KeyError):
        abort(404)
    try:
        data = confirmation_signer.loads(request.form.get("token", ""), max_age=3600)
        if data.get("render_job") != status["job_id"]:
            abort(400)
    except (BadSignature, SignatureExpired):
        abort(400, "Reload the posting or selection page and try again.")
    if status.get("state") != "ready_for_review":
        abort(409, "A selection must pass validation before rendering a resume.")
    try:
        inventory = yaml.safe_load(
            (Path(status["run_dir"]) / "inventory.yaml").read_text(encoding="utf-8")
        )
        selection = json.loads(Path(status["selection_file"]).read_text(encoding="utf-8"))
        generated_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        filename = f"resume-{generated_at}-{task_id}-{uuid4().hex}.docx"
        output = produce(
            inventory, selection, PROJECT_DIR / "templates" / "resume-template.docx",
            filename,
        )
        status.update(resume_generated_at=generated_at, resume_file=str(output))
        tasks.write_status(tasks.TASK_ROOT / task_id, status)
    except Exception as error:
        app.logger.exception("Resume rendering failed for %s", task_id)
        return render_template(
            "resume_error.html", detail_url=status["detail_url"],
            message=f"The resume could not be generated: {error}",
        ), 422
    return send_file(
        output, as_attachment=True, download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.post("/resume/<task_id>/cancel")
def resume_cancel(task_id):
    try:
        task_id = str(UUID(task_id))
        data = confirmation_signer.loads(request.form.get("token", ""), max_age=3600)
        if data.get("cancel") != task_id:
            abort(400)
        task_dir = tasks.TASK_ROOT / task_id
        status = tasks.read_status(task_dir)
    except (ValueError, OSError, KeyError, BadSignature, SignatureExpired):
        abort(404)
    if status.get("state") != "running":
        return redirect(url_for("resume_status", task_id=task_id))
    pid = status.get("pid")
    if isinstance(pid, int) and pid > 0:
        process = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, check=False,
        )
        if process.returncode == 0 and "resume_web_worker.py" in process.stdout and str(task_dir) in process.stdout:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    status = tasks.read_status(task_dir)
    if status.get("state") == "running":
        status.update(state="canceled", finished_at=tasks.now_utc(), message="Selection canceled by user.")
        tasks.write_status(task_dir, status)
    return redirect(url_for("resume_status", task_id=task_id))


def main():
    parser = argparse.ArgumentParser(description="Browse saved Job Miner postings locally.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5055)
    args = parser.parse_args()
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
