"""Failure-driven data growth: run the student on unlabeled commands, find what it gets wrong,
label those with the teacher, and record preference pairs for DPO.

  python live-status/cli.py mine_failures --backend ollama:live-status-smol135 --round r1 --pool 1500

Stage A: screen student outputs, by default with Jev ranking (or an Opus judge pass).
Stage B: failures get teacher candidates and a second judge pass that also sees the
student output, yielding a corrected label and a (chosen, rejected) pair.
Rebuild the dataset afterwards; frozen test/validation families stay put.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import append_jsonl, home, read_jsonl, write_jsonl  # noqa: E402
from evaluation.validators import check  # noqa: E402
from judging.judge import judge_all, latest_judgements  # noqa: E402
from labeling.teacher import generate, load_commands, select, teacher_path  # noqa: E402

PASS_SCORE = 88


def unlabeled_pool(n: int, seed: int) -> list[dict]:
    labeled = {r["id"] for r in read_jsonl(teacher_path())} if teacher_path().exists() else set()
    labeled |= set(latest_judgements())
    rows = [r for r in load_commands() if r["id"] not in labeled]
    return select(rows, n, seed=seed)


def main(argv=None):
    p = argparse.ArgumentParser(prog="mine_failures")
    p.add_argument("--backend", required=True)
    p.add_argument("--round", required=True, help="round tag, e.g. r1")
    p.add_argument("--pool", type=int, default=1000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--screen", choices=["jev", "opus"], default="jev",
                   help="jev: cheap reference-free ranking; opus: judge every student output")
    p.add_argument("--fail-fraction", type=float, default=0.4, help="jev screen: share of lowest-ranked outputs to relabel")
    a = p.parse_args(argv)
    from inference.backends import from_spec

    out_dir = home() / "active" / a.round
    backend = from_spec(a.backend)
    a.seed = a.seed or int.from_bytes(a.round.encode()[:4].ljust(4, b"0"), "little")
    pool = unlabeled_pool(a.pool, a.seed)
    outputs = {}
    for i, r in enumerate(pool, 1):
        try:
            text, _ = backend.generate(r["command_redacted"])
        except Exception as exc:
            text = ""
            print(f"  generation failed: {exc}", flush=True)
        outputs[r["id"]] = text
        if i % 200 == 0:
            print(f"  generated {i}/{len(pool)}", flush=True)
    write_jsonl(out_dir / "student_outputs.jsonl", ({"id": k, "output": v} for k, v in outputs.items()))

    cmds = {r["id"]: r for r in pool}
    failures = []
    if a.screen == "jev":
        # Reference-free Jev ranks outputs (AUC ~0.68 vs Opus); the weakest go to the teacher,
        # plus a random slice so the ranking's misses are still sampled.
        from judging.jev import combined, grade
        invalid = [cid for cid, t in outputs.items() if not t or not check(t, cmds[cid]["command_redacted"])["pass"]]
        rest = [cid for cid in outputs if cid not in set(invalid)]
        graded = grade([(cid, cmds[cid]["command_redacted"], outputs[cid]) for cid in rest])
        ranked = sorted(rest, key=lambda cid: combined(graded[cid]) if "error" not in graded[cid] else -1)
        k = int(len(ranked) * a.fail_fraction)
        tail = ranked[k:]
        rng = random.Random(a.seed)
        failures = invalid + ranked[:k] + rng.sample(tail, min(len(tail), max(1, k // 5)))
        write_jsonl(out_dir / "jev_screen.jsonl", ({"id": cid, **graded[cid]} for cid in rest))
    else:
        screen = {k: {"m": v} for k, v in outputs.items() if v}
        print(json.dumps({"stage": "A", **judge_all(extra=screen, teacher=False, only_ids=set(screen), workers=a.workers)}), flush=True)
        judged = latest_judgements()
        for cid, text in outputs.items():
            j = judged.get(cid)
            verdict = (j or {}).get("verdicts", {}).get("m", {}) if j else {}
            ok = bool(text) and verdict.get("correct") and verdict.get("score", 0) >= PASS_SCORE and check(text, cmds[cid]["command_redacted"])["pass"]
            if not ok:
                failures.append(cid)
    ids_file = out_dir / "failure_ids.txt"
    ids_file.write_text("\n".join(failures), encoding="utf-8")
    print(json.dumps({"pool": len(pool), "failures": len(failures), "failure_rate": round(len(failures) / max(1, len(pool)), 3)}), flush=True)

    if failures:
        print(json.dumps({"stage": "B-teacher", **generate(ids_file=str(ids_file), workers=a.workers)}), flush=True)
        extra = {cid: {"m": outputs[cid]} for cid in failures if outputs[cid]}
        print(json.dumps({"stage": "B-judge", **judge_all(only_ids=set(failures), extra=extra, workers=a.workers)}), flush=True)
    judged = latest_judgements()
    prefs = []
    for cid in failures:
        j = judged.get(cid)
        if not j or not outputs[cid]:
            continue
        chosen = j["recommended_output"]
        if chosen.strip() != outputs[cid].strip() and j["validators"]["pass"] and (j.get("recommended_score") or 0) >= 85:
            prefs.append({"id": cid, "command": cmds[cid]["command_redacted"], "chosen": chosen,
                          "rejected": outputs[cid], "round": a.round})
    append_jsonl(home() / "labels" / "prefs.jsonl", prefs)
    summary = {"round": a.round, "backend": backend.name, "pool": len(pool), "failures": len(failures), "pref_pairs": len(prefs)}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
