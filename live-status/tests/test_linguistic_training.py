from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from linguistic_training import action_catalog, apply_reviewed, simulate, validate_proposals


class LinguisticTrainingTests(unittest.TestCase):
    def test_simulates_each_mapping_in_combinations(self):
        rows = simulate(seed=7)
        self.assertEqual(len(rows), len(action_catalog()))
        self.assertTrue(all(len(row["simulated_sentences"]) == 3 for row in rows))
        self.assertTrue(any(row["key"] == "git:status" for row in rows))

    def test_invalid_or_unknown_proposals_are_rejected(self):
        proposals = validate_proposals([
            {"key": "git:status", "suggested_phrase": "reviewing Git status"},
            {"key": "git:status", "suggested_phrase": "review Git status"},
            {"key": "git:status", "suggested_phrase": "git status; delete everything"},
            {"key": "unknown:key", "suggested_phrase": "doing something"},
        ])
        self.assertEqual([item["suggested_phrase"] for item in proposals], ["reviewing Git status"])
        self.assertFalse(proposals[0]["accepted"])

    def test_only_human_accepted_proposals_change_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "map.json"
            destination.write_text('{"version":1,"action_overrides":{}}', encoding="utf-8")
            proposals = root / "proposals.json"
            proposals.write_text(json.dumps({"proposals": [
                {"key": "git:status", "suggested_phrase": "reviewing Git status", "accepted": True},
                {"key": "git:diff", "suggested_phrase": "reviewing Git changes", "accepted": False},
            ]}), encoding="utf-8")
            result = apply_reviewed(proposals, destination)
            saved = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(result["applied"], ["git:status"])
        self.assertEqual(saved["action_overrides"], {"git:status": "reviewing Git status"})


if __name__ == "__main__":
    unittest.main()
