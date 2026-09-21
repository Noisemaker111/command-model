from __future__ import annotations

import shutil
import unittest

from inference.backends import from_spec
from inference.parser_first import ABSTENTION, PowerShellAstBackend, render


def command(name: str, *elements: str):
    return {
        "kind": "command", "name": name, "dynamic": False,
        "elements": [name, *elements], "evidence": " ".join([name, *elements]),
        "start": 0,
    }


class ParserFirstTests(unittest.TestCase):
    def test_git_switch_does_not_invent_branch_creation(self):
        status, metrics = render({
            "ok": True, "errors": [], "nodes": [command("git", "switch", "topic")]
        })
        self.assertEqual(status, "Switching Git branches.")
        self.assertTrue(metrics["fully_mapped"])

    def test_parse_errors_and_dynamic_invocation_abstain(self):
        status, metrics = render({
            "ok": False, "errors": ["Incomplete input"], "nodes": []
        })
        self.assertEqual(status, ABSTENTION)
        self.assertTrue(metrics["abstained"])
        dynamic = command("", "&", "$tool")
        dynamic["dynamic"] = True
        status, metrics = render({
            "ok": True, "errors": [], "nodes": [dynamic]
        })
        self.assertEqual(status, ABSTENTION)
        self.assertTrue(metrics["abstained"])

    def test_unknown_executable_is_literal_fallback(self):
        status, metrics = render({
            "ok": True, "errors": [], "nodes": [command("widgetctl", "deploy")]
        })
        self.assertEqual(status, "Running widgetctl.")
        self.assertTrue(metrics["literal_fallback"])
        self.assertFalse(metrics["fully_mapped"])

    def test_long_sequence_is_bounded_by_parsed_step_count(self):
        nodes = [
            command("Get-Content"), command("Select-String"),
            command("git", "status"), command("Write-Output"),
            command("Test-Path"),
        ]
        status, metrics = render({"ok": True, "errors": [], "nodes": nodes})
        self.assertEqual(
            status,
            "Reading a file, searching text, and checking Git status, "
            "plus 2 more parsed steps.",
        )
        self.assertEqual(metrics["total_actions"], 5)
        self.assertEqual(len(metrics["facts"]), 3)

    @unittest.skipUnless(
        shutil.which("pwsh") or shutil.which("powershell"),
        "PowerShell unavailable",
    )
    def test_persistent_host_parses_pipeline_and_sequence(self):
        backend = PowerShellAstBackend()
        try:
            status, metrics = backend.generate(
                "Get-Content README.md | Select-String TODO; git status"
            )
        finally:
            backend.close()
        self.assertEqual(
            status, "Reading a file, searching text, and checking Git status."
        )
        self.assertEqual(metrics["mapped_actions"], 3)
        self.assertFalse(metrics["abstained"])

    def test_public_backend_spec(self):
        backend = from_spec("parser:powershell")
        try:
            self.assertIsInstance(backend, PowerShellAstBackend)
        finally:
            backend.close()


if __name__ == "__main__":
    unittest.main()
