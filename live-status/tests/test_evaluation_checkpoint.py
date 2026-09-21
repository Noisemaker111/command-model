import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from evaluation.evaluate import run_eval


ROW = {
    "id": "one",
    "command": "git status",
    "status": "Checking Git status.",
    "shell": "bash",
    "tags": [],
    "complexity": "simple",
}


class FakeBackend:
    name = "fake"

    def generate(self, command):
        return "Checking Git status.", {"wall_s": 0.001, "tokens_per_s": 100}


class EvaluationCheckpointTests(unittest.TestCase):
    def test_none_grader_stays_local_and_saves_final_output(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"LIVE_STATUS_HOME": td}):
            with patch("evaluation.evaluate.jev_grade_outputs", side_effect=AssertionError("external grader called")):
                report = run_eval(FakeBackend(), [ROW], "local-only", judge=False, grader="none")
            self.assertEqual(report["n"], 1)
            self.assertEqual(report["reference_overlap"]["coverage_pct"], 100.0)
            self.assertEqual(report["reference_overlap"]["f1_avg"], 1.0)
            self.assertTrue((Path(td) / "evaluation" / "outputs" / "local-only.jsonl").exists())
            self.assertFalse((Path(td) / "evaluation" / "outputs" / "local-only.generated.jsonl").exists())

    def test_disabled_grading_stays_local_even_with_configured_grader(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"LIVE_STATUS_HOME": td}):
            with patch("evaluation.evaluate.jev_grade_outputs", side_effect=AssertionError("external grader called")):
                report = run_eval(FakeBackend(), [ROW], "disabled-grading", judge=False, grader="jev")
            self.assertEqual(report["n"], 1)

    def test_existing_generation_checkpoint_is_reused(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"LIVE_STATUS_HOME": td}):
            output_dir = Path(td) / "evaluation" / "outputs"
            output_dir.mkdir(parents=True)
            checkpoint = {**ROW, "output": "Checking Git status.",
                          "metrics": {"wall_s": 0.001, "tokens_per_s": 100},
                          "validators": {"pass": True, "style_ok": True, "one_sentence": True,
                                         "length_ok": True, "live_tense": True, "no_secret": True,
                                         "no_boilerplate": True, "no_shell_noise": True}}
            from common import write_jsonl
            write_jsonl(output_dir / "resume.generated.jsonl", [checkpoint])
            backend = FakeBackend()
            with patch.object(backend, "generate", side_effect=AssertionError("checkpoint was regenerated")):
                report = run_eval(backend, [ROW], "resume", judge=False, grader="none")
            self.assertEqual(report["n"], 1)
            self.assertTrue((output_dir / "resume.jsonl").exists())
            self.assertFalse((output_dir / "resume.generated.jsonl").exists())

    def test_grader_failure_keeps_generated_output(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"LIVE_STATUS_HOME": td}):
            with patch("evaluation.evaluate.jev_grade_outputs", side_effect=RuntimeError("grader unavailable")):
                with self.assertRaisesRegex(RuntimeError, "grader unavailable"):
                    run_eval(FakeBackend(), [ROW], "failed-grade", judge=True, grader="jev")
            self.assertTrue((Path(td) / "evaluation" / "outputs" / "failed-grade.generated.jsonl").exists())


if __name__ == "__main__":
    unittest.main()