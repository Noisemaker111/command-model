# Agents and main

`agents` is the development integration branch. `main` is the stable installation
branch. Jon authorized agents-branch automation on September 10, 2026: agents may
prepare owned changes, verify them, open ready PRs against `agents`, and merge them
when the gates below pass. This replaces per-PR human merge requests for `agents`.
Merging into `main`, publication, deployments, model/weight changes, and production
data changes still require explicit approval for the concrete batch.

Start from fetched `agents` in an owned worktree. Preserve other sessions and reuse
existing PRs for the same work. Run commands from the repository root with Python
3.12. Required checks are:

```
python -m compileall -q scripts experiments/command_specialist
python -m unittest discover -s experiments/command_specialist -p test_bindings.py -v
python -m unittest discover -s experiments/command_specialist -p test_contract.py -v
```

Also verify the affected user operation through the public CLI and reopen its saved
artifact. Hosted CI has no private model, GPU, or transcripts; it supplements local
product verification. Do not run live model benchmarks concurrently or change the
shared Ollama service. Retain `shell-specialist-pilot` and its existing adapter.

`.github/workflows/agent-checks.yml` runs the required `Windows core` check on PRs
into both branches and pushes to `agents`. It runs on a hosted Windows runner with
read-only permissions and no persisted checkout credentials. PR code never receives
a privileged merge token. Both branches require this GitHub Actions check and an
up-to-date PR, prevent force pushes/deletion, and apply protection to administrators.
No approving review is required for `agents`.

The local coordinator is `scripts/integrate_agents.py`. After reviewing the diff,
verifying the current head locally, and waiting for CI, run:

```
python scripts/integrate_agents.py --pr <number> --verified-head <verified-head>
```

It accepts only ready same-repository PRs authored by Noisemaker111 targeting
`agents`; checks the exact head, workflow identity/result, and mergeability; and
merges with GitHub's expected-head condition. It refuses `main`. `--check-only`
checks eligibility without merging. Invoke it from a trusted checkout; passing a
head is the agent's attestation of actual local verification, not proof supplied
by CI. This is agent-operated automation, not an installed unattended scheduler.
The agent continues through merge and merged-revision verification without asking
Jon for routine agents integration approval.

This repository is a local skill/CLI, with no hosted frontend, backend, database,
queue, production service, or deployment trigger configured here. Dev validation
runs the merged `agents` revision from an isolated worktree with fresh fixtures and
ignored `work/` artifacts. Stable users continue to install `main`; existing local
installations and sessions are not repointed. No automatic host integration is
claimed. Source revision, loaded CLI source, and saved artifact must agree when
reporting dev verification.

For stable promotion, branch a frozen release candidate from a verified agents
revision and open a ready PR into `main`. Include the full diff, user-facing notes,
verification evidence, and rollback target (the prior main revision). Later agents
changes must not join that candidate silently. Ask Jon to approve that concrete
batch before merging. GitHub PR/check gates are enforced, but this account is shared
by Jon and agents: human authorization is a workflow rule, not an independently
verified GitHub reviewer identity. The coordinator cannot merge stable. No package
or runtime deployment is implied by either merge.
