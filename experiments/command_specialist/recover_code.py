"""Recover static shell-call candidates from frozen training-side Codex code mode.

Historical code is parsed, never executed. Output is a private review sidecar and
does not alter the frozen split or claim that a syntactic call actually ran.
"""
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
from ingest_adapters import digest, object_value
from label_data import iter_rows, session_key, shell_text


def recover(root, frozen, out):
    start = time.perf_counter()
    if out.exists():
        raise ValueError("Recovery output exists; use a new directory")
    manifest = json.loads((frozen / "manifest.json").read_text(encoding="utf-8"))
    raw = (frozen / "train.jsonl").read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["artifact_sha256"]["train"]:
        raise ValueError("Frozen training partition changed")
    training = [json.loads(line) for line in raw.splitlines()]
    if any(row["partition"] != "train" for row in training):
        raise ValueError("Non-training record found in training partition")
    sessions = {row["session_group"] for row in training}
    ids = {row["record_id"] for row in training}
    training_artifacts = {row["artifact"] for row in training}
    run = json.loads((root / "runs" / manifest["run"]).read_text(encoding="utf-8"))
    # Compare only training observations. Exact text in the same session is a
    # reconciliation lead, not proof that a particular AST branch executed.
    known = collections.defaultdict(list)
    selected_run = {"sources": [s for s in run["sources"] if s["source"]["kind"] == "codex"]}
    known_run = {"sources": [s for s in selected_run["sources"] if s["normalization"] in training_artifacts]}
    for row, _ in iter_rows(known_run, root):
        if row["record_id"] in ids:
            text = shell_text(row["command"])
            if text is not None:
                known[(session_key(row), digest(text))].append(row["record_id"])
    out.mkdir(parents=True)
    counts = collections.Counter()
    units = {}
    input_path, output_path = out / "parser-input.jsonl", out / "parser-output.jsonl"
    with input_path.open("wb") as target:
        for source in selected_run["sources"]:
            meta = source["snapshot"]
            snapshot = meta["snapshot_sha256"]
            session = digest(meta["source_path"])
            # Codex rollouts normally identify their session in the first record.
            # Skip non-training files before decompressing their full contents.
            with gzip.open(root / "snapshots" / (snapshot + ".gz"), "rb") as peek:
                try:
                    header = json.loads(peek.readline())
                except (ValueError, UnicodeDecodeError):
                    header = {}
            if isinstance(header, dict) and header.get("type") == "session_meta" and isinstance(header.get("payload"), dict):
                header_session = header["payload"].get("id") or header["payload"].get("session_id")
                if (header_session and source["normalization"] not in training_artifacts
                        and session_key({"session": header_session, "source_kind": "codex"}) not in sessions):
                    counts["skipped_non_training_snapshots"] += 1
                    continue
            sha = hashlib.sha256()
            with gzip.open(root / "snapshots" / (snapshot + ".gz"), "rb") as handle:
                for line_number, line in enumerate(handle, 1):
                    sha.update(line)
                    try:
                        row = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        counts["malformed_source_records"] += 1
                        continue
                    if not isinstance(row, dict) or not isinstance(row.get("payload"), dict):
                        continue
                    p = row["payload"]
                    if row.get("type") == "session_meta":
                        session = p.get("id") or p.get("session_id") or session
                    group = session_key({"session": session, "source_kind": "codex"})
                    if group not in sessions:
                        continue
                    if row.get("type") != "response_item" or p.get("type") not in {"custom_tool_call", "function_call"}:
                        continue
                    if p.get("name") not in {"exec", "functions.exec"}:
                        continue
                    code = p.get("input")
                    if not isinstance(code, str):
                        code = object_value(p.get("arguments")).get("code")
                    if not isinstance(code, str):
                        counts["unsupported_code_envelope"] += 1
                        continue
                    identifier = digest([snapshot, line_number, p.get("call_id")])
                    units[identifier] = {"snapshot": snapshot, "line": line_number,
                                         "outer_call_id": p.get("call_id"), "session_group": group,
                                         "code_sha256": hashlib.sha256(code.encode()).hexdigest()}
                    target.write(json_bytes({"id": identifier, "code": code}))
            if sha.hexdigest() != snapshot:
                raise ValueError("Snapshot content hash mismatch")
    parser_dir = Path(__file__).with_name("js_parser")
    parser_start = time.perf_counter()
    with input_path.open("rb") as source, output_path.open("wb") as target:
        process = subprocess.run(["node", str(parser_dir / "extract.mjs")], stdin=source, stdout=target,
                                 stderr=subprocess.PIPE, timeout=120)
    if process.returncode:
        raise RuntimeError("Static parser failed: " + process.stderr.decode("utf-8", errors="replace")[-2000:])
    parser_elapsed = time.perf_counter() - parser_start
    counts["code_units"] = len(units)
    seen = set()
    with output_path.open(encoding="utf-8") as source, gzip.open(out / "candidates.jsonl.gz", "wt", encoding="utf-8") as target:
        for line in source:
            result = json.loads(line)
            key = result["id"]
            if key not in units or key in seen:
                raise ValueError("Static parser returned an unknown or duplicate identity")
            seen.add(key)
            counts["status:" + result["status"]] += 1
            for rejection in result["rejected"]:
                counts["rejected:" + rejection["reason"]] += 1
            for index, candidate in enumerate(result["candidates"]):
                counts["static_command_candidates"] += 1
                counts["candidates_with_dynamic_environment"] += bool(candidate["dynamic_fields"])
                counts["candidates_in_control_context"] += bool(candidate["control_context"])
                text = shell_text(candidate["command"])
                matches = known.get((units[key]["session_group"], digest(text)), []) if text is not None else []
                counts["candidates_with_same_session_text_match"] += bool(matches)
                target.write(json.dumps({"id": digest([key, index]), "partition": "train", "origin": units[key],
                                         **candidate, "span_units": result["span_units"],
                                         "matching_training_record_ids": matches,
                                         "training_eligible": False}, ensure_ascii=False) + "\n")
    if seen != set(units):
        raise ValueError("Static parser omitted input units")
    # Keep exact parser dispositions, including failures, alongside source pointers.
    with output_path.open("rb") as source, gzip.open(out / "parser-results.jsonl.gz", "wb") as target:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            target.write(block)
    atomic_json(out / "units.json", units)
    input_path.unlink()
    output_path.unlink()
    report = {"counts": dict(counts), "elapsed_seconds": time.perf_counter() - start,
              "parser_seconds": parser_elapsed, "used_partitions": ["train"],
              "frozen_train_sha256": manifest["artifact_sha256"]["train"],
              "parser_sha256": hashlib.sha256((parser_dir / "extract.mjs").read_bytes()).hexdigest(),
              "parser_lock_sha256": hashlib.sha256((parser_dir / "package-lock.json").read_bytes()).hexdigest(),
              "candidates_sha256": hashlib.sha256((out / "candidates.jsonl.gz").read_bytes()).hexdigest(),
              "historical_code_executed": False,
              "scope": "Codex code-mode calls in assigned training sessions; syntactic candidates, not verified executions or task-success labels."}
    atomic_json(out / "report.json", report)
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    recover(args.root, args.frozen, args.out)


if __name__ == "__main__":
    main()
