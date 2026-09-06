# Baseline: first run (Windows 11 workstation, Jul 9 – Sep 6 2026)

Use these to sanity-check a new run. Large departures usually mean a classifier needs a new model ID or a new host-shell rule, not that the behavior changed.

| Measure | Value |
|---|---|
| Shell commands | 38,176 across 874 sessions, 48 model IDs |
| Sources | Codex 20,072 · OpenCode 13,104 · Claude Code 4,421 · Cursor 579 |
| Failed (harness-flagged) | 10.7% |
| Hidden failures (OK + hard error string) | 876 (2.3%) |
| Calls carrying an embedded program | 24.9% |
| Dialect mismatch fail rate vs matched | 29.8% vs 11.2% |
| POSIX on Git Bash / on Windows PowerShell 5.1 / on cmd.exe | 2.7% / 40.8% / 26.6% |
| python -c / python heredoc / node -e / node stdin / PS here-string / jq / awk-perl | 27.8% / 10.3% / 15.0% / 5.9% / 9.4% / 8.5% / 0% |
| Top "not found" name | `head` typed into PowerShell, 96 times |
| Codex exit code visible (text(r) vs text(r.output)) | GPT-6 Astra 75% · GPT-5.6 Sol 8% · GPT-5.6 Luna 8% |
| Shell share of all tool calls | Codex models 56–71% (structural) · Claude Opus 5 81% (uninstructed) · Claude Fable 5.1 73% (auto-mode instructed) · Claude Sonnet 5 37% |
| Outputs over 10k chars | 6.2% of measured (Codex omitted, token-counted) |

## Harness facts verified from binaries on that machine

- OpenCode 1.18.25 resolves its shell as `$SHELL`, else the first of: `pwsh`, `powershell`, Git Bash (`OPENCODE_GIT_BASH_PATH` or `<git>/../../bin/bash.exe`), `%COMSPEC%`. It has per-shell prompt notes (tells the model `&&` is unsupported on Windows PowerShell 5.1). Config key `shell` ("Default shell to use for terminal and bash tool") overrides all of it. On that machine it spawned `powershell.exe` 5.1 even though pwsh 7.6 and Git Bash were installed.
- Codex CLI 0.153 has no Git Bash host on Windows; `exec_command` takes a `shell` parameter that models passed as `cmd.exe` or a PowerShell path. Features include `powershell_shell_version`, `unified_exec`, `code_mode`, `js_repl`. The exec result object carries `exit_code`; the cell prints only what the model prints.
- Claude Code's Bash tool on Windows is Git Bash; it was the lowest-failure host in the corpus.
