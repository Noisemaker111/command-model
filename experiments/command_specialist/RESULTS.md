# First local pilot: September 9, 2026

Training improved the narrow contract substantially. It did not establish superiority
to a frontier model, 20x whole-agent speed, or production reliability.

## Measured local results

| Model / backend | Command results | Exact evidence sets | Median command operation | Median evidence operation |
|---|---:|---:|---:|---:|
| Qwen2.5-Coder 1.5B, untrained, PowerShell | 28/40 | 0/16 | 1,070 ms | 630 ms |
| Qwen3.5 0.8B, untrained, PowerShell | 26/40 | 0/16 | 1,244 ms | 1,070 ms |
| Qwen2.5-Coder 1.5B + trained adapter, PowerShell | 40/40 | 15/16 | 1,085 ms | 193 ms |
| Same trained adapter, direct file operations | 40/40 | 16/16 | 181 ms | 151 ms |
| Existing Qwen3 8B, untrained, direct file operations | 40/40 | 12/16 | 408 ms | 490 ms |
| Plain-code structured-log filter | Not a planner | 16/16 | Not applicable | 0.027 ms |

The native file backend avoids launching PowerShell for each of the five supported
operations. Its results were still checked against actual PowerShell reference
commands. This yielded roughly 6x lower median local command-operation time than
the trained PowerShell run. It is an executor improvement, not a 6x increase in
model generation speed or a claim about arbitrary shell commands.

Against the already-installed 8B local model using the same native backend, the
specialist matched command correctness, returned more exact evidence sets on this
pilot, and had about 2.3x lower median command-operation time. The 8B model is a
larger local reference, not a current frontier/SOTA comparator.

The evidence model call is unchanged between the two trained runs. One run missed
an exact evidence set; the repeat passed it. Do not attribute that accuracy change
to the file backend, discard the failure, or interpret temperature zero as a
guarantee of identical results. These small scores are observations, not an
estimated real-world reliability rate.

The separate historical-session holdout passed 20/20 read operations, at a median
222 ms using direct file operations. Its commands came from sessions excluded from
training, but its request descriptions and file contents were synthesized. It is
not a test of full historical task reproduction.

## Conditions

AMD Ryzen 9 3900X, 64 GB system RAM, RTX 3070 with 8 GB VRAM, Windows, Ollama 0.33.3.
The 1.5B baseline is Q4_K_M and the 0.8B baseline is Q8_0. The adapter is applied to
the same Q4_K_M coder base as its baseline. Models ran sequentially with thinking
disabled, temperature zero, a fixed seed, 4,096 context tokens, and at most 160 output
tokens. This was a normal workstation, not an exclusively reserved benchmark host.

Times start with an already-written intent and end with its local result. They
include model requests, validation, execution, and extraction. They exclude the
reference command used by the evaluator, the frontier's creation of the intent,
and the frontier's subsequent response. Single CLI process startup is outside
the in-process benchmark timing. A separate actual CLI smoke operation returned
the expected last three lines, recorded 387 ms inside the runner, and its saved
raw result was reloaded and checked.

Initial warm-ups took 65.1 seconds for the coder baseline, 49.4 seconds for the 0.8B,
and 14.0 seconds for the newly loaded trained model. These included model/runtime
initialization and are recorded separately; the table shows warm-request medians.
The warmed native run's command p95 was 213 ms. Those initial warm-ups are not
a controlled cold-start comparison.

The existing 8B model's initial warm-up was 7.3 seconds. Its native command p95 was
558 ms. Model initialization conditions differ across these sequential runs.

## Training and data

486 examples, two epochs, 244 optimizer steps, 4,358,144 trainable adapter parameters.
Training took 560.1 seconds (9 minutes 20 seconds) and peaked at 5.86 GiB of CUDA
tensor allocation, excluding other applications and non-PyTorch GPU allocations.
The BF16 base was frozen. Only rank-16 attention adapters were trained. The saved
Safetensors adapter is 17.5 MB; its F16 GGUF conversion is 8.7 MB. Ollama reports
the local base-plus-adapter model at approximately 994 MB of model files, not total
runtime memory.

420 training examples are synthetic fixtures; 66 derive from conservatively mined
historical read commands with generated requests. The frozen synthetic test has
40 planning and 16 extraction cases. Operations and log families overlap training;
test paths, wording, and contents differ. No test case was used for loss or checkpoint
selection. Training loss is not used as proof of task correctness.

The saved historical audit contains 32,690 recovered command strings in 38,332 total
records. The supplementary native-event recovery contains 10,200 records, with
5,964 outputs longer than 700 characters. Their median recorded output length is
1,239 characters and p95 is 28,189. These measure volume, not how much was irrelevant.

## Output reduction

The deterministic filter preserved all required fixture evidence and reduced
12,324 raw-output tokens to 979 compact-result tokens: 92.1%. These counts use the
Qwen2.5-Coder tokenizer, not a frontier provider's billing tokenizer. The trained
model's first run reduced tokens by 91.8% on its 15 successful extraction cases;
that conditional reduction excludes its failed case and is not a reliability claim.
Exit codes and truncation flags are retained in the result packet. Full raw results
remain retrievable locally.

The immediate recommendation is a hybrid: direct operations and structured parsers
for known formats, with the trained model interpreting the request and handling
context-dependent evidence selection. The plain-code filter already wins on this
predictable log family, so paying even local model latency for those cases is unnecessary.

## Remaining acceptance work

The pilot does not cover unrestricted command generation, Bash, mutation, repair
loops, unknown tools, calibrated abstention, or actual host integration. It has no
matched frontier-model run or measured provider charges. Expand the independently
labeled real-task set and compare a named frontier endpoint before making a SOTA,
20x, cost-saving, or deployment-readiness claim.

Raw datasets, predictions, model weights, and per-run reports remain in the ignored
local work directory. This report publishes aggregate experimental results only.
