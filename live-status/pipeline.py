"""End-to-end data pipeline: mine -> label -> judge -> regenerate rejects -> build dataset.

GPU stages (baseline, train, export, evaluate, mine_failures) are separate commands
because their model choices come from the previous stage's measurements.
"""
from __future__ import annotations

import json

from common import home, read_jsonl


def regenerate_rejects(version: str) -> dict:
    """Second teacher attempt for rejected labels, with the judge's notes as feedback."""
    from judging.judge import judge_all
    from labeling.teacher import generate

    path = home() / "datasets" / version / "rejected.jsonl"
    if not path.exists():
        return {"regenerated": 0}
    rejected = [r for r in read_jsonl(path) if r["reason"] == "low_score"]
    if not rejected:
        return {"regenerated": 0}
    ids = home() / "labels" / f"regen-{version}.txt"
    ids.write_text("\n".join(r["id"] for r in rejected), encoding="utf-8")
    feedback = {r["id"]: {"output": r["status"], "notes": r.get("notes")} for r in rejected}
    g = generate(ids_file=str(ids), feedback=feedback)
    j = judge_all(only_ids={r["id"] for r in rejected})
    return {"regenerated": len(rejected), "teacher": g, "judge": j}


def run(args) -> dict:
    from data_miner.mine import run_all
    from dataset_build.build import build
    from judging.judge import judge_all
    from labeling.teacher import generate

    out = {}
    if not args.skip_mining:
        out["mining"] = run_all()["dedup"]
    out["teacher"] = generate(limit=args.label_limit)
    out["judge"] = judge_all()
    out["dataset"] = build()
    out["regenerate"] = regenerate_rejects("v1")
    if out["regenerate"]["regenerated"]:
        out["dataset"] = build()
    (home() / "reports" / "pipeline_last.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
