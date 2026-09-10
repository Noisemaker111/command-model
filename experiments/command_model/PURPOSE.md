# Command Model: purpose and evidence

Command Model is the project name. Shell Gatherer collects observations; separate
mining, labeling and verification processes produce saved datasets.

This is the current project direction. Historical reports describe their own
experiments; they do not redefine the product. The goal is to reduce frontier
agent time and token use on command/cell work while preserving task correctness.
Training throughput, model size and isolated inference speed are supporting
measurements, not the product outcome.

## Division of work

The frontier owns the user goal, higher-level reasoning, task decomposition and
whether a result is sufficient to continue. It delegates a bounded mechanical
job in English, with exact known paths, constraints, relevant environment/API
facts and a checkable result. It should not have to write the command or program
that the local worker is supposed to produce.

The local worker owns the delegated implementation: inspect actual inputs,
construct commands or code within the supported executor, execute, inspect the
result and repair ordinary failures. One delegation creates one fresh worker
lifecycle; it can contain several internal actions. It returns compact observed
results and a retrievable raw artifact to the same frontier turn, then ends.
Warm model weights are compatible with fresh task context. A later delegation
receives explicit inputs and prior artifacts, not hidden conversation memory.

The runtime owns exact path binding, input inspection, execution limits, process
cleanup, saved evidence and completion checks. Unknown contents, schemas and API
behavior must be inspected or reported as missing context. They are not details
for the model to guess. Verification must check the requested result: exit zero
or a printed success marker does not establish that saved artifacts are correct.
The frontier owns recovery after an unsuccessful handoff; measure that cost too.

Python is the current trusted local execution prototype, not the definition of
the product. The original PTY startup/cancel job remains a representative future
boundary. The project is neither restricted forever to five reads nor committed
to turning the local worker into an independent general-purpose coding agent.

## What was trained versus what was tested

| Layer | Actual scope | What it does not establish |
| --- | --- | --- |
| Pretrained Qwen2.5-Coder model | Existing coding/instruction abilities before this project | Reliable performance on every local task |
| Preserved pilot LoRA | 486 examples: 366 typed inspection plans and 120 evidence-line selections | Post-training for arbitrary Python writing, repair or multi-step English execution |
| Original inspection runner | Five read/search/list/JSON-field operations and faithful evidence extraction | A complete command/cell delegation product |
| Codex English prototype | A real configured MCP handoff to a fresh local Python worker and return to the originating frontier | Transparent shell replacement, all native per-command permission semantics, or desktop UI verification |
| Expanded ten-stage experiment | Chained/grouped mechanical work with independent artifact assessment | Ten independently arising frontier decisions or ten required native tool calls |

The 486 rows comprised 420 synthetic fixture examples and 66 examples with
synthetic instructions derived from historical read commands. The data pipeline
later recovered 70,611 command observations, not 70,611 gold training examples.
Recorded exit zero does not prove task correctness. See [data results](DATA_RESULTS.md).
The adapter's training objective and the English code-generation objective are
different. A failed broader task cannot by itself establish a model-size ceiling.

## Why the successful frontier handoff was possible

The [single-handoff CSV smoke](codex/RESULTS.md) used the real Codex host and
preserved FP16 specialist adapter. Both arms passed original and changed-input
checks. Normal shell work took 71.075 seconds; English delegation took 43.118
seconds, including 2.813 seconds inside the local worker. Frontier native calls
fell from six to one, alongside one English handoff.

That success demonstrates a working handoff/return path and one successful task.
The pretrained model already had coding ability; the harness could use that even
though the project adapter was trained on a narrower objective. We did not isolate
the adapter's causal contribution. Fewer frontier interactions are a plausible
source of savings, but this single pair also includes different startup, approval
and recovery costs. It does not prove typical savings or general training success.

The [ten-stage pilot](codex/TEN-STAGE-PILOT.md) changed the workload. Normal Codex
batched it into five native calls and passed all original/alternate checks in
93.998 seconds. Ten handoffs took 200.381 seconds and two grouped handoffs took
156.575 seconds; both failed all stage assessments. One local worker satisfied a
stdout marker without creating the required artifact. That exposed a completion
contract defect, not successful execution. Dependent stage failures are not ten
independent estimates of model accuracy.

These observations coexist: one handoff worked and was faster in its smoke;
the expanded task did not. Neither observation should be erased or generalized.
We drifted by treating broader code generation as if it had already been trained,
then pursuing prompts, model capacity and training throughput before closing the
handoff's grounding and correctness gaps.

## Current implementation versus ongoing experiments

The merged prototype and its recorded smokes are documented in the
[English contract](ENGLISH_HANDOFF.md) and [Codex hookup](codex/README.md).
Local work has explored explicit input inspection, artifact acceptance checks,
raw prompt changes, adapter removal, a separate 3B FP16 model and training-speed
profiling. These are diagnostics, not a new verified end-to-end result. Some
runtime changes remain unmerged; a new description is not evidence they are
available through the configured host. Preserve their raw failures and source
identities. Do not transfer old measurements to a changed harness.

The 3B diagnostic runs but partly offloads to CPU at 32K context on the test GPU;
it is not an established replacement. A short-example checkpoint experiment sped
up training on 32 old training rows with identical saved adapter bytes. It neither
trains the English execution objective nor establishes product latency savings.
No new 5,000-example English-execution training run has been completed.

## Next work and decision gates

1. Re-establish one grounded English handoff through the real frontier host.
   Supply observable inputs, preserve actual execution errors, check saved task
   artifacts and replay on changed inputs. Reopen the result received by the
   originating frontier. Start with the previous successful task shape before
   expanding it. Do not count a local-only probe as this verification.
2. Compare that frozen setup with the same frontier doing normal shell work.
   Let the baseline batch naturally. Repeat in alternating order, retain failures,
   and include repair/fallback in total time through frontier completion. Report
   frontier cached/uncached input and output separately from local model tokens;
   token counts are not measured charges. Report independent evaluator time
   separately from user-operation time.
3. Extend to several independently arising jobs and dependent jobs. Distinguish
   mechanical stages, frontier decisions, handoff events and internal actions.
   More handoffs are not inherently better. Choose boundaries for useful work,
   not to inflate the baseline or projected savings.
4. If failure analysis requires training, build execution-verified examples for
   the actual runtime protocol: grounded English jobs, valid implementations,
   actual failures and repairs, and faithful return evidence. Keep frozen held-out
   sessions/families separate; never turn the benchmark answers into training
   targets. Counts alone do not establish coverage. Evaluate accuracy and whole
   handoff cost before promoting a new adapter or model.

Only investigate a lower-level optimization when an observed handoff failure or
bottleneck motivates it. State the connection and the success criterion first.
Do not automatically launch more model comparisons or training-speed work because
an earlier diagnostic made those measurements available. User steering can change
priority; update this direction explicitly instead of silently replacing the goal.
