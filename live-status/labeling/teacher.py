"""Teacher pass: batched Opus 5 calls producing candidate statuses for redacted commands.

Appends to labels/teacher.jsonl; reruns skip ids already labeled under the same
prompt version, so interrupted runs resume without repeating paid calls.
"""
from __future__ import annotations

import json
import random
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from common import append_jsonl, home, read_jsonl
from labeling.llm import DEFAULT_MODEL, QuotaExhausted, chat, model_code, parse_results
from labeling.prompts import TEACHER_REGEN_NOTE, TEACHER_SYSTEM, TEACHER_VERSION
from redaction.redact import find_secrets

MAX_LABEL_CHARS = 6000
BATCH_CHARS = 30000
TEMPERATURE = 0.4


def version_of(model: str, regen: bool) -> str:
    return TEACHER_VERSION + ("+regen" if regen else "") + "@" + model


def teacher_path() -> Path:
    return home() / "labels" / "teacher.jsonl"


def load_commands() -> list[dict]:
    return list(read_jsonl(home() / "commands_redacted.jsonl"))


def select(rows: list[dict], limit: int, seed: int = 20260916) -> list[dict]:
    """Frequent templates first, then round-robin over (shell, first action, complexity) buckets."""
    rows = [r for r in rows if r["length"] <= MAX_LABEL_CHARS and r["command_redacted"].strip()]
    if not limit or limit >= len(rows):
        return rows
    rng = random.Random(seed)
    frequent = [r for r in rows if r["count"] >= 3][: int(limit * 0.4)]
    chosen = {r["id"] for r in frequent}
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r["id"] in chosen:
            continue
        acts = r["structure"]["actions"]
        first = next((a["type"] for a in acts if a["type"] not in ("env", "format")), acts[0]["type"] if acts else "none")
        buckets[(r["shell"], first, r["complexity"])].append(r)
    for b in buckets.values():
        rng.shuffle(b)
        b.sort(key=lambda r: -len(r["tags"]))  # hard examples surface earlier within a bucket
    order = sorted(buckets, key=lambda k: -len(buckets[k]))
    out = list(frequent)
    while len(out) < limit and any(buckets.values()):
        for k in order:
            if buckets[k] and len(out) < limit:
                out.append(buckets[k].pop(0))
    return out


def _batches(items: list[dict], size: int) -> list[list[dict]]:
    batches, cur, chars = [], [], 0
    for it in items:
        n = len(it["command"])
        if cur and (len(cur) >= size or chars + n > BATCH_CHARS):
            batches.append(cur); cur, chars = [], 0
        cur.append(it); chars += n
    if cur:
        batches.append(cur)
    return batches


def salient_names(st: dict) -> list[str]:
    """Concrete targets the parser found: file basenames, process names, git/package subcommands."""
    out = []
    for a in st.get("actions", []):
        out += [t for t in a.get("targets", []) if t and not t.startswith(("<", "$", "-")) and len(t) < 60]
        if a.get("sub"):
            out.append(a["sub"])
    seen = []
    for n in out:
        if n not in seen:
            seen.append(n)
    return seen[:10]


def _item(r: dict, feedback: dict | None = None) -> dict:
    from judging.judge import compact_structure
    from parsers.shell import analyze
    st = r.get("structure") or analyze(r["command_redacted"], r.get("shell")).to_dict()
    it = {"id": r["id"], "shell": r["shell"], "command": r["command_redacted"],
          "structure": compact_structure(st), "names": salient_names(st)}
    if feedback:
        it["previous_attempt"] = feedback.get("output")
        it["judge_feedback"] = feedback.get("notes")
    return it


def run_batch(batch: list[dict], model: str, regen: bool) -> list[dict]:
    system = TEACHER_SYSTEM + ("\n\n" + TEACHER_REGEN_NOTE if regen else "")
    user = "Items:\n" + json.dumps(batch, ensure_ascii=False, indent=1)
    t0 = time.time()
    text, usage = chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                       model=model, max_tokens=min(32000, 250 * len(batch) + 800), temperature=TEMPERATURE)
    results = {str(x.get("id")): x for x in parse_results(text) if isinstance(x, dict)}
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    out = []
    for it in batch:
        res = results.get(it["id"])
        cands = {k: res[k].strip() for k in ("a", "b") if res and isinstance(res.get(k), str) and res[k].strip()}
        out.append({"id": it["id"], "teacher_model": model, "prompt_version": version_of(model, regen),
                    "params": {"temperature": TEMPERATURE, "batch_size": len(batch)}, "candidates": cands,
                    "missing": not cands, "ts": now, "latency_s": round(time.time() - t0, 1),
                    "usage": usage if it is batch[0] else None})
    return out


def generate(limit: int = 0, batch: int = 20, model: str = DEFAULT_MODEL, workers: int = 3,
             ids_file: str | None = None, feedback: dict[str, dict] | None = None) -> dict:
    rows = load_commands()
    if ids_file:
        wanted = set(Path(ids_file).read_text(encoding="utf-8").split())
        todo = [r for r in rows if r["id"] in wanted]
    else:
        todo = select(rows, limit)
    regen = bool(feedback)
    version = version_of(model, regen)
    done = set()
    if teacher_path().exists():
        done = {x["id"] for x in read_jsonl(teacher_path()) if x["prompt_version"] == version and not x["missing"]}
    items, skipped = [], 0
    for r in todo:
        if r["id"] in done:
            continue
        if find_secrets(json.dumps(r["command_redacted"])):
            skipped += 1  # redaction residue: never send
            continue
        items.append(_item(r, (feedback or {}).get(r["id"])))
    batches = _batches(items, batch)
    print(f"teacher: {len(items)} items in {len(batches)} batches ({len(done)} already labeled, {skipped} withheld)", flush=True)
    lock = threading.Lock()
    written = failed = 0
    stopped = False
    with ThreadPoolExecutor(workers) as pool:
        futs = {pool.submit(run_batch, b, model, regen): b for b in batches}
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
                append_jsonl(teacher_path(), out)
                written += len(out)
            if i % 10 == 0 or i == len(batches):
                print(f"  {i}/{len(batches)} batches, {written} labeled", flush=True)
    return {"selected": len(todo), "sent": len(items), "written": written, "failed_batches": failed, "stopped_on_quota": stopped, "withheld": skipped}
