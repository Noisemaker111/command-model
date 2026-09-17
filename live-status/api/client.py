"""Client usable against localhost or a remote gateway, with a local heuristic fallback.

  from api.client import summarize
  summarize("git status", shell="bash")                        # http://127.0.0.1:8765
  summarize(cmd, url="https://my-server.example", token="...")  # remote gateway
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_URL = os.environ.get("LIVE_STATUS_URL", "http://127.0.0.1:8765")


def summarize(command: str, shell: str | None = None, cwd: str | None = None, *, url: str = DEFAULT_URL,
              token: str | None = os.environ.get("LIVE_STATUS_API_TOKEN"), timeout: float = 3.0) -> str:
    from redaction.redact import redact
    body = json.dumps({"command": redact(command), "shell": shell, "cwd": cwd}).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url.rstrip("/") + "/v1/summarize-command", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())["status"]
    except Exception:
        from inference.heuristic import describe
        return describe(redact(command), shell)[0]


if __name__ == "__main__":
    print(summarize(" ".join(sys.argv[1:]) or sys.stdin.read()))
