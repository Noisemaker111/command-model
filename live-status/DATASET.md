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

- Teacher: Opus 5, `teacher-v1`, temperature 0.4, two candidates per command (concise and
  complete), batches of ≤20 commands / 30k characters.
- Judge: Opus 5, `judge-v1`, temperature 0, scores each candidate plus the heuristic,
  picks the best and writes `recommended_output`.
- Decision: accepted when the recommended score ≥ 85, validators pass and the judge is not
  uncertain; manual review at 70–84, uncertain, or validator failure; rejected for secret
  leakage or score < 70. The judge rewrites weak candidates, so v1 has no rejections.

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
