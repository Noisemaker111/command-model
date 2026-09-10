"""Private, resumable source snapshots and command normalization; standard library only."""
from __future__ import annotations

import argparse
import base64
import collections
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid

from ingest_adapters import Adapter, digest


TABLES = {"opencode": ("session", "session_v2", "message", "part", "session_message"),
          "cursor": ("meta", "blobs")}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def atomic_json(path, value):
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_bytes(json_bytes(value))
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def fingerprint(path, database=False):
    result = []
    for p in [path] + ([Path(str(path) + "-wal")] if database else []):
        try:
            s = p.stat()
            result.append([str(p), s.st_size, s.st_mtime_ns])
        except FileNotFoundError:
            result.append([str(p), None, None])
    return result


def inventory(config):
    sources = []
    issues = []
    seen = set()
    for spec in config["sources"]:
        root = Path(spec["path"]).expanduser().resolve()
        if spec["kind"] not in {"codex", "claude", "legacy", "opencode", "cursor"}:
            raise ValueError("Unsupported source kind: " + spec["kind"])
        if not root.exists():
            issues.append({"path": str(root), "reason": "missing_source_root"})
            continue
        paths = sorted(root.rglob(spec["glob"])) if root.is_dir() and spec.get("glob") else [root]
        if not paths:
            issues.append({"path": str(root), "reason": "no_matching_files"})
        for path in paths:
            key = str(path).casefold() if os.name == "nt" else str(path)
            if key in seen:
                continue
            seen.add(key)
            if path.is_file():
                sources.append({"path": str(path), "kind": spec["kind"], "size": path.stat().st_size})
            else:
                issues.append({"path": str(path), "reason": "not_a_file"})
    return sources, issues


def sqlite_rows(path, kind, metadata):
    """A read transaction freezes selected transcript tables, including committed WAL data.

    Unrelated account/credential tables are neither read nor copied. The snapshot
    is a lossless logical export of the selected rows, not a database file backup.
    """
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        available = {x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        selected = set(TABLES[kind]) & available
        metadata["selected_tables"] = sorted(selected)
        metadata["excluded_tables"] = sorted(available - selected)
        metadata["missing_expected_tables"] = sorted(set(TABLES[kind]) - available)
        metadata["table_rows"] = {}
        # Export old messages and parts in one deterministic temporal stream so
        # preceding user context does not depend on physical SQLite row order.
        groups = [[t] for t in TABLES[kind] if t in selected and t not in {"message", "part"}]
        old = [t for t in ("message", "part") if t in selected]
        if old:
            groups.insert(0, old)
        for group in groups:
            if len(group) == 2:
                query = ("SELECT 'message',id,session_id,time_created FROM message UNION ALL "
                         "SELECT 'part',id,session_id,time_created FROM part ORDER BY 3,4,1,2")
                order = db.execute(query)
                for table, row_id, *_ in order:
                    cur = db.execute(f'SELECT * FROM "{table}" WHERE id=?', (row_id,))
                    row = dict(zip([x[0] for x in cur.description], cur.fetchone()))
                    metadata["table_rows"][table] = metadata["table_rows"].get(table, 0) + 1
                    yield {"table": table, "row": row}
            else:
                table = group[0]
                columns = [x[1] for x in db.execute(f'PRAGMA table_info("{table}")')]
                order = 'session_id,seq,id' if table == "session_message" else 'id' if "id" in columns else 'key'
                cur = db.execute(f'SELECT * FROM "{table}" ORDER BY {order}')
                metadata["table_rows"][table] = 0
                for values in cur:
                    row = {k: {"base64": base64.b64encode(v).decode()} if isinstance(v, bytes) else v
                           for k, v in zip(columns, values)}
                    metadata["table_rows"][table] += 1
                    yield {"table": table, "row": row}
        db.rollback()


def snapshot(source, out):
    path = Path(source["path"])
    database = source["kind"] in TABLES
    before = fingerprint(path, database)
    meta = {"source_path": str(path), "source_kind": source["kind"], "fingerprint_before": before,
            "snapshot_format": "sqlite_selected_rows_jsonl" if database else "original_bytes",
            "snapshot_started_unix": time.time()}
    sha = hashlib.sha256()
    size = 0
    fd, name = tempfile.mkstemp(prefix="snapshot-", suffix=".tmp", dir=out / "tmp")
    os.close(fd)
    temp = Path(name)
    try:
        with temp.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=1, mtime=0, filename="") as target:
            if database:
                for row in sqlite_rows(path, source["kind"], meta):
                    block = json_bytes(row)
                    sha.update(block)
                    size += len(block)
                    target.write(block)
            else:
                remaining = before[0][1]
                with path.open("rb") as handle:
                    while remaining:
                        block = handle.read(min(1024 * 1024, remaining))
                        if not block:
                            raise ValueError("Source shortened during snapshot")
                        remaining -= len(block)
                        size += len(block)
                        sha.update(block)
                        target.write(block)
        meta.update(snapshot_sha256=sha.hexdigest(), snapshot_bytes=size,
                    compressed_bytes=temp.stat().st_size, fingerprint_after=fingerprint(path, database))
        meta["source_changed_during_snapshot"] = before != meta["fingerprint_after"]
        target = out / "snapshots" / (sha.hexdigest() + ".gz")
        if target.exists():
            temp.unlink()
        else:
            temp.rename(target)
        return meta
    finally:
        temp.unlink(missing_ok=True)


def normalize(meta, out, version):
    snapshot_id = meta["snapshot_sha256"]
    # Include the source identity: formats without session IDs use it for grouping.
    source_key = digest(meta["source_path"])
    key = digest([snapshot_id, meta["source_kind"], source_key, version])
    report_path = out / "normalized" / (key + ".json")
    output_path = out / "normalized" / (key + ".jsonl.gz")
    if report_path.exists() and output_path.exists():
        return json.loads(report_path.read_text(encoding="utf-8")), True
    adapter = Adapter(meta["source_kind"], source_key)
    counts = collections.Counter()
    errors = []
    sha = hashlib.sha256()
    with gzip.open(out / "snapshots" / (snapshot_id + ".gz"), "rb") as handle:
        for number, raw in enumerate(handle, 1):
            sha.update(raw)
            counts["source_records"] += 1
            if not raw.strip():
                counts["disposition:blank"] += 1
                continue
            try:
                row = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                counts["disposition:malformed"] += 1
                errors.append({"line": number, "error_type": type(exc).__name__})
                continue
            if not isinstance(row, dict):
                counts["disposition:non_object"] += 1
                continue
            disposition = adapter.consume(row, {"snapshot": snapshot_id, "line": number})
            counts["disposition:" + disposition] += 1
    if sha.hexdigest() != snapshot_id:
        raise ValueError("Snapshot content hash mismatch")
    tmp = output_path.with_suffix(".tmp")
    row_sha = hashlib.sha256()
    with tmp.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=1, mtime=0, filename="") as target:
        for row in adapter.finish():
            row["source_path"] = meta["source_path"]
            row["source_changed_during_snapshot"] = meta["source_changed_during_snapshot"]
            encoded = json_bytes(row)
            target.write(encoded)
            row_sha.update(encoded)
            counts["commands"] += 1
            counts["execution:" + row["labels"]["execution"]] += 1
            counts["with_user_context"] += bool(row["request_context"])
            counts["missing_result"] += not row["result_present"]
            counts["source_truncation_marker"] += row["labels"]["source_truncation_marker"]
    tmp.replace(output_path)
    counts.update(adapter.counts)
    if counts["source_records"] != sum(v for k, v in counts.items() if k.startswith("disposition:")):
        raise AssertionError("Every source record must have exactly one disposition")
    report = {"key": key, "snapshot_sha256": snapshot_id, "pipeline_version": version,
              "normalized_sha256": row_sha.hexdigest(), "counts": dict(counts), "parse_errors": errors}
    atomic_json(report_path, report)
    return report, False


def run(config_path, out, refresh=False):
    started = time.perf_counter()
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for folder in ("snapshots", "normalized", "runs", "tmp", "versions"):
        (out / folder).mkdir(exist_ok=True)
    # One writer owns this cache. A crashed run leaves an explicit lock to inspect.
    lock = out / "writer.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        return run_locked(config_path, out, refresh, started)
    finally:
        lock.unlink()


def run_locked(config_path, out, refresh, started):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    sources, issues = inventory(config)
    code = {name: Path(__file__).with_name(name).read_text(encoding="utf-8")
            for name in ("data_pipeline.py", "ingest_adapters.py")}
    version = digest(code)
    version_file = out / "versions" / (version + ".json")
    if version_file.exists():
        if digest(json.loads(version_file.read_text(encoding="utf-8"))) != version:
            raise ValueError("Pipeline source archive hash mismatch")
    else:
        atomic_json(version_file, code)
    cache_path = out / "source-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    totals = collections.Counter()
    entries = []
    dirty = False
    print(json.dumps({"phase": "inventory", "files": len(sources), "bytes": sum(s["size"] for s in sources), "issues": len(issues)}), flush=True)
    for index, source in enumerate(sources):
        key = digest([source["kind"], source["path"]])
        saved = cache.get(key)
        try:
            signature = fingerprint(Path(source["path"]), source["kind"] in TABLES)
            hit = (not refresh and saved and saved["fingerprint_after"] == signature
                   and not saved["source_changed_during_snapshot"]
                   and (out / "snapshots" / (saved["snapshot_sha256"] + ".gz")).exists())
            meta = saved if hit else snapshot(source, out)
            report, normalized_hit = normalize(meta, out, version)
            totals.update(report["counts"])
            totals["snapshot_cache_hits"] += bool(hit)
            totals["normalization_cache_hits"] += normalized_hit
            totals["source_files_processed"] += 1
            totals["source_changed_during_snapshot"] += meta["source_changed_during_snapshot"]
            entries.append({"source": source, "snapshot": meta, "normalization": report["key"]})
            cache[key] = meta
            dirty = dirty or not hit
        except (OSError, ValueError, sqlite3.Error, TypeError, KeyError) as exc:
            issues.append({"path": source["path"], "reason": "processing_failed", "error_type": type(exc).__name__, "error": str(exc)[:300]})
            totals["source_files_failed"] += 1
        if index % 25 == 0 or index == len(sources) - 1:
            if dirty:
                atomic_json(cache_path, cache)
                dirty = False
            print(json.dumps({"phase": "ingest", "files_done": index + 1, "commands": totals["commands"],
                              "failures": totals["source_files_failed"], "elapsed_seconds": round(time.perf_counter() - started, 2)}), flush=True)
    report = {"schema": 1, "pipeline_version": version, "config_sha256": digest(config),
              "created_unix": time.time(), "elapsed_seconds": time.perf_counter() - started,
              "discovered_files": len(sources), "discovered_bytes": sum(s["size"] for s in sources),
              "counts": dict(totals), "issues": issues, "sources": entries,
              "scope": "Configured sources only; snapshots and normalized rows are private, not training labels.",
              "cache_validation": "size/mtime including SQLite WAL; --refresh rereads sources; snapshots are SHA256 checked on normalization"}
    name = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8] + ".json"
    atomic_json(out / "runs" / name, report)
    atomic_json(out / "latest.json", {"run": name})
    print(json.dumps({k: v for k, v in report.items() if k != "sources"}, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("work/command-specialist/data-v2"))
    parser.add_argument("--refresh", action="store_true", help="Reread source bytes even when metadata is unchanged")
    args = parser.parse_args()
    report = run(args.config, args.out, args.refresh)
    if report["issues"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
