# Command Model

"Our model", "the model we are building", and "Command Model" refer to this
project. Shell Gatherer is only the collection component in skills/shell-gatherer.
Mining, labeling, execution verification, datasets and training are downstream
steps. Do not describe gathered observations as verified training examples.

Build a small, fast local model and execution loop that does command/cell work for
frontier agents. Accept English intent and known context, perform the mechanical
work, inspect real outcomes, repair ordinary failures, and return compact verified
evidence with retrievable raw output. Each delegation gets a fresh, bounded worker
lifecycle. A generated program or claimed success is not completion.

Read [project purpose and evidence](experiments/command_model/PURPOSE.md)
before choosing the next experiment. The frontier owns reasoning and delegation;
the worker owns bounded mechanical implementation and verified evidence. The
486-example inspection/evidence adapter is not an English code-execution-trained
model. Keep product intent, trained capability and measured behavior distinct.

Prioritize a correct grounded handoff through the real frontier host, then a
matched normal-shell comparison. Do not substitute model-size, training-speed,
or local inference experiments for that outcome. Tie supporting experiments to
an observed failure or bottleneck and a stated decision. Preserve the successful
single-handoff smoke and failed expanded workload as separate evidence. Never
infer savings from failed tasks, force baseline call counts, or treat missing
input contents as something the model should guess. Distinguish proposed,
unmerged, merged and host-verified behavior in documentation.

Work autonomously: choose the next observed failure or bottleneck, measure it,
make the smallest useful improvement, verify the actual user operation and saved
result, then continue. Coordinate with other agents and existing PRs instead of
duplicating owned work. Do not ask Jon what to do next when evidence supplies it.

Use deterministic code for exact mechanics and the model for interpretation.
Preserve correctness, useful context, output capacity and faithful evidence.
Measure whole handoffs, including repair and fallback; small synthetic probes do
not establish general reliability. Preserve held-out data and the current pilot
model/adapter; keep private corpora and weights out of Git.

Follow [DEVELOPMENT.md](DEVELOPMENT.md) for checks, isolation, maintainer permissions
and automatic agents integration. Keep release details out of routine reports.
Jon initiates release work. Report observed improvements, failures and limitations.
