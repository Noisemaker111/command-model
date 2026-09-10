# Ten-stage incident packet pilot

Read [project purpose and evidence](../PURPOSE.md) for the distinction between
the trained inspection adapter, the English runtime and measured frontier results.
This document describes its named prototype or historical experiment, not general
command-execution reliability.

September 10, 2026. Three sequential fresh Codex CLI sessions used gpt-6-astra,
low effort, existing login/configuration and normal approval review. Local workers
used shell-specialist-f16 with the unchanged pilot adapter, 32768 context, 8192
output allowance and one fresh bounded process/history per handoff. No quantized
model or retraining was introduced. This is one observation per arm, not a
statistical benchmark or a claim about general command work.

Eight recent local chat transcripts contained 78 shell-tool events. Aggregate
patterns included reading files, inventory, log search, JSON processing, Git
state, validation, saved evidence, path handling and table data. Those patterns
informed ten synthetic stages; no transcript text or real project data appears
in the fixture. Private source hashes/provenance and raw events remain local.

| Strategy | Handoffs | Native calls | Whole chat | Correct original stages | Correct alternate stages |
| --- | ---: | ---: | ---: | ---: | ---: |
| Normal Codex shell | 0 | 5 | 93.998 s | 10/10 | 10/10 |
| One handoff per stage | 10 | 0 | 200.381 s | 0/10 | 0/10 |
| Two groups of five | 2 | 0 | 156.575 s | 0/10 | 0/10 |

The baseline could batch efficiently and implemented one script. All ten stages
were known at session start, with later stages consuming earlier outputs. This
is not ten independently arising requests, nor ten forced native commands.
Whole-chat timing includes startup, instruction/tool discovery, approval, model
work, execution and frontier completion. Independent original/alternate artifact
assessment runs afterward and is excluded from that timing. Input bytes stayed
unchanged in all three arms. Source and fixture hashes matched across the series.

| Strategy | Frontier input | Cached input (included) | Uncached input | Frontier output | Local input / output |
| --- | ---: | ---: | ---: | ---: | ---: |
| Normal shell | 136130 | 123776 | 12354 | 2134 | 0 / 0 |
| Ten handoffs | 330385 | 310272 | 20113 | 2425 | 215216 / 4117 |
| Two handoffs | 254899 | 239360 | 15539 | 1588 | 92908 / 7417 |

Input totals accumulate across model requests; they are not a single context
window size. Cached input is already included in input. These are observed token
counts, not actual dollar charges. Two handoffs used 25.6% fewer frontier output
tokens than baseline, but more input tokens and failed the task; that is not a
successful-task efficiency improvement.

Ten handoffs made 151 local model calls and recorded ten failed executions.
Nine workers exhausted their limits. The one execution-verified worker only
printed its expected marker and created no requested JSON. The external oracle
rejected it. The first stage wrote a non-JSON inventory; later outputs were
missing. Two grouped workers made 32 model calls and seven failed executions;
one exhausted its limits and one failed. Detailed actions and stderr remain in
local result artifacts. Dependent failures are not independent model trials.

| Strategy | Observed tool span union | Local worker time within spans | Outside observed tool spans |
| --- | ---: | ---: | ---: |
| Normal shell | 8.841 s | 0 s | 85.157 s |
| Ten handoffs | 98.306 s | 64.983 s | 102.075 s |
| Two handoffs | 100.688 s | 87.937 s | 55.887 s |

Tool spans use event arrival timestamps. Outside-span time includes startup and
frontier work, not exclusively model inference. Removing all observed local
worker time, while holding every other cost fixed, leaves 135.398 s for ten
handoffs and 68.638 s for two. The latter is arithmetically 25.360 s below the
baseline, but both underlying runs failed. Neither number estimates an accurate
implementation or a global best possible saving. Correct repair, different
handoff boundaries and frontier behavior would change the timings.

The experiment establishes that ten fresh lifecycles can be chained through the
real host, with saved results returned to the frontier. It does not establish
reliable task completion or time savings. Correctness and useful artifact-level
completion checks are the next bottlenecks. Grouping appears worth investigating,
but faster inference alone does not fix incorrect programs or redundant handoffs.

An earlier 134.725 s baseline preflight also passed all twenty artifact checks.
Its original summary falsely flagged an input change because the collector used
Windows default decoding for a Unicode filename. Explicit UTF-8 decoding fixed
the collector; a separate correction artifact preserves the original evidence.
The preflight lacked the supplied interpreter context and is excluded above.

Reproduce with the three ten_step.py arms and compare_ten.py documented in
README.md. Repeat successful matched runs in alternating order before estimating
typical latency or savings. No raw chat logs, generated worker programs, private
machine paths or model weights belong in this report's public source.
