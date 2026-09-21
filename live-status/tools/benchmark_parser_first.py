"""Benchmark parser-first status generation without model or GPU calls."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inference.parser_first import PowerShellAstBackend


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows = [
        json.loads(line)
        for line in args.sample.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    args.out.mkdir(parents=True, exist_ok=True)
    backend = PowerShellAstBackend()
    outputs = []
    try:
        backend.warm()
        for row in rows:
            status, metrics = backend.generate(row["command"])
            outputs.append({
                "id": row.get("id"), "session": row.get("session"),
                "complexity": row.get("complexity"), "tags": row.get("tags"),
                "command": row["command"], "status": status, "metrics": metrics,
            })
    finally:
        backend.close()

    count = len(outputs)
    latencies = [item["metrics"]["wall_s"] * 1000 for item in outputs]
    parse_success = sum(not item["metrics"]["parse_errors"] for item in outputs)
    fully_mapped = sum(item["metrics"]["fully_mapped"] for item in outputs)
    literal = sum(item["metrics"]["literal_fallback"] for item in outputs)
    abstained = sum(item["metrics"]["abstained"] for item in outputs)
    mapped = sum(item["metrics"]["mapped_actions"] > 0 for item in outputs)
    evidence = sum(
        bool(item["metrics"]["facts"])
        and all(fact["evidence"] for fact in item["metrics"]["facts"])
        for item in outputs
    )
    validator = sum(
        item["status"].endswith(".") and "\n" not in item["status"]
        and all(
            fact["text"].lower() in item["status"].lower()
            for fact in item["metrics"]["facts"]
        )
        for item in outputs
    )

    def pct(value: int) -> float:
        return round(100 * value / count, 1) if count else 0.0

    summary = {
        "backend": "parser:powershell", "rows": count,
        "ast_parse_success_pct": pct(parse_success),
        "fully_mapped_coverage_pct": pct(fully_mapped),
        "literal_fallback_pct": pct(literal),
        "abstention_pct": pct(abstained),
        "mapped_action_coverage_pct": pct(mapped),
        "evidence_grounded_pct": pct(evidence),
        "validator_pass_pct": pct(validator),
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 3) if latencies else 0.0,
            "p50": round(percentile(latencies, 0.5), 3),
            "p90": round(percentile(latencies, 0.9), 3),
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        "limitations": [
            "Mapped coverage and grounding are mechanical measurements, not human-rated semantic accuracy.",
            "The prototype handles PowerShell only.",
            "Literal fallback repeats an AST-proven executable name without claiming its purpose.",
        ],
    }
    with (args.out / "outputs.jsonl").open("w", encoding="utf-8") as handle:
        for output in outputs:
            handle.write(json.dumps(output, ensure_ascii=False) + "\n")
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
