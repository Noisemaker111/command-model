# Agents and main

`agents` is the development integration branch. `main` is the stable installation
branch. Jon authorized agents-branch automation on September 10, 2026: agents may
prepare owned changes, verify them, open ready PRs against `agents`, and merge them
when the gates below pass. This replaces per-PR human merge requests for `agents`.
Only Jon personally merges release PRs into `main`. Agents must never merge main,
enable its auto-merge, or push directly to it, even after chat approval. Publication,
deployments, model/weight changes, and production data changes need separate approval.
This agents automation applies to every agent acting for a maintainer with live
repository write, maintain, or admin permission; no particular model/host is privileged.

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
a privileged merge token. `agents` requires this GitHub Actions check and an up-to-date PR, prevents force
pushes/deletion, and applies protection to administrators. No approving review is
required for `agents`. Main requires the same CI/PR gate; Jon performs the merge
himself. A separate approving reviewer is not required because Jon authors these
PRs through the same account. The platform cannot distinguish Jon from an agent
using his credentials; the human-only merge rule is enforced by this workflow and
the coordinator's unconditional refusal of main.

The local coordinator is `scripts/integrate_agents.py`. After reviewing the diff,
verifying the current head locally, and waiting for CI, run:

```
python scripts/integrate_agents.py --pr <number> --verified-head <verified-head>
```

It accepts only ready same-repository PRs targeting `agents` when both the PR author
and the acting account have live write/maintain/admin permission; checks the exact head, workflow identity/result, and mergeability; and
merges with GitHub's expected-head condition. It refuses `main`. `--check-only`
checks eligibility without merging. Invoke it from a trusted checkout; passing a
head is the agent's attestation of actual local verification, not proof supplied
by CI. Every maintainer's agent uses this same automatic integration path; it does not
require Jon to run the command. It is agent-operated, not an unattended scheduler.
The agent continues through merge and merged-revision verification without asking
Jon for routine agents integration approval. Each successful merge automatically
runs `scripts/prepare_release.py`: it generates patch notes from merged change
titles and opens a frozen main release PR. An existing open release batch is
preserved; later agents changes wait for the next batch. Release preparation may
be resumed with `python scripts/prepare_release.py`; this never merges main.

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
changes must not join that candidate silently. CI checks the candidate identity
and generated patch notes via `scripts/check_release.py`, in addition to core
checks. Ask Jon to merge the CI-green release PR himself; agents stop before main. The agents GitHub PR/check gates are enforced, but this account is shared
by Jon and agents: human authorization is a workflow rule, not an independently
verified GitHub reviewer identity. The coordinator cannot merge stable. No package
or runtime deployment is implied by either merge.
