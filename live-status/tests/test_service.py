"""Service access boundaries: auth, request limits, loopback-only default, model-output validation."""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import server  # noqa: E402


class FakeBackend:
    name = "fake"

    def __init__(self, reply):
        self.reply = reply

    def generate(self, command):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply, {}


class CwdBackend(FakeBackend):
    source = "parser"
    accepts_cwd = True

    def generate(self, command, *, cwd=None):
        return f"Using {cwd}.", {}


def post(url, body, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body if isinstance(body, bytes) else json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class ServiceTests(unittest.TestCase):
    def serve(self, service, token=None, rate=0):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(service, token, server.RateLimiter(rate)))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return f"http://127.0.0.1:{httpd.server_address[1]}/v1/summarize-command"

    def test_auth_limits_and_rate(self):
        url = self.serve(server.Service(None), token="t0ken-for-test", rate=2)
        self.assertEqual(post(url, {"command": "git status"})[0], 401)
        self.assertEqual(post(url, {"command": "git status"}, "wrong")[0], 401)
        code, body = post(url, {"command": "git status"}, "t0ken-for-test")
        self.assertEqual((code, body), (200, {"status": "Checking Git status."}))
        self.assertEqual(post(url, b"x" * (server.MAX_BODY + 1), "t0ken-for-test")[0], 413)
        self.assertEqual(post(url, {"command": "ls"}, "t0ken-for-test")[0], 429)

    def test_non_loopback_requires_token(self):
        with mock.patch.dict(os.environ, {"LIVE_STATUS_API_TOKEN": ""}):
            with self.assertRaises(SystemExit):
                server.main(["--backend", "none", "--host", "0.0.0.0", "--port", "0"])

    def test_invalid_or_failed_model_output_falls_back(self):
        cmd = "python build_index.py --incremental"
        for reply in ("This command runs a script | tee log", RuntimeError("down"), "Uploading sk-ant-api03-Zx9Yw8Vu7Ts6Rq5Po4Nm3Lk2Ji1Hg0Fe."):
            out = server.Service(FakeBackend(reply), cache_size=0).summarize(cmd, "bash", None)
            self.assertTrue(out["source"].startswith("fallback"), out)
            self.assertEqual(out["status"], "Running build_index.py.")
        good = server.Service(FakeBackend("Building the incremental search index.")).summarize(cmd, "bash", None)
        self.assertEqual((good["status"], good["source"]), ("Building the incremental search index.", "model"))

    def test_deterministic_backend_keeps_source_and_skips_best_of(self):
        backend = FakeBackend("Checking Git status.")
        backend.source = "parser"
        service = server.Service(backend, cache_size=0, best_of=4)
        with mock.patch.object(service, "_best_of", side_effect=AssertionError("model-only")):
            out = service.summarize("git status", "powershell", None)
        self.assertEqual((out["status"], out["source"]), ("Checking Git status.", "parser"))

    def test_context_backend_receives_cwd(self):
        out = server.Service(CwdBackend("unused"), cache_size=0).summarize(
            "git status", "powershell", "C:/repo"
        )
        self.assertEqual((out["status"], out["source"]), ("Using C:/repo.", "parser"))


if __name__ == "__main__":
    unittest.main()
