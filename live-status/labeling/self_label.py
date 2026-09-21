"""Label commands without a paid model: the student writes candidates, Jev picks one.

  python live-status/cli.py self_label --backend ollama:live-status-v1b-qwen3-06b-lora-q4_k_m --pool 8000

Jev cannot write text, but a Choice/Score returns one of the options it was given, so a local
sampler supplies 4-5 candidates per command (well inside Jev's 255-option limit) and Jev
selects. Measured on the 583-command v1 test set against gold labels:

  greedy decoding            69.1% accepted
  random sample              61.1%
  Jev Choice over the pool   76.3%
  Jev score over the pool    77.4%   <- used here
  oracle (best in pool)      83.9%

Kept labels are gated on the selector's own score; at the default 0.30 the gate keeps 66% of
commands at 89.6% precision (`evaluation/self_label_threshold.json`). Rejected commands are
written to `needs_teacher.txt` for a paid pass. Self-labels are training-only: held-out gold
is never overwritten (see `datasets/gold_lock.json`).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import append_jsonl, home, read_jsonl, save_json  # noqa: E402
from evaluation.validators import check  # noqa: E402
from judging.jev import combined, grade  # noqa: E402
from judging.judge import latest_judgements  # noqa: E402
from labeling.teacher import load_commands, select, teacher_path  # noqa: E402
from redaction.redact import find_secrets  # noqa: E402

KEEP_THRESHOLD = 0.30
SELF_VERSION = "self-jev-v1"


def self_labels_path() -> Path:
    return home() / "labels" / "self_labels.jsonl"


def load_self_labels() -> dict[str, dict]:
    if not self_labels_path().exists():
        return {}
    return {r["id"]: r for r in read_jsonl(self_labels_path())}


def pool_for(n: int, seed: int) -> list[dict]:
    labeled = {r["id"] for r in read_jsonl(teacher_path())} if teacher_path().exists() else set()
    labeled |= set(latest_judgements()) | set(load_self_labels())
    return select([r for r in load_commands() if r["id"] not in labeled], n, seed=seed)


def candidates(backend, command: str, k: int) -> list[str]:
    out = []
    greedy, _ = backend.generate(command)
    if greedy:
        out.append(greedy)
    for i in range(k):
        text, _ = backend.generate(command, temperature=0.8, seed=1000 + i)
        if text and text not in out:
            out.append(text)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="self_label")
    p.add_argument("--backend", required=True)
    p.add_argument("--pool", type=int, default=2000)
    p.add_argument("--samples", type=int, default=4)
    p.add_argument("--threshold", type=float, default=KEEP_THRESHOLD)
    p.add_argument("--seed", type=int, default=20260917)
    p.add_argument("--ids", help="label these command ids instead of an automatic pool")
    a = p.parse_args(argv)
    from inference.backends import from_spec

    backend = from_spec(a.backend)
    if hasattr(backend, "warm"):
        backend.warm()
    if a.ids:
        wanted = set(Path(a.ids).read_text(encoding="utf-8").split())
        rows = [r for r in load_commands() if r["id"] in wanted]
    else:
        rows = pool_for(a.pool, a.seed)
    done = load_self_labels()
    rows = [r for r in rows if r["id"] not in done]
    t0 = time.time()
    pools: dict[str, list[str]] = {}
    for i, r in enumerate(rows, 1):
        cmd = r["command_redacted"]
        if find_secrets(json.dumps(cmd)):
            continue
        pools[r["id"]] = [c for c in candidates(backend, cmd, a.samples) if check(c, cmd)["pass"]]
        if i % 250 == 0:
            print(f"  generated {i}/{len(rows)} in {round(time.time() - t0)}s", flush=True)
    by_id = {r["id"]: r for r in rows}
    graded = grade([(f"{cid}|{i}", by_id[cid]["command_redacted"], c)
                    for cid, cands in pools.items() for i, c in enumerate(cands)])
    kept, rejected = [], []
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    for cid, cands in pools.items():
        best, text = -1.0, None
        for i, c in enumerate(cands):
            g = graded.get(f"{cid}|{i}")
            if g and "error" not in g and combined(g) > best:
                best, text = combined(g), c
        if text is None:
            rejected.append(cid)
            continue
        row = {"id": cid, "status": text, "score": round(best, 4), "candidates": len(cands),
               "source": SELF_VERSION, "selector": "jev", "generator": backend.name, "ts": now}
        (kept if best >= a.threshold else rejected).append(row if best >= a.threshold else cid)
    append_jsonl(self_labels_path(), kept)
    out_dir = home() / "labels"
    (out_dir / "needs_teacher.txt").write_text("\n".join(rejected), encoding="utf-8")
    summary = {"pool": len(rows), "generated": len(pools), "kept": len(kept), "needs_teacher": len(rejected),
               "threshold": a.threshold, "generator": backend.name, "seconds": round(time.time() - t0)}
    save_json(out_dir / "self_label_summary.json", summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
