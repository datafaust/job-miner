# Job Miner GPU Measurements

Measured November 4, 2026; times below are Eastern Standard Time.

**Finding:** the ten-minute cooldown successfully lowers GPU temperature between batches, but individual fit grades still produce sustained high power and thermal throttling. Longer breaks can delay throttling by providing a cooler starting point; they do not reduce the workload during inference. Scheduled grading is currently paused following the user's request. No power or temperature cap is applied by the application.

## What the fit grader does

The fit grader compares a saved job posting against the candidate's documented experience in `master_accomplishments.yaml`. It sends the posting, skills, education, certifications, and an accomplishment-ID/evidence map to a local Ollama model. The response contains a 0–100 score, a summary, and 2–8 requirements assessed as match, partial match, or gap, with source citations. Python validates the response, checks named-tool evidence, assigns a strong/possible/weak tier, and saves the result in SQLite for display in the frontend. A failed validation preserves any previous grade.

It is separate from searching job boards and generating tailored resumes.

## Measurements

Hardware: NVIDIA GeForce RTX 3090, 24 GiB VRAM, driver 595.99.02. Observed enforced power limit: 420 W. Two batches produced **1,080 samples** at approximately one-second intervals, spanning about 18 minutes with a short gap. These logs do not cover last night's search or the period before monitoring was installed.

| Metric | Batch starting 1:25 p.m. | Batch starting 1:41 p.m. |
|---|---:|---:|
| Outcome | Batch finished; both grades failed validation | One grade saved; next grade interrupted when grading was halted |
| Observed grading time | ~303 seconds | ~169 seconds |
| Mean / peak grading power | 323 / 418 W | 289 / 417 W |
| Mean / peak core temperature | 81 / 88°C | 77 / 88°C |
| Estimated thermal-throttling time | 175 seconds (~58%) | 65 seconds (~39%) |
| Peak reported fan speed | 100% | 100% |
| Peak VRAM usage | ~18.55 GiB | ~18.45 GiB |

The first batch's cooldown reached **60°C after one minute, 57°C after five minutes, and 59°C after ten minutes**, averaging about **42 W**. The next batch started near 59–61°C and nevertheless reached 88°C. The second batch has no recorded cooldown because it was halted.

The GPU is engaging thermal protection during substantial portions of grading. NVIDIA describes thermal slowdown flags as temperature-related clock reductions ([NVIDIA documentation](https://docs.nvidia.com/deploy/nvidia-smi/index.html)). This supports investigating cooling and active workload before resuming unchanged. It does **not** establish hardware damage or predict lifespan.

## What the code looks like

Relevant files:

- [Core grader](job_miner/cli/grade.py): prompt, JSON schema, Ollama request, validation, and grade persistence.
- [Scheduled batch worker](job_miner/cli/grade_batch.py): queue order, limits, locking, cooldown, and optional monitoring.
- [Browser grading worker](job_miner/workers/grade.py): explicit single-job reruns, sharing the batch lock and cooldown.
- [Browser request settings](job_tools/grade_web_tasks.py): hardcoded manual model default.
- [GPU monitor](job_tools/grade_monitor.py): NVML sampling, events, summaries, and retention.

The core request is effectively:

```python
requests.post(
    "http://127.0.0.1:11434/api/generate",
    json={
        "model": model,
        "prompt": prompt,
        "format": grade_schema(evidence),
        "stream": False,
        "keep_alive": 0,
        "think": True,
        "options": {
            "temperature": 0,
            "num_ctx": 16384,
            "num_predict": 8192,
        },
    },
    timeout=1200,
)
```

The current model is `qwen3.5-27b-16k:latest`. Read-only Ollama metadata identifies it as **26.9B parameters, Q4_K_M quantization**, derived from `qwen3.5:27b`. The scheduled command selects it with `--model`; the browser default is hardcoded separately. Other sampling defaults can come from the model: the installed model reports `presence_penalty=1.5`, `top_k=20`, and `top_p=0.95`; the request explicitly overrides temperature to zero.

The scheduled worker attempts at most ten grades, stops starting new ones after five minutes, and allows an in-flight grade to finish before beginning the ten-minute cooldown. There is no temperature-based pause inside an individual inference. Failed jobs are deferred 24 hours. Browser reruns use `force=True`; direct manual CLI grading bypasses batch pacing. Only monitored batch runs currently produce the GPU logs discussed here.

## Token and timing evidence

Ollama reported the following for the three completed inference requests:

| Request | Input tokens | Generated tokens | Model loading | Prompt evaluation | Generation | Result |
|---|---:|---:|---:|---:|---:|---|
| 1 | 4,268 | 5,497 | 42.2 s | 3.1 s | 142.3 s | Validation failed |
| 2 | 4,213 | 2,963 | 35.5 s | 3.0 s | 76.3 s | Validation failed |
| 3 | 4,134 | 3,607 | 33.3 s | 3.0 s | 95.8 s | Grade saved |

Generation accounted for approximately **72%** of their combined request time, loading about **26%**, and prompt evaluation about **2%**. Generation throughput was roughly 38 tokens/second. All three stopped normally rather than hitting the generation limit.

`num_ctx=16384` is context capacity, not evidence that every prompt uses 16,384 tokens. `num_predict=8192` is an output ceiling, not a mandatory output length ([Ollama parameter reference](https://docs.ollama.com/modelfile)). Thinking is enabled and its text is returned separately from the final answer; the present logs do not measure the thinking/final-answer token split ([Ollama thinking documentation](https://docs.ollama.com/capabilities/thinking)).

## Potential issues and what to investigate

1. **Generation workload and model size.** A 27B thinking model is substantial for this task. Compare a smaller model and a non-thinking configuration against the same representative jobs. Evaluate citation correctness, domain gaps, and scoring quality alongside heat, runtime, and energy per valid grade. These are proposed experiments, not proven fixes.
2. **Output budget.** Thousands of generated tokens accompany a relatively compact final assessment. Test tighter answer instructions and a lower generation ceiling, such as 2,048–4,096 tokens. With thinking still enabled, a lower ceiling may truncate reasoning before valid JSON is produced; the grader rejects length-limited responses. Measure validity before adopting a change.
3. **Context sizing and prompt content.** The complete evidence inventory is sent for every job. Consider a carefully validated relevance-selection step or a smaller context. Preserve relevant accomplishments and room for generation: an 8K context cannot necessarily accommodate a ~4.3K prompt plus a long thinking/answer sequence. Context reduction may save memory without substantially reducing instantaneous power; prompt processing was already short in this sample.
4. **Schema versus semantic validation.** Both first-batch failures were `Gaps must have no evidence; matches and partial matches need evidence`. The schema constrains field types and allowed IDs but does not encode that relationship. Explore supported conditional schema alternatives that enforce empty IDs for gaps and nonempty IDs for matches/partial matches. Retain Python validation. These failures consumed GPU time without a usable grade; there is no automatic in-request repair loop today.
5. **Reloading every job.** `keep_alive=0` unloads the model after every response. This was deliberately added for a previously observed cache/memory-buildup concern. Reloading cost 33–42 seconds per completed request. Investigate that memory concern before testing short model retention within a bounded batch and unloading afterward. Retaining an idle model is not equivalent to sustained inference, but changes require memory and temperature measurements.
6. **Sampling settings.** Temperature zero differs from Qwen's published mode-specific recommendations. Benchmark those settings if investigating output failures or lengthy generation; the current evidence does not establish temperature as their cause ([official Qwen model card](https://huggingface.co/Qwen/Qwen3.5-27B)).
7. **Power and physical cooling.** The 420 W enforced limit permits the observed peaks near 418 W. A lower power-limit experiment could reduce active heat, with a throughput tradeoff; it was previously removed at the user's request and remains disabled. Also inspect airflow, dust, ambient temperature, and fan operation. Software logs alone cannot diagnose heatsink contact or thermal-pad condition.

## Evidence limits and log references

The monitor records whole-GPU readings, so other applications may contribute. Memory temperature was unavailable. The thermal flag combines hardware and software thermal-slowdown reasons; it cannot identify which sensor or component triggered the event. Reported temperature thresholds are not proof of a safe operating margin for every component. One-second samples miss short spikes; energy and throttling durations are estimates.

The interrupted batch's summary counts only jobs with a recorded end event. Its event log shows a second job started but was interrupted, so the summary's `attempted` count understates starts. Raw logs are excluded from Git, retained locally for 30 days, and summaries are retained longer.

- [Batch 1 summary](generated_search_requests/grading_logs/20261104T182501-336edd98/summary.json), [GPU samples](generated_search_requests/grading_logs/20261104T182501-336edd98/gpu.csv), [events](generated_search_requests/grading_logs/20261104T182501-336edd98/events.jsonl).
- [Batch 2 summary](generated_search_requests/grading_logs/20261104T184101-f333eb29/summary.json), [GPU samples](generated_search_requests/grading_logs/20261104T184101-f333eb29/gpu.csv), [events](generated_search_requests/grading_logs/20261104T184101-f333eb29/events.jsonl).

**Next comparison:** change one factor at a time, retaining the cooldown and recording temperatures, throttling fraction, duration, token counts, and watt-hours per valid grade. No grading configuration was changed or grading resumed for this report.
