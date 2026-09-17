"""Secrets never reach teacher/judge prompts, stored redacted data, or service output."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from redaction.redact import find_secrets, redact  # noqa: E402

# Fixture values are fake but shaped like real credentials.
GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
SK = "sk-ant-" + "api03-Zx9Yw8Vu7Ts6Rq5Po4Nm3Lk2Ji1Hg0Fe"
AWS = "AKIA" + "IOSFODNN7EXAMPLE"
JWT = "eyJhbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0" + ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
PW = "Hunter2-Sup3r!"
CASES = [
    (f'curl -H "Authorization: Bearer {SK}" https://api.example.com/v1/models', SK),
    (f"git clone https://jon:{GH}@github.com/acme/app.git", GH),
    (f"$env:OPENAI_API_KEY = '{SK}'; node app.js", SK),
    (f"export GITHUB_TOKEN={GH} && gh pr list", GH),
    (f"aws configure set aws_access_key_id {AWS}", AWS),
    (f"mysql -u root -p{PW} -e 'show databases'", PW),
    (f"psql postgresql://admin:{PW}@db.internal:5432/app -c 'select 1'", PW),
    (f"Invoke-RestMethod -Uri https://x.test/api -Headers @{{Authorization = 'Bearer {JWT}'}}", JWT),
    (f"curl --cookie 'session={PW}abc' https://x.test", PW),
    (f"docker login -u jon --password {PW} registry.test", PW),
    (f"$pw = ConvertTo-SecureString '{PW}' -AsPlainText -Force", PW),
    (f'python -c "import requests; requests.get(url, params={{\'api_key\': \'{PW}\'}})"', PW),
    (f"curl 'https://x.test/hook?token={PW}&x=1'", PW),
    ("ssh-add - <<'EOF'\n-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmU\n-----END OPENSSH PRIVATE KEY-----\nEOF", "b3BlbnNzaC1rZXktdjEAAAAABG5vbmU"),
]
KEEP = [
    "git log --oneline -5 && git show 4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39",
    "Get-Process opencode2,node,powershell -ErrorAction SilentlyContinue",
    "export PATH=$PATH:/usr/local/bin && echo $GITHUB_TOKEN | wc -c",
    "$env:API_KEY = $secret; bun run dev",
    "Get-ChildItem -Recurse | Select-String -Pattern 'TODO' -PassThru",
    "git checkout -b fix/memory-budget && git push -u origin HEAD",
    'node -e "const tokens = {input: 1}; if (sessionID === x) console.log(password === y)"',
    "Get-Content C:/Users/me/.codex/sessions/rollout-2026-09-13T21-42-44-019a4c3c-6f1d-7e2a-8b1c-3d2e1f0a9b8c.jsonl",
    "$pwd = $svc.password; python -c \"password=os.environ['DB_PASSWORD']\"",
]


class RedactionTests(unittest.TestCase):
    def test_secrets_removed_and_idempotent(self):
        for cmd, secret in CASES:
            out = redact(cmd)
            self.assertNotIn(secret, out, cmd)
            self.assertEqual(redact(out), out)
            self.assertEqual(find_secrets(out), [], out)

    def test_ordinary_commands_preserved(self):
        for cmd in KEEP:
            self.assertEqual(redact(cmd), cmd)

    def test_extraction_and_teacher_prompt_never_carry_secrets(self):
        from data_miner.sources import REGISTRY
        from labeling import llm
        from labeling.teacher import _item, run_batch

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            lines = []
            for i, (cmd, _) in enumerate(CASES):
                lines.append({"type": "assistant", "message": {"model": "m", "content": [
                    {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": cmd, "description": "d"}}]}})
                lines.append({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": f"t{i}", "content": f"token was {CASES[i][1]}"}]}})
            path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
            recs = list(REGISTRY["claude-code"].extract(path))
            self.assertEqual(len(recs), len(CASES))

            sent = []

            def fake_urlopen(req, timeout=0):
                sent.append(req.data.decode())
                items = json.loads(json.loads(req.data)["messages"][1]["content"].split("Items:\n", 1)[1])
                body = {"choices": [{"message": {"content": json.dumps({"results": [{"id": x["id"], "a": "Running a command.", "b": "Running it."} for x in items]})}}]}
                return mock.MagicMock(__enter__=lambda s: mock.MagicMock(read=lambda: json.dumps(body).encode()), __exit__=lambda *a: False)

            items = [_item({"id": r["id"], "shell": "bash", "command_redacted": redact(r["command_raw"])}) for r in recs]
            with mock.patch.object(llm.urllib.request, "urlopen", fake_urlopen):
                run_batch(items, "test-model", False)
            joined = "\n".join(sent)
            for _, secret in CASES:
                self.assertNotIn(secret, joined)

            with self.assertRaises(llm.SecretInPrompt):
                llm.chat([{"role": "user", "content": CASES[0][0]}])

    def test_service_output_and_logs_never_carry_secrets(self):
        from api import server

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "service.log"
            svc = server.Service(backend=None, log_path=log, cache_size=0)
            for cmd, secret in CASES:
                status = svc.summarize(cmd, "bash", None)["status"]
                self.assertNotIn(secret, status)
            text = log.read_text(encoding="utf-8") if log.exists() else ""
            for _, secret in CASES:
                self.assertNotIn(secret, text)

    def test_validator_flags_leaks(self):
        from evaluation.validators import check
        cmd, secret = CASES[0]
        self.assertFalse(check(f"Calling the API with key {secret}.", cmd)["no_secret"])
        self.assertTrue(check("Listing models from api.example.com.", cmd)["no_secret"])


if __name__ == "__main__":
    unittest.main()
