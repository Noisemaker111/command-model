"""Benchmark explicit backends on novel commands from recent Codex sessions.

Commands are redacted before persistence or model access. Candidate identities are
permuted per row before the independent judge sees them.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import random
import statistics
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from common import append_jsonl, read_jsonl, save_json, sha, write_jsonl  # noqa: E402
from data_miner.mine import default_shell, hard_tags, template_key  # noqa: E402
from data_miner.sources import codex  # noqa: E402
from evaluation.validators import check  # noqa: E402
from inference.backends import from_spec  # noqa: E402
from judging.judge import cand_hash, compact_structure, judge_key, run_batch  # noqa: E402
from parsers.shell import analyze, complexity  # noqa: E402
from redaction.redact import find_secrets, redact  # noqa: E402


def parse_args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--session-root", type=Path, required=True)
    p.add_argument("--recent-sessions", type=int, required=True)
    p.add_argument("--dataset-dir", type=Path, required=True)
    p.add_argument("--sample", type=int, required=True)
    p.add_argument("--backend", action="append", required=True, metavar="NAME=SPEC")
    p.add_argument("--judge-model", required=True)
    p.add_argument("--judge-route", required=True,
                   help="Explicit provider/account route used for the judge (for provenance)")
    p.add_argument("--judge-batch", type=int, default=8)
    p.add_argument("--judge-workers", type=int, default=3)
    p.add_argument("--out", type=Path, required=True)
    return p.parse_args(argv)


def backend_specs(values: list[str]) -> dict[str, str]:
    result = {}
    for value in values:
        name, sep, spec = value.partition("=")
        if not sep or not name or not spec:
            raise ValueError(f"invalid --backend {value!r}; expected NAME=SPEC")
        if name in result:
            raise ValueError(f"duplicate backend name {name!r}")
        result[name] = spec
    return result


def old_templates(dataset_dir: Path) -> set[str]:
    found = set()
    for split in ("train", "validation", "test"):
        path = dataset_dir / f"{split}.jsonl"
        if path.exists():
            found.update(template_key(row["command"]) for row in read_jsonl(path))
    return found


def recent_files(root: Path, count: int) -> list[tuple[Path, list[dict]]]:
    found = []
    for path in sorted(root.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        rows = list(codex(path))
        if rows:
            found.append((path, rows))
        if len(found) >= count:
            break
    return found


def collect(args) -> tuple[list[dict], dict]:
    prior = old_templates(args.dataset_dir)
    seen = set()
    rows = []
    session_stats = []
    for path, extracted in recent_files(args.session_root, args.recent_sessions):
        counts = collections.Counter(extracted=len(extracted))
        for record in extracted:
            command = redact(record["command_raw"])
            if find_secrets(command):
                counts["secret_residue"] += 1
                continue
            key = template_key(command)
            if key in prior:
                counts["old_template"] += 1
                continue
            if key in seen:
                counts["recent_duplicate"] += 1
                continue
            seen.add(key)
            shell = default_shell(record)
            structure = analyze(command, shell)
            row_id = "recent_" + sha(f"{path.name}|{key}")
            rows.append({
                "id": row_id,
                "session": path.name,
                "timestamp": record.get("timestamp"),
                "command": command,
                "shell": structure.shell,
                "structure": structure.to_dict(),
                "complexity": complexity(structure, command),
                "tags": hard_tags(command, command, structure),
            })
            counts["novel_unique"] += 1
        session_stats.append({"session": path.name, **counts})
    return rows, {"sessions": session_stats, "novel_unique": len(rows), "prior_templates": len(prior)}


def balanced_sample(rows: list[dict], size: int) -> list[dict]:
    if size >= len(rows):
        return rows
    buckets: dict[tuple, list[dict]] = collections.defaultdict(list)
    for row in rows:
        actions = row["structure"]["actions"]
        first = next((a["type"] for a in actions if a["type"] not in ("env", "format")), "none")
        buckets[(row["session"], row["complexity"], first)].append(row)
    for key, values in buckets.items():
        random.Random(int(hashlib.sha256(repr(key).encode()).hexdigest()[:8], 16)).shuffle(values)
    chosen = []
    order = sorted(buckets, key=lambda key: (-len(buckets[key]), repr(key)))
    while len(chosen) < size and any(buckets.values()):
        for key in order:
            if buckets[key] and len(chosen) < size:
                chosen.append(buckets[key].pop())
    return chosen


def generate(rows: list[dict], specs: dict[str, str], checkpoint: Path) -> list[dict]:
    outputs = [{**row, "outputs": {}} for row in rows]
    done = {}
    if checkpoint.exists():
        for saved in read_jsonl(checkpoint):
            key = (saved.get("id"), saved.get("name"), saved.get("spec"))
            done[key] = saved.get("result")
    for name, spec in specs.items():
        if all((row["id"], name, spec) in done for row in outputs):
            for row in outputs:
                row["outputs"][name] = done[(row["id"], name, spec)]
            continue
        backend = from_spec(spec)
        if hasattr(backend, "warm"):
            backend.warm()
        for row in outputs:
            key = (row["id"], name, spec)
            result = done.get(key)
            if result is None:
                text, metrics = backend.generate(row["command"])
                result = {"text": text, "metrics": metrics,
                          "validators": check(text, row["command"])}
                append_jsonl(checkpoint, [{"id": row["id"], "name": name,
                                           "spec": spec, "result": result}])
            row["outputs"][name] = result
    return outputs


def blinded_items(rows: list[dict], model_names: list[str]) -> tuple[list[dict], dict[str, dict[str, str]]]:
    items, maps = [], {}
    for row in rows:
        names = list(model_names)
        random.Random(int(hashlib.sha256(row["id"].encode()).hexdigest()[:8], 16)).shuffle(names)
        mapping = {f"c{i}": name for i, name in enumerate(names)}
        maps[row["id"]] = mapping
        candidates = {alias: row["outputs"][name]["text"] for alias, name in mapping.items()}
        item = {"id": row["id"], "shell": row["shell"], "command": row["command"],
                "structure": compact_structure(row["structure"]), "candidates": candidates,
                "cand_hash": cand_hash(candidates)}
        if find_secrets(json.dumps(item, ensure_ascii=False)):
            raise RuntimeError(f"secret residue after redaction for {row['id']}")
        items.append(item)
    return items, maps


def routed_judge_key(model: str, route: str) -> str:
    return f"{judge_key(model)}|route={route}"


def judge(items: list[dict], model: str, route: str, batch_size: int, workers: int,
          checkpoint: Path) -> list[dict]:
    key = routed_judge_key(model, route)
    saved = [row for row in read_jsonl(checkpoint) if row.get("judge_key") == key] \
        if checkpoint.exists() else []
    done = {(row.get("id"), row.get("cand_hash")) for row in saved if not row.get("missing")}
    pending = [item for item in items if (item["id"], item["cand_hash"]) not in done]
    batches = [pending[i:i + batch_size] for i in range(0, len(pending), batch_size)]
    judged = list(saved)
    lock = threading.Lock()
    failures = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_batch, batch, model) for batch in batches]
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as exc:
                failures.append(exc)
                continue
            for row in result:
                row["judge_route"] = route
                row["judge_key"] = key
            with lock:
                append_jsonl(checkpoint, result)
                judged.extend(result)
    if failures:
        raise RuntimeError(f"{len(failures)} judge batch(es) failed; rerun to resume") from failures[0]
    return judged


def wilson(passes: int, total: int) -> list[float]:
    if not total:
        return [0.0, 0.0]
    z = 1.959963984540054
    p = passes / total
    d = 1 + z * z / total
    center = (p + z * z / (2 * total)) / d
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return [round(100 * (center - radius), 1), round(100 * (center + radius), 1)]


def summarize(rows: list[dict], judgments: list[dict], maps: dict[str, dict[str, str]], specs: dict[str, str]) -> dict:
    by_id = {row["id"]: row for row in rows}
    results = {}
    for name, spec in specs.items():
        scores = []
        strict = invented = omitted = preferred = 0
        walls = [row["outputs"][name]["metrics"]["wall_s"] for row in rows]
        validator_pass = sum(row["outputs"][name]["validators"]["pass"] for row in rows)
        judged_n = 0
        for result in judgments:
            if result.get("missing") or result["id"] not in by_id:
                continue
            alias = next(alias for alias, candidate in maps[result["id"]].items() if candidate == name)
            verdict = (result.get("verdicts") or {}).get(alias) or {}
            judged_n += 1
            score = float(verdict.get("score") or 0)
            scores.append(score)
            missing = bool(verdict.get("missing_actions"))
            hallucinated = bool(verdict.get("hallucinated_actions"))
            omitted += missing
            invented += hallucinated
            strict += bool(verdict.get("correct") and score >= 80 and not missing and not hallucinated
                           and verdict.get("names_ok") and not verdict.get("secret_leak")
                           and verdict.get("style_ok"))
            preferred += result.get("best") == alias
        results[name] = {
            "backend": spec,
            "generated": len(rows),
            "judged": judged_n,
            "strict_pass_pct": round(100 * strict / max(1, judged_n), 1),
            "strict_pass_95ci_pct": wilson(strict, judged_n),
            "invention_pct": round(100 * invented / max(1, judged_n), 1),
            "omission_pct": round(100 * omitted / max(1, judged_n), 1),
            "preferred_pct": round(100 * preferred / max(1, judged_n), 1),
            "judge_score_mean": round(statistics.mean(scores), 1) if scores else None,
            "validator_pass_pct": round(100 * validator_pass / max(1, len(rows)), 1),
            "latency_s": {"p50": round(statistics.median(walls), 4),
                          "p90": round(sorted(walls)[min(len(walls) - 1, int(.9 * len(walls)))], 4)},
        }
    return results


def main(argv=None):
    args = parse_args(argv)
    specs = backend_specs(args.backend)
    args.out.mkdir(parents=True, exist_ok=True)
    sample_path = args.out / "sample.jsonl"
    collection_path = args.out / "collection.json"
    if sample_path.exists() and collection_path.exists():
        rows = list(read_jsonl(sample_path))
        collection = json.loads(collection_path.read_text(encoding="utf-8"))
    elif (args.out / "outputs.jsonl").exists():
        prior_outputs = list(read_jsonl(args.out / "outputs.jsonl"))
        rows = [{key: value for key, value in row.items() if key != "outputs"}
                for row in prior_outputs]
        collection = {"recovered_from_outputs": True, "novel_unique": len(rows)}
        write_jsonl(sample_path, rows)
        save_json(collection_path, collection)
    else:
        pool, collection = collect(args)
        rows = balanced_sample(pool, args.sample)
        write_jsonl(sample_path, rows)
        save_json(collection_path, collection)
    outputs = generate(rows, specs, args.out / "generation-checkpoint.jsonl")
    write_jsonl(args.out / "outputs.jsonl", outputs)
    items, maps = blinded_items(outputs, list(specs))
    judgments = judge(items, args.judge_model, args.judge_route,
                      args.judge_batch, args.judge_workers,
                      args.out / "judgments.jsonl")
    report = {
        "collection": collection,
        "sample": {"requested": args.sample, "rows": len(rows),
                   "sessions": dict(collections.Counter(row["session"] for row in rows)),
                   "complexity": dict(collections.Counter(row["complexity"] for row in rows)),
                   "shells": dict(collections.Counter(row["shell"] for row in rows))},
        "judge_model": args.judge_model,
        "judge_route": args.judge_route,
        "judge_key": routed_judge_key(args.judge_model, args.judge_route),
        "models": summarize(outputs, judgments, maps, specs),
    }
    save_json(args.out / "summary.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
