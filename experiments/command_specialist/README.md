# Local command specialist pilot

This experiment tests whether a small local model can translate short inspection
requests into commands and select useful evidence from output. It is a Windows
PowerShell capability pilot, not a general shell agent or a SOTA claim.

See [measured pilot results](RESULTS.md) and the [model shortlist and feasibility analysis](RESEARCH.md).
The [data preparation pipeline](DATA_PIPELINE.md) adds source snapshots, automated
fact extraction, frozen 30/10/50/10 review partitions, and executable label checks.
See the [data-pipeline measurements](DATA_RESULTS.md) for recovered volume,
partition sizes, and the scoped bulk-verification throughput result.

The model emits a typed plan for five operations: first lines, last lines, literal
search, nonrecursive filename listing, and a top-level JSON field. Ordinary Python
validates the plan, confines paths to a fixture directory, quotes PowerShell
literals, and executes the command. The model cannot submit arbitrary shell code.
For evidence extraction it chooses source line numbers; the runtime returns the
original text and preserves exit code and truncation independently.

## Intended handoff

The product goal is an agent-to-specialist handoff: the frontier agent supplies
intent and known context, the local specialist handles supported mechanical work,
and the agent receives compact faithful evidence with a retrievable raw result.
These five inspection operations are a capability pilot, not the complete command
runner product or a new chat interface. Automatic host integration remains pending.

Exact paths can now be supplied separately from task wording. The runner binds them
to request-local references for prediction and restores the original paths before
validation, execution and presentation. Both the returned `request` and `plan.path`
are readable; internal references appear only in the private raw artifact's audit
trace. Output text is never rewritten to substitute references.

A caller can hand off a UTF-8 JSON task file:

```json
{
  "request": "Read the last 5 lines of {{build}}.",
  "targets": {"build": "logs/build [draft]'s.log"},
  "evidence_request": "Return every error and the final summary."
}
```

```powershell
python experiments/command_specialist/run.py --root '<directory>' --task-file task.json --backend native
```

Runtime limits are explicit CLI options and keyword arguments on `inspect_request`.
Defaults remain `--num-ctx 4096 --num-predict 160` for compatibility. To evaluate
more context/output capacity with the same model and adapter:

```powershell
python experiments/command_specialist/run.py --root '<directory>' --task-file task.json --backend native --num-ctx 8192 --num-predict 2048
```

These values reach **both** planning and evidence requests; Modelfile defaults do
not override them. 8192/2048 is an evaluation profile, not a universal capacity
recommendation or a speed claim. `--evidence-max-lines` (100),
`--evidence-max-chars` (8000), and `--packet-max-chars` (2000) independently bound
selection input and compact stdout/stderr. All limits must be positive integers.
The character window includes newline separators. It is not a tokenizer budget:
callers must allow room for their intent, numbered evidence, system instructions,
and generated output within the chosen context. Ollama may truncate overlong
prompts; this pilot does not prove arbitrary inputs fit from character counts.

A line-limited selection is marked truncated; a character-overflow window skips
selection and asks the caller to inspect the raw artifact. Increasing model context
alone does not enlarge the evidence window. `fallback: "inspect_raw_result"`
identifies bounded or rejected output; it does not trigger an automatic retry or
host action. Raw stdout/stderr remain complete for the executed bounded operation
(the plan's requested line count is still part of that operation).

Empty stdout deterministically returns empty evidence without a second model call.
For nonempty evidence, the artifact records the requested selection, model response,
selection timing, and returned packet. Planning output stopped at the generation
limit is rejected before execution and saved with its timing and raw response;
evidence output stopped at the limit falls back to the already saved raw result.
The artifact records effective runtime limits, execution time, prompt/decode token
counts and durations, and Ollama's stop reason. No model or service settings change.
See [runtime handoff evaluation](RUNTIME_RESULTS.md) for measured scope and limits.

Or use the Python `run.inspect_request(root, request, targets=...)` boundary. For a
small CLI request, `--target 'build=logs/build.log' --request 'Read the last 5 lines
of {{build}}.'` supplies the same binding. Existing unbound `--request` calls retain
their original behavior for compatibility and comparison.

The caller supplies the exact target from its existing context, file selection or
discovery result. This layer does not infer an unknown filename from a description,
crawl the workspace, or install a host-wide file registry. Bindings live for one
request and must not be cached or reused independently of that request. Up to 16
candidate files/directories are allowed; their paths must exist inside the chosen
root. The model's path field is constrained to those references, and resolution
rejects any unknown reference. The ordinary executor revalidates the actual path.

The trained adapter's existing plan shape is retained: internally its `path` field
holds a short reference such as `file_1`; externally it holds the real path. No
filename-specific retraining is required. Literal search strings and JSON keys
still use the existing value field; binding those is a separate extension.

See [binding measurements](BINDING_RESULTS.md). Run the paired live-model experiment
with new filenames and two reference candidates per task:

```powershell
python experiments/command_specialist/benchmark_bindings.py --out work/command-specialist/binding-trial --backend native
```

The test alternates bound/unbound order and compares executed output against an
independent PowerShell reference. It does not consume historical development or
final-test observations and does not prove file-discovery accuracy.

## Why this design

The shell-forensics corpus exposes expensive mechanical failures: wrong dialects,
lost exit codes, nested quoting, and irrelevant output. Removing those failures
with templates and parsers is useful even before training. A local model should
interpret ambiguous requests when fixed code cannot. Sending it an already exact
typed plan adds no value.

The frontier model still supplies the intent, relevant environment, and requested
evidence. It does not need to generate the whole PowerShell program or ingest the
full log. Whole-operation latency includes that handoff, model prefill and decoding,
validation, shell startup, command execution, output extraction, and any retry.

## Local data

`prepare.py` audits an existing `records_annotated.jsonl`. It conservatively mines
single successful literal `Get-Content` commands with a bounded head/tail count.
Historical paths become synthetic fixture paths; their natural-language requests
are generated from the commands, **not recovered user intent**. Whole historical
sessions are grouped into train or historical holdout. This is deliberately a
small seed rather than treating every successful process as a correct action.

The initial pilot has 486 training cases (420 synthetic, 66 historical-command
derivatives), 28 validation cases, 56 synthetic test cases, and 20 historical read
holdouts. Generated test wording and paths differ from training, but the operations
and log families are shared. This tests transfer within the narrow contract,
not independent real-world generalization. Evidence fixtures contain three relevant
lines, routine progress, a log-injection decoy, and some exit-zero/error and truncated
output cases. The deterministic filter knows those structured log families.

`extract_full.py` additionally recovers native completed-command events from old
Codex transcripts. It ignores pasted transcripts and approval-review text. That
format is not available in every historical session. The output remains private,
with source pointers, exit codes, truncation flags, and unverified preceding context.
It is not silently added to training. Each output is capped at 200,000 characters,
with an explicit flag; original transcript pointers remain available.

All corpora, prompts, predictions, adapters, and downloaded dependencies live in
ignored `work/` or `.venv/`. Do not publish raw transcripts or model weights without
reviewing what the training set contains and explicitly authorizing publication.

## Reproduce on Windows

Use Python 3.12. The dependency-free preparation and Ollama benchmark work with
the system Python. Training uses the separate environment. The recorded pilot
used CUDA PyTorch 2.11.0+cu128, Transformers 4.57.6, PEFT 0.20.0, and Ollama 0.33.3.

```powershell
python -m unittest discover -s experiments/command_specialist -p 'test_*.py' -v
python experiments/command_specialist/prepare.py --corpus '<private records_annotated.jsonl>'
python experiments/command_specialist/extract_full.py
ollama pull qwen2.5-coder:1.5b
ollama pull qwen3.5:0.8b
python experiments/command_specialist/benchmark.py --model qwen2.5-coder:1.5b
python experiments/command_specialist/benchmark.py --model qwen3.5:0.8b
python experiments/command_specialist/benchmark.py --model rules
```

Do not run inference benchmarks alongside GPU training. Keep models warm for the
warm-request measurements; the initial warm-up and load time are reported separately.
The two downloaded models use different default quantization: Q4_K_M for the 1.5B
coder and Q8_0 for the 0.8B. Their results compare practical downloaded configurations,
not parameter count alone. Before/after training must use the same base and runtime.

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install --no-cache-dir torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128
.venv/Scripts/python.exe -m pip install --no-cache-dir transformers==4.57.6 peft==0.20.0 accelerate==1.15.0 safetensors
ollama stop qwen2.5-coder:1.5b
ollama stop qwen3.5:0.8b
.venv/Scripts/python.exe experiments/command_specialist/train.py
```

Training uses response-only loss, rank-16 LoRA on attention projections, BF16 frozen
base weights, gradient checkpointing, batch 1 with four-example accumulation,
two epochs, and a 2,048-token ceiling. Overlength examples fail rather than silently
losing their answer labels. The test set is never used to train or select checkpoints.

For fast inference, use the official llama.cpp `convert_lora_to_gguf.py` and load its
GGUF adapter into Ollama on **the same** Qwen2.5-Coder-1.5B-Instruct base. `--base`
accepts the downloaded snapshot directory. A Modelfile contains:

```text
FROM qwen2.5-coder:1.5b
ADAPTER <absolute path to the converted adapter.gguf>
```

Create a local model with `ollama create shell-specialist-pilot -f <Modelfile>`, then
run `benchmark.py --model shell-specialist-pilot`. This creates a local model only.
New benchmark attempts need distinct `--label` values; existing result files are
preserved. The same applies to dataset and adapter output directories.

Once the model is created, try a read-only request against an explicitly chosen root:

```powershell
python experiments/command_specialist/run.py --root '<directory>' --request 'Read the last 5 lines of "build.log".'
```

The CLI prints the plan, result, status, and measured latency. It also saves the full
raw result locally. `--evidence-request` enables experimental line selection; returned
stderr is always handled separately. A bounded or rejected selection is flagged and
the full raw artifact remains available. The CLI is a pilot, not an installed host
integration or a replacement for authorization checks.

For the pilot's UTF-8 file tasks, `--backend native` uses direct Python equivalents
instead of starting PowerShell. The benchmark still checks their results against
the PowerShell reference. This isolates process-startup savings; it is not a claim
that arbitrary commands can run without a shell. Native Unicode comparison,
encoding handling, and JSON behavior are not a complete PowerShell emulation.

```powershell
python experiments/command_specialist/benchmark.py --model shell-specialist-pilot --backend native --label trained-native
python experiments/command_specialist/run.py --backend native --root '<directory>' --request 'Read the last 5 lines of "build.log".'
```

## What the scores do and do not mean

Command success compares actual fixture results against a reference command, not
just exact command text. Evidence success requires the exact relevant line set;
recall and precision are also reported. Invalid JSON, invalid plans, timeouts, and
invalid line selections count as failures. The runtime guarantees verbatim selected
text, but cannot guarantee that the model selected all relevant evidence.

`rules` is a real non-ML evidence-selection baseline. `deterministic` is an oracle
typed-input latency floor; it must not be presented as natural-language accuracy.
Character reduction is labeled as characters. `token_audit.py` measures successful
evidence outputs with the specified local tokenizer; that is not automatically the
frontier provider's billing tokenizer. No dollar savings are measured here.

The original frozen test contains 40 planning and 16 extraction cases. A single
run on such a small synthetic set cannot establish reliability, frontier superiority,
20x whole-operation speed, or a production deployment gate.

## Next experiment

The next data-recovery and smaller-model stage is documented in
[RECOVERY_RESULTS.md](RECOVERY_RESULTS.md), with reproduction commands in
[DATA_PIPELINE.md](DATA_PIPELINE.md#static-recovery-and-expanded-training).

Recover real request/command/result triples, retain the known environment and
requested evidence, and label actual task outcomes. Add Bash, multi-step reads,
ambiguous requests, no-match cases, and abstention only as separately testable
capabilities. Split by session, repository, time, and near-duplicate task template.
Freeze a larger independent set before training. Compare the same intent, fixtures,
tool permissions, output contract, retries, and warm/cold conditions against a named
frontier endpoint. Report failures and fallback rate, not only answered cases.

Integrate only once measured gains survive the whole host operation. Expensive or
destructive actions retain the host's permission checks; model output never grants
authorization. Keep full raw results retrievable when a compact packet is insufficient.
