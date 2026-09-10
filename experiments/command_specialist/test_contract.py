import json
import tempfile
import unittest
from pathlib import Path

from contract import execute_plan, evidence_result, validate_plan


class ContractTests(unittest.TestCase):
    def test_all_operations_and_literal_shell_metacharacters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "report [draft]'s.txt"
            needle = "$(throw 'injection')"
            file.write_text(f"alpha\n{needle}\nomega\n", encoding="utf-8")
            (root / "meta.json").write_text(json.dumps({"a.b": "ready"}))
            cases = [
                ({"op": "read_head", "path": file.name, "value": "", "limit": 1}, "alpha"),
                ({"op": "read_tail", "path": file.name, "value": "", "limit": 1}, "omega"),
                ({"op": "find_literal", "path": file.name, "value": needle, "limit": 2}, needle),
                ({"op": "json_field", "path": "meta.json", "value": "a.b", "limit": 20}, '"ready"'),
                ({"op": "list_files", "path": ".", "value": "*.json", "limit": 20}, "meta.json"),
            ]
            for plan, expected in cases:
                with self.subTest(op=plan["op"]):
                    result = execute_plan(plan, root)
                    self.assertEqual(result["exit_code"], 0, result)
                    self.assertEqual(result["stdout"], expected)
                    native = execute_plan(plan, root, backend="native")
                    self.assertEqual(native["stdout"], result["stdout"])
                    self.assertEqual(native["exit_code"], result["exit_code"])

    def test_rejects_path_escape_and_unknown_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ok.txt").write_text("ok")
            plan = {"op": "read_head", "path": "ok.txt", "value": "", "limit": 1}
            for update in [{"path": "../outside.txt"}, {"path": "C:/Windows/win.ini"},
                           {"op": "run_shell"}, {"limit": True}, {"limit": 101},
                           {"command": "Remove-Item x"}]:
                with self.subTest(update=update), self.assertRaises(ValueError):
                    validate_plan(plan | update, root)

    def test_evidence_preserves_status_and_verbatim_text(self):
        case = {"exit_code": 0, "truncated": True, "output_lines": ["noise", "ERROR failed", "summary"]}
        result = evidence_result({"lines": [2]}, case)
        self.assertEqual(result, {"exit_code": 0, "truncated": True, "evidence": ["ERROR failed"], "source_lines": [2]})
        for selection in [{"lines": [0]}, {"lines": [4]}, {"lines": [2, 2]},
                          {"lines": [True]}, {"lines": [2], "exit_code": 1}]:
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                evidence_result(selection, case)


if __name__ == "__main__":
    unittest.main()
