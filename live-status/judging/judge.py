"""Judge pass: an independent Opus 5 prompt scores every candidate and writes the final label.

Candidates per command: teacher "a"/"b" (and regenerated ones) plus the deterministic
heuristic. Output: labels/judged.jsonl, one row per (command, candidate-set).
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from common import append_jsonl, home, read_jsonl, sha
from evaluation.validators import check
from inference.heuristic import describe
from labeling.llm import DEFAULT_MODEL, QuotaExhausted, chat, parse_results
from labeling.prompts import JUDGE_SYSTEM, JUDGE_VERSION
from redaction.redact import find_secrets

BATCH_CHARS = 30000


def judged_path():
    return home() / "labels" / "judged.jsonl"


def compact_structure(st: dict) -> str:
    acts = [a["type"] + (f"({','.join(a['targets'][:3])})" if a.get("targets") else "") for a in st["actions"][:12]]
    extra = [f"{k}={st[k]}" for k in ("loops", "conditionals", "pipelines") if st.get(k)]
    return "; ".join(acts + extra)


def candidate_sets() -> dict[str, dict]:
    """Latest candidates per command id from all teacher runs."""
    sets: dict[str, dict] = {}
    for row in read_jsonl(home() / "labels" / "teacher.jsonl"):
        if row["missing"]:
            continue
        tag = "r" if "regen" in row["prompt_version"] else "t"
        cur = sets.setdefault(row["id"], {})
        for k, v in row["candidates"].items():
            cur[f"{tag}{k}"] = v
    return sets


def run_batch(items: list[dict], model: str) -> list[dict]:
    payload = [{k: it[k] for k in ("id", "shell", "command", "structure", "candidates")} for it in items]
    text, usage = chat([{"role": "system", "content": JUDGE_SYSTEM},
                        {"role": "user", "content": "Items:\n" + json.dumps(payload, ensure_ascii=False, indent=1)}],
                       model=model, max_tokens=min(32000, 900 * len(items) + 1000), temperature=0)
    results = {str(x.get("id")): x for x in parse_results(text) if isinstance(x, dict)}
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    out = []
    for it in items:
        res = results.get(it["id"])
        if not res or not isinstance(res.get("recommended_output"), str):
            out.append({"id": it["id"], "missing": True, "judge_version": JUDGE_VERSION, "cand_hash": it["cand_hash"], "ts": now})
            continue
        rec = res["recommended_output"].strip()
        out.append({
            "id": it["id"], "missing": False, "judge_model": model, "judge_version": JUDGE_VERSION,
            "cand_hash": it["cand_hash"], "candidates": it["candidates"], "verdicts": res.get("candidates") or {},
            "best": res.get("best"), "recommended_output": rec, "recommended_score": res.get("recommended_score"),
            "uncertain": bool(res.get("uncertain")), "notes": res.get("notes"),
            "validators": check(rec, it["command"]), "ts": now,
        })
    return out


def judge_all(limit: int = 0, batch: int = 8, model: str = DEFAULT_MODEL, workers: int = 3,
              only_ids: set[str] | None = None, extra: dict[str, dict] | None = None,
              teacher: bool = True) -> dict:
    """extra: additional candidates per id (e.g. {"m": student output}); teacher=False judges only those."""
    cmds = {r["id"]: r for r in read_jsonl(home() / "commands_redacted.jsonl")}
    sets = candidate_sets() if teacher else {}
    for cid, more in (extra or {}).items():
        sets[cid] = {**sets.get(cid, {}), **more}
    done = set()
    if judged_path().exists():
        done = {(x["id"], x["cand_hash"]) for x in read_jsonl(judged_path()) if not x.get("missing")}
    items = []
    for cid, cands in sets.items():
        if only_ids is not None and cid not in only_ids:
            continue
        r = cmds.get(cid)
        if not r:
            continue
        h_text, h_conf = describe(r["command_redacted"], r["shell"])
        if h_conf >= 0.7 and teacher:
            cands = {**cands, "h": h_text}
        ch = sha(json.dumps(cands, sort_keys=True))
        if (cid, ch) in done or find_secrets(json.dumps(r["command_redacted"])):
            continue
        items.append({"id": cid, "shell": r["shell"], "command": r["command_redacted"],
                      "structure": compact_structure(r["structure"]), "candidates": cands, "cand_hash": ch})
        if limit and len(items) >= limit:
            break
    batches, cur, chars = [], [], 0
    for it in items:
        n = len(it["command"]) + 300
        if cur and (len(cur) >= batch or chars + n > BATCH_CHARS):
            batches.append(cur); cur, chars = [], 0
        cur.append(it); chars += n
    if cur:
        batches.append(cur)
    print(f"judge: {len(items)} items in {len(batches)} batches ({len(done)} already judged)", flush=True)
    lock = threading.Lock()
    written = failed = 0
    stopped = False
    with ThreadPoolExecutor(workers) as pool:
        futs = [pool.submit(run_batch, b, model) for b in batches]
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                out = fut.result()
            except QuotaExhausted as exc:
                print(f"  stopping: {exc}; rerun later to resume", flush=True)
                for other in futs:
                    other.cancel()
                stopped = True
                break
            except Exception as exc:
                failed += 1
                print(f"  batch failed: {str(exc)[:200]}", flush=True)
                continue
            with lock:
                append_jsonl(judged_path(), out)
                written += len(out)
            if i % 10 == 0 or i == len(batches):
                print(f"  {i}/{len(batches)} batches, {written} judged", flush=True)
    return {"items": len(items), "written": written, "failed_batches": failed, "stopped_on_quota": stopped}


def latest_judgements() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if judged_path().exists():
        for x in read_jsonl(judged_path()):
            if not x.get("missing"):
                out[x["id"]] = x
    return out
