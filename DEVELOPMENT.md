# Development workflow

`agents` is the development integration branch. `main` is the stable installation
branch. Jon authorized agents-branch automation on September 10, 2026: agents may
prepare owned changes, verify them, open ready PRs against `agents`, and merge them
when the gates below pass. This replaces per-PR human merge requests for `agents`.
Jon reaffirmed that authorization in chat on September 10, 2026 after an external
approval control rejected a merge. The explicit authorization is also recorded
directly in root AGENTS.md so readers need not infer it from this policy link.
Only Jon personally merges release PRs into `main`. Agents must never merge main,
enable its auto-merge, or push directly to it, even after chat approval. Publication,
deployments, model/weight changes, and production data changes need separate approval.
This agents automation applies to every agent acting for a maintainer with live
repository write, maintain, or admin permission; no particular model/host is privileged.

Start from fetched `agents` in an owned worktree. Preserve other sessions and reuse
existing PRs for the same work. Run commands from the repository root with Python
3.12. Required checks are:

```
python -m compileall -q scripts skills experiments/command_model
python -m unittest discover -s experiments/command_model -p test_bindings.py -v
python -m unittest discover -s experiments/command_model -p test_contract.py -v
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
Jon for routine agents integration approval. Routine integration does not prepare or announce releases. Only when Jon explicitly
requests release work, run `python scripts/prepare_release.py` to generate patch
notes and a frozen release PR. It preserves an existing open batch and never merges
main. Do not display release PR numbers; use a descriptive link when release work
was requested. Do not invite Jon to release during ordinary development.

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
checks. Only act on explicit release requests; Jon performs the merge himself. Do not
announce release readiness during normal work. The agents GitHub PR/check gates are enforced, but this account is shared
by Jon and agents: human authorization is a workflow rule, not an independently
verified GitHub reviewer identity. The coordinator cannot merge stable. No package
or runtime deployment is implied by either merge.

## Switching branches

Use the shared `agents-and-main` skill command: `sb agents` or `sb main` inside
the intended project checkout. It switches the branch and fast-forwards from
origin; Git retains the selection. Install the command once from the skill's
`scripts/install.ps1`. No project-specific launcher or selection state is needed.

Switch only a checkout you own. Agents keep active work in isolated worktrees;
the command refuses dirty checkouts and branches owned by another worktree.
It does not move existing sessions or reload running processes.
