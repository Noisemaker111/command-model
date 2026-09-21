# Small model sweep — 2026-09-20

## Method

Candidates were discovered from the Hugging Face model registry by creation date, then joined to the public `FlameF0X/lm-cpu-benchmarks` results. This avoids starting from remembered model names. The registry date is only a discovery filter. A candidate still needs independent capability evidence and evaluation on the private shell-to-status test set.

The CPU leaderboard measures unquantized base-model prefill, decode, and WikiText-2 perplexity. It is a community benchmark; perplexity is a generic coherence signal, not shell-to-English accuracy. The Open SLM leaderboard is a second community check for models below roughly 250M parameters.

## Current shortlist

| Model | HF created | Parameters | CPU prefill tok/s | CPU decode tok/s | WikiText-2 PPL | Decision |
|---|---:|---:|---:|---:|---:|---|
| Qwen/Qwen3.5-0.8B | 2026-02-28 | 873M | 40.6 | 7.1 | 25.44 | Quality candidate; test and fine-tune |
| LiquidAI/LFM2.5-350M-Base | 2026-03-31 | 354M | 84.5 | 13.6 | 193.31 | Speed candidate; fine-tune before judging task quality |
| LiquidAI/LFM2.5-230M-Base | 2026-06-16 | 230M | 127.4 | 19.3 | 222.30 | Extreme-size candidate; only continue if structured task training works |
| HuggingFaceTB/nanowhale-100m-base | 2026-04-24 | 110M | 1820.5 | 34.0 | unavailable | Reject for now: its general benchmark scores are near chance and perplexity failed |
| tencent/Hunyuan-0.5B-Pretrain | 2025-07-28 | 539M | — | — | 25.05 | Older fallback; lower priority than Qwen3.5 |

The newest credible small base is not automatically the best candidate. LFM2.5-230M is newer and faster than Qwen3.5-0.8B, but its generic perplexity is much worse. The task benchmark decides whether domain fine-tuning closes that gap.

Sources: [Hugging Face model registry](https://huggingface.co/models?pipeline_tag=text-generation&sort=created), [CPU LM Speed Leaderboard](https://huggingface.co/spaces/FlameF0X/cpu-lm-benchmark), [Open SLM Leaderboard](https://huggingface.co/spaces/AxiomicLabs/Open_SLM_Leaderboard), [Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B), [LFM2.5-350M-Base](https://huggingface.co/LiquidAI/LFM2.5-350M-Base), [LFM2.5-230M-Base](https://huggingface.co/LiquidAI/LFM2.5-230M-Base).

## What the existing score means

The current Qwen3-0.6B LoRA model's saved Jev results show 94.3% same-action probability at the 0.5 threshold and 93.8% no-invention. Only 70.0% clears the 2.5/4 prose-quality threshold, producing a 69.3% combined pass rate. The old headline was therefore not factual accuracy. The remaining approximately 6% semantic error is still unacceptable for a trusted UI.

Report these dimensions separately from now on:

- action agreement and omission rate;
- invention rate;
- important-name preservation;
- deterministic secret and format checks;
- prose quality;
- latency, resident memory, and artifact size.

## Local Qwen3.5 prompt A/B

The full 587-row held-out set was run locally through the installed Ollama qwen3.5:0.8b model with identical decoding settings. No external grader was used.

| Input | Validator pass | Target recall | Secret-safe | p50 | p90 | Output rate |
|---|---:|---:|---:|---:|---:|---:|
| Raw command + few-shot chat | 97.3% | 40.2% | 99.7% | 225 ms | 301 ms | 136.4 tok/s |
| Mechanical parse + raw command + same examples | 98.6% | 85.9% | 100.0% | 219 ms | 294 ms | 135.5 tok/s |

The structured input improved target recall by 45.7 percentage points with no latency penalty, but target recall is computed for only 46 of 587 rows (7.8%): simple commands where the parser exposes one salient target. This is evidence that parser hints help name preservation, not a whole-set accuracy result. Reference-overlap checks across the full set remain weaker than the trained Qwen3 0.6B model, so Qwen3.5 0.8B is not a replacement without fine-tuning. Its installed artifact and measured residency are about 1.06 GB, versus 655 MB for the current quantized model.

## Local evaluation limits found

The deterministic target-recall check runs on only 46 of 587 held-out rows (7.8%), so it cannot be reported as model accuracy. Validator pass mostly measures sentence shape, tense, shell-noise removal, and secret handling. The new report also includes whole-set lexical overlap with the vetted reference, explicitly labeled as a regression signal rather than semantic accuracy. Whole-set semantic action agreement and invention still require an independent judge.

The structured parser emits an average of 3.35 actions on the held-out set. It finds no action for 27 rows, no meaningful action for 59, and more than the 12-action prompt cap for 24. These are concentrated in long PowerShell, nested quoting, JavaScript cells, heredocs, and pipelines, so the bounded raw command remains in the prompt.

With the LFM2.5 tokenizer, structured prompts have median lengths of 183 train and 196 test tokens. Thirty train and six test prompts exceed the 768-token training window. Training and checkpoint inference now retain both the prompt head and tail when truncating, preserving the mechanical action record and the end of the raw command.

## Trained LFM2.5-350M result

The structured LoRA run trained 0.98M parameters for three epochs on an RTX 3070. Validation loss was best at epoch 2 (1.2664), and the trainer restored that checkpoint after epoch 3 regressed to 1.2977. Training took 540 seconds and reported 1.5 GB peak allocated GPU memory.

| Model and runtime | Resident/model size | p50 | Output tok/s | Validator pass | Target recall (7.8% coverage) | Whole-set lexical F1 |
|---|---:|---:|---:|---:|---:|---:|
| Current Qwen3 0.6B Q4_K_M | 655 MB | 105 ms | 334.9 | 99.0% | 0.815 | 0.525 |
| LFM2.5 350M merged HF | 1,668 MB process RSS | 687 ms | 29.9 | 99.7% | 0.815 | 0.419 |
| LFM2.5 350M Q8_0 | 437 MB | 90 ms | 425.1 | 99.3% | 0.837 | 0.418 |
| LFM2.5 350M Q4_K_M | 287 MB | 85 ms | 475.6 | 98.8% | 0.859 | 0.393 |

The Q8 GGUF file is 379 MB and the Q4_K_M file is 229 MB. Q8 preserves the merged model's local lexical signal while reducing measured residency 33% and p50 latency 14% versus the current model. Q4 is smaller and faster but loses more reference overlap. The 350M Q8 candidate advances to independent semantic grading; it does not replace the current model based on local validators. Do not spend a run on LFM2.5 230M until the 350M candidate clears the action-agreement and invention gates.

## Architecture experiment

The raw-command formulation asks a small model to parse shell syntax, resolve action order, copy names, ignore injection-like strings, and write polished prose in one unconstrained generation. The repository already performs much of the parsing deterministically. Structured training made the 350M model viable on size and speed, but it did not reach the current model's whole-set lexical signal. A deterministic final renderer for recognized actions remains the next architectural experiment after semantic grading.

Weight pruning comes after semantic parity. Removing generic-domain weights without retraining can destroy useful syntax and language behavior, and zeroed weights do not guarantee lower latency in Ollama/llama.cpp. Quantizing the smaller dense base already produced the useful size and latency gain. If semantic grading passes and further compression is needed, distill the structured task into a smaller student and compare quantization-aware training before structured pruning.
Relevant pruning evidence: [Iterative Structured Pruning with Multi-Domain Calibration](https://arxiv.org/abs/2601.02674) argues for hardware-friendly structured removal and mixed-domain calibration; [GPrune-LLM](https://arxiv.org/abs/2603.13418) shows that single-domain calibration can bias neuron importance; [Pruning as a Domain-specific LLM Extractor](https://arxiv.org/abs/2405.06275) supports task-calibrated pruning but does not establish that arbitrary out-of-domain weights can be safely deleted from a sub-1B model.