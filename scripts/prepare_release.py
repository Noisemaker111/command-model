"""Generate patch notes and a frozen release PR; only Jon merges main."""
import argparse
import json
from pathlib import Path
import re
import subprocess

REPO = "Noisemaker111/command-model"


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8", timeout=60).stdout.strip()


def prepare(candidate=None):
    command("git", "fetch", "origin", "agents", "main")
    candidate = candidate or command("git", "rev-parse", "origin/agents")
    if not re.fullmatch(r"[0-9a-f]{40}", candidate):
        raise ValueError("candidate must be a full commit ID")
    command("git", "merge-base", "--is-ancestor", candidate, "origin/agents")
    stable = command("git", "rev-parse", "origin/main")
    command("git", "merge-base", "--is-ancestor", stable, candidate)
    if not command("git", "diff", "--name-only", stable, candidate):
        return {"release": "no changes"}
    existing = json.loads(command("gh", "pr", "list", "--repo", REPO, "--base", "main", "--state", "open", "--json", "headRefName,url"))
    releases = [p for p in existing if p["headRefName"].startswith("release/agents-")]
    if releases:
        return {"release": "existing batch preserved for Jon", "url": releases[0]["url"]}
    subjects = command("git", "log", "--first-parent", "--reverse", "--format=%s", f"{stable}..{candidate}").splitlines()
    if not subjects:
        raise ValueError("No release changes were found")
    notes = (f"<!-- release-candidate: {candidate} -->\n<!-- release-base: {stable} -->\n"
             "## Patch notes\n\n" + "\n".join(f"- {subject}" for subject in subjects) +
             f"\n\n[Full release diff](https://github.com/{REPO}/compare/{stable}...{candidate})\n\n"
             "## Merge and verification\n\nOnly Jon merges this PR into main. Agents must not enable auto-merge or perform the stable merge. "
             "This candidate is frozen; later agents changes belong to a later batch.\n\n"
             "Required CI runs the Windows binding/contract checks, syntax validation, and frozen-candidate metadata check. "
             "Review the candidate's included PRs for their affected-user-operation evidence; hosted CI does not run the private model. "
             "These patch notes are generated from merged change titles and do not imply additional performance or deployment validation.\n\n"
             f"Previous stable source / rollback target: `{stable}`. No deployment, package publication, or data migration is performed by this helper.\n")
    out = Path("work/releases") / candidate
    out.mkdir(parents=True, exist_ok=True)
    body = out / "patch-notes.md"
    body.write_text(notes, encoding="utf-8")
    branch = f"release/agents-{candidate[:12]}"
    remote = command("git", "ls-remote", "origin", f"refs/heads/{branch}")
    if remote and remote.split()[0] != candidate:
        raise ValueError("Release branch already points elsewhere; refusing to move it")
    if not remote:
        command("git", "push", "origin", f"{candidate}:refs/heads/{branch}")
    url = command("gh", "pr", "create", "--repo", REPO, "--base", "main", "--head", branch,
                  "--title", "Release verified agents changes to main", "--body-file", str(body))
    receipt = {"release": "ready for Jon after CI", "url": url, "candidate": candidate, "notes": str(body.resolve())}
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate")
    print(json.dumps(prepare(parser.parse_args().candidate)))
