"""Integrate a locally verified, CI-green owner PR into agents; never main.

Run from a trusted agents checkout after inspecting the diff and completing the
real user-operation check. No PR code is downloaded or executed by this tool.
"""
import argparse
import json
import re
import subprocess

REPO = "Noisemaker111/shell-forensics"
OWNER = "Noisemaker111"


def gh(*args):
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True, encoding="utf-8", timeout=60)
    return json.loads(result.stdout) if result.stdout.strip() else None


def eligible(pr, verified_head):
    if pr["baseRefName"] != "agents":
        raise ValueError("Only agents PRs may be integrated; main needs Jon's explicit batch approval")
    if pr["state"] != "OPEN" or pr["isDraft"] or pr["isCrossRepository"] or pr["author"]["login"].lower() != OWNER.lower():
        raise ValueError("Require an open, ready, same-repository owner PR")
    if pr["headRefOid"] != verified_head:
        raise ValueError("Head changed or was not locally verified; recheck the actual user operation")
    if pr["mergeable"] != "MERGEABLE" or pr["mergeStateStatus"] != "CLEAN":
        raise ValueError("PR must be up to date, mergeable, and pass branch protection")
    checks = pr["statusCheckRollup"]
    core = [c for c in checks if c.get("name") == "Windows core"]
    if not core or any(c.get("status") != "COMPLETED" or c.get("conclusion") != "SUCCESS" for c in core):
        raise ValueError("Windows core is missing, pending, or unsuccessful")
    if any(c.get("conclusion") not in ("SUCCESS", "NEUTRAL", "SKIPPED") or c.get("status") != "COMPLETED" for c in checks):
        raise ValueError("A check is incomplete or unsuccessful")
    return core


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--verified-head", required=True, help="Exact head already reviewed and verified through the product")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    fields = "state,isDraft,isCrossRepository,author,baseRefName,headRefOid,mergeable,mergeStateStatus,statusCheckRollup"
    pr = gh("pr", "view", str(args.pr), "--repo", REPO, "--json", fields)
    checks = eligible(pr, args.verified_head)
    for check in checks:
        match = re.fullmatch(r"https://github\.com/Noisemaker111/shell-forensics/actions/runs/(\d+)/job/\d+", check.get("detailsUrl", ""))
        if not match:
            raise ValueError("Required check is not the repository Actions job")
        run = gh("api", f"repos/{REPO}/actions/runs/{match[1]}")
        if (run["path"] != ".github/workflows/agent-checks.yml" or run["event"] != "pull_request"
                or run["head_sha"] != args.verified_head or run["conclusion"] != "success"):
            raise ValueError("Required workflow does not validate this PR head")
    # Server-side strict checks and the expected-head condition close update races.
    latest = gh("pr", "view", str(args.pr), "--repo", REPO, "--json", fields)
    eligible(latest, args.verified_head)
    if args.check_only:
        print(json.dumps({"eligible": True, "pr": args.pr, "base": "agents"}))
        return
    subprocess.run(["gh", "pr", "merge", str(args.pr), "--repo", REPO, "--squash", "--match-head-commit", args.verified_head], check=True, timeout=60)
    receipt = gh("pr", "view", str(args.pr), "--repo", REPO, "--json", "state,baseRefName,mergeCommit,url")
    if receipt["state"] != "MERGED" or receipt["baseRefName"] != "agents":
        raise RuntimeError("Merge receipt did not confirm agents integration")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
