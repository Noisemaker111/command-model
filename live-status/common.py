"""Shared paths and JSONL helpers for the live-status pipeline.

Private corpora live under LIVE_STATUS_HOME (default: <main checkout>/work/live-status),
which Git ignores. Worktrees share that location so data survives branch changes.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Iterable, Iterator

ROOT = Path(__file__).resolve().parent


def _main_checkout() -> Path:
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return Path(common).parent
    except (OSError, subprocess.CalledProcessError):
        return ROOT.parent


def home() -> Path:
    env = os.environ.get("LIVE_STATUS_HOME")
    path = Path(env) if env else _main_checkout() / "work" / "live-status"
    path.mkdir(parents=True, exist_ok=True)
    return path


def private_dir() -> Path:
    """Raw (unredacted) data. Never sent to teachers, judges or logs."""
    path = home() / "private"
    if not path.exists():
        path.mkdir(parents=True)
        protect(path)
    return path


def protect(path: Path) -> None:
    """Best-effort owner-only ACL on Windows; chmod 700 elsewhere."""
    if os.name == "nt":
        user = os.environ.get("USERNAME")
        if user:
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:(OI)(CI)F"],
                           capture_output=True)
    else:
        os.chmod(path, 0o700)


def read_jsonl(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    os.replace(tmp, path)
    return count


def append_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()


def sha(text: str, n: int = 16) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:n]


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
