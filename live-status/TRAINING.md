# Training

```powershell
$V = "C:\Users\Jk101\Projects\command-model\.worktrees\command-specialist\.venv\Scripts\python.exe"  # torch 2.11 cu128, transformers 4.57, peft 0.20
& $V live-status/cli.py train --base Qwen/Qwen3-0.6B --data v1 --method lora --lora-r 64 --name v1-qwen3-06b-lora
& $V live-status/cli.py export_gguf --name v1-qwen3-06b-lora --quants q8_0 q4_K_M
python live-status/cli.py evaluate --backend ollama:live-status-v1-qwen3-06b-lora-q4_k_m --name v1-qwen3-06b-lora-q4_k_m --promote
```

## Format

```
Command:
<redacted command, head 70% / tail 30% if over 2,400 chars>

Status: <gold sentence><eos>
```

Loss covers only the status and EOS. `--prompt instruct` prepends the long instruction
(serve it with the `:long` backend suffix); `mixed` uses it on 30% of rows.

## Mechanics

- Left padding plus `logits_to_keep`, so logits are computed only for the target tail.
  With gradient checkpointing this took SmolLM2-135M from 21.6 GB (spilling into shared
  memory, 110 s/epoch on 145 rows) to 4.2 GB.
- Full fine-tunes of 270–360M models use `--optim adafactor` to fit in 8 GB; AdamW ran at
  ~7 s/step from memory spill.
- The epoch with the lowest validation loss is kept (validation loss rises after epoch 2).
- DPO (`--dpo prefs.jsonl`) trains a LoRA adapter on top of a merged SFT model, with the
  adapter disabled as the reference policy. Preference pairs come from failure mining.
- Checkpoints are never overwritten; each run writes `train_meta.json` (git revision, data
  version, hyperparameters, best epoch, peak memory).

## Round 1 results (v1 test, 494 commands, jev-graded, Ollama q8_0 on an RTX 3070)

| Model | Method | Accepted | Invented | Validators | p50 | Size | Train time |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| SmolLM2-135M untuned (few-shot) | — | 3.6% | 56.3% | 83.4% | 77 ms | — | — |
| Qwen2.5-Coder-0.5B untuned (best baseline) | — | 23.5% | 17.6% | 95.7% | 78 ms | — | — |
| SmolLM2-135M | full, plain | 35.4% | 21.1% | 99.4% | 74 ms | 205 MB | 6 min |
| SmolLM2-135M | full, instruct prompt | 35.6% | 21.3% | 98.8% | 79 ms | 205 MB | 9 min |
| Gemma3-270M | full, Adafactor | 33.8% | 27.7% | 99.6% | 91 ms | 321 MB | 18 min |
| SmolLM2-360M | full, Adafactor | 52.8% | 10.7% | 99.4% | 98 ms | 492 MB | 11 min |
| Qwen2.5-0.5B | LoRA r64 | 58.3% | 9.3% | 99.8% | 86 ms | 588 MB | 11 min |
| **Qwen3-0.6B** | LoRA r64 | **69.4%** | **6.3%** | 99.4% | 106 ms | 898 MB | 16 min |

Quantization of Qwen3-0.6B (same test set):

| Level | GGUF | Accepted | Invented | p50 GPU | p50 CPU-only |
| --- | ---: | ---: | ---: | ---: | ---: |
| f16 | 1.2 GB | 69.0% | 6.3% | 139 ms | — |
| q8_0 | 639 MB | 69.4% | 6.3% | 106 ms | — |
| q6_K | 495 MB | 66.8% | 7.9% | 104 ms | — |
| q5_K_M | 444 MB | 66.6% | 6.1% | 113 ms | — |
| **q4_K_M** | **397 MB** | **67.8%** | 6.9% | 100 ms | 393 ms |

Findings: the instruction prompt adds nothing once the model is fine-tuned, so the plain
format stays. Quality tracks base-model capability more than parameter count (Gemma3-270M
trails SmolLM2-135M). Quantizing to q4_K_M costs about one point, within run-to-run noise.
For scale: Opus's own alternate (non-selected) candidates for the same 200 test commands
score 72.0% accepted under jev (86% under the Opus evaluator), so Qwen3-0.6B at 69.4% is
close to the teacher's second-choice quality under the same grader.

## Iteration loop

```
build_dataset -> train -> export_gguf -> evaluate (jev) -> mine_failures -> build_dataset ...
```

`mine_failures` runs the current student over unlabeled commands, ranks its outputs with
jev, sends the weakest 40% (plus a random fifth as many) to the Opus teacher and judge,
and appends (chosen, rejected) pairs to `labels/prefs.jsonl`. Round r1 (SmolLM2-135M, 1,500
commands) sent 726 to the teacher; the judge stopped after 104 when the Opus subscription
entered a cooldown, and resumes on rerun.
