import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bindings import bind_request
from contract import execute_plan, messages, prediction_schema, PLAN_SCHEMA
from run import inspect_request


class BindingTests(unittest.TestCase):
    def test_exact_paths_survive_model_boundary_and_both_executors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "caf\u00e9 \u6f22\u5b57 [draft]'s {{other}} file_2.txt"
            (root / name).write_text("first\nERROR exact\nlast\n", encoding="utf-8")
            (root / 'meta.json').write_text('{"state":"ready"}', encoding='utf-8')
            cases = [('read_head', name, '', 1, 'first'),
                     ('read_tail', name, '', 1, 'last'),
                     ('find_literal', name, 'ERROR', 2, 'ERROR exact'),
                     ('json_field', 'meta.json', 'state', 20, '"ready"'),
                     ('list_files', '.', '*.json', 20, 'meta.json')]
            for op, target, value, limit, expected in cases:
                bound = bind_request(root, 'Inspect {{chosen}}.', {'decoy': 'meta.json', 'chosen': target})
                self.assertEqual(bound.model_request, 'Inspect "file_2".')
                self.assertEqual(bound.display_request, 'Inspect ' + json.dumps(target, ensure_ascii=False) + '.')
                self.assertNotIn(name, json.dumps(messages(bound.case()), ensure_ascii=False))
                self.assertEqual(prediction_schema(bound.case())['properties']['path']['enum'], ['file_1', 'file_2'])
                resolved = bound.resolve({'op': op, 'path': 'file_2', 'value': value, 'limit': limit})
                self.assertEqual(resolved['path'], target)
                for backend in ('native', 'powershell'):
                    with self.subTest(op=op, backend=backend):
                        result = execute_plan(resolved, root, backend=backend)
                        self.assertEqual(result['exit_code'], 0, result)
                        self.assertEqual(result['stdout'], expected)
            self.assertNotIn('enum', PLAN_SCHEMA['properties']['path'])

    def test_bindings_are_request_local_and_unknown_references_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('a.txt', 'b.txt'):
                (root/name).write_text(name)
            first = bind_request(root, 'Read {{log}}.', {'log': 'a.txt'})
            second = bind_request(root, 'Read {{log}}.', {'log': 'b.txt'})
            prediction = {'op': 'read_head', 'path': 'file_1', 'value': '', 'limit': 1}
            self.assertEqual(first.resolve(prediction)['path'], 'a.txt')
            self.assertEqual(second.resolve(prediction)['path'], 'b.txt')
            for value in ('file_2', 'a.txt', '../outside', None, []):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    first.resolve({**prediction, 'path': value})
            for request, targets in [('Read {{missing}}.', {'log': 'a.txt'}),
                                     ('Read a.txt.', {'log': 'a.txt'}),
                                     ('Read {{log}}.', {}),
                                     ('Read {{log}}.', {'log': '../outside'}),
                                     ('Read {{log}}.', {'log': str(root/'a.txt')}),
                                     ('Read {{log}}.', {'log': 'missing'}),
                                     ('Read {{log}}.', {'log': None})]:
                with self.subTest(targets=targets), self.assertRaises(ValueError):
                    bind_request(root, request, targets)

    def test_readable_packet_saved_binding_and_verbatim_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "report [new]'s \u6f22\u5b57.log"
            content = 'progress\nERROR preserve this\nSUMMARY failed\n'
            (root/name).write_text(content, encoding='utf-8')
            predictions = [({'op':'read_tail','path':'file_1','value':'','limit':3}, {'inference_wall_ms':1}),
                           ({'lines':[2,3]}, {'inference_wall_ms':1})]
            with patch('run.predict', side_effect=predictions) as predict:
                packet = inspect_request(root, 'Read last 3 lines of {{log}}.', targets={'log':name},
                                         evidence_request='errors and summary', backend='native', artifacts=root/'runs',
                                         num_ctx=8192, num_predict=2048)
            self.assertEqual(predict.call_args_list[0].args[2]['request'], 'Read last 3 lines of "file_1".')
            self.assertEqual(packet['plan']['path'], name)
            self.assertIn(name, packet['request'])
            self.assertEqual(packet['evidence'], ['ERROR preserve this', 'SUMMARY failed'])
            self.assertEqual(packet['source_lines'], [2,3])
            self.assertTrue(all(call.kwargs == {'num_ctx':8192, 'num_predict':2048}
                                for call in predict.call_args_list))
            self.assertEqual(packet['exit_code'], 0)
            self.assertNotIn('binding_trace', packet)
            saved = json.loads(Path(packet['raw_result']).read_text(encoding='utf-8'))
            self.assertEqual(saved['plan']['path'], name)
            self.assertEqual(saved['binding_trace']['references'], {'file_1':name})
            self.assertEqual(saved['result']['stdout'], content.rstrip('\n'))
            self.assertEqual(saved['selection'], {'lines':[2,3]})
            self.assertEqual(saved['runtime']['num_predict'], 2048)
            self.assertEqual(saved['packet']['evidence'], packet['evidence'])

    def test_invalid_reference_never_executes_and_deleted_target_is_revalidated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root/'a.txt'
            target.write_text('ok')
            with patch('run.predict', return_value=({'op':'read_head','path':'invented','value':'','limit':1}, {})), patch('run.execute_plan') as execute:
                with self.assertRaisesRegex(ValueError, 'unknown file reference'):
                    inspect_request(root, 'Read {{log}}.', targets={'log':'a.txt'}, artifacts=root/'runs')
                execute.assert_not_called()
            def removed(*args, **kwargs):
                target.unlink()
                return {'op':'read_head','path':'file_1','value':'','limit':1}, {}
            with patch('run.predict', side_effect=removed):
                with self.assertRaisesRegex(ValueError, 'outside fixture or missing'):
                    inspect_request(root, 'Read {{log}}.', targets={'log':'a.txt'}, backend='native', artifacts=root/'runs')

    def test_rejected_evidence_keeps_raw_result_and_readable_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'a.txt').write_text('ERROR original')
            with patch('run.predict', side_effect=[({'op':'read_head','path':'file_1','value':'','limit':1}, {'inference_wall_ms':1}), ({'lines':[99]}, {})]):
                packet = inspect_request(root, 'Read {{log}}.', targets={'log':'a.txt'}, evidence_request='errors', backend='native', artifacts=root/'runs')
            self.assertIn('selection_error', packet)
            self.assertTrue(packet['truncated'])
            saved = json.loads(Path(packet['raw_result']).read_text(encoding='utf-8'))
            self.assertEqual(saved['result']['stdout'], 'ERROR original')
            self.assertEqual(packet['plan']['path'], 'a.txt')


if __name__ == '__main__':
    unittest.main()
