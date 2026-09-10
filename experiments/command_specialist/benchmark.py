"""Measure correct results, wall latency, generation rate, and evidence fidelity.

Generated plans execute only through the confined five-operation compiler.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
import urllib.request
from pathlib import Path

from contract import PLAN_SCHEMA, EVIDENCE_SCHEMA, evidence_result, execute_plan, messages


def post(base: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(base + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


def predict(base: str, model: str, case: dict) -> tuple[dict, dict]:
    start = time.perf_counter()
    response = post(base, "/api/chat", {
        "model": model, "messages": messages(case), "stream": False,
        "format": PLAN_SCHEMA if case["kind"] == "plan" else EVIDENCE_SCHEMA,
        "think": False, "keep_alive": "5m",
        "options": {"temperature": 0, "seed": 20260909, "num_ctx": 4096, "num_predict": 160},
    })
    timing = {"inference_wall_ms": (time.perf_counter() - start) * 1000}
    timing.update({key: response.get(key) for key in ["total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count", "eval_duration"]})
    return json.loads(response["message"]["content"]), timing


def score(case: dict, prediction: dict, root: Path, expected_output: dict | None, backend: str = "powershell") -> dict:
    if case["kind"] == "plan":
        start = time.perf_counter()
        actual = execute_plan(prediction, root, backend=backend)
        execution_ms = (time.perf_counter() - start) * 1000
        passed = (actual["exit_code"] == 0 and expected_output["exit_code"] == 0
                  and actual["stdout"] == expected_output["stdout"])
        return {"passed": passed, "plan_exact": prediction == case["expected"],
                "execution_ms": execution_ms, "result": actual}
    actual = evidence_result(prediction, case)
    expected, selected = set(case["expected"]["lines"]), set(prediction["lines"])
    recall = len(expected & selected) / len(expected) if expected else 1.0
    precision = len(expected & selected) / len(selected) if selected else float(not expected)
    raw = json.dumps({"exit_code": case["exit_code"], "truncated": case["truncated"], "output": "\n".join(case["output_lines"])})
    compact = json.dumps(actual)
    return {"passed": selected == expected, "evidence_recall": recall, "evidence_precision": precision,
            "raw_chars": len(raw), "compact_chars": len(compact), "result": actual}


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * q) - 1)]


def rule_evidence(case: dict) -> dict:
    """A deliberately simple non-ML baseline for these structured log families."""
    prefixes = ("version=", "active_model=", "SUMMARY") if "version" in case["request"] else ("ERROR", "SUMMARY")
    return {"lines": [i for i, line in enumerate(case["output_lines"], 1) if line.startswith(prefixes)]}


def summarize(rows: list[dict]) -> dict:
    result = {}
    for kind in ["plan", "evidence", "all"]:
        group = [r for r in rows if kind == "all" or r["kind"] == kind]
        times = [r["wall_ms"] for r in group]
        inference = [r["inference_wall_ms"] for r in group if "inference_wall_ms" in r]
        generated = sum(r.get("eval_count") or 0 for r in group)
        generation_seconds = sum(r.get("eval_duration") or 0 for r in group) / 1e9
        result[kind] = {"cases": len(group), "passed": sum(bool(r.get("passed")) for r in group),
                        "pass_rate": sum(bool(r.get("passed")) for r in group) / len(group) if group else None,
                        "median_wall_ms": statistics.median(times) if times else None,
                        "p95_wall_ms": percentile(times, .95),
                        "median_inference_ms": statistics.median(inference) if inference else None,
                        "decode_tokens_per_second": generated / generation_seconds if generation_seconds else None}
        if kind == "evidence":
            raw = sum(r.get("raw_chars", 0) for r in group)
            compact = sum(r.get("compact_chars", 0) for r in group)
            result[kind].update({"mean_evidence_recall": statistics.mean(r.get("evidence_recall", 0) for r in group) if group else None,
                                 "mean_evidence_precision": statistics.mean(r.get("evidence_precision", 0) for r in group) if group else None,
                                 "character_reduction": 1 - compact / raw if raw else None,
                                 "reduction_cases": sum("raw_chars" in r for r in group),
                                 "reduction_unit": "characters, not tokenizer tokens"})
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("work/command-specialist"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--split", default="test", choices=["test", "validation", "historical_holdout"])
    parser.add_argument("--label")
    parser.add_argument("--backend", choices=["powershell", "native"], default="powershell")
    args = parser.parse_args()
    cases = [json.loads(line) for line in (args.data / f"{args.split}.jsonl").read_text(encoding="utf-8").splitlines()]
    if args.model == "rules":
        cases = [case for case in cases if case["kind"] == "evidence"]
    root = (args.data / "fixtures").resolve()
    label = args.label or args.model.replace(":", "-").replace("/", "-")
    output = args.data / f"results-{label}-{args.split}"
    records_path = Path(str(output) + ".jsonl")
    report_path = Path(str(output) + ".json")
    if records_path.exists():
        raise SystemExit("Result exists; use a new label to preserve the prior run.")
    # Warm-up is recorded separately. Model load is excluded from warm-request metrics.
    warmup = None
    if args.model not in {"deterministic", "rules"}:
        _, warmup = predict(args.base_url, args.model, {"kind": "plan", "request": 'Read first 1 lines of "warmup.txt".'})
    rows = []
    with records_path.open("w", encoding="utf-8") as handle:
        for case in cases:
            expected = execute_plan(case["expected"], root) if case["kind"] == "plan" else None
            if expected is not None and expected["exit_code"]:
                raise RuntimeError("Fixture reference command failed: " + json.dumps(expected))
            start = time.perf_counter()
            row = {"id": case["id"], "kind": case["kind"]}
            try:
                if args.model == "deterministic":
                    # Typed-input floor: it does not solve natural-language planning.
                    prediction, timing = case["expected"], {"inference_wall_ms": 0}
                elif args.model == "rules":
                    prediction, timing = rule_evidence(case), {"inference_wall_ms": 0}
                else:
                    prediction, timing = predict(args.base_url, args.model, case)
                row.update(timing)
                row["prediction"] = prediction
                row.update(score(case, prediction, root, expected, args.backend))
            except Exception as error:
                row.update({"passed": False, "error": str(error)})
            row["wall_ms"] = (time.perf_counter() - start) * 1000
            rows.append(row)
            handle.write(json.dumps(row) + "\n")
            handle.flush()
            print(json.dumps({k: row[k] for k in ["id", "passed", "wall_ms"]}), flush=True)
    report = {"model": args.model, "split": args.split, "warmup": warmup,
              "test_sha256": hashlib.sha256((args.data / f"{args.split}.jsonl").read_bytes()).hexdigest(),
              "conditions": {"thinking": False, "context": 4096, "max_new_tokens": 160, "temperature": 0,
                             "execution_backend": args.backend,
                             "execution_shell": "Windows PowerShell, new process per plan" if args.backend == "powershell" else "none: direct Python UTF-8 fixture operations", "sequential": True,
                             "wall_includes": "inference, validation, command execution, result extraction; reference execution excluded",
                             "deterministic_baseline": "pre-specified correct plan/selection; latency floor, not a language-model competitor"},
              "summary": summarize(rows)}
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
