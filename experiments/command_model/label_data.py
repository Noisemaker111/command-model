"""Freeze private review partitions and executable-label candidates, never gold-by-exit-code."""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path
import re
import time

from data_pipeline import atomic_json, json_bytes
from ingest_adapters import digest


READ = re.compile(r"^\s*Get-Content\s+(?:(?P<flag>-LiteralPath|-Path)\s+)?"
                  r"(?P<path>'(?:[^']|'')*'|\"[^\"$`]*\"|[^\s'\";|&<>$`(){}]+)"
                  r"\s+-(?P<mode>Head|TotalCount|Tail)\s+(?P<n>\d+)\s*$", re.I)


def shell_text(command):
    if isinstance(command, str):
        return command
    if not isinstance(command, list) or not command:
        return None
    executable = str(command[0]).replace("\\", "/").split("/")[-1].lower()
    if executable not in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        return None
    for i, value in enumerate(command[:-1]):
        if value.lower() in {"-command", "-c"} and i + 2 == len(command):
            return command[i + 1]
    return None


def read_contract(command):
    text = shell_text(command)
    match = READ.fullmatch(text) if isinstance(text, str) else None
    if not match or not 1 <= int(match["n"]) <= 100:
        return None
    path = match["path"]
    if not path.startswith(("'", '"')) and path.startswith(("@", "#", "-")):
        return None
    if path.startswith("'"):
        path = path[1:-1].replace("''", "'")
    elif path.startswith('"'):
        path = path[1:-1]
    if not path or (match["flag"] or "").lower() != "-literalpath" and any(c in path for c in "*?[]"):
        return None
    # Never expose an original path as the generated training target.
    return {"op": "read_tail" if match["mode"].lower() == "tail" else "read_head",
            "limit": int(match["n"]), "value": "", "path": "fixture.txt"}


def session_key(row):
    text = str(row["session"])
    match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text, re.I)
    return digest(match.group().lower() if match else [row["source_kind"], text])


def task_key(context):
    """Conservative extra grouping signal; not a semantic equivalence claim."""
    if len(context.split()) < 8:
        return None
    normalized = re.sub(r"\s+", " ", context).strip().lower()
    # Case/whitespace, UUIDs and absolute path differences cannot split a copied task.
    normalized = re.sub(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", "<id>", normalized)
    normalized = re.sub(r"[a-z]:[\\/][^\s\"'<>]+", "<path>", normalized)
    return digest(normalized)


class Groups:
    def __init__(self):
        self.parents = {}

    def find(self, key):
        self.parents.setdefault(key, key)
        if self.parents[key] != key:
            self.parents[key] = self.find(self.parents[key])
        return self.parents[key]

    def join(self, a, b):
        a, b = self.find(a), self.find(b)
        self.parents[max(a, b)] = min(a, b)


def assign_partitions(group_counts, seed):
    """Balance record counts without breaking groups; freeze the assignment afterward."""
    weights = {"train": .30, "development": .10, "reserve": .50, "final_test": .10}
    total = sum(group_counts.values())
    remaining = {key: total * value for key, value in weights.items()}
    assignment = {}
    for group in sorted(group_counts, key=lambda g: (-group_counts[g], digest([seed, g]))):
        split = max(remaining, key=lambda s: (remaining[s], digest([seed, group, s])))
        assignment[group] = split
        remaining[split] -= group_counts[group]
    return assignment


def iter_rows(run, root):
    for source in run["sources"]:
        key = source["normalization"]
        report = json.loads((root / "normalized" / (key + ".json")).read_text(encoding="utf-8"))
        sha = hashlib.sha256()
        with gzip.open(root / "normalized" / (key + ".jsonl.gz"), "rb") as handle:
            for raw in handle:
                sha.update(raw)
                yield json.loads(raw), key
        if sha.hexdigest() != report["normalized_sha256"]:
            raise ValueError("Normalized artifact hash mismatch: " + key)


def freeze(root, out, run_name=None, seed="command-specialist-v2"):
    started = time.perf_counter()
    if out.exists():
        raise ValueError("Freeze output exists; use a new directory to preserve partitions")
    run_name = run_name or json.loads((root / "latest.json").read_text(encoding="utf-8"))["run"]
    run = json.loads((root / "runs" / run_name).read_text(encoding="utf-8"))
    groups = Groups()
    task_owners = {}
    rows = []
    seen = {}
    counts = collections.Counter()
    for row, artifact in iter_rows(run, root):
        counts["input_command_observations"] += 1
        identity = digest([row["record_id"], row["command_sha256"], row["output_sha256"]])
        if identity in seen:
            counts["duplicate_observations"] += 1
            continue
        seen[identity] = True
        session = session_key(row)
        groups.find(session)
        for parent in row.get("parent_sessions", []):
            groups.join(session, session_key({"session": parent, "source_kind": row["source_kind"]}))
        task = task_key(row["request_context"]) if not row["context_truncated"] else None
        if task:
            if task in task_owners:
                groups.join(session, task_owners[task])
            else:
                task_owners[task] = session
        contract = read_contract(row["command"])
        reasons = []
        if row["context_association"] == "missing":
            reasons.append("missing_user_context")
        if row["context_truncated"]:
            reasons.append("context_truncated")
        if row.get("source_changed_during_snapshot"):
            reasons.append("changing_source")
        if row.get("call_id_conflict"):
            reasons.append("conflicting_call_id")
        if not row["result_present"]:
            reasons.append("missing_result")
        if row["source_kind"] == "legacy":
            reasons.append("legacy_extraction_unverified")
        # This view is deliberately free of transcript text, original paths and outputs.
        # Private source pointers allow an authorized review to recover them separately.
        rows.append({"id": identity, "record_id": row["record_id"], "source_kind": row["source_kind"],
                     "session_group": session, "task_key": task, "artifact": artifact,
                     "command_sha256": row["command_sha256"], "output_sha256": row["output_sha256"],
                     "labels": row["labels"], "exit_code_origin": row["exit_code_origin"],
                     "review_reasons": reasons, "read_contract_candidate": contract,
                     "training_eligible": False, "correctness": "abstain"})
        counts["source:" + row["source_kind"]] += 1
        counts["read_contract_candidates"] += contract is not None
        for reason in reasons:
            counts["review:" + reason] += 1
    out.mkdir(parents=True)
    (out / "labeler-source.py").write_bytes(Path(__file__).read_bytes())
    split_counts = collections.Counter()
    group_counts = collections.Counter()
    for row in rows:
        group_counts[groups.find(row["session_group"])] += 1
    assignment = assign_partitions(group_counts, seed)
    files = {}
    hashes = {}
    try:
        for split in ("train", "development", "reserve", "final_test"):
            files[split] = (out / (split + ".jsonl")).open("wb")
            hashes[split] = hashlib.sha256()
        for row in rows:
            group = groups.find(row["session_group"])
            row["partition_group"] = group
            row["partition"] = split = assignment[group]
            data = json_bytes(row)
            files[split].write(data)
            hashes[split].update(data)
            split_counts[split] += 1
    finally:
        for handle in files.values():
            handle.close()
    manifest = {"schema": 1, "run": run_name, "pipeline_version": run["pipeline_version"],
                "labeler_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "seed": seed, "target_record_percentages": {"train": 30, "development": 10, "reserve": 50, "final_test": 10},
                "split_records": dict(split_counts), "unique_observations": len(rows), "counts": dict(counts),
                "partition_groups": len(group_counts), "largest_group_records": max(group_counts.values(), default=0),
                "artifact_sha256": {s: h.hexdigest() for s, h in hashes.items()},
                "elapsed_seconds": time.perf_counter() - started,
                "training_eligible": 0,
                "gate": "review_partitions_only: context is unverified; no historical task-success labels yet",
                "limitations": ["Record proportions are balanced subject to keeping related sessions intact; large groups can prevent exact targets.",
                                "Exact and normalized-context copies are grouped; semantic near-duplicate review remains required.",
                                "Missing context and opaque tool formats remain explicit; do not treat these partitions as a blind benchmark yet.",
                                "The read contract is a parser candidate, not proof of original intent or historical success."]}
    atomic_json(out / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("work/command-specialist/data-v2"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run", help="Saved run filename; defaults to latest")
    args = parser.parse_args()
    freeze(args.root, args.out, args.run)


if __name__ == "__main__":
    main()
