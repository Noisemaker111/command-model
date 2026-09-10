"""Core evidence and authorization invariants; real model verification is separate."""
import json
from pathlib import Path
import tempfile
import unittest

from delegate import completion_matches, delegate, digest, execute, validate


class DelegationInvariants(unittest.TestCase):
    def test_denial_is_terminal_and_each_handoff_is_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            task = {'task': 'Write and run a sum program', 'targets': {'p': 'sum.py'},
                    'completion': {'target': 'p', 'stdout': '55\n'}}
            first = delegate(task, root, root / 'artifacts', base_url='http://127.0.0.1:1')
            second = delegate(task, root, root / 'artifacts', base_url='http://127.0.0.1:1')
            self.assertNotEqual(first['raw_result'], second['raw_result'])
            saved = json.loads(Path(first['raw_result']).read_text())
            self.assertEqual(saved['status'], 'denied')
            self.assertEqual(saved['model_calls'], [])
            self.assertEqual(saved['actions'], [])
            self.assertFalse((root / 'sum.py').exists())

    def test_verification_requires_executed_saved_bytes_and_actual_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'sum.py'
            path.write_text('print(sum(range(1, 11)))', encoding='utf-8')
            identity = digest(path)
            actual = execute(path, root, root, 5, 65536)
            actual['sha256_before'] = identity
            self.assertTrue(completion_matches('unverified', path, identity, actual, actual['stdout']))
            self.assertFalse(completion_matches('exhausted', path, identity, actual, actual['stdout']))
            self.assertFalse(completion_matches('unverified', path, identity, actual, 'wrong'))
            path.write_text('print(0)', encoding='utf-8')
            self.assertFalse(completion_matches('unverified', path, identity, actual, actual['stdout']))

    def test_exact_target_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                validate({'task': 'write', 'targets': {'p': '../escape.py'}}, Path(directory))


if __name__ == '__main__':
    unittest.main()
