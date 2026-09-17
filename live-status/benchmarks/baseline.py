"""Benchmark untuned tiny models (via Ollama) on a held-out split before any fine-tuning.

  python live-status/cli.py benchmark_base_models --models smollm2:135m gemma3:270m qwen2.5:0.5b --limit 150

Each model uses the chat few-shot prompt ("instruct"), temperature 0. Models run one
at a time; the previous model is unloaded so memory numbers are per model.
"""
from __future__ import annotations

import json
import urllib.request

from common import home, save_json
from evaluation.evaluate import load_split, run_eval
from inference.backends import OllamaBackend


def unload(backend: OllamaBackend) -> None:
    try:
        req = urllib.request.Request(f"{backend.url}/api/generate", method="POST",
                                     data=json.dumps({"model": backend.model, "keep_alive": 0}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
    except Exception:
        pass


def run(models: list[str], split: str = "test", limit: int = 0, judge: bool = True, prompt: str = "instruct",
        data: str = "v1") -> dict:
    rows = load_split(data, split, limit)
    table = []
    for m in models:
        backend = OllamaBackend(m, mode="plain" if prompt == "plain" else "instruct", timeout=60)
        name = f"baseline-{data}-{m.replace(':', '-').replace('/', '_')}-{prompt}-{split}{limit or ''}"
        print(f"== {m} ({len(rows)} rows)", flush=True)
        rep = run_eval(backend, rows, name, judge=judge)
        unload(backend)
        table.append({"model": m, "prompt": prompt, "n": rep["n"], "judge": rep.get("judge"), "validators": rep["validators"],
                      "latency_s": rep["latency_s"], "tokens_per_s": rep["tokens_per_s_median"], "memory": rep["memory"],
                      "cpu_percent_avg": rep["cpu_percent_avg"]})
        print(json.dumps(table[-1]), flush=True)
    out = {"split": split, "limit": limit, "data": data, "results": table}
    save_json(home() / "benchmarks" / f"baseline-{data}-{prompt}-{split}{limit or ''}.json", out)
    return out
