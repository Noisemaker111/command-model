"""Verify bounded read semantics in fixtures and export synthetic-intent derivatives.

Uses only the frozen TRAIN partition. It never executes historical commands and
never labels the original task successful. No raw transcript text enters the export.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import random
import subprocess
import tempfile
import time

from contract import messages
from data_pipeline import atomic_json, json_bytes


def verify(out, shell="powershell", serial_samples=0):
    if not 0 <= serial_samples <= 100:
        raise ValueError("Serial samples must be in 0..100")
    out.mkdir(parents=True, exist_ok=True)
    if (out / "verification.json").exists():
        raise ValueError("Verification output exists; choose a fresh output directory")
    start = time.perf_counter()
    cases = []
    expected = {}
    with tempfile.TemporaryDirectory(prefix="command-label-fixtures-") as directory:
        root = Path(directory)
        for op in ("read_head", "read_tail"):
            for limit in range(1, 101):
                for boundary, length in enumerate((0, 1, max(0, limit - 1), limit + 3)):
                    identifier = f"{op}-{limit}-{boundary}"
                    path = root / (identifier + " [draft] can't $expand.txt")
                    lines = [f"entry {i} café [x] $literal" for i in range(length)]
                    path.write_bytes(("\r\n".join(lines) + ("\r\n" if lines else "")).encode("utf-8"))
                    cases.append({"id": identifier, "op": op, "limit": limit, "path": str(path)})
                    expected[identifier] = lines[:limit] if op == "read_head" else lines[-limit:]
        case_file, result_file = root / "cases.json", root / "results.json"
        case_file.write_bytes(json_bytes(cases))
        script = Path(__file__).with_name("verify_read_contracts.ps1")
        result = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(script),
                                 "-Cases", str(case_file), "-Results", str(result_file)],
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError("Fixture verifier failed: " + result.stderr[-2000:])
        observed = json.loads(result_file.read_text(encoding="utf-8-sig"))
        ids = [r["id"] for r in observed]
        if len(ids) != len(set(ids)) or set(ids) != set(expected):
            raise RuntimeError("Verifier returned missing or duplicate case identities")
        failures = [r["id"] for r in observed if r["error"] or r["lines"] != expected[r["id"]]]
        bulk_elapsed = time.perf_counter() - start
        comparison = None
        if serial_samples:
            selected = random.Random(20260909).sample(cases, serial_samples)
            serial_start = time.perf_counter()
            for case in selected:
                case_file.write_bytes(json_bytes([case]))
                single = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-File", str(script),
                                         "-Cases", str(case_file), "-Results", str(result_file)],
                                        capture_output=True, text=True, timeout=15)
                if single.returncode:
                    raise RuntimeError("Serial verifier failed: " + single.stderr[-1000:])
                actual = json.loads(result_file.read_text(encoding="utf-8-sig"))
                if len(actual) != 1 or actual[0]["id"] != case["id"] or actual[0]["error"] or actual[0]["lines"] != expected[case["id"]]:
                    raise RuntimeError("Serial verifier returned an incorrect result")
            serial_elapsed = time.perf_counter() - serial_start
            comparison = {"sample_cases": serial_samples, "passed": serial_samples,
                          "elapsed_seconds": serial_elapsed,
                          "mean_seconds_per_case": serial_elapsed / serial_samples,
                          "bulk_seconds_per_case": bulk_elapsed / len(cases),
                          "observed_per_case_throughput_ratio": (serial_elapsed / serial_samples) / (bulk_elapsed / len(cases)),
                          "conditions": "One fresh PowerShell per sampled case versus 800 cases in one process; same verifier and already-created fixture files. Bulk includes fixture creation. This is per-case throughput, not 800-case serial elapsed time or historical labeling cost."}
    report = {"cases": len(cases), "passed": len(cases) - len(failures), "failures": failures,
              "elapsed_seconds": time.perf_counter() - start, "bulk_elapsed_seconds": bulk_elapsed,
              "serial_comparison": comparison, "shell": shell,
              "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
              "scope": "read_head/read_tail, limits 1..100, empty/short/long UTF-8 CRLF files, literal metacharacter paths",
              "historical_commands_executed": 0, "historical_task_correctness_verified": False}
    atomic_json(out / "verification.json", report)
    if failures:
        raise RuntimeError("Read-contract verifier failed; no examples may be promoted")
    return report


def export_train(frozen, out, verification, read_recovery=None):
    if verification["failures"] or verification["passed"] != 800:
        raise ValueError("Complete successful verifier evidence is required")
    manifest = json.loads((frozen / "manifest.json").read_text(encoding="utf-8"))
    source = frozen / "train.jsonl"
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    if sha != manifest["artifact_sha256"]["train"]:
        raise ValueError("Frozen training partition changed")
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    if any(row.get("partition") != "train" for row in rows):
        raise ValueError("Frozen training file contains a non-training record")
    candidates = [r for r in rows if r["read_contract_candidate"] and not any(
        reason in r["review_reasons"] for reason in ("conflicting_call_id", "changing_source"))]
    direct_candidates = len(candidates)
    recovery_hash = None
    if read_recovery:
        recovery_report = json.loads((read_recovery / "report.json").read_text(encoding="utf-8"))
        recovered_raw = (read_recovery / "read-candidates.jsonl").read_bytes()
        recovery_hash = hashlib.sha256(recovered_raw).hexdigest()
        if (recovery_report["frozen_train_sha256"] != sha or recovery_report["used_partitions"] != ["train"]
                or recovery_report["candidates_sha256"] != recovery_hash):
            raise ValueError("Read recovery changed or belongs to another partition")
        for row in map(json.loads, recovered_raw.splitlines()):
            plan = row["plan"]
            if (row["partition"] != "train" or plan.get("op") not in {"read_head", "read_tail"}
                    or type(plan.get("limit")) is not int or not 1 <= plan["limit"] <= 100):
                raise ValueError("Invalid training read candidate")
            candidates.append({"id": "ast-" + row["id"], "read_contract_candidate": plan})
    # Preserve record ancestry, but avoid multiplying identical generated instructions.
    groups = collections.defaultdict(list)
    for row in candidates:
        contract = row["read_contract_candidate"]
        groups[(contract["op"], contract["limit"])].append(row["id"])
    examples = []
    for (op, limit), parents in sorted(groups.items()):
        for wording in range(3):
            relative = f"fixture-{op}-{limit}-{wording}.txt"
            edge = "first" if op == "read_head" else "last"
            requests = [f'Read the {edge} {limit} lines of "{relative}".',
                        f'Show at most {limit} lines from the {"beginning" if op == "read_head" else "end"} of "{relative}".',
                        f'Inspect "{relative}": return its {edge} {limit} lines.']
            row = {"id": f"verified-{op}-{limit}-{wording}", "kind": "plan", "split": "train",
                   "origin": "synthetic-intent-from-train-command-family",
                   "request": requests[wording], "expected": {"op": op, "path": relative, "value": "", "limit": limit},
                   "source_training_records": parents,
                   "read_recovery_sha256": recovery_hash,
                   "verification": "synthetic-operation-semantics; not original task correctness"}
            examples.append(row)
    for filename, rows in (("verified-train.jsonl", examples), ("sft.jsonl", [
            {"id": row["id"], "messages": messages(row) + [{"role": "assistant", "content": json.dumps(row["expected"], separators=(",", ":"))}]}
            for row in examples])):
        path = out / filename
        if path.exists():
            raise ValueError("Export exists; refusing to overwrite")
        path.write_bytes(b"".join(json_bytes(row) for row in rows))
    report = {"training_source_candidates": len(candidates), "direct_frozen_candidates": direct_candidates,
              "ast_candidates": len(candidates) - direct_candidates, "read_recovery_sha256": recovery_hash,
              "distinct_operation_count_pairs": len(groups),
              "synthetic_training_examples": len(examples), "frozen_train_sha256": sha,
              "used_partitions": ["train"], "verifier_cases": verification["passed"],
              "sft_sha256": hashlib.sha256((out / "sft.jsonl").read_bytes()).hexdigest(),
              "original_task_success_labels": 0,
              "scope": "Supplemental synthetic read examples; insufficient alone for a broad command specialist."}
    atomic_json(out / "export.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--shell", default="powershell")
    parser.add_argument("--serial-samples", type=int, default=0, help="Optional fresh-process baseline sample, maximum 100")
    parser.add_argument("--read-recovery", type=Path, help="Verified-integrity AST recovery from the same frozen training partition")
    args = parser.parse_args()
    evidence = verify(args.out, args.shell, args.serial_samples)
    export = export_train(args.frozen, args.out, evidence, args.read_recovery)
    print(json.dumps({"verification": evidence, "export": export}, indent=2))


if __name__ == "__main__":
    main()
