"""Deterministic statuses for commands simple enough to need no model.

`describe()` returns (status, confidence). Confidence >= FAST_PATH means the service
may skip the model; lower values are only used as a fallback when inference fails.
"""
from __future__ import annotations

import re

from parsers.shell import ACTIONS, Structure, analyze

FAST_PATH = 0.9

GIT = {
    "status": "Checking Git status", "diff": "Reviewing the Git diff", "log": "Reading the Git log",
    "fetch": "Fetching from the Git remote", "pull": "Pulling the latest changes", "push": "Pushing commits",
    "add": "Staging changes", "commit": "Committing changes", "checkout": "Switching Git branches",
    "switch": "Switching Git branches", "branch": "Checking Git branches", "show": "Showing a Git commit",
    "stash": "Stashing changes", "rebase": "Rebasing the branch", "merge": "Merging branches",
    "clone": "Cloning a repository", "worktree": "Managing Git worktrees", "remote": "Checking Git remotes",
    "rev-parse": "Resolving Git revisions", "restore": "Restoring files", "reset": "Resetting Git state",
    "tag": "Checking Git tags", "ls-files": "Listing tracked files", "blame": "Reading Git blame",
    "grep": "Searching the repository", "cherry-pick": "Cherry-picking a commit", "init": "Initializing a Git repository",
}
GH = {"pr": "pull requests", "issue": "issues", "run": "workflow runs", "api": "the GitHub API", "repo": "the repository",
      "release": "releases", "workflow": "workflows", "auth": "GitHub authentication", "search": "GitHub"}
PKG_VERB = {"install": "Installing", "i": "Installing", "add": "Adding", "ci": "Installing", "remove": "Removing",
            "uninstall": "Removing", "update": "Updating", "upgrade": "Upgrading", "list": "Listing", "outdated": "Checking outdated"}


def _name(target: str) -> str:
    return target.strip("\"'").rstrip("/\\")


def _join(items: list[str]) -> str:
    items = list(dict.fromkeys(i for i in items if i))
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (", and " if len(items) > 2 else " and ") + items[-1]


def _one(a, st: Structure) -> tuple[str, float] | None:
    t, targets, sub = a.type, [_name(x) for x in a.targets], a.sub
    if t == "read_file" and targets:
        return f"Reading {_join(targets)}", 0.95
    if t == "list_dir" and a.exe == "test-path":
        return (f"Checking whether {targets[0]} exists", 0.92) if targets else None
    if t == "list_dir" and a.exe in ("which", "where", "get-command", "command"):
        return (f"Locating {targets[-1]}", 0.9) if targets else None
    if t == "list_dir":
        return (f"Listing files in {targets[0]}", 0.92) if targets else ("Listing files in the current directory", 0.9)
    if t == "search" and a.targets:
        return "Searching files" + (f" in {targets[-1]}" if len(targets) > 1 else ""), 0.75
    if t == "process_check" and a.exe in ("get-process", "ps", "tasklist", "pgrep") :
        return (f"Checking {_join(targets)} processes", 0.95) if targets else ("Checking running processes", 0.9)
    if t == "wait" and targets:
        unit = "milliseconds" if any(x.lower() in ("-milliseconds", "-m") for x in a.args) else "seconds"
        return (f"Waiting {targets[0]} {unit}", 0.95) if a.exe in ("sleep", "start-sleep") else (f"Waiting for {targets[0]}", 0.6)
    if t == "git" and sub in GIT:
        return GIT[sub], 0.92
    if t == "github" and sub in GH:
        return f"Checking {GH[sub]} with the GitHub CLI", 0.75
    if t == "package" and sub:
        head = sub.split()[0]
        if head in PKG_VERB:
            return f"{PKG_VERB[head]} {a.exe} packages", 0.85
        if head in ("run", "exec", "x") and " " in sub:
            script = sub.split()[1]
            return (f"Running {script} with {a.exe}" if script.lower() in ACTIONS else f"Running the {script} script with {a.exe}"), 0.85
    if t in ("build", "test") and sub and a.exe in ("npm", "pnpm", "yarn", "bun", "bunx", "npx", "uv", "cargo", "go", "dotnet"):
        script = sub.split()[-1]
        if script in ("test", "tests"):
            return f"Running tests with {a.exe}", 0.85
        return f"Running {script} with {a.exe}", 0.85
    if t == "build":
        return f"Building with {a.exe}", 0.8
    if t == "test":
        return f"Running tests with {a.exe}" if a.exe not in ("python", "py", "python3") else "Running Python tests", 0.8
    if t == "delete" and targets:
        return f"Deleting {_join(targets)}", 0.9
    if t == "network" and targets:
        return f"Fetching {targets[0]}", 0.7
    if t == "run_script" and targets and not st.has_inline_script:
        return f"Running {targets[0]}", 0.8
    if t == "env" and a.exe in ("pwd", "get-location"):
        return "Checking the current directory", 0.95
    return None


def describe(command: str, shell: str | None = None, structure: Structure | None = None) -> tuple[str, float]:
    st = structure or analyze(command, shell)
    meaningful = [a for a in st.actions if a.type not in ("format", "env")] or st.actions
    if not meaningful:
        return "Running a shell command.", 0.2
    parts, confs = [], []
    for a in meaningful[:4]:
        one = _one(a, st)
        if one is None:
            parts.append(f"running {a.exe}" if a.exe and len(a.exe) < 30 else "running a command")
            confs.append(0.3)
        else:
            parts.append(one[0][0].lower() + one[0][1:] if parts else one[0])
            confs.append(one[1])
    parts = list(dict.fromkeys(parts))
    text = _join(parts) if len(parts) > 1 else parts[0]
    text = text[0].upper() + text[1:]
    if len(meaningful) > 4:
        text += ", and more"
    conf = min(confs) * (1.0 if len(meaningful) == 1 else 0.8)
    if st.loops or st.conditionals or st.has_inline_script:
        conf *= 0.5
    return text.rstrip(".") + ".", round(conf, 3)
