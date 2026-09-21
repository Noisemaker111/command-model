import json
import unittest

from labeling.prompts import structured_student_input, student_prompt


class StructuredStudentInputTests(unittest.TestCase):
    def test_preserves_action_order_and_targets(self):
        prompt = structured_student_input("git fetch origin && git status -sb && git log --oneline -5")
        parsed = json.loads(prompt.split("\n", 2)[1])
        self.assertEqual([a["subcommand"] for a in parsed["actions"]], ["fetch", "status", "log"])
        self.assertIn("origin", parsed["actions"][0]["targets"])

    def test_bounds_raw_command_but_keeps_parser_hints(self):
        prompt = structured_student_input("echo " + "x" * 5000)
        self.assertLess(len(prompt), 1800)
        self.assertIn('"action":"format"', prompt)

    def test_training_prompt_uses_structured_input_and_status_boundary(self):
        prompt = student_prompt("git status -sb", instruct=False, structured=True)
        self.assertIn('"action":"git"', prompt)
        self.assertIn("Raw command:\ngit status -sb", prompt)
        self.assertTrue(prompt.endswith("\n\nStatus:"))


if __name__ == "__main__":
    unittest.main()