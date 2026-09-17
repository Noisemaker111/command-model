# Live status

A tiny local model that turns a shell or tool command into one live status sentence:

```
Get-Process opencode2,node,powershell -ErrorAction SilentlyContinue | Select-Object Name,Id
→ Checking running opencode2, node, and powershell processes.
```

Current best: **Qwen3-0.6B + LoRA, GGUF q4_K_M (397 MB)**, 67.8% of held-out statuses
accepted by the grader (the teacher's own second choices score 72%), 100 ms p50 on an
RTX 3070 and 393 ms on CPU only. Untuned models of the same size score at most 23.5%.
Details: [TRAINING.md](TRAINING.md), [EVALUATION.md](EVALUATION.md),
[DATASET.md](DATASET.md), [ARCHITECTURE.md](ARCHITECTURE.md).

## Use it

```powershell
python live-status/cli.py serve --backend ollama:live-status-v1-qwen3-06b-lora-q4_k_m --port 8765
python live-status/api/client.py "git fetch origin && git status -sb"
```

`POST /v1/summarize-command` with `{"command": "...", "shell": "powershell", "cwd": "optional"}`
returns `{"status": "..."}` (add `"debug": true` for source and latency). The service redacts
before inference, caches by normalised command, bounds concurrency, falls back to a
deterministic describer on timeout or invalid output, and never logs commands. For remote use
set `LIVE_STATUS_API_TOKEN` and pass `--tls-cert/--tls-key`; a non-loopback bind without a
token is refused. `api/client.py` works unchanged against `https://my-server.example`.

## Pipeline

Run from the repository root. GPU steps use the training venv (see TRAINING.md).

| Step | Command |
| --- | --- |
| Inventory transcript sources | `python live-status/cli.py inventory_sources` |
| Extract, redact, deduplicate, report | `python live-status/cli.py extract_commands` |
| Teacher labels (Opus 5) | `python live-status/cli.py generate_labels --limit 4000` |
| Judge labels (Opus 5) | `python live-status/cli.py judge_labels` |
| Build splits | `python live-status/cli.py build_dataset --version v1` |
| Baseline tiny models | `python live-status/cli.py benchmark_base_models --models smollm2:135m qwen3:0.6b` |
| Train | `live-status/cli.py train --base Qwen/Qwen3-0.6B --method lora --name ...` |
| Export GGUF + Ollama | `live-status/cli.py export_gguf --name ... --quants q8_0 q4_K_M` |
| Evaluate / promote | `python live-status/cli.py evaluate --backend ollama:... --name ... --promote` |
| Mine failures | `python live-status/cli.py mine_failures --backend ollama:... --round r2` |
| Mining → dataset in one go | `python live-status/cli.py run_full_pipeline` |
| Redact any JSONL | `python live-status/cli.py redact_dataset in.jsonl out.jsonl` |

`live-status/scripts/<step>.py` wraps each command. Private data lives in
`LIVE_STATUS_HOME` (default `<main checkout>/work/live-status`, ignored by Git); raw
commands stay in its `private/` folder.

## Models and keys

- Teacher and judge: `claude-opus-5` through the local CLIProxyAPI (`127.0.0.1:8317`).
  It shares the Claude subscription; keep `--workers` at 4 or below. On a long cooldown
  the run stops and resumes on rerun.
- Grader: TypeSafe `jev` through Vercel AI Gateway (`AI_GATEWAY_API_KEY` in the repo
  `.env`) or directly (`TYPESAFE_API_KEY`). Needs Bun; `bun install` in `live-status/jev`.
- Serving: Ollama; k-quants are produced with llama.cpp's `llama-quantize`.

## Tests

```powershell
python -m unittest discover -s live-status/tests -t live-status -v
```

Redaction (secrets never reach teacher prompts, stored redacted data, service output or
logs) and service boundaries (auth, size and rate limits, loopback-only default,
invalid-output fallback).
