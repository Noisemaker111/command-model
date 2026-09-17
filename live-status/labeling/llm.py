"""Minimal OpenAI-compatible client for the local CLIProxyAPI (teacher and judge).

Only redacted text may be passed here; `chat()` refuses input that still contains
secret patterns, so a redaction regression fails loudly instead of leaking.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from redaction.redact import find_secrets

BASE_URL = os.environ.get("LIVE_STATUS_LLM_URL", "http://127.0.0.1:8317/v1")
API_KEY = os.environ.get("LIVE_STATUS_LLM_KEY", "local")  # CLIProxyAPI localhost gate, not a vendor key
DEFAULT_MODEL = os.environ.get("LIVE_STATUS_TEACHER", "claude-haiku-4-5-20251001")
MODEL_CODES = {"claude-haiku-4-5-20251001": "h", "claude-opus-5": "o", "claude-sonnet-5": "s"}


def model_code(model: str) -> str:
    """Short per-model tag so candidates from different teachers stay distinguishable."""
    return MODEL_CODES.get(model, model.split("-")[1][:1] if "-" in model else model[:1])


MAX_COOLDOWN_WAIT = float(os.environ.get("LIVE_STATUS_MAX_COOLDOWN", "900"))


class SecretInPrompt(RuntimeError):
    pass


class QuotaExhausted(RuntimeError):
    """The provider asked for a longer pause than we are willing to wait; stop the run."""


class _Breaker:
    """Shared pause: one 429 makes every worker wait instead of burning requests."""

    def __init__(self):
        import threading
        self.lock = threading.Lock()
        self.until = 0.0

    def trip(self, seconds: float) -> None:
        with self.lock:
            self.until = max(self.until, time.time() + seconds)

    def wait(self) -> None:
        delay = self.until - time.time()
        if delay > 0:
            time.sleep(delay)


BREAKER = _Breaker()


def _cooldown_seconds(detail: str) -> float:
    try:
        err = json.loads(detail).get("error", {})
        return float(err.get("reset_seconds") or 60)
    except (ValueError, AttributeError):
        return 60.0


def chat(messages: list[dict], *, model: str = DEFAULT_MODEL, max_tokens: int = 4000,
         temperature: float | None = None, retries: int = 4, timeout: int = 300) -> tuple[str, dict]:
    for m in messages:
        hits = find_secrets(m["content"])
        if hits:
            raise SecretInPrompt(f"refusing to send {len(hits)} secret-like span(s) to {model}")
    body = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if temperature is not None:
        body["temperature"] = temperature
    data = json.dumps(body).encode()
    delay = 5.0
    for attempt in range(retries + 1):
        BREAKER.wait()
        req = urllib.request.Request(f"{BASE_URL}/chat/completions", data=data, method="POST",
                                     headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                out = json.loads(resp.read())
            content = out["choices"][0]["message"]["content"]
            if not content:
                raise ValueError(f"empty reply (finish_reason={out['choices'][0].get('finish_reason')})")
            return content, out.get("usage") or {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            if exc.code == 429:
                wait = _cooldown_seconds(detail)
                if wait > MAX_COOLDOWN_WAIT:
                    raise QuotaExhausted(f"{model} cooling down for {wait:.0f}s") from exc
                BREAKER.trip(wait + 5)
                continue
            detail = detail[:300]
            if exc.code in (400, 401, 403) or attempt == retries:
                raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as exc:
            if attempt == retries:
                raise RuntimeError(f"LLM call failed: {exc}") from exc
        time.sleep(delay)
        delay *= 2
    raise RuntimeError("unreachable")


SEPARATORS = frozenset(" \r\n\t,")


def parse_results(text: str) -> list[dict]:
    """Result objects from {"results": [...]}, salvaging complete items from a truncated reply."""
    try:
        data = parse_json(text)
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            return data["results"]
        if isinstance(data, list):
            return data
    except ValueError:
        pass
    start = text.find("[", max(0, text.find('"results"')))
    if start == -1:
        raise ValueError(f"no results array in reply: {text[:200]}")
    dec = json.JSONDecoder()
    out, i = [], start + 1
    while i < len(text):
        while i < len(text) and text[i] in SEPARATORS:
            i += 1
        if i >= len(text) or text[i] != "{":
            break
        try:
            obj, i = dec.raw_decode(text, i)
        except ValueError:
            break
        out.append(obj)
    return out


def parse_json(text: str):
    """Extract the first JSON object/array from a model reply."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        i = text.find(opener)
        j = text.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(text[i:j + 1])
            except ValueError:
                continue
    raise ValueError(f"no JSON in reply: {text[:200]}")
