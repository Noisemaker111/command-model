"""List benchmarked sub-1B base models by Hub creation date.

Reads the public FlameF0X CPU LM benchmark bucket and joins each measured row
with Hugging Face Hub metadata. This keeps discovery registry-driven instead
of starting from hand-picked model names.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from huggingface_hub import HfApi, download_bucket_files, list_bucket_tree

BUCKET = "FlameF0X/lm-cpu-benchmarks"
FINETUNE = re.compile(r"(instruct|chat|sft|dpo|rlhf|finetun|fine-?tun)", re.I)


def length_index(row: dict) -> float:
    values = []
    for value in (row.get("lengths") or {}).values():
        prefill, decode = value.get("prefill_ts", 0), value.get("decode_ts", 0)
        if prefill > 0 and decode > 0:
            values.append(2 * prefill * decode / (prefill + decode))
    return sum(values) / len(values) * len(values) / 5 if values else 0.0


def quality(row: dict) -> float:
    ppl = row.get("perplexity")
    return 1 / math.log2(ppl + 1) if ppl is not None and ppl > 0 else 0.0


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="2025-01-01")
    args = p.parse_args()
    files = [x.path for x in list_bucket_tree(BUCKET, prefix="results") if x.type == "file" and x.path.endswith(".json")]
    with tempfile.TemporaryDirectory() as td:
        pairs = [(name, str(Path(td) / Path(name).name)) for name in files]
        download_bucket_files(BUCKET, files=pairs)
        rows = [json.loads(Path(local).read_text(encoding="utf-8")) for _, local in pairs]
    rows = [r for r in rows if 10_000_000 <= r.get("parameters", 0) <= 1_000_000_000
            and not r.get("is_finetune") and not FINETUNE.search(r.get("model_id", "").split("/")[-1])]
    api = HfApi()
    def metadata(row: dict) -> dict:
        try:
            info = api.model_info(row["model_id"])
            created = info.created_at.isoformat() if info.created_at else ""
        except Exception:
            created = ""
        return {
            "model": row["model_id"],
            "created": created[:10],
            "parameters_m": round(row["parameters"] / 1e6),
            "architecture": row.get("architecture"),
            "cpu_prefill_tps": round(row.get("prefill_ts", 0), 1),
            "cpu_decode_tps": round(row.get("decode_ts", 0), 1),
            "perplexity": round(row["perplexity"], 2) if row.get("perplexity") is not None else None,
            "speed_quality": round(length_index(row) * quality(row), 2),
            "benchmarked": str(row.get("timestamp", ""))[:10],
        }
    with ThreadPoolExecutor(max_workers=8) as pool:
        found = list(pool.map(metadata, rows))
    found = [r for r in found if r["created"] >= args.since]
    found.sort(key=lambda r: (r["created"], r["speed_quality"]), reverse=True)
    print(json.dumps({"source": BUCKET, "count": len(found), "models": found}, indent=2))


if __name__ == "__main__":
    main()
