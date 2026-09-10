# Command-data preparation

`data_pipeline.py` inventories explicitly configured transcript sources, saves
private source snapshots, and normalizes recorded shell calls and results.
`label_data.py` creates immutable review partitions. `verify_labels.py` checks
bounded read semantics against PowerShell and exports synthetic training examples
from the training partition alone. These tools use Python's standard library;
the executable verifier additionally requires PowerShell.

## Reproduce

Save a private source configuration, for example under `work/data-sources.json`:

```json
{
  "sources": [
    {"kind": "codex", "path": "~/.codex/sessions", "glob": "*.jsonl"},
    {"kind": "codex", "path": "~/.codex/archived_sessions", "glob": "*.jsonl"},
    {"kind": "claude", "path": "~/.claude/projects", "glob": "*.jsonl"},
    {"kind": "cursor", "path": "~/.cursor/chats", "glob": "store.db"},
    {"kind": "opencode", "path": "~/.local/share/opencode/opencode.db"}
  ]
}
```

An optional `legacy` entry can point to an existing `records_annotated.jsonl`.
Its records remain separately attributed; they can overlap native transcripts.

```powershell
python experiments/command_model/data_pipeline.py --config work/data-sources.json --out work/data-v2
python experiments/command_model/label_data.py --root work/data-v2 --out work/data-v2/frozen-review
python experiments/command_model/review_queue.py --frozen work/data-v2/frozen-review --out work/data-v2/review-queue.json
python experiments/command_model/verify_labels.py --frozen work/data-v2/frozen-review --out work/data-v2/verified-reads
python -m unittest discover -s experiments/command_model -p 'test_*.py' -v
```

Run ingestion again to process changes. `--refresh` forces source rereads even if
size and modification time are unchanged. `label_data.py --run <saved-run.json>`
selects an existing inventory instead of the latest one. Freeze and verifier
outputs must use fresh directories. Ingestion has a single-writer lock; after a
crash, inspect the recorded process before removing its stale lock.

## Recovery and accounting

JSONL snapshots preserve the original captured bytes in gzip files addressed by
SHA-256. Growing files are captured to their initial size; a changed fingerprint
is recorded. SQLite sources are opened read-only, with a read transaction covering
the selected transcript tables and committed WAL contents. The logical export
retains original field values, including base64 for binary blobs. It excludes
unrelated tables, including credentials, and lists selected, missing, and excluded
tables explicitly. This is not a complete physical SQLite backup.

Supported records include Codex native completed-command events and explicit shell
function calls, Claude shell tool uses/results, Cursor JSON tool-call/result blobs,
OpenCode old message/part records and newer session messages, and legacy extracted
commands. Cursor blobs are joined by call ID without inventing conversation order.
Repeated events are counted, conflicting IDs are retained and flagged, and matching
native/function events are combined when they share identity.

Each input record receives exactly one disposition. Non-JSON blobs, unsupported
tool calls, missing commands, and malformed records remain visible in counters and
source snapshots. Code-mode JavaScript is not evaluated. Embedded shell commands
inside unsupported orchestration code are therefore not automatically recovered.
Pasted transcripts inside messages do not become native command events.

The normalized view retains full extracted output text, source pointers, command
identity, and recorded exit codes. Preceding user context is capped at 8,000
characters with an explicit flag and an original-source pointer. It is always
marked as an unverified association. Arbitrary text resembling an exit code does
not become a structured exit label. Error keywords and truncation markers are
heuristics, not ground truth. All original task-correctness labels initially abstain.

## Frozen partitions and label promotion

Keep complete sessions, recorded parent/fork relationships, and exact or normalized
copies of nontruncated user context in the same group. Common command strings alone
do not join unrelated sessions. Deterministically balance whole groups toward 30%
training, 10% development, 50% expansion reserve, and 10% final test by record count.
Large groups can prevent exact proportions. Save the assignment and source hashes;
never silently rebalance an existing freeze as new data arrives.

These are **review partitions**, not an independent blind benchmark. Semantic
near-duplicate review, reliable task expectations, and environment fixtures are
still needed. Missing context, uncertain legacy extraction, changing sources,
conflicting IDs, and missing results remain explicit review reasons. A low-quality
record keeps its assigned partition and source provenance; it does not gain
training eligibility from its exit code.

Review files contain hashes, typed candidates, and factual/heuristic labels rather
than raw requests, commands, outputs, or original paths. They are still private
metadata. Source content can be retrieved separately through its artifact pointer.
There is no claim of a general-purpose secret scrubber for raw transcripts.

`review_queue.py` routes training records toward source reconciliation, missing
context recovery, identity-conflict inspection, or task-verifier development. It
selects up to three distinct command hashes per group, with source artifact
pointers and no raw transcript text. Development and final-test files are never
read by the queue builder. Groups are review priorities, not interchangeable tasks;
reviewing one representative does not label all members automatically.

The first reusable verifier checks head/tail limits 1 through 100 on empty, short,
and longer UTF-8 CRLF files, with quotes and metacharacters in literal paths. Python
computes expected slices; one PowerShell process returns actual line arrays for all
800 cases. Cast PowerShell output to plain string arrays before JSON serialization:
otherwise Windows PowerShell can expand attached file metadata instead of emitting
just the text. The initial implementation timed out for this reason; a regression
test now exercises the complete nonempty batch.

The training exporter reads only `train.jsonl`, verifies its frozen hash, groups
supported read candidates by operation and count, and produces three synthetic
instructions per pair. Requests and paths are generated, not recovered human
intent. Each example keeps hashed training ancestry. The verifier establishes
fixture operation semantics, not that a historical command fulfilled its task.
This supplement alone does not justify retraining a broad command model.

## Static recovery and expanded training

Install the exact Acorn dependency from `experiments/command_model/js_parser`
using `npm ci --ignore-scripts --no-audit --no-fund`; run `npm test` in that directory.
Use a current Node runtime (verified with the installed Node 24.18.0 runtime). Acorn's
[parser API](https://github.com/acornjs/acorn/tree/master/acorn) produces a JavaScript
AST; the extractor evaluates no historical code, imports, or variable expressions.
Literal command fields retain source spans, dynamic environment fields, and control
context. Syntactic candidates are never labeled as observed executions.

From the repository root, with a previously frozen dataset and fresh output paths:

```powershell
python experiments/command_model/recover_code.py --root work/command-specialist/data-v2 --frozen work/command-specialist/data-v2/frozen-review-final --out work/command-specialist/code-recovery-new
python experiments/command_model/recover_reads.py --root work/command-specialist/data-v2 --frozen work/command-specialist/data-v2/frozen-review-final --code-recovery work/command-specialist/code-recovery-new --out work/command-specialist/read-recovery-new
python experiments/command_model/verify_labels.py --frozen work/command-specialist/data-v2/frozen-review-final --read-recovery work/command-specialist/read-recovery-new --out work/command-specialist/verified-reads-new
python experiments/command_model/verify_more_operations.py --out work/command-specialist/verified-operations-new
python experiments/command_model/prepare_expanded.py --pilot work/command-specialist --verified work/command-specialist/verified-reads-new --frozen work/command-specialist/data-v2/frozen-review-final --out work/command-specialist/expanded-data-new
```

The PowerShell recovery stage uses the SDK's
[Parser.ParseInput](https://learn.microsoft.com/en-us/dotnet/api/system.management.automation.language.parser.parseinput?view=powershellsdk-7.4.0)
to find literal bounded `Get-Content` subcommands, including compound statements.
Dynamic paths/counts, unsupported flags, conflicting parameters, and wildcard
`-Path` forms retain rejection reasons. The enclosing pipeline is not executed or
declared equivalent to a standalone read. Original paths remain in private sidecars;
only synthetic fixture paths enter training. Snapshots may contain multiple sessions;
the selected training session/record identities control candidate eligibility.

Recovery and export artifacts carry hashes tying them to the frozen training file.
The expanded preparer reuses only the pilot's synthetic training rows, excluding its
older mined examples. It never reads pilot evaluation files or frozen non-training
partition files. Do not manually add historical examples from a different split.
Run `python -m unittest discover -s experiments/command_model -p 'test_*.py'`
after installing the parser dependency. See [RECOVERY_RESULTS.md](RECOVERY_RESULTS.md)
for measured coverage, failures, and scope.

## Efficiency and reproducibility

Source fingerprints cache unchanged snapshots; immutable content and parser-version
keys cache normalization. The size/mtime fast path is not a content rehash. Snapshot
bytes are hashed when normalized, and normalized bytes are verified before freezing.
Pipeline source versions, labeler source, source/config hashes, artifact hashes,
record counts, and timings are saved for reproducibility. Cached summaries are not
evidence that every unchanged artifact was reread on each invocation.

Raw snapshots, normalized text, caches, datasets, and verification artifacts stay
under ignored `work/`. Snapshot retention is append-only and uses disk space; this
CLI does not run a background collector or remove older snapshots automatically.

Measure cold ingestion, changed-input refresh, unchanged-input refresh, and verifier
throughput separately. Include fixture creation and review/verifier development
costs in any overall labeling-efficiency claim. A short bulk check does not prove
100x cheaper gold labeling or a faster end-to-end model workflow.

For an optional fresh-process comparison, pass `--serial-samples 16` to
`verify_labels.py` with a fresh output directory. It checks a deterministic sample
against the same expected results, starting one PowerShell per case. The reported
per-case throughput ratio compares that sample with the full 800-case bulk run;
it is not a measurement of serial execution of all 800 cases.
