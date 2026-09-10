# Data-pipeline measurements

Measured locally on 2026-09-09, using the same Ryzen 9 3900X / 64 GB Windows machine
as the command-specialist pilot. This stage used standard-library Python and
Windows PowerShell. It made no model/API labeling calls and ran no new training.
Development and review effort are not included in the runtime timings below.

## Recovered data and partitions

The final frozen inventory covered 827 configured files, about 6.409 GB of source
file sizes, and 598,370 source records. Every scanned record received a disposition;
there were no source-processing failures. Source file sizes include whole SQLite
files, whereas snapshots contain only explicitly selected transcript tables.
This inventory is not proof that every command store on the machine was found.

| Normalized source | Command observations |
|---|---:|
| Legacy extracted corpus | 32,690 |
| Codex native/function events | 19,680 |
| Claude tool events | 5,164 |
| OpenCode transcript tables | 12,526 |
| Cursor JSON blobs | 551 |
| Total | 70,611 |

Observations are not necessarily unique real-world executions: legacy records can
overlap native logs. Identity-based event handling counted 1,871 repeated call
events and 4,910 repeated result events. It does not merge unrelated tasks merely
because they use identical command text.

Recorded exit fields yielded 44,541 zero, 7,758 nonzero, and 18,312 unknown statuses.
Legacy exit fields retain their unverified-extractor provenance. None of these
statuses establishes original task correctness. There were 37,370 records with
preceding user context, including 4,141 with explicitly capped context; 33,241 had
no recovered user context, 65 lacked a result, and 11 flagged conflicting call IDs.
Review reasons overlap.

The freeze kept 1,078 session/context groups intact, with the largest containing
5,586 observations. The resulting record allocation was:

| Partition | Observations | Target |
|---|---:|---:|
| Initial training review | 21,183 | 30% |
| Development gate | 7,061 | 10% |
| Expansion reserve | 35,306 | 50% |
| Final-test reserve | 7,061 | 10% |

These are immutable review partitions. They still need task expectations and
semantic near-duplicate review before serving as an independent benchmark.
The training-only review queue selected 115 distinct-command samples across 42
groups. That is a routing aid, not 21,183 automatically verified task labels.

## Measured efficiency

An earlier first scan of 826 files / 70,507 observations took 187.21 seconds.
Two live-source refreshes reused 820 files and took 13.22 and 28.49 seconds, about
14.2x and 6.6x shorter than that first scan. Source contents and concurrent local
activity differed; the slower run overlapped the initially stalled verifier.
These are exploratory refresh measurements, not a controlled whole-pipeline
speedup. Rebuilding normalization after parser changes correctly invalidated the
normalization cache; the final rebuild took 93.79 seconds while reusing 820 source
snapshots. Freezing its partitions and verifying normalized hashes took 10.33 seconds.

The executable read verifier produced a more specific, controlled result:

| Mode | Verified cases | Elapsed | Average per case |
|---|---:|---:|---:|
| One PowerShell process for the full batch | 800/800 | 1.926 s | 2.407 ms |
| Fresh PowerShell process for each sampled case | 16/16 | 15.112 s | 944.500 ms |

This is **392x higher per-case throughput** for the bulk verifier, compared with
the sampled fresh-process baseline. Both used the same verifier and expected
results; the serial sample was deterministic, used already-created fixture files,
and ran after the bulk test. Bulk time includes fixture construction. Serial
execution of all 800 cases was not measured. Earlier bulk runs took 1.90–2.04 s.
This result concerns read-fixture verification; it is not a claim of 392x cheaper
historical gold labeling, 100x faster ingestion, or a faster model workflow.

The initial verifier timed out at 120 seconds because Windows PowerShell attempted
to serialize file metadata attached to nonempty output lines. Casting them to
plain string arrays fixed the issue. The full-batch regression test covers it.

## Training output and limits

The current conservative parser found 268 bounded read-contract candidates across
the frozen corpus. From the training partition, 96 candidate observations reduced
to 32 distinct operation/count pairs, yielding 96 synthetic instruction examples.
All paths and requests in the export are generated; source ancestry is hashed.
The 800-case verifier establishes head/tail semantics for limits 1–100, empty,
short and longer UTF-8 CRLF files, and literal paths containing quotes and shell
metacharacters. It does not verify historical intent or original environment state.
No original historical task-success labels were promoted.

This supplement is too narrow to justify another broad-model training run by
itself. The next useful dataset work is expanding executable operation verifiers,
recovering contextual gaps and unsupported orchestration formats, and building
task-level expectations for the held-out evaluation. The earlier trained pilot
remains the only trained model from this project; its limitations still apply.

The runner now reads UTF-8 explicitly in PowerShell, emits UTF-8 to its captured
console, and preserves significant leading/trailing whitespace and blank lines
within selected output. Actual PowerShell/native regression tests cover these
changes. Fifteen unittest cases passed, including the 800-case bulk verifier,
snapshot reload, committed-WAL capture, excluded credential tables, duplicate
handling, partition integrity, cache invalidation, and training-only exports and
review sampling. No CI checks are configured on the existing PR.
