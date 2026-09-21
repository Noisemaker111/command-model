"""Measure the running service under concurrent load.

  python live-status/benchmarks/service_load.py --url http://127.0.0.1:8765 --clients 8 --requests 200

Sends held-out commands (cache disabled by appending a unique comment unless --allow-cache),
and reports end-to-end latency percentiles, throughput and the mix of answer sources.
"""
from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import home, read_jsonl, save_json  # noqa: E402


def post(url: str, body: dict, token: str | None, timeout: float) -> tuple[float, dict | None]:
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url.rstrip("/") + "/v1/summarize-command", data=data, headers=headers, method="POST")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return time.perf_counter() - t0, json.loads(resp.read())
    except Exception:
        return time.perf_counter() - t0, None


def main(argv=None):
    p = argparse.ArgumentParser(prog="service_load")
    p.add_argument("--url", default="http://127.0.0.1:8765")
    p.add_argument("--clients", type=int, default=8)
    p.add_argument("--requests", type=int, default=200)
    p.add_argument("--data", default="v1")
    p.add_argument("--split", default="test")
    p.add_argument("--token")
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--allow-cache", action="store_true")
    a = p.parse_args(argv)
    rows = list(read_jsonl(home() / "datasets" / a.data / f"{a.split}.jsonl"))
    jobs = [rows[i % len(rows)] for i in range(a.requests)]
    results: list[tuple[float, dict | None]] = []
    lock = threading.Lock()
    nxt = [0]

    def worker():
        while True:
            with lock:
                i = nxt[0]
                nxt[0] += 1
            if i >= len(jobs):
                return
            cmd = jobs[i]["command"] if a.allow_cache else f"{jobs[i]['command']}   # run {i}"
            out = post(a.url, {"command": cmd, "shell": jobs[i]["shell"], "debug": True}, a.token, a.timeout)
            with lock:
                results.append(out)

    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker) for _ in range(a.clients)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t0
    lat = sorted(x for x, _ in results)
    ok = [r for _, r in results if r]
    sources = collections.Counter((r.get("source") or "?").split(":")[0] for r in ok)
    rep = {"url": a.url, "clients": a.clients, "requests": len(results), "failed": len(results) - len(ok),
           "wall_s": round(wall, 2), "throughput_rps": round(len(results) / wall, 1),
           "latency_s": {"p50": round(lat[len(lat) // 2], 3), "p90": round(lat[int(len(lat) * 0.9)], 3),
                         "p99": round(lat[min(len(lat) - 1, int(len(lat) * 0.99))], 3),
                         "max": round(lat[-1], 3), "mean": round(statistics.mean(lat), 3)},
           "sources": dict(sources), "cache_bypassed": not a.allow_cache}
    save_json(home() / "benchmarks" / f"service-load-{a.clients}x{len(results)}.json", rep)
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
