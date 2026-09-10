# Static recovery and the smaller-model experiment

Measured locally on September 9–10, 2026, on Windows with a Ryzen 9 3900X,
64 GB RAM, and RTX 3070 8 GB. Private artifacts remain under ignored
`work/command-specialist/`. The earlier ingestion results are in [DATA_RESULTS.md](DATA_RESULTS.md).

## Recovering more usable structure

The frozen corpus still contains 70,611 command observations, divided into
21,183 training, 7,061 development, 35,306 expansion-reserve, and 7,061 final-test
observations. These remain review partitions, not a certified independent benchmark.
This experiment derives examples only from the assigned training sessions and
training observations. The split is unchanged.

| Stage | Observed result | Measured wall time |
|---|---|---:|
| JavaScript static recovery | 8,722 code units; 8,699 parsed, 23 parse errors; 8,565 command candidates | 8.37 s |
| Acorn parsing subprocess within that stage | Same code units | 0.885 s |
| PowerShell static read recovery | 5,687 distinct input command strings; 5,653 parsed, 34 parse errors; 3,886 bounded read candidates | 13.83 s |
| PowerShell parsing subprocess within that stage | Same input strings | 8.89 s |
| Read fixture verification | 800/800 passed | 2.00 s including comparison/report overhead |
| Additional operation verification | 81 cases, 162/162 native/PowerShell checks | 1.31 s |

Of the JavaScript candidates, 7,829 have identical command text in an existing
training observation from the same session. This is a reconciliation lead, not
proof that that particular call ran. Another 736 lack that match. There are 35
candidates with dynamic environment fields and 16 inside control-flow/function
contexts. The parser abstains on 193 dynamic/missing commands and two objects with
spreads, computed properties, or accessors. None becomes a historical success label.

The first complete recovery took 57.99 seconds. Skipping 478 source snapshots
outside the training scope reduced it to 8.37 seconds, a 6.93× observed ratio.
The decompressed candidate artifacts have identical SHA-256 hashes. An intermediate
optimization incorrectly skipped mixed-session source files and lost 125 code
units; it was rejected. The final implementation checks training artifact membership
as well as the first session header, and a mixed-session regression test protects it.
These are single local timing runs with cache/order effects, not a controlled CPU
microbenchmark or a claim of 100× total labeling speed.

The 96 direct candidates plus 3,886 AST candidates cover 130 distinct read
operation/count pairs. Three generated instructions per pair produce 390 synthetic
examples, compared with the previous 96 examples from 32 pairs. Requests and fixture
paths are generated. Historical task intent and execution correctness remain unknown.

The broader verifier found five listing failures: PowerShell's filesystem `-Filter`
uses matching behavior different from the native simple glob. The compiler now
filters file names with `-like`; tests check `*.*`, `a?.txt`, and nonrecursive listing
through the actual compiler/executor. Search and JSON cases cover literal regex
metacharacters, quotes, dollar signs, Unicode, no matches, missing keys, arrays,
objects, null, and keys containing dots. This is bounded fixture parity, not complete
PowerShell emulation.

## Reproducible training boundary

The expanded dataset contains 810 examples: 420 synthetic pilot examples
(300 plans and 120 evidence selections) plus 390 verified read derivatives.
The original pilot's 66 historical derivatives are excluded because they used an
older session split. No development, expansion-reserve, or final-test observations
enter this new training dataset. The preparer verifies the frozen training hash,
verified export hash, case counts, and unique example identities before writing a
new output directory.

Training uses the official [Qwen2.5-Coder-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-Coder-0.5B-Instruct)
base, response-only LoRA, and the existing training script. The model card specifies
Apache 2.0 licensing and approximately 0.49 billion parameters. Model weights and
adapters stay local. The existing trained 1.5B pilot remains the default until the
smaller candidate demonstrates sufficient accuracy.

The original synthetic pilot evaluation has been inspected in earlier experiments.
It is a useful regression comparison, not the new corpus's frozen final 10% and not
an independent SOTA benchmark. Comparing the new 0.5B adapter with the old 1.5B
adapter changes both model size and training data. The untrained-versus-trained
0.5B comparison isolates fine-tuning on the same base, with the same evaluation
requests, contract, fixture execution, and local inference settings.

## What the measurements imply

The largest measured data-preparation gain so far comes from amortizing PowerShell
startup across 800 checks: the previous 16-case fresh-process comparison yielded
392× per-case throughput. That does not include finding a trustworthy historical
intent, building the verifier, or correcting a label. Static parsing adds coverage
without asking a frontier model to label every line, but it cannot certify intent.

Rust is not yet justified by these measurements. The existing trained 1.5B native
pilot spends about 179.7 ms in inference and 1.12 ms in the remaining wrapper at a
roughly 181 ms planning median. Even eliminating that wrapper entirely saves under
1% of that operation. Typed inputs that bypass generation, reusable process hosts,
deterministic extraction for explicit requests, and preventing unnecessary output
from being produced offer larger opportunities. A Rust implementation should follow
a measured throughput or memory bottleneck, with the same correctness contract.

No frontier endpoint has been benchmarked here, no API charges were incurred by
these local experiments, and neither 20× whole-operation latency nor 100× complete
labeling efficiency has been demonstrated.

## Local evidence

The final recovery artifacts are `code-recovery-checked`, `read-recovery-checked`,
`verified-expanded-reads`, and `more-operations-final` beneath the private work root.
`code-recovery-checked/lossless-comparison.json` records byte-equivalent recovery.
`halfb-data/manifest.json` records the dataset composition and hashes.
Intermediate failure artifacts are retained separately and are not promoted.

Frozen training SHA-256:
`f7eaef4e338bd1ffd5291f12b62569c394123e418ec2cbe22eaacc5b7d4e0bb2`.
Expanded SFT SHA-256:
`e563c41917cbfef2bc8f9446f2b636bc644729b88636bd9cec7b5eb4c9a2a403`.

## Completed adapter comparison

The expanded 810-example run completed on the 0.5B model in 983.28 seconds,
with 4.08GB peak allocated CUDA memory. The 1.5B baseline still uses its original
486-example adapter. On the original pilot, the trained 0.5B passed 32/40 plans
and 15/16 evidence selections; the current 1.5B run passed 40/40 and 15/16.
Median native planning-operation times were 140.9ms and 176.5ms respectively.
These models differ in both size and training data, so this is not an isolated
model-size experiment or evidence that the 810-example dataset is worse.

The separate opaque-filename probe gave 16/40 for trained 0.5B and 29/40 for
trained 1.5B. Both chose the correct operation/count in all forty cases; the
failures involved path copying. The follow-up [binding experiment](BINDING_RESULTS.md)
removes exact path regeneration from the model's output contract and measures
that change on a new paired dataset. The default remains the trained 1.5B pilot.
