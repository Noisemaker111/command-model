"""Summarize semantic evaluation failures without printing private commands."""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("output", type=Path)
    p.add_argument("--examples", type=int, default=12)
    args = p.parse_args()
    rows = [json.loads(line) for line in args.output.read_text(encoding="utf-8").splitlines() if line.strip()]
    failed = [r for r in rows if r.get("jev") and r["jev"].get("score", 0) < 0.45]
    by_tag: collections.Counter[str] = collections.Counter()
    reasons: collections.Counter[str] = collections.Counter()
    for row in failed:
        by_tag.update(row.get("tags") or [])
        grade = row["jev"]
        if grade.get("invented", 0) > 0.5:
            reasons["invented"] += 1
        if grade.get("same", 0) <= 0.5:
            reasons["different_actions"] += 1
        if grade.get("quality", 0) < 2.5:
            reasons["low_quality"] += 1
    print(json.dumps({
        "rows": len(rows),
        "failed": len(failed),
        "failure_reasons": reasons.most_common(),
        "failure_tags": by_tag.most_common(20),
        "schema": sorted(rows[0]) if rows else [],
        "examples": [{
            "shell": r.get("shell"),
            "length": len(r.get("command", "")),
            "tags": r.get("tags"),
            "reference": r.get("reference") or r.get("status"),
            "output": r.get("output"),
            "grade": r.get("jev"),
        } for r in failed[:args.examples]],
    }, indent=2))


if __name__ == "__main__":
    main()
