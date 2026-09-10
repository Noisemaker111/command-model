---
name: shell-gatherer
description: Collect recorded shell commands and tool results from local Codex, Claude Code, OpenCode and Cursor transcripts into a local observation dataset. Use when asked to gather or collect shell-command history for Command Model, analysis, or a later mining and labeling pipeline. Does not train the model or certify task success.
---

# Shell Gatherer

Shell Gatherer is the collection component of Command Model. Gather recorded
observations; downstream scripts mine, label, verify and save training examples.
Do not treat exit zero as proof that the user's task succeeded.

Run with Python 3.10+ (standard library only), using this skill's directory:

```powershell
New-Item -ItemType Directory -Force work
python <skill>/scripts/gather.py work
```

The collector reads available local Codex, Claude Code, OpenCode and Cursor
transcripts and writes records.jsonl and toolcounts.json. It does not execute
collected commands or upload results. Missing sources are skipped; if no records
are found it exits unsuccessfully. Reopen the saved outputs and report actual
counts, skipped sources and limitations.

This existing collector caps recorded output at 700 characters and keeps out_len;
it is not a full-fidelity archival copy or a complete recovery of human intent.
Keep source/session identifiers and recorded exit information. Missing results
remain unknown. Do not invent labels, claim examples are training-ready, or
publish private commands and paths without explicit authorization.

Requests to train, label, verify task success, or benchmark frontier delegation
belong to the downstream Command Model pipeline, not this collection skill.
