# Public handoff runtime evaluation

Measured September 10, 2026. The unchanged `shell-specialist-pilot` model is
Qwen2.5-Coder 1.5B Q4_K_M with its existing LoRA adapter. Current checks confirmed
Ollama 0.33.3, RTX 3070 8GB, Ryzen 9 3900X, and GPU execution. Shared Ollama service
configuration, weights, quantization, and adapter were not changed. No deployment
or host integration occurred.

## Outcome

The confirmed bug was unnecessary model selection on empty stdout. In the merged
handoff, both no-match cases generated 160 tokens of nonexistent line numbers,
stopped at the output limit, and fell back with invalid JSON. Deterministic empty
selection fixes those cases and removes the second inference call. Nonempty
evidence still uses the model and is returned verbatim.

The public CLI and callable now expose context/output and evidence/packet window
limits. Defaults remain compatible at 4096/160; 8192/2048 is an opt-in evaluation
profile. Raw artifacts now retain evidence selection/timing, effective settings,
execution timing, stop reasons, and raw model responses. Output-limit planning
failures save diagnostic artifacts and execute nothing. Selection failure keeps
the pre-selection raw artifact. Character-window accounting includes newlines.

## Final paired measurements

Three runs used the same saved 16-case synthetic set across all treatments,
with fresh opaque filenames and two registered candidates per case. All five
operations were included, along with longer caller context, evidence selection,
two empty searches, a character-window overflow, compact-output truncation, and
an escaping target rejected before inference. PowerShell reference outputs were
prepared outside measurement. JSON correctness compares values; other operations
compare actual stdout and exit status. Evidence compares requested source lines
and verbatim text; explicit overflow fallback and invalid-input rejection have
separate expected outcomes. Exact plan text is not the correctness definition.

Each treatment block ran a full-workload warmup and then the same measured cases.
Order was merged/compat/capacity, capacity/compat/merged, then merged/compat/capacity.
Blocks avoid forcing context reload on every case. These are paired by saved case,
with alternating treatment order, not randomized interleaving or independent samples.

| Run | Source/profile | Checks | CLI median ms | CLI p95 ms | Mean generated tokens | Mean prompt ms | Mean decode ms | Weighted decode tokens/s |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | Merged PR2, 4096/160 | 14/16 | 289.6 | 1186.1 | 40.94 | 37.6 | 226.8 | 180.53 |
| 1 | Revised, 4096/160 | 16/16 | 278.6 | 450.3 | 20.94 | 29.9 | 116.1 | 180.31 |
| 1 | Revised, 8192/2048 | 16/16 | 292.7 | 418.8 | 20.94 | 30.4 | 119.3 | 175.57 |
| 2 | Merged PR2, 4096/160 | 14/16 | 289.4 | 1166.3 | 40.94 | 33.1 | 221.8 | 184.58 |
| 2 | Revised, 4096/160 | 16/16 | 287.4 | 438.1 | 20.94 | 29.2 | 119.1 | 175.78 |
| 2 | Revised, 8192/2048 | 16/16 | 283.9 | 419.2 | 20.94 | 28.5 | 117.7 | 177.94 |
| 3 | Merged PR2, 4096/160 | 14/16 | 295.7 | 1191.8 | 40.94 | 36.1 | 225.3 | 181.67 |
| 3 | Revised, 4096/160 | 16/16 | 298.6 | 463.3 | 20.94 | 32.7 | 125.4 | 166.96 |
| 3 | Revised, 8192/2048 | 16/16 | 296.7 | 482.3 | 20.94 | 29.5 | 120.5 | 173.76 |

Whole-handoff time includes Python/CLI startup, task-file reading, binding, model
calls, validation, native execution, real raw-artifact writes, packet output, and
artifact reload. The loopback diagnostic proxy buffers requests/replies in memory;
trace serialization, report writes, and correctness scoring occur after the timer.
Proxy overhead remains included equally. Prompt/decode figures sum both model calls
per handoff, including rejected generations. Means include the pre-inference invalid
case as zero tokens/time. Weighted throughput is total tokens / total decode seconds,
not the arithmetic mean of per-request throughput. No decode improvement is claimed.

Across 48 measured attempts per treatment, execution was correct on all 45 executable
cases and all three invalid cases were rejected. Evidence/fallback checks passed
42/48 for merged code and 48/48 for each revised profile. The six merged failures
were empty-search evidence selection, not wrong execution or filename resolution.
There were no observed execution/evidence regressions. Nonempty evidence selection
passed throughout this set. Each revised arm had six flagged truncations/fallbacks
(three compact-output windows, three oversized selection windows); merged had 12,
including its six selection failures. Fallback means the caller must inspect the
raw artifact; no automated retry or host fallback is installed.

Pooled medians/p95 were 291.2/1186.1 ms merged, 288.0/438.1 ms revised compatibility,
and 290.1/418.8 ms revised capacity. Median differences are small and inconsistent
across runs. The lower tail latency and generation count come from removing the
failed empty-selection calls. With only 16 cases per run, nearest-rank p95 is the
maximum observation; do not generalize it to production. No >5% decode-throughput
win, general reliability claim, or whole-agent speed claim is supported.

## Cache conditions and capacity checks

The initial unchanged public-CLI smoke returned the correct execution and selected
error/summary lines; its raw artifact was reopened. It took 2379.4 ms including
2001.4 ms model load. This is a cold-load observation, not a warm baseline.

The final paired table reports warmed repeated workloads. First traversal blocks
were retained separately: median 299.3 ms merged, 284.0 ms compatibility, and
299.2 ms capacity; largest load times were 2866.9, 5.9, and 2891.4 ms respectively.
These are not controlled cold-cache comparisons: context changes can reload the
runner, later arms reuse prompts, and fresh filenames become short references.
No shared-service unload/cache reset was performed. Novel real-world prompt and
cold-start performance remain unestablished.

Separate final-source public-CLI probes (not pooled into the paired table):

- 100 error lines: the 160-token selection cap was reached and flagged; raw stdout
  survived. At 2048, all 100 source lines were selected verbatim using 296 tokens.
- Longer caller context: Ollama reported 5187 prompt tokens at context 8192; actual
  execution and requested error/summary evidence were correct.
- A two-line evidence window omitted the third-line summary with `truncated: true`
  and raw-result fallback. A five-character evidence window skipped selection.
- A five-character packet window returned the prefix, flagged truncation, and kept
  complete raw stdout. A one-token planning cap exited nonzero, saved the raw model
  reply/stop reason, and executed nothing. Zero context was rejected before inference.
- The final public CLI also passed through the actual PowerShell backend, with
  readable bound paths, source lines 2/3, and the saved output reopened.

These probes demonstrate particular capacities, not that arbitrary prompts fit.
Character windows are not token counts; the pilot does not detect all server-side
prompt truncation. The 100-line operation contract remains. Larger context alone
does not enlarge selection windows. Unexpected provider/network error recovery and
arbitrary Unicode/JSON equivalence beyond the existing pilot remain unproven.

## Evidence and reproduction

Local evidence remains under this task worktree in `work/runtime-final/`:
`evaluate.py`, immutable `source-before/` and `source-after/`, `manifest.json`,
saved tasks/fixtures and PowerShell references, all 288 warmup/measured records,
per-operation raw artifacts and buffered wire traces, `summary.json`, and nine
CLI probes under `probes/`. SHA-256 source/input checks passed after measurement;
the four executed production modules match the final worktree byte-for-byte.
The exploratory set remains separately in `work/runtime-evaluation/`. The final
set was generated after implementation was frozen and not used to tune the model
or code. Historical development/final-test corpora were never opened.

To reproduce locally, copy the saved evaluator and both source snapshots into a
new empty result directory, then run `python <new-directory>/evaluate.py` from the
repository. It creates new filenames, freezes inputs, and performs all three runs.
The evaluator is local diagnostic evidence, not a retained product scenario suite.
Raw inputs, model traces, corpora, and weights are excluded from Git.

Validation: all 10 focused binding/contract invariant tests passed, including actual
native and PowerShell execution, path confinement, revalidation, literal quoting,
configured settings on both model calls, and persisted faithful evidence. This does
not validate automatic OpenCode2 integration; that remains a subsequent bounded step.
