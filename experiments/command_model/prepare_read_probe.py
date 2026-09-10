"""Freeze a supplemental synthetic read probe; never adds examples to training."""
import argparse
import hashlib
import json
from pathlib import Path

from data_pipeline import atomic_json, json_bytes


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    fixtures = out / 'fixtures'
    fixtures.mkdir()
    rows = []
    for op in ('read_head', 'read_tail'):
        for limit in (1, 4, 9, 16, 27, 43, 58, 73, 91, 100):
            for wording in range(2):
                opaque = hashlib.sha256(f'{op}:{limit}:{wording}'.encode()).hexdigest()[:12]
                name = f"probe {opaque} [draft] can't caf\u00e9.txt"
                (fixtures / name).write_bytes(('\r\n'.join(
                    f'  record {i}: caf\u00e9 $literal [x]  ' for i in range(113)) + '\r\n').encode('utf-8'))
                quoted = json.dumps(name, ensure_ascii=False)
                edge = 'opening' if op == 'read_head' else 'trailing'
                side = 'top' if op == 'read_head' else 'bottom'
                request = (f'Please fetch no more than {limit} {edge} lines from file {quoted}.' if wording == 0 else
                           f'{quoted} is the log to inspect. Give me {limit} lines starting at its {side}.')
                rows.append({'id': f'read-probe-{op}-{limit}-{wording}', 'kind': 'plan',
                    'origin': 'supplemental-synthetic-read-probe', 'split': 'validation',
                    'request': request, 'expected': {'op': op, 'path': name, 'value': '', 'limit': limit}})
    raw = b''.join(json_bytes(row) for row in rows)
    (out / 'validation.jsonl').write_bytes(raw)
    report = {'cases': len(rows), 'sha256': hashlib.sha256(raw).hexdigest(),
              'scope': 'New synthetic wording/paths/count coverage; not historical development or final-test data, not a SOTA benchmark.',
              'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    atomic_json(out / 'manifest.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().out), indent=2))
