"""Build a bounded, diverse review queue from the frozen training partition only."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

from data_pipeline import atomic_json


def build(frozen, out, per_group=3):
    if out.exists():
        raise ValueError("Review queue exists; choose a new output file")
    if not 1 <= per_group <= 10:
        raise ValueError("Samples per group must be in 1..10")
    manifest = json.loads((frozen / "manifest.json").read_text(encoding="utf-8"))
    raw = (frozen / "train.jsonl").read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest["artifact_sha256"]["train"]:
        raise ValueError("Frozen training partition changed")
    groups = collections.defaultdict(list)
    for line in raw.splitlines():
        row = json.loads(line)
        if row["partition"] != "train":
            raise ValueError("Non-training record in training partition")
        reasons = row["review_reasons"]
        action = ("reconcile_with_native_source" if "legacy_extraction_unverified" in reasons else
                  "recover_context_or_result" if any(r in reasons for r in ("missing_user_context", "context_truncated", "missing_result")) else
                  "inspect_conflicting_identity" if "conflicting_call_id" in reasons else
                  "develop_task_verifier")
        key = (action, row["source_kind"], row["labels"]["execution"],
               row["labels"]["output_error_keyword"], bool(row["read_contract_candidate"]))
        groups[key].append(row)
    queue = []
    for (action, source, execution, error_keyword, read_candidate), rows in sorted(groups.items()):
        samples = []
        seen_commands = set()
        for row in sorted(rows, key=lambda x: x["id"]):
            if row["command_sha256"] in seen_commands:
                continue
            seen_commands.add(row["command_sha256"])
            if len(samples) < per_group:
                samples.append({key: row[key] for key in ("id", "record_id", "artifact", "review_reasons")})
        queue.append({"action": action, "source_kind": source, "execution": execution,
                      "error_keyword": error_keyword, "read_contract_candidate": read_candidate,
                      "record_count": len(rows), "unique_command_strings": len(seen_commands), "samples": samples})
    queue.sort(key=lambda x: (-x["record_count"], x["action"], x["source_kind"]))
    report = {"used_partitions": ["train"], "frozen_train_sha256": manifest["artifact_sha256"]["train"],
              "training_records": sum(g["record_count"] for g in queue), "review_groups": len(queue),
              "sampled_records": sum(len(g["samples"]) for g in queue), "groups": queue,
              "scope": "Routing and verifier-development samples only. A reviewed sample does not label its whole group."}
    atomic_json(out, report)
    print(json.dumps({k: v for k, v in report.items() if k != "groups"}, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-group", type=int, default=3)
    args = parser.parse_args()
    build(args.frozen, args.out, args.per_group)


if __name__ == "__main__":
    main()
