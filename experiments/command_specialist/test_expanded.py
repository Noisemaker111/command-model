import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from prepare_expanded import prepare
from verify_labels import export_train
from benchmark import equivalent_output


class ExpandedTests(unittest.TestCase):
    def test_json_scoring_preserves_values_without_requiring_identical_escapes(self):
        case = {'expected': {'op': 'json_field'}}
        self.assertTrue(equivalent_output(case, '"can\'t"', '"can\\u0027t"'))
        self.assertTrue(equivalent_output(case, '{"b":2,"a":1}', '{"a":1,"b":2}'))
        self.assertFalse(equivalent_output(case, 'true', '1'))
        self.assertFalse(equivalent_output(case, '"1"', '1'))
        self.assertFalse(equivalent_output(case, '"  x  "', '"x"'))
        self.assertFalse(equivalent_output({'expected': {'op': 'read_head'}}, 'x ', 'x'))

    def test_training_boundaries_and_export_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pilot, verified, frozen, recovery = [root / x for x in ('pilot', 'verified', 'frozen', 'recovery')]
            for path in (pilot, verified, frozen, recovery):
                path.mkdir()
            record = {'id': 'historical', 'partition': 'train', 'read_contract_candidate': None, 'review_reasons': []}
            raw = (json.dumps(record) + '\n').encode()
            sha = hashlib.sha256(raw).hexdigest()
            (frozen / 'train.jsonl').write_bytes(raw)
            (frozen / 'manifest.json').write_text(json.dumps({'artifact_sha256': {'train': sha}}))
            (frozen / 'final_test.jsonl').write_bytes(b'\xffDO_NOT_READ')
            candidate = {'id': 'ast', 'partition': 'train', 'plan': {'op': 'read_tail', 'limit': 6}}

            def save_candidate():
                raw = (json.dumps(candidate) + '\n').encode()
                (recovery / 'read-candidates.jsonl').write_bytes(raw)
                (recovery / 'report.json').write_text(json.dumps({'frozen_train_sha256': sha,
                    'used_partitions': ['train'], 'candidates_sha256': hashlib.sha256(raw).hexdigest()}))

            save_candidate()
            export_train(frozen, verified, {'failures': [], 'passed': 800}, recovery)
            synthetic = {'id': 'fixture', 'kind': 'plan', 'origin': 'synthetic-fixture', 'split': 'train',
                         'request': 'Read the last 6 lines of "x".',
                         'expected': {'op': 'read_tail', 'path': 'x', 'value': '', 'limit': 6}}
            (pilot / 'train.jsonl').write_text('\n'.join(map(json.dumps, [synthetic,
                {'id': 'old-mined', 'origin': 'historical'}])))
            report = prepare(pilot, verified, frozen, root / 'combined')
            self.assertEqual(report['examples'], 4)
            self.assertEqual(report['excluded_pilot_historical_examples'], 1)
            self.assertNotIn('old-mined', (root / 'combined/sft.jsonl').read_text())
            with self.assertRaises(FileExistsError):
                prepare(pilot, verified, frozen, root / 'combined')
            candidate['partition'] = 'final_test'
            save_candidate()
            with self.assertRaisesRegex(ValueError, 'Invalid training'):
                export_train(frozen, root / 'bad', {'failures': [], 'passed': 800}, recovery)
            candidate['partition'] = 'train'
            save_candidate()
            with (recovery / 'read-candidates.jsonl').open('a') as handle:
                handle.write('{}\n')
            with self.assertRaisesRegex(ValueError, 'Read recovery changed'):
                export_train(frozen, root / 'bad', {'failures': [], 'passed': 800}, recovery)
            with (verified / 'sft.jsonl').open('a') as handle:
                handle.write('{}\n')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                prepare(pilot, verified, frozen, root / 'bad-combined')


if __name__ == '__main__':
    unittest.main()
