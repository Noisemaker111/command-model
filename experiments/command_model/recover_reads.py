"""Mine bounded read subcommands from frozen training observations and static JS candidates."""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import time

from data_pipeline import atomic_json, json_bytes
from ingest_adapters import digest
from label_data import iter_rows, shell_text


def recover(root, frozen, out, code_recovery=None):
    start = time.perf_counter()
    if out.exists():
        raise ValueError("Read recovery output exists; use a new directory")
    manifest = json.loads((frozen / "manifest.json").read_text(encoding="utf-8"))
    raw = (frozen / "train.jsonl").read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["artifact_sha256"]["train"]:
        raise ValueError("Frozen training partition changed")
    training = {row["record_id"]: row for row in map(json.loads, raw.splitlines())}
    if any(row["partition"] != "train" for row in training.values()):
        raise ValueError("Non-training record found in training partition")
    run = json.loads((root / "runs" / manifest["run"]).read_text(encoding="utf-8"))
    units = {}
    for row, artifact in iter_rows(run, root):
        if row["record_id"] not in training:
            continue
        command = shell_text(row["command"])
        if command and 'get-content' in command.lower():
            key = digest(command)
            item = units.setdefault(key, {"command": command, "ancestors": []})
            item["ancestors"].append({"kind": "recorded_command", "record_id": row["record_id"], "artifact": artifact})
    if code_recovery:
        code_report = json.loads((code_recovery / "report.json").read_text(encoding="utf-8"))
        if code_report["frozen_train_sha256"] != manifest["artifact_sha256"]["train"]:
            raise ValueError("Code recovery belongs to a different partition")
        if hashlib.sha256((code_recovery / "candidates.jsonl.gz").read_bytes()).hexdigest() != code_report["candidates_sha256"]:
            raise ValueError("Static code candidates changed")
        with gzip.open(code_recovery / "candidates.jsonl.gz", "rt", encoding="utf-8") as handle:
            for row in map(json.loads, handle):
                if row["partition"] != "train":
                    raise ValueError("Non-training static candidate")
                command = shell_text(row["command"])
                if command and 'get-content' in command.lower():
                    key = digest(command)
                    item = units.setdefault(key, {"command": command, "ancestors": []})
                    item["ancestors"].append({"kind": "static_code_candidate", "candidate_id": row["id"]})
    out.mkdir(parents=True)
    cases, results = out / "cases.jsonl", out / "results.jsonl"
    cases.write_bytes(b"".join(json_bytes({"id": key, "command": unit["command"]}) for key, unit in units.items()))
    script = Path(__file__).with_name("parse_read_commands.ps1")
    parser_start = time.perf_counter()
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-File", str(script),
                             "-Cases", str(cases), "-Results", str(results)], capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError("PowerShell AST recovery failed: " + result.stderr[-2000:])
    parser_seconds = time.perf_counter() - parser_start
    counts = collections.Counter()
    seen = set()
    with (out / "read-candidates.jsonl").open("wb") as target:
        for line in results.read_text(encoding="utf-8-sig").splitlines():
            row = json.loads(line)
            key = row["id"]
            if key not in units or key in seen:
                raise ValueError("Unknown or duplicate parser result")
            seen.add(key)
            counts["status:" + row["status"]] += 1
            for index, candidate in enumerate(row["candidates"]):
                counts["candidate:" + candidate["status"]] += 1
                if candidate["status"] == "read_candidate":
                    target.write(json_bytes({"id": digest([key, index]), "partition": "train",
                                             "ancestors": units[key]["ancestors"], **candidate,
                                             "source_command_sha256": key, "task_correctness": "abstain"}))
    if seen != set(units):
        raise ValueError("PowerShell parser omitted cases")
    report = {"unique_input_commands": len(units), "counts": dict(counts),
              "elapsed_seconds": time.perf_counter() - start, "parser_seconds": parser_seconds,
              "used_partitions": ["train"], "frozen_train_sha256": manifest["artifact_sha256"]["train"],
              "parser_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
              "candidates_sha256": hashlib.sha256((out / "read-candidates.jsonl").read_bytes()).hexdigest(),
              "historical_commands_executed": False,
              "scope": "Static bounded read subcommands; enclosing pipelines, execution and historical intent remain unverified."}
    atomic_json(out / "report.json", report)
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--code-recovery", type=Path)
    args = parser.parse_args()
    recover(args.root, args.frozen, args.out, args.code_recovery)


if __name__ == "__main__":
    main()
