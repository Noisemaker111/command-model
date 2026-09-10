import contextlib
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from data_pipeline import run
from ingest_adapters import digest
from recover_code import recover
from verify_more_operations import verify as verify_more


class RecoveryTests(unittest.TestCase):
    def test_search_listing_and_json_contract_oracles(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            report = verify_more(Path(directory) / 'verified')
        self.assertEqual(report['backend_checks'], 162)
        self.assertEqual(report['passed_checks'], 162)

    def test_powershell_ast_recovers_compound_reads_without_running_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "must-not-exist"
            commands = [
                f"Set-Content -LiteralPath '{marker}' -Value 'bad'; Get-Content -Tail 7 -LiteralPath 'a[1].txt'",
                "Get-Content 'b.txt' -Head 2; Get-Content -LiteralPath 'c.txt' -TotalCount:3",
                'Get-Content "$env:USERPROFILE/a" -Head 2',
                "Get-Content '*.txt' -Head 2",
                "Get-Content a -Raw",
                "if ($false) { Get-Content a -Tail 2 }",
                "'Get-Content fake -Head 2'",
                "Get-Content a -Head 2 -TotalCount 3",
                "Get-Content a -Tail 2 -Head 2",
                "Get-Content a -Head (",
            ]
            cases = root / "cases.jsonl"
            cases.write_text("\n".join(json.dumps({"id": i, "command": c}) for i, c in enumerate(commands)), encoding="utf-8")
            result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-File",
                                     str(Path(__file__).with_name("parse_read_commands.ps1")),
                                     "-Cases", str(cases), "-Results", str(root / "results.jsonl")],
                                    capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [json.loads(x) for x in (root / "results.jsonl").read_text().splitlines()]
            self.assertFalse(marker.exists())
            self.assertEqual(rows[0]["candidates"][0]["plan"]["limit"], 7)
            self.assertEqual([x["plan"]["limit"] for x in rows[1]["candidates"]], [2, 3])
            self.assertEqual(rows[2]["candidates"][0]["status"], "dynamic_positional")
            self.assertEqual(rows[3]["candidates"][0]["status"], "wildcard_path")
            self.assertEqual(rows[4]["candidates"][0]["status"], "unsupported_parameter")
            self.assertIn("IfStatementAst", rows[5]["candidates"][0]["control_context"])
            self.assertEqual(rows[6]["candidates"], [])
            self.assertEqual(rows[7]["candidates"][0]["status"], "duplicate_parameter")
            self.assertEqual(rows[8]["candidates"][0]["status"], "missing_or_conflicting_count")
            self.assertEqual(rows[9]["status"], "parse_error")

    def test_code_recovery_inherits_training_sessions_and_preserves_unknowns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = []
            for session in ('train-session', 'heldout-session'):
                path = root / (session + '.jsonl')
                rows = [
                    {"type": "session_meta", "payload": {"id": session}},
                    {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "native", "arguments": '{"cmd":"Get-Content a -Head 2"}'}},
                    {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "call_id": "code", "input": 'await tools.exec_command({cmd:"Get-Content a -Head 2"}); await tools.exec_command({cmd:dynamic});'}},
                ]
                if session == 'train-session':
                    rows[:0] = [
                        {"type": "session_meta", "payload": {"id": "heldout-prefix"}},
                        {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
                         "call_id": "prefix", "arguments": '{"cmd":"Get-Content other -Head 2"}'}},
                    ]
                path.write_text('\n'.join(map(json.dumps, rows)), encoding='utf-8')
                sources.append({"kind": "codex", "path": str(path)})
            config = root / 'config.json'
            config.write_text(json.dumps({"sources": sources}))
            with contextlib.redirect_stdout(io.StringIO()):
                report = run(config, root / 'data')
            first = report['sources'][0]
            with gzip.open(root / 'data/normalized' / (first['normalization'] + '.jsonl.gz'), 'rt', encoding='utf-8') as f:
                normalized = next(row for row in map(json.loads, f) if row['session'] == 'train-session')
            frozen = root / 'frozen'
            frozen.mkdir()
            row = {"record_id": normalized['record_id'], "partition": "train",
                   "artifact": first['normalization'],
                   "session_group": digest(['codex', 'train-session'])}
            raw = (json.dumps(row) + '\n').encode()
            (frozen / 'train.jsonl').write_bytes(raw)
            (frozen / 'final_test.jsonl').write_bytes(b'\xffMUST_NOT_READ')
            run_name = json.loads((root / 'data/latest.json').read_text())['run']
            (frozen / 'manifest.json').write_text(json.dumps({"run": run_name,
                "artifact_sha256": {"train": hashlib.sha256(raw).hexdigest()}}))
            with contextlib.redirect_stdout(io.StringIO()):
                result = recover(root / 'data', frozen, root / 'recovered')
            self.assertEqual(result['counts']['code_units'], 1)
            self.assertEqual(result['counts']['static_command_candidates'], 1)
            self.assertEqual(result['counts']['rejected:missing_or_dynamic_command'], 1)
            with gzip.open(root / 'recovered/candidates.jsonl.gz', 'rt', encoding='utf-8') as f:
                candidate = json.loads(f.readline())
            self.assertEqual(candidate['partition'], 'train')
            self.assertFalse(candidate['execution_observed'])
            self.assertEqual(len(candidate['matching_training_record_ids']), 1)


if __name__ == '__main__':
    unittest.main()
