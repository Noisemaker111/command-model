# Command Model

A small local model and execution loop for command/cell work delegated by a
frontier agent. The frontier supplies English intent and known context; one fresh
local worker performs bounded mechanical work, verifies the result and returns
compact evidence. "Our model" and "the model we are building" refer to this project.

Start with [purpose and evidence](experiments/command_model/PURPOSE.md),
[agent instructions](AGENTS.md), and the [Codex handoff prototype](experiments/command_model/codex/README.md).
The original inspection adapter and later execution experiments have different
scopes; the purpose document preserves what each actually demonstrated.

## Components

| Component | Responsibility |
| --- | --- |
| Shell Gatherer | Collect recorded shell commands, results and provenance |
| Mining and labeling pipeline | Normalize observations, recover useful candidates and assign supported labels |
| Execution verification and datasets | Check candidate behavior and save examples with frozen held-out partitions |
| Model training | Train for the actual delegation protocol, preserving original adapters |
| Local execution loop and frontier evaluation | Execute grounded English jobs and measure verified whole-operation accuracy, time and tokens |

The gatherer does not certify training examples. See the
[data pipeline](experiments/command_model/DATA_PIPELINE.md) and
[measured data results](experiments/command_model/DATA_RESULTS.md).

## Repository and local work

```powershell
git clone https://github.com/Noisemaker111/command-model
cd command-model
```

Follow [DEVELOPMENT.md](DEVELOPMENT.md) for owned worktrees, checks and integration.
The model source is in experiments/command_model. Existing shell-specialist model
aliases, frozen dataset seeds and old work/command-specialist data paths retain
their identities for reproducibility; this rename does not retrain weights.

## Shell Gatherer

The self-contained skill is [skills/shell-gatherer](skills/shell-gatherer/SKILL.md).
Copy that directory to ~/.claude/skills/shell-gatherer or
~/.codex/skills/shell-gatherer to install it. In a fresh session request
"Use Shell Gatherer to collect my local shell-command observations."

To run directly with Python 3.10+ and no dependencies:

```powershell
New-Item -ItemType Directory -Force work
python skills/shell-gatherer/scripts/gather.py work
```

This writes records.jsonl and toolcounts.json. The old scripts/extract.py command
forwards to the same implementation. Recorded output is capped at 700 characters;
full-transcript ingestion is a separate pipeline. No collected commands execute.

## Downstream shell analysis

These scripts consume observations; they are not part of gathering:

```powershell
python scripts/analyze.py work
python scripts/scratch.py work
python scripts/build.py work --no-gallery
```

The report is work/shell-analysis.html with page-data.json. Analysis uses heuristic
classifications, not verified task-success labels. The optional gallery exposes
recorded commands and paths; keep private data local unless publication is authorized.
[Historical observations](reference.md) preserve the original analysis context.

## Naming and compatibility

The repository was formerly shell-forensics and the model experiment was called
command specialist. Current names are **Command Model** (project) and **Shell
Gatherer** (collection). Historical artifacts and installed model aliases may keep
old names. On the development machine, the former repository folder is a
compatibility junction to command-model so existing worktrees, environments and
saved absolute paths remain accessible. New work should use the canonical name.

MIT license.
