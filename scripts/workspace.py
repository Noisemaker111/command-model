"""Select a source channel and create independent, fresh session worktrees."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import uuid


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True,
        text=True, encoding="utf-8", timeout=90,
    ).stdout.strip()


def state_directory(repo):
    return Path(git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "workspace-selector"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def selected(repo):
    path = state_directory(repo) / "selection.json"
    channel = json.loads(path.read_text(encoding="utf-8"))["channel"] if path.exists() else "agents"
    if channel not in ("agents", "main"):
        raise ValueError("Invalid saved channel")
    return channel


def create(repo, name="session"):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}", name):
        raise ValueError("Name must be 1-48 letters, digits, underscores or hyphens")
    channel = selected(repo)
    # Private fetch refs prevent races with other sessions fetching origin.
    fetch_ref = "refs/workspace-selector/" + uuid.uuid4().hex
    try:
        git(repo, "fetch", "--no-write-fetch-head", "origin", f"refs/heads/{channel}:{fetch_ref}")
        revision = git(repo, "rev-parse", fetch_ref)
    finally:
        git(repo, "update-ref", "-d", fetch_ref)
    state = state_directory(repo)
    root = Path(git(repo, "worktree", "list", "--porcelain").splitlines()[0].removeprefix("worktree "))
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    path = root / ".worktrees" / "sessions" / (channel + "-" + name + "-" + identifier)
    branch = "session/" + name + "-" + identifier
    git(repo, "worktree", "add", "-b", branch, str(path), revision)
    receipt = dict(channel=channel, revision=revision, branch=branch, path=str(path), created_at=identifier)
    write_json(state / "sessions" / (identifier + ".json"), receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("agents", "main", "status"):
        commands.add_parser(command)
    new = commands.add_parser("new")
    new.add_argument("--name", default="session")
    new.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.command in ("agents", "main"):
            write_json(state_directory(args.repo) / "selection.json", {"channel": args.command})
            print(f"Selected {args.command} for new workspaces only.")
        elif args.command == "status":
            print(selected(args.repo))
        else:
            receipt = create(args.repo, args.name)
            print(json.dumps(receipt) if args.json else receipt["path"])
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Workspace creation/selection failed: {error}\n")


if __name__ == "__main__":
    main()
