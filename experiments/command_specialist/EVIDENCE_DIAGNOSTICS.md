# Nonempty negative evidence diagnostics

Two fresh development comparisons on September 10, 2026 tested runtime context
changes with the unchanged `shell-specialist-pilot` model and adapter. Neither
candidate was adopted. This is evidence for the next English-worker iteration,
not a new inspection interface or an instruction to retrain.

Each comparison used 12 saved synthetic cases, three paired runs, alternating
source/treatment blocks and full-workload warmups. Real public CLI calls included
planning, native file execution, evidence selection and raw-artifact reopening.
Source snapshots and SHA-256 input guards passed. Context/output stayed 4096/160.
Model responses, errors and raw output were retained. Historical corpora and the
frozen final-test partition were not opened.

| Runtime treatment | Baseline correct | Treatment correct | New regressions |
| --- | ---: | ---: | ---: |
| Add an explicit instruction to return an empty list for no matches | 15/36 | 15/36 | 0 |
| Add three small negative/positive selection examples | 15/36 | 21/36 | 3 |

Correctness required the actual executed stdout, expected source-line set and
verbatim evidence. Cases included routine-only pages, a no-errors message,
standalone error/summary lines, present/absent requested identifiers, and a
100-line page with the error/summary at 99/100. These deliberately challenging
cases are not interchangeable with earlier five-operation planning benchmarks.

The examples fixed two singleton negatives and a singleton error, but replaced
the correctly selected long-page error at line 99 with unrelated line 79 in every
run. They also selected all lines of a routine-only page, omitted a standalone
summary, and returned an unrelated identifier for an absent requested identifier.
The aggregate score conceals a consequential regression; do not adopt it.

The one-sentence instruction did not repair any task. It reduced generation on
one failure path, but no evidence-quality improvement was established. Neither
comparison establishes production reliability, cold performance, throughput gains
or whole-agent speed. Invalid selections and truncations remain visible failures;
valid line numbers alone do not establish relevance or completion.

For the English execution loop, retain task-specific observable completion checks
and raw results. Distinguish empty stdout from a nonempty page with no relevant
lines. Do not silently treat a selected line or an exit-zero process as proof that
the requested work was done. Keep this diagnostic separate from the other
session's loop implementation and configured-host verification.

All 288 warmup/measured records remain locally under the mission worktree's
`work/evidence-abstention/` and `work/evidence-context/`, including the runnable
`evaluate.py`, source snapshots, fresh fixtures, manifests and per-case artifacts.
`work/EVIDENCE_DIAGNOSTICS.md` contains detailed per-case scores and timing figures.
Those artifacts and experimental prompt variants are intentionally outside Git.
