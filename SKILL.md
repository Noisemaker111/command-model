---
name: shell-forensics
description: Mine the local transcripts of Codex, Claude Code, OpenCode and Cursor for every shell command the models ran, classify dialect, job, embedded programs (python -c, node -e, heredocs), failures and recoveries, and publish a screenshot-ready card deck with a post for each finding. Use when someone asks how their coding agents use bash/PowerShell, why shell calls fail, which model "does everything through bash", or wants the Shell Forensics report for their own machine.
---

# Shell Forensics

Turns the transcript stores that coding agents already keep on disk into one dataset of shell commands, then into a report. Nothing is self-reported by a model; every record is a tool call joined to its result.

## Sources read (all optional; missing ones are skipped)

| Harness | Path | What is parsed |
|---|---|---|
| Codex (CLI + desktop) | `~/.codex/sessions/**/*.jsonl`, `~/.codex/archived_sessions` | `exec` JS cells; each `tools.exec_command` / `shell_command` inside is one record. Exit code comes from the `{"exit_code":n}` JSON the cell printed, when it printed it. Model from `turn_context`. |
| Claude Code | `~/.claude/projects/**/*.jsonl` | `Bash` and `PowerShell` tool_use joined to tool_result by id. Flags sessions carrying the auto-mode "work through Bash" instruction. |
| OpenCode | `~/.local/share/opencode/opencode.db` | v1 `part` and v2 `session_message` tool parts (`bash`, `shell`, `oc_bash`, `execute` JS cell), de-duplicated by call id. |
| Cursor CLI | `~/.cursor/chats/*/*/store.db` | `Shell` tool-calls joined to results. |

Read-only. Nothing is uploaded until the user publishes the page.

## Run

Needs Python 3.10+ (stdlib only) and, for the palette check, nothing else. Pick a work directory (the session scratchpad is fine).

```
python <skill>/scripts/extract.py  <work>     # -> records.jsonl, toolcounts.json
python <skill>/scripts/analyze.py  <work>     # -> records_annotated.jsonl, summary.json (prints headline tables)
python <skill>/scripts/scratch.py  <work>     # -> scratch.json  (scratch scripts written to disk, per model)
python <skill>/scripts/build.py    <work>     # -> shell-forensics.html, page-data.json
```

`<skill>` is this skill's directory. On Windows run them through the Bash tool with `PYTHONIOENCODING=utf-8`, or through the PowerShell tool as `python <path>`. The Codex parse is the slow step (about 1 minute per 2 GB of sessions).

Options for `build.py`:
- `--no-gallery` drops the 1,500-command sample and the retry examples from the page. Use it when the page will be shared outside the machine's owner: the gallery embeds real commands with real paths.
- `posts.json` in the work directory overrides any post by key (`lead`, `share`, `corpus`, `jobs`, `dialect`, `head`, `embed`, `form`, `scratch`, `hidden`, `exit`, `causes`, `recovery`, `output`, `rules`, `change`). Write it after reading `summary.json` when the default wording does not match what the data shows; keep each under 280 characters.

## After it runs

1. Read the tables `analyze.py` printed (per-family fail rates, dialect × host, interpreter forms, recovery moves). Sanity-check the two classifiers most likely to be wrong on a new machine: `host_shell()` in `analyze.py` (Windows values are inferred per harness; on macOS/Linux it uses `$SHELL`) and the `family()` map of model IDs to display names. Add any model ID the map does not know.
2. Publish `shell-forensics.html` with the Artifact tool (favicon 🐚). Before publishing a page with the gallery, tell the user it contains real commands and paths and offer `--no-gallery`.
3. Tell the user the numbers that changed what they should do, not the method. The page's "What to change" card is written for a Windows host with Git Bash and pwsh 7; on macOS/Linux only the output-cap, heredoc and exit-code rules apply, so say so.

## What the classifiers mean

- **dialect** is what the model typed: `posix`, `powershell`, `cmd`, `neutral` (valid anywhere: bare git/bun/gh), `mixed` (cmdlets and Unix tools in one line), `js-only` (a Codex/OpenCode cell that never called the shell).
- **host** is what ran it. Harness tools do not always run what their name says: on Windows, OpenCode's `bash` tool was observed spawning `powershell.exe` 5.1 and its `shell` tool cmd.exe; Codex runs PowerShell unless `shell:"cmd.exe"` is passed; Claude Code's `Bash` is Git Bash.
- **mismatch** is a POSIX command on a Windows shell or a PowerShell/cmd command on a POSIX shell.
- **interp** is an embedded program inside the shell call: `python -c`, python via heredoc/stdin, `node -e`, node via stdin, `bun -e`, bun/npx/tsx scripts, nested `pwsh -Command`, `cmd /c`, heredoc, PowerShell here-string, jq, sqlite3, perl/awk.
- **cause** is the first matching error pattern in the output; `nonzero/other` means a non-zero exit with no recognizable string; `build/test failure` means the tool worked and the code did not.
- **hidden** is a call the harness marked OK whose output still contains a hard error (cmdlet not recognized, command not found, Traceback, syntax error, path not found, access denied). It is a lower bound.
- **recovery** compares each failed command with the next shell command in the same session: identical retry, rewrite in the same dialect, dialect switch, interpreter switch, tool switch, or leaving the shell; and whether that next one worked.

All of these are regex heuristics checked by hand on samples. Expect a few percent noise per cell and say so on the page (the Method card already does).

## Caveats to carry into any conclusion

- Harness design dominates: Codex has no read/edit tools, so its shell share is structural. Compare models within one harness.
- Instructions leak in: auto mode and repo AGENTS.md files push models toward Bash. The page marks instructed families with ⚑.
- Host shells differ per harness, so failure rates across harnesses are not comparable.
- One user, one machine, one task mix.

## Files

- `scripts/extract.py` — parsers for the four stores, JS-cell parser for `tools.*` calls.
- `scripts/analyze.py` — classifiers and aggregates.
- `scripts/scratch.py` — census of script files written through Write/patch tools.
- `scripts/build.py` + `scripts/template.html` — the card deck (IBM Plex, validated categorical palette, light and dark).
- `reference.md` — what was found on the first machine this ran on, as a baseline to compare against.
