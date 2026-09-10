# Command specialist

Build a small, fast local model and execution loop that does command/cell work for
frontier agents. Accept English intent and known context, perform the mechanical
work, inspect real outcomes, repair ordinary failures, and return compact verified
evidence with retrievable raw output. Each delegation gets a fresh, bounded worker
lifecycle. A generated program or claimed success is not completion.

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
