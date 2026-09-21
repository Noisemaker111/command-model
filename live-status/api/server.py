"""Local-first status service: POST /v1/summarize-command.

  python live-status/cli.py serve --backend ollama:live-status --port 8765

Order per request: size limits -> redaction -> cache -> [optional heuristic fast path] ->
model (bounded concurrency, timeout; `--best-of N` samples N candidates and lets Jev pick) ->
validation -> heuristic fallback.
Commands are never logged; optional logs hold hashes, timings and the status only.
For remote use set LIVE_STATUS_API_TOKEN and pass --tls-cert/--tls-key; binding a
non-loopback address without a token is refused.
"""
from __future__ import annotations

import argparse
import collections
import hmac
import ipaddress
import json
import os
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import sha  # noqa: E402
from data_miner.mine import normalize_ws  # noqa: E402
from evaluation.validators import check  # noqa: E402
from inference.heuristic import FAST_PATH, describe  # noqa: E402
from redaction.redact import leaks, redact  # noqa: E402

MAX_BODY = 64_000
MAX_COMMAND = 20_000
MODEL_INPUT_CHARS = 6000


class Service:
    def __init__(self, backend=None, *, cache_size: int = 2048, log_path: Path | None = None,
                 max_concurrency: int = 4, queue_wait: float = 2.0, fast_path: bool = False,
                 best_of: int = 1):
        self.backend = backend
        self.cache: collections.OrderedDict[str, str] = collections.OrderedDict()
        self.cache_size = cache_size
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(max_concurrency)
        self.queue_wait = queue_wait
        self.fast_path = fast_path
        self.best_of = best_of
        self.log_path = log_path

    def _log(self, row: dict) -> None:
        if self.log_path:
            with self.lock, open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")

    def summarize(self, command: str, shell: str | None, cwd: str | None) -> dict:
        t0 = time.perf_counter()
        red = redact(command[:MAX_COMMAND])
        key = sha(f"{shell}|{normalize_ws(red)}")
        with self.lock:
            hit = self.cache.get(key)
            if hit is not None:
                self.cache.move_to_end(key)
        if hit is not None:
            return self._done(hit, "cache", key, t0)
        h_text, h_conf = describe(red, shell)
        if (self.fast_path and h_conf >= FAST_PATH) or self.backend is None:
            return self._done(h_text, "heuristic" if h_conf >= FAST_PATH else "fallback", key, t0, cache=h_conf >= FAST_PATH)
        status = None
        source = getattr(self.backend, "source", "model")
        if self.slots.acquire(timeout=self.queue_wait):
            try:
                model_in = red if len(red) <= MODEL_INPUT_CHARS else red[:MODEL_INPUT_CHARS] + " …"
                status, _ = self.backend.generate(model_in)
                if self.best_of > 1 and source == "model":
                    picked, source = self._best_of(model_in, status)
                    status = picked or status
            except Exception as exc:  # timeouts, backend down
                source = f"fallback:{type(exc).__name__}"
            finally:
                self.slots.release()
        else:
            source = "fallback:busy"
        if status is not None:
            v = check(status, command)
            if not v["pass"] or leaks(status, command):
                status, source = None, "fallback:invalid"
        if status is None:
            return self._done(h_text, source, key, t0, cache=False)
        return self._done(status, source, key, t0)

    def _best_of(self, command: str, greedy: str) -> tuple[str | None, str]:
        """Sample extra candidates and let Jev pick; falls back to the greedy answer."""
        from judging.jev import combined, grade
        pool = [greedy] if greedy else []
        for i in range(self.best_of - 1):
            try:
                text, _ = self.backend.generate(command, temperature=0.8, seed=1000 + i)
            except Exception:
                break
            if text and text not in pool:
                pool.append(text)
        pool = [c for c in pool if check(c, command)["pass"]]
        if len(pool) < 2:
            return (pool[0] if pool else None), "model"
        try:
            graded = grade([(str(i), command, c) for i, c in enumerate(pool)])
        except Exception:
            return greedy, "model:best-of-failed"
        scored = [(combined(g), pool[int(k)]) for k, g in graded.items() if "error" not in g]
        if not scored:
            return greedy, "model:best-of-failed"
        return max(scored)[1], "model:best-of"

    def _done(self, status: str, source: str, key: str, t0: float, cache: bool = True) -> dict:
        if cache and self.cache_size:
            with self.lock:
                self.cache[key] = status
                self.cache.move_to_end(key)
                while len(self.cache) > self.cache_size:
                    self.cache.popitem(last=False)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        self._log({"ts": time.time(), "key": key, "source": source, "ms": ms, "status": status})
        return {"status": status, "source": source, "latency_ms": ms}


class RateLimiter:
    def __init__(self, per_minute: int):
        self.rate = per_minute / 60.0
        self.cap = max(1, per_minute)
        self.buckets: dict[str, tuple[float, float]] = {}
        self.lock = threading.Lock()

    def allow(self, client: str) -> bool:
        if self.rate <= 0:
            return True
        now = time.monotonic()
        with self.lock:
            tokens, last = self.buckets.get(client, (self.cap, now))
            tokens = min(self.cap, tokens + (now - last) * self.rate)
            ok = tokens >= 1
            self.buckets[client] = (tokens - 1 if ok else tokens, now)
            return ok


def make_handler(service: Service, token: str | None, limiter: RateLimiter):
    class Handler(BaseHTTPRequestHandler):
        server_version = "live-status/1"

        def log_message(self, *args):  # never echo request lines (they can carry data)
            pass

        def _send(self, code: int, obj: dict) -> None:
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/healthz":
                self._send(200, {"ok": True, "backend": getattr(service.backend, "name", None)})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/v1/summarize-command":
                return self._send(404, {"error": "not found"})
            if token:
                got = self.headers.get("Authorization", "")
                if not hmac.compare_digest(got.encode(), f"Bearer {token}".encode()):
                    return self._send(401, {"error": "unauthorized"})
            if not limiter.allow(self.client_address[0]):
                return self._send(429, {"error": "rate limited"})
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._send(413, {"error": "body too large or empty"})
            try:
                req = json.loads(self.rfile.read(length))
                command = req["command"]
                if not isinstance(command, str) or not command.strip():
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                return self._send(400, {"error": "expected JSON with a non-empty string 'command'"})
            if len(command) > MAX_COMMAND:
                return self._send(413, {"error": "command too long"})
            out = service.summarize(command, req.get("shell"), req.get("cwd"))
            self._send(200, {"status": out["status"]} if not req.get("debug") else out)

    return Handler


def main(argv=None):
    p = argparse.ArgumentParser(prog="serve")
    p.add_argument("--backend", default=os.environ.get("LIVE_STATUS_BACKEND", "ollama:live-status"),
                   help="parser:powershell | ollama:<model> | llama-server:<url> | hf:<base>@<adapter> | none")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--timeout", type=float, default=8.0)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--rate-per-minute", type=int, default=0, help="0 disables (default for localhost)")
    p.add_argument("--cache-size", type=int, default=2048)
    p.add_argument("--log", type=Path, help="JSONL log of hashes/timings/statuses (off by default)")
    p.add_argument("--best-of", type=int, default=1,
                   help="sample N candidates and let Jev select (measured +8 points, ~5x latency)")
    p.add_argument("--fast-path", action="store_true", help="answer high-confidence heuristic matches without the model (judge-rated less specific; off by default)")
    p.add_argument("--tls-cert"); p.add_argument("--tls-key")
    a = p.parse_args(argv)
    token = os.environ.get("LIVE_STATUS_API_TOKEN")
    if not ipaddress.ip_address(a.host if a.host != "localhost" else "127.0.0.1").is_loopback and not token:
        raise SystemExit("Refusing non-loopback bind without LIVE_STATUS_API_TOKEN.")
    backend = None
    if a.backend != "none":
        from inference.backends import from_spec
        backend = from_spec(a.backend)
        backend.timeout = a.timeout
        if hasattr(backend, "warm"):
            backend.warm()
    service = Service(backend, cache_size=a.cache_size, log_path=a.log, max_concurrency=a.concurrency,
                      fast_path=a.fast_path, best_of=a.best_of)
    httpd = ThreadingHTTPServer((a.host, a.port), make_handler(service, token, RateLimiter(a.rate_per_minute)))
    httpd.daemon_threads = True
    scheme = "http"
    if a.tls_cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(a.tls_cert, a.tls_key)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    print(f"live-status listening on {scheme}://{a.host}:{a.port}/v1/summarize-command backend={getattr(backend, 'name', None)}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
