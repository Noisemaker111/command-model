# Configured-host results — September 10, 2026

The OpenCode2 `inspect_file` adapter was exercised through the installed public
`opencode2 run --standalone` command, using the existing configured
`cliproxyapi/gpt-5.6-sol#xhigh` frontier route and local
`shell-specialist-pilot`. The installed host reported `0.0.0-beta-19398`.
The dev configuration was loaded with an isolated verification agent, database,
Quest state and telemetry. Shell, edits and delegation were denied for that agent.
The plugin was added only to the isolated launch configuration; no global release
was changed. The trained model, corpus and previous worktree were untouched.

## Observed operation

The frontier discovered the typed tool through Code Mode, supplied a known exact
path and evidence intent, received selected text and file line numbers, and used
native read for saved raw-page access and continuation/fallback. The local model
received numbered authorized text, never a path to regenerate.

| Case | Observed result |
| --- | --- |
| Unicode/apostrophe filename, whole five-line page | Correct ERROR and SUMMARY at source lines 3 and 5; eight generated selection tokens |
| Same file, offset 2 and limit 4 | Same correct source lines 3 and 5; raw four-line page reopened successfully through native read |
| 105-line file, first 100 lines | ERROR retained, truncation true and next offset 101; model also selected two irrelevant INFO lines |
| Continuation | Frontier used native read at offset 101 and returned the actual final SUMMARY from line 105 |
| One-line no-match file, twice | Selection failed; raw page retained with explicit native-read fallback; frontier followed it and distinguished no matches from selection failure |
| Existing file denied by native per-path read policy | Tool failed; no specialist result artifact for the denied target; no alternate executor used |
| Page exceeding 8,000-character context budget | Explicit fallback before model invocation; frontier reopened saved raw text with native read |

Every saved selected line was also reopened and compared with its original fixture
line; all were verbatim. This establishes text integrity, not selection relevance
or recall. All seven saved result records and their raw artifacts were reopened.
The no-match errors did not retain model token/timing telemetry, so their generation
counts are unknown, not zero.

## Timing and limits

Windows, sequential local calls, unchanged trained 1.5B baseline, 4K model context,
thinking off, temperature zero, 160-token generation cap. Cache state was not reset.
These are acceptance observations, not a statistically powered benchmark.

| Observation | Adapter wall | Awaited host tool call |
| --- | ---: | ---: |
| Initial correct small-page selection | 263 ms | Not separately recorded |
| Offset-page selection with model reload | 3,266 ms | 3,276 ms |
| First 100-line selection | 320 ms | 327 ms |
| Later 100-line selection | 621 ms | 632 ms |
| No-match selection failures | 1,008 / 1,027 ms | 1,016 / 1,035 ms |
| Context-budget fallback, no model call | 6 ms | 13 ms |
| Denied source read | No adapter packet | 6 ms |

The 3,266 ms call included 2,937 ms of Ollama-reported model load, rather than a
uniform warm-call assumption. The adapter timing includes native read, Python
startup/transport, local inference, validation, raw/record persistence and record
reopening, excluding the final timing-stamp write and host serialization.

Two timed full CLI sessions took **61.4 seconds** and **129.9 seconds**, respectively,
from standalone process launch to final frontier response. They included discovery,
multiple inspections, frontier generation, native fallback/reopening, and, in the
second session, incorrect tool-name attempts and recovery. These are different
multi-case workloads, not comparable speedup arms. No frontier token/cost saving,
p50/p95, cost per correct task, or whole-workflow speedup is claimed.

## Failures discovered during verification

The first host run could not discover the plugin: the initial configuration named
a module file. This host requires `plugins` entries naming directories with an
index entrypoint. The final implementation and instructions use that format.

A later frontier run incorrectly used `tools[item.path]` when discovery returned
`tools.inspect_file`, then tried another incorrect name. It eventually recovered
to `tools.inspect_file(...)` and completed the requested continuation and fallback.
Those retries remain in the full-operation time. They are evidence that successful
adapter calls alone do not establish a reliable or faster frontier workflow.

The local model selected irrelevant INFO lines in both long-page trials and failed
both no-match trials. It must remain an opt-in evidence aid with visible coverage
and raw access. Improving negative-case behavior and evidence precision belongs in
a fresh development evaluation before expanding or retraining the specialist.

An auxiliary `debug config` command timed out waiting for a background service;
verification used task-owned standalone sessions instead. The isolated worktree
initially lacked Acorn; `npm ci` restored its declared dependency. Final checks:
26 Python tests, six parser tests, three adapter core checks, and `git diff --check`.

Private reproduction evidence is under the task worktree's `work/host-smoke/` and
the OS temporary `command-specialist-host/` directory. Raw logs are not published.
The next integration work is command planning/execution through appropriate native
host authorization and a larger real-intent development benchmark; this change
only integrates bounded file-page evidence extraction.
