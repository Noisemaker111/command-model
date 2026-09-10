import gzip
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from prepare import corpus_audit


class DataTests(unittest.TestCase):
    def test_mining_excludes_unverified_and_compound_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [
                {"cmd": "Get-Content secret.txt -Head 7", "exit": 0, "session": "a", "source": "codex"},
                {"cmd": "Get-Content wrong.txt -Head 7", "exit": None, "session": "b", "source": "codex"},
                {"cmd": "Get-Content bad.txt -Tail 2", "exit": 0, "hidden": True, "session": "b", "source": "codex"},
                {"cmd": "Get-Content x.txt -Head 2; Remove-Item x.txt", "exit": 0, "session": "c", "source": "codex"},
            ]
            source = root / "records.jsonl"
            source.write_text("\n".join(map(json.dumps, rows)))
            audit, mined = corpus_audit(source, root / "fixtures")
            self.assertEqual(audit["recoverable_commands"], 4)
            self.assertEqual(len(mined), 1)
            self.assertEqual(mined[0]["expected"]["limit"], 7)
            self.assertNotIn("secret", json.dumps(mined))
            self.assertEqual(mined[0]["origin"], "verified-historical-command-synthetic-intent")

    def test_native_extraction_ignores_pasted_records_and_marks_caps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = root / "sessions"
            session.mkdir()
            native = {"timestamp": "2026-09-01T12:00:00Z", "type": "event_msg",
                      "payload": {"type": "item_completed", "item": {"type": "CommandExecution",
                                  "id": "one", "command": ["powershell", "-Command", "Get-Content x"],
                                  "exit_code": 1, "aggregated_output": "ERROR " + "x" * 30}}}
            pasted = {"timestamp": "2026-09-01T12:01:00Z", "type": "response_item",
                      "payload": {"type": "message", "role": "user", "content": [{"text": json.dumps(native)}]}}
            (session / "rollout-2026-09-01-test.jsonl").write_text("\n".join(map(json.dumps, [native, native, pasted])))
            output = root / "full.jsonl.gz"
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("extract_full.py")),
                                     "--sessions", str(session), "--out", str(output), "--max-output-chars", "10"],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            with gzip.open(output, "rt", encoding="utf-8") as handle:
                rows = list(map(json.loads, handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["exit_code"], 1)
            self.assertTrue(rows[0]["extraction_truncated"])
            self.assertFalse(rows[0]["intent_verified"])
            self.assertEqual(len(rows[0]["output"]), 10)


if __name__ == "__main__":
    unittest.main()
