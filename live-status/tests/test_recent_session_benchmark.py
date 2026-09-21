import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from tools.benchmark_recent_sessions import (
    backend_specs,
    balanced_sample,
    blinded_items,
    generate,
    judge,
    wilson,
)
from judging.judge import run_batch


class FakeBackend:
    def warm(self):
        pass

    def generate(self, command):
        return f"Running {command}.", {"wall_s": 0.01}


def row(row_id, session="s1", complexity="simple", action="run"):
    return {
        "id": row_id,
        "session": session,
        "complexity": complexity,
        "shell": "powershell",
        "command": row_id,
        "structure": {"actions": [{"type": action}], "loops": 0,
                      "conditionals": 0, "pipelines": 0},
    }


class RecentSessionBenchmarkTests(unittest.TestCase):
    def test_backend_specs_require_unique_named_specs(self):
        self.assertEqual(backend_specs(["a=ollama:one", "b=ollama:two"]),
                         {"a": "ollama:one", "b": "ollama:two"})
        with self.assertRaisesRegex(ValueError, "expected NAME=SPEC"):
            backend_specs(["ollama:one"])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            backend_specs(["a=one", "a=two"])

    def test_balanced_sample_is_deterministic_and_spans_buckets(self):
        rows = [row("a1"), row("a2"), row("b1", "s2", "complex", "pipeline"),
                row("b2", "s2", "complex", "pipeline")]
        first = balanced_sample(rows, 2)
        second = balanced_sample(rows, 2)
        self.assertEqual([x["id"] for x in first], [x["id"] for x in second])
        self.assertEqual({x["session"] for x in first}, {"s1", "s2"})

    def test_blinding_is_stable_and_complete(self):
        item = row("one")
        item["outputs"] = {"left": {"text": "L"}, "right": {"text": "R"}}
        items, maps = blinded_items([item], ["left", "right"])
        self.assertEqual(set(maps["one"].values()), {"left", "right"})
        self.assertEqual(set(items[0]["candidates"].values()), {"L", "R"})

    def test_generation_checkpoint_is_reused(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "generated.jsonl"
            with patch("tools.benchmark_recent_sessions.from_spec", return_value=FakeBackend()):
                first = generate([row("one")], {"m": "fake:model"}, path)
            with patch("tools.benchmark_recent_sessions.from_spec",
                       side_effect=AssertionError("backend reloaded")):
                second = generate([row("one")], {"m": "fake:model"}, path)
            self.assertEqual(first, second)

    def test_judge_checkpoint_is_reused(self):
        item = row("one")
        item.update({"candidates": {"c0": "ok"}, "cand_hash": "hash"})
        result = {"id": "one", "cand_hash": "hash", "missing": False,
                  "judge_model": "judge", "judge_key": "judge"}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "judged.jsonl"
            with patch("tools.benchmark_recent_sessions.run_batch", return_value=[result]) as run:
                self.assertEqual(judge([item], "judge", 8, 1, path), [result])
                self.assertEqual(judge([item], "judge", 8, 1, path), [result])
            self.assertEqual(run.call_count, 1)

    def test_wilson_interval_contains_observed_rate(self):
        low, high = wilson(75, 100)
        self.assertLess(low, 75)
        self.assertGreater(high, 75)

    def test_local_judge_uses_ollama_without_external_chat(self):
        item = row("one")
        item.update({"candidates": {"c0": "Running one."}, "cand_hash": "hash"})
        verdict = {"id": "one", "verdicts": {"c0": {
            "correct": True, "score": 90, "missing_actions": False,
            "hallucinated_actions": False, "names_ok": True, "style_ok": True}},
            "best": "c0"}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

            def read(self):
                return json.dumps({"message": {"content": json.dumps({"results": [verdict]})}}).encode()

        with patch("judging.judge.chat", side_effect=AssertionError("external chat called")), \
             patch("judging.judge.urllib.request.urlopen", return_value=Response()) as opened:
            result = run_batch([item], "ollama:qwen3:8b")
        self.assertFalse(result[0]["missing"])
        self.assertEqual(result[0]["judge_model"], "ollama:qwen3:8b")
        self.assertEqual(result[0]["judge_key"], "ollama:qwen3:8b|ctx=8192|compact=v1")
        self.assertEqual(opened.call_count, 1)


if __name__ == "__main__":
    unittest.main()
