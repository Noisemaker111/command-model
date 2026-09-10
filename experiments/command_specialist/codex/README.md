# Codex English-delegation hookup

Read [project purpose and evidence](../PURPOSE.md) for the distinction between
the trained inspection adapter, the English runtime and measured frontier results.
This document describes its named prototype or historical experiment, not general
command-execution reliability.

This connects the local FP16 worker to a **fresh Codex chat**, and captures a
comparison against Codex using its normal shell/file tools. It does not compare
two local models. It is a Windows, trusted-workspace Python-task prototype.

## Start a separate chat

Install into an isolated Python 3.12 environment:

```
python -m pip install -r experiments/command_specialist/codex/requirements.txt
python experiments/command_specialist/codex/bench.py prepare --case csv --arm delegated
```

Open the printed directory's `workspace` folder as a project in Codex, start a
fresh chat, and send the text from the adjacent `prompt.txt`. The project-local
`.codex/config.toml` connects `command_specialist.run_python_task`. Trust that
specific project when Codex requests it. The tool executes generated Python with
the account's privileges, so approve only the intended trusted fixture operation.
No global configuration is edited. Desktop tool loading must be verified in the
new chat; CLI connection evidence is not a claim that the desktop UI was exercised.

The tool takes English intent, an exact target, context, constraints and the
completion condition. It starts a new process/history per delegation and returns
verified observations and raw evidence to the originating Codex turn. Python
worker startup uses the base interpreter without site initialization, separate
from the MCP SDK's environment. Failed workers never change model or executor.
Cancellation terminates the worker process tree; an abruptly cancelled artifact
may remain marked running and must never be treated as success.

## Measure through real Codex chats

Run each arm separately (never concurrently) using the same model and effort:

```
python experiments/command_specialist/codex/bench.py run --case csv --arm baseline --model gpt-6-astra --effort low
python experiments/command_specialist/codex/bench.py run --case csv --arm delegated --model gpt-6-astra --effort low
```

`repair` is a second case with an actual broken program. Each run creates an
independent Git workspace and persisted Codex session, preserves normal user
configuration/rules, and uses automatic approval review with workspace-write.
It never disables sandboxing or hook trust. It uses the existing Codex login;
no API key is introduced and no dollar charge is inferred from token counts.

The adjacent `events.jsonl` is the actual `codex exec --json` stream.
`final.txt` is the frontier's final response, `run.json` contains timing/config,
and `summary.json` contains observed usage and independent accuracy checks.
The first `thread.started` event identifies the saved chat for `codex resume`.
Opening/resuming it after measurement is allowed, but that interaction is not part
of the completed measured turn. A desktop conversation without captured events
must not be assigned CLI token/timing figures.

Create a comparison from the two saved summaries:

```
python experiments/command_specialist/codex/compare.py BASELINE/summary.json DELEGATED/summary.json --out work/comparison.json
```

The runner checks the saved program on the original input and an alternate input,
then restores the original fixture. This detects hardcoded expected output. It
records failed local actions and requires the delegated worker to report verified
completion. The baseline writes/runs with native tools. The delegated arm submits
English once; fallback is not silently counted as local success.

Measure whole process startup through frontier completion, including discovery,
permission handling, native commands, local inference/repair and persistence.
Report input, cached input, uncached input, output and local tokens separately.
Model generation time alone is not the user operation. Configured plugins and
existing instruction overhead remain part of this realistic first comparison.
The independent evaluator runs after the timed chat and is not in chat latency.

One pair is a hookup smoke, **not evidence of general savings**. For benchmark
claims, freeze source/config/tasks, alternate AB/BA order, repeat matched pairs,
include failures/denials and multiple task sizes, separate model cold/warm state,
and report success plus p50/p95 with sufficient samples. Current fixtures are
development smoke tasks, not a frozen final test or a broad command benchmark.
Do not edit the harness mid-series and pool measurements as one experiment.

## Boundary still open

This is an explicit MCP operation with its own fixed workspace and trusted-code
execution permission. It does not intercept or replace Codex's native shell, and
its internal Python actions do not inherit all native shell resource checks.
It is not general arbitrary-shell delegation or the actual PTY recorder workload.
The old OpenCode2 inspection adapter is unrelated. The local 1.5B specialist can
fail; keep those results and frontier recovery cost visible.


## Ten-stage continuous session

Run `ten_step.py run --arm baseline`, then `--arm chained`, then `--arm grouped`
from the repository root with the MCP-enabled Python environment. Never run the
arms concurrently. `prepare` creates a fixture and prompt for manual use in a new
Codex chat instead. The same ten-stage synthetic incident packet covers inventory,
logs, configuration differences, tests, changed paths, command durations, failure
details, a combined summary and a SHA-256 manifest. Later stages consume earlier
outputs. No private transcript text is used in fixture data.

Baseline may batch all work in one script and choose its own native call count.
Chained requests ten serial English handoffs, each with a new local process and
history. Grouped requests two handoffs of five stages. This tests ten mechanical
steps known at the start of one session; it does not force ten frontier decisions
or simulate discoveries that were unavailable in the original prompt.

All arms get the installed interpreter path. The runner preserves ordinary host
startup, instructions, tool discovery and approval costs. The current loop uses
the nonquantized FP16 specialist, not a new model or trained adapter. Each local
worker has its existing action/time limits. Failures are retained without silent
native fallback. A success marker alone is insufficient: the external evaluator
reopens every saved JSON and checks the content and manifest, then reruns the
saved scripts on changed inputs in a separate directory. All twenty checks, input
integrity, expected handoff count, and local completion must pass. External
assessment is outside the timed chat. These scripts are trusted local code, not
sandboxed by the harness.

Compare saved runs with:

```
python experiments/command_specialist/codex/compare_ten.py BASELINE/summary.json CHAINED/summary.json GROUPED/summary.json --out work/ten-stage-comparison.json
```

Keep each summary beside its original run.json and fixture.json. Savings require
successful runs with matching source hashes, input hashes, model and effort.
Token usage separates cached and uncached frontier input, frontier output, and
local model input/output. It does not estimate actual charges. event-times.jsonl
records arrival timestamps for raw events; the union of started/completed tool
spans avoids double counting overlap. Time outside those spans includes startup
and frontier work and must not be labeled entirely model inference.

Subtracting observed serial local worker time gives a conditional instant-worker
floor with every other cost unchanged. It is not an achievable optimum or a
ceiling on redesigned workflows. Failed arms receive no savings claim. Repeat
successful matched AB/BA series before claiming typical savings; one run per arm
is a pilot that can reveal failure modes and batching effects.
