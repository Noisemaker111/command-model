# Dataset

## Sources (mined 2026-09-16)

| Source | Parser | Records |
| --- | --- | ---: |
| Codex CLI sessions (incl. JS `exec` cells) | `codex` | 33,515 |
| Claude Code transcripts (`Bash`, `PowerShell`) | `claude-code` | 12,002 |
| OpenCode SQLite store | `opencode` | 12,500 |
| OpenCode2 host stores (live + release evidence) | `opencode2` | 5,369 |
| Grok CLI chat histories | `grok` | 933 |
| PSReadLine history (human-typed) | `psreadline` | 857 |
| Cursor agent chats | `cursor` | 555 |
| Curated adversarial fixtures | `adversarial` | 36 |

65,767 executions → 59,812 exact-unique → 58,109 template groups (numbers, UUIDs, hex ids,
timestamps and temp paths normalised). 95% of groups occur once; 54 occur 20+ times.
Known but unparsed locations (T3 state, legacy `.opencode`, the OpenCode2 request ledger) are
listed in `inventory.json`. Full distributions: `reports/mining_stats.md`.

Each record keeps the schema requested in the brief (`id, source_file, source_type, timestamp,
shell, command_raw, command_redacted, working_directory, preceding_context, following_context,
existing_model_text, exit_code, tags`). `existing_model_text` is the agent's own description
when the tool recorded one (12,000 groups); it is kept for analysis but never shown to the
teacher, because it carries intent the command does not show.

The shell is taken from the recording tool when known (Claude `Bash` → bash, Codex/OpenCode2/
Cursor on a Windows cwd → PowerShell, Codex `shell: cmd.exe` → cmd) and from syntax otherwise.

## Redaction

`redaction/redact.py` replaces vendor keys, bearer/basic tokens, cookies, URL credentials,
connection-string passwords, credential flags and env assignments, private keys and
high-entropy tokens with `<API_KEY> <TOKEN> <PASSWORD> <SECRET> <COOKIE> <PRIVATE_KEY>`.
Variable references (`$env:X`, `$secret`), code expressions and hex digests are kept.
An audit of the first pass found 4,336 groups flagged, mostly false positives (`-Pattern`
read as `mysql -p`, `git checkout -b` read as a curl cookie, `sessionID ===`); after fixes
180 groups are redacted. Raw commands exist only in `private/` (owner-only ACL).
The LLM client refuses any prompt in which `find_secrets` still matches, and payloads are
checked in their serialised form (9 commands are withheld because JSON escaping makes
ordinary text look secret-shaped).

## Labels

- Teacher: `teacher-v2`, temperature 0.4, two candidates per command (concise and complete),
  batches of ≤20 commands / 30k characters. Items carry the parser's `structure` and `names`
  so the model keeps concrete names instead of "the script".
- Judge: `judge-v1`, temperature 0, scores each candidate plus the heuristic, picks the best
  and writes `recommended_output`.
- Decision: accepted when the recommended score ≥ 85, validators pass and the judge is not
  uncertain; manual review at 70–84, uncertain, or validator failure; rejected for secret
  leakage or score < 70. The judge rewrites weak candidates, so v1 has no rejections.
- Model: **Haiku 4.5** by default (`LIVE_STATUS_TEACHER`). v1's labels were written by Opus 5;
  rows record `teacher_model` and `judge_model`, and candidate keys are prefixed per model
  (`ota` = Opus teacher candidate a, `hta` = Haiku), so mixed provenance stays traceable.

### Why Haiku

On 300 test commands that already had Opus labels, Haiku relabelled from scratch and its
labels were graded against the Opus gold:

| Teacher | Accepted vs Opus gold | Same actions | Invented |
| --- | ---: | ---: | ---: |
| Haiku, `teacher-v1` prompt | 74.0% | 97.6% | 4.5% |
| Haiku, `teacher-v2` prompt (+structure, +names) | **78.9%** | 96.7% | 3.7% |
| Opus's own second-choice candidate (reference point) | 72.0% | — | — |

Haiku with the structure hints matches Opus's own alternate candidates, at a fraction of the
cost and without exhausting the Claude subscription that the interactive session shares.
Opus stays available (`--model claude-opus-5`) for spot checks.

### Self-labels (no paid model)

`labeling/self_label.py` has the fine-tuned student write 4-5 candidates for a command and
Jev select one, keeping the label when the selector's score clears 0.30. Measured against gold
on the v1 test set, that gate keeps 66% of commands at 89.6% precision (0.25 → 77% at 87.7%,
0.35 → 55% at 90.0%; `evaluation/self_label_threshold.json`). Kept rows join **training only**,
carry `label_source: "self"`, and are dropped when their family belongs to a held-out split.
Rejected commands land in `labels/needs_teacher.txt` for a paid pass, so the teacher only sees
what the local loop could not label.

## v1 splits

| Split | Rows |
| --- | ---: |
| train | 3,113 |
| validation | 425 |
| test | 494 |
| manual_review | 102 |
| rejected | 0 |

Selection: the 40% most frequent templates, then round-robin over (shell, first action,
complexity) buckets with tagged hard examples first, plus every secret/injection/synthetic
group. Families (identical template or MinHash Jaccard ≥ 0.7) never cross splits; 0 template
collisions between train and validation/test. Test/validation ids are frozen in
`datasets/frozen_families.json`. Half of the secret, injection-like and synthetic families
go to test: test holds 82 secret-bearing, 38 injection-like and 16 synthetic commands, plus
124 long PowerShell, 66 loops, 45 conditionals, 60 natural-language and 52 malformed commands.
Per-split distributions are in `datasets/v1/report.json`.

Rows carry `weight = min(4, 1 + log2(count))`; training repeats a row that many times.
