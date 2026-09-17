"""Redact every string field of a JSONL file (for datasets that arrive from elsewhere)."""
from __future__ import annotations

from pathlib import Path

from common import read_jsonl, write_jsonl
from redaction.redact import find_secrets, redact

RAW_FIELDS = ("command_raw",)


def _walk(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_walk(v) for v in value]
    if isinstance(value, dict):
        return {k: _walk(v) for k, v in value.items() if k not in RAW_FIELDS}
    return value


def redact_file(src: Path, dst: Path) -> dict:
    if src.resolve() == dst.resolve():
        raise SystemExit("Refusing to overwrite the input; choose a new output path.")
    rows = [_walk(r) for r in read_jsonl(src)]
    residue = sum(1 for r in rows for v in r.values() if isinstance(v, str) and find_secrets(v))
    return {"rows": write_jsonl(dst, rows), "output": str(dst), "residual_secret_fields": residue}
