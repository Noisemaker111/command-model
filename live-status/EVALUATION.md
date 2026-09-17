# Evaluation

```powershell
python live-status/cli.py evaluate --backend ollama:<model>[:plain|:long|:instruct][:cpu] --name <run> [--grader jev|opus|both|none] [--promote]
python live-status/cli.py evaluate --regrade --name <run> --grader opus      # re-grade saved outputs
```

Every run writes `evaluation/<run>.json` (report) and `evaluation/outputs/<run>.jsonl`
(per-command output, metrics, validator results and grades).

## Deterministic validators (`evaluation/validators.py`)

one sentence · 2–22 words (hard limit 30) · starts with an `-ing` verb · no boilerplate
("This command…") · no shell syntax (`|`, `&&`, `$env:`, `2>&1`…) · no secret: nothing that
`find_secrets` matches, no placeholder, and no secret substring of the raw command · target
recall for simple read/process/delete commands.

## Graders

| Grader | What it sees | Cost / speed | Agreement with Opus 5 |
| --- | --- | --- | --- |
| `opus` | command, reference, output; returns correct, score, missing/hallucinated actions, secret leak, injection followed | ~20 outputs per call, ~60 s | — |
| `jev` (default) | command, reference, output; answers `same_actions`, `invented`, `quality` | 700 outputs in ~3 s, ~$0.02 | AUC 0.92, 86.4% agreement at score ≥ 0.45 (700 Opus-graded outputs) |

A jev-accepted output passes validators and has
`same × (1 − invented) × quality/4 ≥ 0.45`. Calibration lives in
`evaluation/jev_eval_calibration.json`; rerun it with `python live-status/judging/jev.py calibrate-eval`.
Grading a status without a reference is much weaker (AUC 0.68 on 3,000 teacher candidates), so
jev only *ranks* unlabeled outputs during failure mining and Opus writes the labels.

jev is stricter than Opus on good outputs: Opus's alternate teacher candidates on 200 test
commands pass 86% of Opus evaluations and 72% of jev evaluations. Compare runs only within
one grader.

Both graders cache verdicts by (command, output), so re-evaluating an unchanged output is free.

The `no_secret` validator also fails outputs that echo a redaction placeholder
(`<TOKEN>`, `<SECRET>`). Two of the round-1 runs did this once each, which blocks promotion;
the service replaces such outputs with the heuristic fallback.

## Promotion (`--promote`)

A run is promoted into `evaluation/registry.json` only if nothing leaks, its accepted rate is at
least the current best, hallucination does not rise by more than a point, and it was graded
by the same grader as the current best.

## Reports

Each report includes validator rates, accepted %, invented/hallucination %, omission % (Opus),
secret leakage %, injection-followed % (Opus), latency p50/p90/p99, tokens/s, model RAM/VRAM
from Ollama, and accepted % per difficulty tag.
