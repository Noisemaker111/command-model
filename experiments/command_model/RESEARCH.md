# Starting point: a local Command Model

A useful local specialist is feasible on an 8 GB RTX 3070. Beating a frontier model
on a narrow operation is a testable hypothesis. Beating frontier models generally,
or making the whole agent 20 times faster, is not established by parameter count or
an instruction-tuned model's coding leaderboard score.

The most useful first split is between command interpretation, mechanical command
rendering, and output extraction. Keep command rendering, quoting, exit codes, and
known structured-output parsing in ordinary code. Use a small model for interpreting
the requested operation and selecting context-dependent evidence. Return exact
evidence with a retrievable raw-result reference; do not ask a tiny model to freely
rewrite diagnostic facts.

## Model shortlist

| Candidate | Why consider it | Evidence and limits |
|---|---|---|
| Qwen2.5-Coder-1.5B-Instruct | The first training baseline; Apache 2.0, code-oriented, established inference and LoRA tooling | Official card reports 1.54B parameters and 32,768 context. Local pilot measurements decide usefulness; its Python/code scores do not establish PowerShell reliability. |
| Qwen3.5-0.8B | Smaller challenger; Apache 2.0; Qwen explicitly identifies task-specific fine-tuning as an intended use | Official BFCL-V4 score 25.3; its 2B sibling reports 43.6. Those are thinking-mode agent results, not this non-thinking shell benchmark. The smaller default Ollama download is Q8_0, while the coder baseline is Q4_K_M. |
| Qwen3.5-2B | Potential accuracy-oriented challenger if 0.8B is too weak | Larger than the user's target, but still practical to evaluate locally with a bounded context. No local result from this pilot. |
| FunctionGemma-270M | Especially relevant for a very small typed function caller | Google designed it for function calling and recommends task-specific fine-tuning. Google reports 58% to 85% on its Mobile Actions task after fine-tuning. It uses Gemma terms, not Apache 2.0; this is not a shell result. |
| LFM2-1.2B-Tool | A purpose-built small tool-use alternative | Official tool-use model available; architecture/runtime and license should be evaluated for the intended distribution. No local result from this pilot. |

Sources: [Qwen2.5 model card](https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct),
[Qwen3.5 model card and benchmark table](https://huggingface.co/Qwen/Qwen3.5-0.8B),
[FunctionGemma](https://deepmind.google/models/gemma/functiongemma/),
[LFM2 tool model](https://huggingface.co/LiquidAI/LFM2-1.2B-Tool).

## Why training might work

Google's FunctionGemma result demonstrates that tiny task-specific function models
can improve substantially after adaptation. Separately, the Data Turnstile authors
report Qwen3-0.6B at 75.9% on BFCL single-turn after fine-tuning without chain of
thought, compared with 67.4% for their thinking-enabled base. Neither result promises
the same improvement on Windows shell tasks. The right inference is that a narrow
specialist is worth testing, not that the problem is already solved.

Sources: [Data Turnstile paper](https://arxiv.org/abs/2607.29250),
[NVIDIA-led position paper on specialized small models](https://arxiv.org/abs/2506.02153).

For future Bash coverage, [NL2Bash](https://github.com/TellinaTool/nl2bash)
provides about 10,000 human-described command pairs, with its data under MIT.
It is an additional training/evaluation source, not a substitute for your Windows
distribution. It is old and public, so frontier pretraining contamination must be
considered before claiming an independent model comparison.

## What the saved log actually contains

The September 6 snapshot has 38,332 total records. Of these, 32,690 contain recovered
command strings, 28,513 command strings are unique, and those records span 815
sessions. 18,892 have explicit exit code zero; 10,844 have no recorded exit code.
The audit flags 864 heuristic hidden failures among recovered commands. 18,517
outputs are exactly 700 characters, the old extractor's cap. The repository's
published 38,176-shell-command headline uses a different inclusion rule.

Those numbers are local measurements of the saved snapshot. They are not a success
benchmark or a count of training-ready pairs. A successful exit does not demonstrate
that the right file, process, or field was inspected. The original extractor also
uses regex heuristics and cannot always associate parallel command results precisely.

The new supplementary pass recovers 10,200 native completed-command records from
107 pre-September-7 Codex sessions. 5,964 have more than 700 output characters.
It retains source pointers and records local extraction truncation separately from
detected source truncation. It does not cover older transcript formats, and preceding
assistant context remains an unverified candidate intent.

## What would make a 20x claim fair

Measure from a frontier request for an operation to the same useful evidence being
available for its next decision. Include intent generation, input/prefill, dispatch,
local generation, validation, shell startup, the command, extraction, and fallbacks.
Report cold-start separately and warm p50/p95 over repeated, identical cases. Keep
accuracy and coverage visible alongside latency. Different quantization and model
thinking settings must be named.

If a local operation takes 1 second end-to-end, a 20x claim requires the comparable
frontier operation to take at least 20 seconds at the same quality. That can happen
on some long, verbose workflows; it cannot be inferred for every short command.
If an unchanged subprocess consumes 10% of the original time, even eliminating all
model overhead only gives a 10x whole-operation ceiling. The 20x goal is most plausible
for replacing substantial model-side planning/output work, or eliminating repeated
round trips. It is not a way to speed up the underlying build by 20x.

Token savings also need two ledgers: frontier tokens avoided and extra local work.
The frontier still writes an intent and reads a result. A 99% reduction is possible
for a sufficiently noisy log, but must retain all requested evidence, errors, exit
status, and incompleteness information. The present fixture measurement is smaller
and should not be extrapolated to 99% of real outputs being useless.

## Decision after the pilot

Keep the lowest-latency candidate that meets the accuracy target, including plain
code where it wins. Expand the real, session-separated labeled set before training
at scale. Then compare a named frontier endpoint and the local specialist under the
same host interface. Do not use this synthetic test as the production acceptance
gate, and do not publish a SOTA claim without a properly held-out comparison.
