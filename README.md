# Shell Forensics

A Claude Code skill that reads the transcripts your coding agents already keep on disk (Codex, Claude Code, OpenCode, Cursor), pulls out every shell command they ran, and builds a report: which model does everything through bash or PowerShell or a JavaScript cell, what the shell is used for, how it fails, and what actually fixed it. The report is a deck of screenshot-sized cards, each with a ready-to-post summary.

Example output from the first machine it ran on: 38,176 commands, 874 sessions, 48 model IDs. Findings included a 30% failure rate when the model typed POSIX into a PowerShell host versus 11% when the dialect matched, `| head` typed into PowerShell as the single most common concrete failure, `python -c` one-liners failing at 28% versus 10% for the same Python fed through a heredoc, and GPT-5.6 models printing only `r.output` in Codex cells 92% of the time so that non-zero exit codes never reached the transcript. See `reference.md` for the baseline numbers.

## Install

Claude Code:

```
git clone https://github.com/Noisemaker111/shell-forensics ~/.claude/skills/shell-forensics
```

Then in any Claude Code session:

```
/shell-forensics
```

Codex reads skills from `~/.codex/skills`, so the same clone works there:

```
git clone https://github.com/Noisemaker111/shell-forensics ~/.codex/skills/shell-forensics
```

You can also run the scripts by hand without any agent. Python 3.10+, standard library only:

```
python scripts/extract.py  work      # records.jsonl, toolcounts.json
python scripts/analyze.py  work      # records_annotated.jsonl, summary.json, prints the headline tables
python scripts/scratch.py  work      # scratch.json: scripts written to disk per model
python scripts/build.py    work      # shell-forensics.html, page-data.json
```

Open `work/shell-forensics.html` in a browser. Add `--no-gallery` to `build.py` for a page you can share: the gallery embeds real commands with real paths from your machine.

## What it reads

| Harness | Path | Parsed |
|---|---|---|
| Codex CLI and desktop | `~/.codex/sessions/**/*.jsonl` | `exec` JS cells; each `tools.exec_command` / `shell_command` inside is one record |
| Claude Code | `~/.claude/projects/**/*.jsonl` | `Bash` and `PowerShell` tool calls joined to their results |
| OpenCode | `~/.local/share/opencode/opencode.db` | `bash`, `shell`, `oc_bash` and `execute` tool parts, v1 and v2 stores |
| Cursor CLI | `~/.cursor/chats/*/*/store.db` | `Shell` tool calls joined to results |

Read-only. Nothing leaves the machine unless you publish the page.

## What the classifiers do

Each command is tagged with the dialect the model wrote (POSIX, PowerShell, cmd, neutral, mixed), the host shell that ran it, its job (git, read, search, build/test, and so on), any embedded program (`python -c`, heredoc, `node -e`, here-string, jq, nested pwsh), the failure cause parsed from the output, and whether the harness reported success while the output contained a hard error. For every failure it also looks at the next shell command in the session to see what the model tried and whether that worked.

These are regex heuristics checked by hand on samples. Expect a few percent noise per cell. The page says so.

## Caveats worth repeating

- Harness design dominates. Codex has no read or edit tools, so its shell share is structural. Compare models within one harness.
- Instructions leak in. Claude Code's auto mode tells the model to work through Bash; the page marks those families.
- Host shells differ per harness and per OS, so failure rates across harnesses are not comparable.
- One user, one machine, one task mix per run. Post your numbers and the picture gets better.

## Files

- `SKILL.md` — instructions the agent follows
- `reference.md` — baseline numbers and verified harness facts from the first run
- `scripts/extract.py`, `analyze.py`, `scratch.py`, `build.py`, `template.html`

MIT license.

## Local command model experiment

The optional [command specialist pilot](experiments/command_specialist/README.md)
audits training-data quality, benchmarks small local models on bounded PowerShell
inspection and evidence-selection tasks, and trains a local LoRA adapter. Its
synthetic capability scores are separate from this repository's observed transcript
statistics and do not establish superiority to frontier models.
