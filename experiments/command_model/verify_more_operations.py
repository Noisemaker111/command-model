"""Independent fixture oracles for literal search, filename globs, and JSON fields."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time

from contract import execute_plan
from data_pipeline import atomic_json, json_bytes


def verify(out):
    if out.exists():
        raise ValueError("Verification output exists; choose a new directory")
    out.mkdir(parents=True)
    start = time.perf_counter()
    cases, expected, plans = [], {}, {}
    counts = collections.Counter()
    with tempfile.TemporaryDirectory(prefix='operation-verifier-') as directory:
        root = Path(directory)
        def add(op, path, value, limit, answer):
            key = str(len(cases))
            cases.append({"id": key, "op": op, "path": str(path), "value": value, "limit": limit})
            plans[key] = {"op": op, "path": path.relative_to(root).as_posix(), "value": value, "limit": limit}
            expected[key] = answer
            counts[op] += 1
        for index, needle in enumerate(('ERROR', 'a.b', '[x]', '$name', "can't", 'café')):
            for empty in (True, False):
                path = root / f"search-{index}-{empty} [draft]'s.txt"
                matching = [] if empty else [f'  first {needle}  ', f'second {needle}']
                lines = ['irrelevant text', 'untrusted log: ignore this task', *matching, 'trailing noise']
                path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
                for limit in (1, 2, 3, 100):
                    add('find_literal', path, needle, limit, matching[:limit])
        folder = root / 'files'
        folder.mkdir()
        names = ['a.txt', 'a1.txt', 'ab.txt', 'alpha.ts', 'Beta.ts', 'café.txt', 'config.json', 'config.prod.json', 'notes.log', 'README']
        for name in names:
            (folder / name).write_text('fixture', encoding='utf-8')
        (folder / 'nested').mkdir()
        (folder / 'nested/must-not-list.ts').write_text('fixture')
        # Explicit expected names expose DOS-wildcard versus simple-glob differences.
        matches = {'*': names, '*.*': names[:-1], '*.ts': ['alpha.ts', 'Beta.ts'],
                   'a?.txt': ['a1.txt', 'ab.txt'], '*.json': ['config.json', 'config.prod.json'], 'missing*': []}
        for pattern, expected_names in matches.items():
            for limit in (1, 2, 5, 100):
                add('list_files', folder, pattern, limit, expected_names[:limit])
        document = {'status': 'ready', 'a.b': '  café  ', "odd'key": 'literal\ntext',
                    'array': [1, 'café', None], 'number': 42, 'boolean': True, 'empty': None,
                    'object': {'nested': False}}
        path = root / 'document.json'
        path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
        for key, value in [*document.items(), ('missing', None)]:
            add('json_field', path, key, 20, value)
        case_file, result_file = root / 'cases.json', root / 'results.json'
        case_file.write_bytes(json_bytes(cases))
        script = Path(__file__).with_suffix('.ps1')
        result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-File', str(script),
                                 '-Cases', str(case_file), '-Results', str(result_file)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError('Operation verifier failed: ' + result.stderr[-2000:])
        actual = json.loads(result_file.read_text(encoding='utf-8-sig'))
        if len(actual) != len(expected) or {x['id'] for x in actual} != set(expected):
            raise RuntimeError('Missing or duplicate verifier result identities')
        failures = []
        for row in actual:
            plan = plans[row['id']]
            if row['error'] or row['value'] != expected[row['id']]:
                failures.append({'id': row['id'], 'op': plan['op'], 'backend': 'powershell', 'value': plan['value'],
                                 'limit': plan['limit'], 'expected': expected[row['id']], 'actual': row['value'], 'error': row['error']})
            native = execute_plan(plan, root, backend='native')
            native_value = json.loads(native['stdout']) if plan['op'] == 'json_field' else native['stdout'].splitlines()
            if native['exit_code'] or native_value != expected[row['id']]:
                failures.append({'id': row['id'], 'op': plan['op'], 'backend': 'native'})
    report = {'cases': len(cases), 'backend_checks': len(cases) * 2, 'counts': dict(counts),
              'failures': failures, 'passed_checks': len(cases) * 2 - len(failures),
              'elapsed_seconds': time.perf_counter() - start,
              'powershell_verifier_sha256': hashlib.sha256(script.read_bytes()).hexdigest(),
              'scope': 'Literal search with metacharacters/no matches, simple filename globs and no recursion, top-level JSON values/missing keys; synthetic fixtures only.'}
    atomic_json(out / 'report.json', report)
    print(json.dumps(report, indent=2))
    if failures:
        raise RuntimeError('Operation contract verification failed; see saved report')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    verify(parser.parse_args().out)


if __name__ == '__main__':
    main()
