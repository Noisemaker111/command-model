# Live status architecture

```
 transcripts ──► data_miner ──► private/records.jsonl ──► dedupe ──► private/commands.jsonl
 (Claude Code,     (sources.py      raw + redacted          template     │ raw representative
  Codex, OpenCode,  one parser                              groups,      ▼
  OpenCode2,        per format)                             counts   commands_redacted.jsonl ──┐
  Cursor, Grok,                                                                                │
  PSReadLine)                        parsers/shell.py ─► structure, difficulty tags ───────────┤
                                                                                               ▼
   labeling/teacher.py  (Haiku 4.5, two candidates per command, batched, resumable) ──► labels/teacher.jsonl
   judging/judge.py     (Haiku 4.5, separate prompt, scores teacher + heuristic candidates,
                         writes recommended_output)                               ──► labels/judged.jsonl
   dataset_build/build.py (accept / review / reject; MinHash families; frozen test) ──► datasets/<v>/*.jsonl
                                                                                               │
   benchmarks/baseline.py ◄── untuned tiny models through Ollama ◄─────────────────────────────┤
   training/train.py      ──► models/<name> (merged HF weights)  ◄────────────────────────────┘
   training/export_gguf.py──► GGUF f16/q8_0 + Ollama quantized tags
   evaluation/evaluate.py ──► validators + jev/Opus grading + latency/memory ──► evaluation/registry.json
   evaluation/active.py   ──► student failures on unlabeled commands ──► teacher/judge ──► prefs.jsonl (DPO)

 client ──► api/server.py ──► redact ─► cache ─► model (Ollama) ─► validate ─► heuristic fallback
```

## Boundaries

| Boundary | Rule | Enforced by |
| --- | --- | --- |
| Raw commands | Only `private/` (owner-only ACL) holds unredacted text | `common.private_dir`, `commands_redacted.jsonl` has no raw field |
| Teacher/judge | Only redacted text is sent | `labeling.llm.chat` refuses any prompt where `find_secrets` matches |
| Model output | Must pass validators and must not contain any secret from the raw command | `api.server.Service`, `evaluation.validators.check` |
| Logs | Service logs hold a hash, source, latency and status only; no request lines | `Service._log`, `Handler.log_message` |
| Network | Loopback by default; non-loopback bind requires `LIVE_STATUS_API_TOKEN` | `api.server.main` |
| Held-out data | Test/validation families are frozen on first build | `datasets/frozen_families.json` |

## Why these choices

- **Heuristic as fallback, not fast path.** The deterministic describer answers in under a millisecond, but its confidence ≥ 0.9 outputs cover only 8.7% of executions and the judge rated just 19% of them ≥ 80 (they are correct but generic: "Reviewing the Git diff." for `git diff --stat`). The service therefore always asks the model and uses the heuristic when the model fails, times out or produces an invalid sentence; `--fast-path` re-enables the shortcut.
- **Plain completion format.** The student learns `Command:\n…\n\nStatus: <sentence>` with no system prompt, so each request costs only the command's tokens.
- **Ollama/llama.cpp for serving.** It already runs on this machine, serves GGUF at every quantization level, and keeps models warm. `llama-server` is supported by the same backend interface.
- **Haiku writes, jev grades, Opus audits.** Teacher and judge run on Haiku 4.5 with different
  prompts; label diversity comes from two candidates per command plus the heuristic. jev
  (TypeSafe System One) returns only probabilities, choices and scores, in milliseconds, at
  $0.042 per million input tokens: given the gold status it agrees with Opus evaluations at
  AUC 0.92, so it grades every benchmark and ranks student outputs for failure mining. It
  cannot replace the judge, because without a reference it reaches only AUC 0.68 and its own
  Choice between near-equal candidates matches the judge just 52% of the time. Opus is kept
  for spot checks and for the calibration sets both graders are measured against.
- **Frequency weighting.** Each template group counts `min(4, 1 + log2(count))` times in training, so common patterns are learned first without drowning the long tail.

## Adding a transcript format

Write a function in `data_miner/sources.py` decorated with `@source(name, description, discover)` that yields `_record(...)` dictionaries, then rerun `extract_commands`.
