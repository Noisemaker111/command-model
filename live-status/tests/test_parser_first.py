from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

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

    def test_bun_test_names_the_test_instead_of_the_runtime(self):
        status, metrics = render({
            "ok": True,
            "errors": [],
            "nodes": [command(
                "bun", "test", "--timeout", "90000",
                "test/codex-quest-dev-installer.test.ts",
            )],
        })
        self.assertEqual(
            status, "Running the codex quest dev installer tests."
        )
        self.assertTrue(metrics["fully_mapped"])

    def test_bun_test_resolves_grounded_intent_from_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "installer.test.ts"
            target.write_text(
                "test('every install creates a sealed version without deleting "
                "the old one', async () => {})\n",
                encoding="utf-8",
            )
            status, metrics = render(
                {
                    "ok": True,
                    "errors": [],
                    "nodes": [command("bun", "test", "installer.test.ts")],
                },
                cwd=directory,
            )
        self.assertEqual(
            status,
            "Testing that every install creates a sealed version without "
            "deleting the old one.",
        )
        self.assertIn("context_evidence", metrics["facts"][0])
        self.assertEqual(metrics["context_actions"], 1)

    def test_invalid_cwd_falls_back_without_failing(self):
        status, metrics = render({
            "ok": True, "errors": [],
            "nodes": [command("bun", "test", "installer.test.ts")],
        }, cwd="Z:/a-directory-that-does-not-exist")
        self.assertEqual(status, "Running the installer tests.")
        self.assertEqual(metrics["context_actions"], 0)

    def test_file_and_python_commands_keep_grounded_targets(self):
        status, _ = render({
            "ok": True, "errors": [],
            "nodes": [command(
                "Get-Content", "-Raw", "-LiteralPath", "local-session.json"
            )],
        })
        self.assertEqual(status, "Reading local-session.json.")
        status, _ = render({
            "ok": True, "errors": [],
            "nodes": [command("python", "tools/audit_failures.py", "--help")],
        })
        self.assertEqual(status, "Running audit_failures.py with Python.")

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
            status, "Reading README.md, searching text, and checking Git status."
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
