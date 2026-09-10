# Configured Codex hookup observations

Read [project purpose and evidence](../PURPOSE.md) for the distinction between
the trained inspection adapter, the English runtime and measured frontier results.
This document describes its named prototype or historical experiment, not general
command-execution reliability.

September 10, 2026. These are development hookup smokes, not a frozen benchmark.
The frontier was the installed Codex CLI with its existing ChatGPT login,
`gpt-6-astra`, low reasoning, normal user configuration and workspace-write with
automatic approval review. Each operation ran in a separately persisted fresh chat
and fresh Git workspace. No global Codex configuration was changed.

The successful delegated CSV operation was observed through the configured real
MCP host: Codex sent one English `run_python_task` call, the FP16 worker returned
verified output, and the originating frontier turn reported it. The saved script,
raw events, local evidence and evaluator outputs were reopened. Original and
alternate-input checks passed for both the normal-shell and delegated programs.

| Observation | Normal shell | English delegation |
| --- | ---: | ---: |
| Whole Codex process through final result | 71.075 s | 43.118 s |
| Frontier input tokens | 154426 | 95506 |
| Cached frontier input tokens | 131456 | 82944 |
| Frontier output tokens | 995 | 486 |
| Local input / output tokens | 0 / 0 | 4454 / 181 |
| Native command calls | 6 | 1 |
| Local English handoffs | 0 | 1 |
| Original and changed-input correctness | pass | pass |

One pair showed lower elapsed time and frontier usage for delegation. It does not
establish expected savings: startup, permission handling, cache state, repeated
runs and task diversity are not controlled sufficiently here. Native baseline
Python access needed sandbox recovery; both chats encountered an inaccessible
shell skill. Configured unrelated Cloudflare authentication also logged an error.
These are real host costs in this smoke, not costs to attribute to the local model.
Local inference/execution consumed 2.813 seconds inside the 43.118-second handoff.
Do not quote local duration as end-to-end latency or infer dollar charges.

Earlier hookup failures are retained privately: the first worker stalled before
artifact initialization and was terminated; using the base stdlib interpreter
without SDK site startup and inherited protocol stdin allowed the next run to
execute. That next run returned an honest exhausted result because source generation
had not received the exact completion stdout. The worker printed `Total: 74.95`
and failed the required exact output. Passing the completion condition into the
source-generation context fixed that context omission. Multiple setup revisions
were involved, so failed and successful runs are not one pooled benchmark series.

Raw artifacts remain in ignored `work/codex-bench`. A separate user workspace is
prepared for interactive testing; the Codex desktop UI itself was not operated.
General shell replacement, host-native per-command permissions, the real PTY
recorder, broad accuracy and statistically supported speedups remain unverified.

A second configured-host operation repaired the existing NameError in one English
handoff with no native frontier commands. Original and alternate inputs passed;
whole Codex time was 32.075 seconds, frontier input/output 69912/348 tokens, local
input/output 4457/173 tokens, and local time 2.765 seconds. No paired repair baseline
was run, so this is additional hookup/repair evidence, not a savings comparison.
