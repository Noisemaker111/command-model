"""Combine synthetic pilot training rows with verified TRAIN-only read derivatives."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

from contract import messages
from data_pipeline import atomic_json, json_bytes


def prepare(pilot, verified, frozen, out):
    original = (pilot / "train.jsonl").read_bytes()
    rows = [json.loads(line) for line in original.splitlines()]
    selected = [r for r in rows if r.get("origin") == "synthetic-fixture"]
    if any(r.get("split") != "train" for r in selected):
        raise ValueError("Synthetic input includes a non-training row")
    report = json.loads((verified / "export.json").read_text(encoding="utf-8"))
    frozen_manifest = json.loads((frozen / "manifest.json").read_text(encoding="utf-8"))
    train_hash = hashlib.sha256((frozen / "train.jsonl").read_bytes()).hexdigest()
    raw = (verified / "sft.jsonl").read_bytes()
    if (report["used_partitions"] != ["train"] or report["verifier_cases"] != 800
            or train_hash != frozen_manifest["artifact_sha256"]["train"]
            or report["frozen_train_sha256"] != train_hash
            or report["sft_sha256"] != hashlib.sha256(raw).hexdigest()):
        raise ValueError("Verified export integrity or partition mismatch")
    derivatives = [json.loads(line) for line in raw.splitlines()]
    if len(derivatives) != report["synthetic_training_examples"]:
        raise ValueError("Verified export count mismatch")
    combined = [{"id": r["id"], "messages": messages(r) + [{"role": "assistant", "content":
                json.dumps(r["expected"], separators=(",", ":"))}]} for r in selected] + derivatives
    if not combined or len({r["id"] for r in combined}) != len(combined):
        raise ValueError("Empty or duplicate training identities")
    out.mkdir(parents=True, exist_ok=False)
    payload = b"".join(json_bytes(r) for r in combined)
    (out / "sft.jsonl").write_bytes(payload)
    result = {"examples": len(combined), "synthetic_pilot_examples": len(selected),
              "excluded_pilot_historical_examples": len(rows) - len(selected),
              "verified_read_examples": len(derivatives), "used_historical_partitions": ["train"],
              "pilot_kinds": dict(collections.Counter(r["kind"] for r in selected)),
              "pilot_train_sha256": hashlib.sha256(original).hexdigest(),
              "verified_sft_sha256": report["sft_sha256"], "frozen_train_sha256": train_hash,
              "sft_sha256": hashlib.sha256(payload).hexdigest(),
              "scope": "Synthetic training only; historical commands supply read operation/count coverage, not task-success labels."}
    atomic_json(out / "manifest.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pilot", "verified", "frozen", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.pilot, args.verified, args.frozen, args.out), indent=2))
