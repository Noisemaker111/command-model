import base64
import contextlib
import gzip
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from data_pipeline import run
from ingest_adapters import Adapter
from label_data import assign_partitions, freeze, read_contract
from verify_labels import verify, export_train
from review_queue import build as build_queue


def pointer(n):
    return {"snapshot": "fixture", "line": n}


class AdapterTests(unittest.TestCase):
    def test_codex_join_ignores_pasted_events_preserves_unknown_and_failure(self):
        adapter = Adapter("codex", "fixture")
        native = {"type": "event_msg", "payload": {"type": "item_completed", "item": {
            "type": "CommandExecution", "id": "a", "command": ["pwsh", "-Command", "Get-Content a"],
            "aggregated_output": "ERROR missing", "exit_code": 1}}}
        rows = [
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"text": json.dumps(native)}]}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "a", "arguments": json.dumps({"cmd": "Get-Content a"})}},
            native, native,
            {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "b", "arguments": '{"cmd":"Get-Content b"}'}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "b", "output": "Process exited with code 0\nERROR actually failed"}},
        ]
        for n, row in enumerate(rows):
            adapter.consume(row, pointer(n))
        result = list(adapter.finish())
        self.assertEqual(len(result), 2)
        self.assertEqual(sorted(x["labels"]["execution"] for x in result), ["exit_nonzero", "unknown"])
        self.assertTrue(all(x["labels"]["task_correctness"] == "abstain" for x in result))
        self.assertEqual(adapter.counts["duplicate_native_events"], 1)
        self.assertTrue(all(x["context_association"].endswith("unverified") for x in result))

    def test_cursor_out_of_order_results_never_invent_context(self):
        adapter = Adapter("cursor", "fixture")
        rows = [
            {"role": "user", "content": "This blob is not ordered."},
            {"role": "tool", "content": [{"type": "tool-result", "toolCallId": "x", "result": {"output": "hello", "exit_code": 0}}]},
            {"role": "assistant", "content": [{"type": "tool-call", "toolCallId": "x", "toolName": "Shell", "args": {"command": "echo hello"}}]},
        ]
        for n, row in enumerate(rows):
            encoded = {"base64": base64.b64encode(json.dumps(row).encode()).decode()}
            adapter.consume({"table": "blobs", "row": {"data": encoded}}, pointer(n))
        result = list(adapter.finish())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["exit_code"], 0)
        self.assertEqual(result[0]["request_context"], "")

    def test_claude_results_and_opencode_sessions(self):
        a = Adapter("claude", "fixture")
        a.consume({"type": "assistant", "sessionId": "s", "message": {"content": [
            {"type": "tool_use", "id": "a", "name": "Bash", "input": {"command": "false"}}]}}, pointer(1))
        a.consume({"type": "user", "sessionId": "s", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "a", "content": "failure", "is_error": True}]}}, pointer(2))
        result = list(a.finish())[0]
        self.assertIsNone(result["exit_code"])
        self.assertTrue(result["recorded_tool_error"])
        a = Adapter("opencode", "fixture")
        for n, (session, typ, data) in enumerate([
            ("one", "user", {"text": "Inspect first file"}),
            ("two", "assistant", {"content": [{"type": "tool", "id": "a", "name": "shell", "state": {
                "input": {"command": "Get-Content b"}, "status": "completed", "content": [{"type": "text", "text": "hi"}], "metadata": {"exit": 0}}}]}),
        ]):
            a.consume({"table": "session_message", "row": {"session_id": session, "type": typ, "data": json.dumps(data)}}, pointer(n))
        result = list(a.finish())[0]
        self.assertEqual(result["request_context"], "")
        self.assertEqual(result["output"], "hi")
        self.assertEqual(result["exit_code"], 0)


class PipelineTests(unittest.TestCase):
    def test_bulk_verifier_and_training_export_do_not_read_other_partitions(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            verified = verify(root / "verified")
            self.assertEqual(verified["passed"], 800)
            frozen = root / "frozen"
            frozen.mkdir()
            row = {"id": "example", "partition": "train", "review_reasons": [], "read_contract_candidate": {
                "op": "read_head", "limit": 4, "path": "fixture.txt", "value": ""}}
            raw = (json.dumps(row) + "\n").encode()
            (frozen / "train.jsonl").write_bytes(raw)
            (frozen / "final_test.jsonl").write_bytes(b'\xffINVALID_DO_NOT_READ')
            (frozen / "manifest.json").write_text(json.dumps({"artifact_sha256": {"train": hashlib.sha256(raw).hexdigest()}}))
            report = export_train(frozen, root / "verified", verified)
            self.assertEqual(report["synthetic_training_examples"], 3)
            self.assertEqual(report["used_partitions"], ["train"])
            with self.assertRaises(ValueError):
                verify(root / "verified")

    def test_partition_assignment_balances_records_without_breaking_groups(self):
        groups = {str(i): 1 for i in range(100)}
        assignment = assign_partitions(groups, "seed")
        self.assertEqual({s: list(assignment.values()).count(s) for s in set(assignment.values())},
                         {"train": 30, "development": 10, "reserve": 50, "final_test": 10})
        self.assertEqual(assignment, assign_partitions(dict(reversed(list(groups.items()))), "seed"))

    def test_read_contract_rejects_interpolation_wildcards_and_compound_commands(self):
        for command in ["Get-Content '$x' -Tail 4; Remove-Item x", 'Get-Content "$x" -Head 4',
                        "Get-Content *.txt -Head 4", "Get-Content x -Head 0",
                        "Get-Content `x -Head 3", "Get-Content 'x[1]' -Head 3",
                        "Get-Content @args -Head 3", "Get-Content #comment -Head 3", "Get-Content -Unknown -Head 3"]:
            self.assertIsNone(read_contract(command), command)
        self.assertEqual(read_contract("Get-Content -LiteralPath 'can''t [x].txt' -Tail 4")["limit"], 4)
        self.assertEqual(read_contract(["pwsh", "-NoProfile", "-Command", "Get-Content x -Head 4"])["op"], "read_head")
        self.assertIsNone(read_contract(["bash", "-c", "Get-Content x -Head 4"]))

    def test_frozen_groups_keep_copied_tasks_together_and_do_not_emit_raw_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = []
            for session in ("one", "two"):
                path = root / (session + ".jsonl")
                rows = [{"type": "session_meta", "payload": {"id": session}},
                        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
                            {"text": "Please inspect the very last lines of this private file secret-name.txt"}]}},
                        {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "a",
                            "arguments": json.dumps({"cmd": "Get-Content secret-name.txt -Tail 4"})}},
                        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "a", "output": '{"output":"secret-data","exit_code":0}'}}]
                path.write_text("\n".join(map(json.dumps, rows)))
                sources.append({"kind": "codex", "path": str(path)})
            config = root / "config.json"
            config.write_text(json.dumps({"sources": sources}))
            with contextlib.redirect_stdout(io.StringIO()):
                run(config, root / "out")
                manifest = freeze(root / "out", root / "freeze")
            self.assertEqual(manifest["partition_groups"], 1)
            self.assertEqual(manifest["training_eligible"], 0)
            all_rows = []
            for path in (root / "freeze").glob("*.jsonl"):
                text = path.read_text()
                self.assertNotIn("secret-name", text)
                self.assertNotIn("secret-data", text)
                all_rows.extend(json.loads(line) for line in text.splitlines())
            self.assertEqual(len({r["partition"] for r in all_rows}), 1)
            # A separate synthetic training-only input makes holdout reads fail loudly.
            train_raw = "\n".join(json.dumps({**r, "partition": "train"}) for r in all_rows).encode()
            import hashlib
            queue_input = root / "queue-input"
            queue_input.mkdir()
            (queue_input / "train.jsonl").write_bytes(train_raw)
            (queue_input / "final_test.jsonl").write_bytes(b'\xffDO_NOT_READ')
            (queue_input / "manifest.json").write_text(json.dumps({"artifact_sha256": {"train": hashlib.sha256(train_raw).hexdigest()}}))
            with contextlib.redirect_stdout(io.StringIO()):
                queue = build_queue(queue_input, root / "queue.json")
            self.assertEqual(queue["training_records"], 2)
            self.assertEqual(queue["sampled_records"], 1)  # identical commands are reviewed once
            self.assertEqual(queue["used_partitions"], ["train"])
            with self.assertRaises(ValueError):
                freeze(root / "out", root / "freeze")

    def test_snapshot_reload_accounting_cache_and_invalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            original = (json.dumps({"cmd": "Get-Content x", "exit": 0, "session": "s", "out": "hello"}) + "\n\nBAD\n[]\n").encode()
            source.write_bytes(original)
            config = root / "config.json"
            config.write_text(json.dumps({"sources": [{"kind": "legacy", "path": str(source)}]}))
            out = root / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                first = run(config, out)
                second = run(config, out)
            self.assertEqual(first["counts"]["source_records"], 4)
            self.assertEqual(first["counts"]["disposition:malformed"], 1)
            self.assertEqual(second["counts"]["snapshot_cache_hits"], 1)
            self.assertEqual(second["counts"]["normalization_cache_hits"], 1)
            item = first["sources"][0]
            with gzip.open(out / "snapshots" / (item["snapshot"]["snapshot_sha256"] + ".gz"), "rb") as handle:
                self.assertEqual(handle.read(), original)
            with gzip.open(out / "normalized" / (item["normalization"] + ".jsonl.gz"), "rt", encoding="utf-8") as handle:
                self.assertEqual(json.loads(handle.readline())["output"], "hello")
            source.write_bytes(original + b'{"cmd":"echo more"}\n')
            with contextlib.redirect_stdout(io.StringIO()):
                third = run(config, out)
            self.assertEqual(third["counts"]["snapshot_cache_hits"], 0)
            self.assertEqual(third["counts"]["commands"], 2)
            self.assertEqual(len(list((out / "snapshots").glob("*.gz"))), 2)

    def test_sqlite_committed_wal_and_credentials_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "opencode.db"
            db = sqlite3.connect(source)
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE credential(id TEXT, secret TEXT)")
            db.execute("INSERT INTO credential VALUES ('private','do-not-copy')")
            db.execute("CREATE TABLE session_message(id TEXT,session_id TEXT,type TEXT,seq INT,time_created INT,data TEXT)")
            db.execute("INSERT INTO session_message VALUES ('m','s','user',1,0,?)", (json.dumps({"text": "A request"}),))
            db.commit()
            config = root / "config.json"
            config.write_text(json.dumps({"sources": [{"kind": "opencode", "path": str(source)}]}))
            with contextlib.redirect_stdout(io.StringIO()):
                report = run(config, root / "out")
            meta = report["sources"][0]["snapshot"]
            self.assertIn("credential", meta["excluded_tables"])
            with gzip.open(root / "out/snapshots" / (meta["snapshot_sha256"] + ".gz"), "rt", encoding="utf-8") as handle:
                raw = handle.read()
            self.assertIn("A request", raw)
            self.assertNotIn("do-not-copy", raw)
            db.close()


if __name__ == "__main__":
    unittest.main()
