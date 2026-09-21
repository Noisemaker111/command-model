"""Shell parser regression tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parsers.shell import analyze  # noqa: E402


class ShellParserTests(unittest.TestCase):
    def test_git_switch_is_not_powershell_control_flow(self):
        structure = analyze("git fetch origin && git switch feature/status", "bash")
        self.assertEqual(structure.conditionals, 0)
        self.assertEqual([action.sub for action in structure.actions], ["fetch", "switch"])

    def test_powershell_switch_is_control_flow(self):
        structure = analyze("switch ($state) { 'ready' { Get-Process } }", "powershell")
        self.assertEqual(structure.conditionals, 1)

    def test_bash_case_is_control_flow(self):
        structure = analyze("case $state in ready) ps ;; esac", "bash")
        self.assertEqual(structure.conditionals, 1)


if __name__ == "__main__":
    unittest.main()
