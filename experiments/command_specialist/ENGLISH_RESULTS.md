# English loop observations — September 10, 2026

The standalone public CLI now accepts one English handoff and returns a saved,
runtime-verified result from a fresh local worker. This is step 1/2 of the handoff
plan, not configured OpenCode2 delegation or the representative PTY recorder test.

The active runtime is non-quantized FP16 Qwen2.5-Coder 1.5B with the original pilot
adapter. Original BF16 training weights were available; BF16 GGUF import failed
Ollama validation, while FP16 import succeeded. `ollama show` reported F16 and
`ollama ps` reported 32768 context, 4.2 GB and 100% GPU on the RTX 3070. These are
runtime observations, not peak memory measurements. The original Q4 model is not
used by the new loop. No retraining occurred.

## Actual public operations

All model calls used local Ollama, 32768 context and an 8192 output-token cap,
12 actions and a 300-second worker budget. Private task/result files and raw model
responses are retained under the owned worktree's ignored `work/` directory.

- Fresh sum program: actual missing-file exit 2, local source generation/write,
  rerun exit 0 with `55`, then finish. Saved source computes the sum. 2.235 seconds.
- Fresh sum-of-squares program with Unicode and an apostrophe in its exact path:
  missing-file exit 2, write, rerun exit 0 with `140`, finish. 2.343 seconds.
- Existing broken program: actual `NameError` for `valuez`, local correction to
  `values`, rerun exit 0 with `16`, finish. 1.594 seconds.
- Final-revision fresh squares target: exit 2, write, exit 0 with `140`, finish.
  2.843 seconds. This includes the corrected source newline handling.
- Without execution authorization: denied before any model/action call.
- One-action budget: exhausted and unverified even though the existing program
  exited zero with the expected stdout.

Times are individual whole CLI-worker measurements including inference, native
operations and persistence, not p50/p95, a speedup claim, or paid charges. They
exclude frontier conversation overhead. Every successful result and saved source
was reopened; recorded precision, action exits and source identity were checked.

## Failures that informed the implementation

The initial Q4 probe repeatedly ran a missing file. A first FP16 prompt generated
correct source but repeatedly copied a write example. Removing that example let
actions advance, but JSON action history contaminated source generation: one
output was a task-shaped dictionary that executed with empty stdout. The runtime
correctly refused success. English-only source-generation context containing the
same task, saved source and actual execution feedback yielded the successful runs.
Multiple variables changed; these observations do not isolate quantization effects.

Action selection still wastes a run on absent files, and final worker explanations
are weak (often just the filename). Deterministic evidence verification is needed.
The model has not demonstrated broad English task reliability or long-context
reasoning. An 8K output cap is configured; these short samples did not use 8K tokens.

Required compileall and both existing five-test suites passed. Three new concise
invariant tests passed for denial/fresh histories, exact target boundaries, and
verification against actual executed/saved bytes. They supplement the real runs.
Host hooks/permissions, PTY startup/cancel, detached child cleanup, and external
frontier delivery remain unverified. No host registration or global installation
was changed by this prototype.
