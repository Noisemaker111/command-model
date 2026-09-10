# English handoff contract (prototype v1)

Read [project purpose and evidence](PURPOSE.md) for the distinction between
the trained inspection adapter, the English runtime and measured frontier results.
This document describes its named prototype or historical experiment, not general
command-execution reliability.

A frontier supplies one English task, exact target bindings, relevant runtime/API
context, constraints, and an observable completion condition. The frontier does
not supply generated source, escaped shell strings, or a command sequence.
Missing target/API context is a context failure, not evidence of model incapacity.

Each invocation creates a fresh worker message history and unique evidence directory.
It retains internal action/result history only for this delegation. It returns one
packet, never recursively delegates, and never resumes a previous local chat.
Ollama may keep model weights warm; that is not conversation persistence.

The worker chooses compact typed actions. Premature finish is rejected with observed failure feedback. A write action requests raw file content
in a separate inference rather than putting a program inside a JSON string. Source generation receives an English view of the same task, saved source and actual last execution result; JSON action history stays in the selector. Native
write/read/process operations preserve exact target bindings. Actual execution
feedback goes back to the same worker for ordinary repair. This split is an
experimental baseline, not a measured superiority claim.

The result distinguishes worker explanation from observed actions, saved files,
SHA-256 identities, exit codes, verbatim stdout/stderr and raw model responses.
Only a runtime-checked completion condition can set `verified`. A generated file,
`finish`, or exit zero alone cannot. A run must execute the same bytes that were
written and remain saved, exit zero without a limit violation, and match the
required stdout exactly, including platform newlines (Windows print uses `\r\n`). The worker must also finish within its action budget.
This verifies the stated stdout condition, not arbitrary semantic correctness.

## Minimal local CLI

From the repository root, invoke Python 3.12:

```
python experiments/command_model/delegate.py --task-file task.json --root scratch --allow-execute
```

Example handoff (scratch must already exist):

```json
{
  "task": "Write a Python program that calculates the sum of integers 1 through 10. Run it, inspect the actual output, then finish.",
  "targets": {"program": "sum.py"},
  "context": "Python 3.12; standard library only.",
  "constraints": ["Modify only the bound program target"],
  "completion": {"target": "program", "stdout": "55\r\n"}
}
```

This CLI supports trusted Python write/read/run tasks only. `--allow-execute`
explicitly authorizes native generated code with the caller's account privileges;
path binding constrains direct adapter operations, not Python's capabilities.
Natural-language constraints are model instructions, not a security sandbox.
Use disposable data. The CLI is not registered as a new host tool. A future host
adapter must use its native capabilities, session identity, hooks, instructions,
permissions and cancellation. CLI authorization does not substitute for those.
A missing authorization terminates as denied before model or native actions; no
alternate executor or model is attempted.

Default bounds: 12 actions, 300 seconds for model/operation work, 20 seconds per
execution, 8192 output tokens per inference, 32768 context tokens, and 64 KiB
execution output. Execution output is spooled to per-action files and monitored;
limit detection can overshoot between polls, and raw files preserve that evidence.
Model HTTP timeout bounds the client's wait; it does not prove server inference
was cancelled. Process cleanup and final persistence can exceed the work deadline.
Ctrl-C terminates the running process tree and saves a cancelled result. Generated
programs that detach children are outside this trusted prototype's lifecycle
coverage. No concurrent benchmark or shared model setting change is implied.

Raw artifacts are saved before execution and after each observation, with atomic
replacement of `result.json`. Abrupt host termination may leave status `running`;
never interpret that as success. The packet provides the artifact path. Reopen it
and the actual target to check persistence. Failure, exhausted budgets, unavailable
worker and denial preserve distinct statuses and do not silently fall back.

## Representative PTY handoff (next stage)

The full contract must accommodate this without the frontier writing code:

> Write and run the bound checker using node-pty. Launch Bun on the exact recorder
> path with inherited environment and working directory, a 100x24 xterm-256color
> PTY, and a normalized absolute script path. Observe the diagnostic banner, send
> Escape once after startup, and report actual cancellation and child exit status.
> Scope: Startup/cancel only; no physical-key evidence generated.

The frontier supplies checker and recorder bindings, the actual banner/cancel
markers and concise node-pty API context. Completion requires observations from
the real recorder and reopened saved report, not a replacement printing markers.
This Python-only prototype cannot yet perform that workload or provide full
host-native per-command permissions. Configured frontier return integration has
been exercised separately through the [Codex MCP prototype](codex/RESULTS.md). The earlier file adapter
remains separate pending a verified replacement; its result is not proof of
English delegation.

## Non-quantized runtime and capacity

The English loop requires `shell-specialist-f16`: the original local
Qwen2.5-Coder-1.5B-Instruct weights exported as FP16 with the unchanged pilot LoRA
adapter. It checks Ollama model metadata before inference and rejects quantized
or unknown precision. FP16 is non-quantized 16-bit floating point, not FP32.
The old Q4 pilot remains installed for historical reproducibility but is not used
by this loop. No retraining or change to the trained adapter is involved.

`--num-ctx 32768 --num-predict 8192 --seconds 300 --max-actions 12` are explicit
CLI controls and the defaults. The context window includes history and generated
output. A conservative UTF-8 byte upper bound plus per-message overhead reserves
the output allowance; oversized history fails instead of intentionally truncating
instructions. This can reject text before the model's token capacity is actually
full. Exact tokenizer budgeting is future work. Increasing output is permission
to generate more, not a minimum response length. Long-context reliability has not
been established by short task smokes.

For a local runtime setup, use the existing llama.cpp `convert_hf_to_gguf.py` on
the original local base snapshot with `--outtype f16`. Import that GGUF with the
existing pilot's exact `ADAPTER` and chat template under `shell-specialist-f16`
using `ollama create`; do not pass a quantization option. Verify `ollama show`
reports F16 and compare the adapter identity. The tested machine's BF16 GGUF import
failed validation, while FP16 succeeded. Weights and setup logs stay private.
