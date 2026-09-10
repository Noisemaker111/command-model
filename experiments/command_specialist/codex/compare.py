"""Compare paired fresh-chat evidence without claiming savings for failed work."""
import argparse
import json
from pathlib import Path


def compare(baseline, delegated):
    if baseline['case'] != delegated['case'] or baseline['model'] != delegated['model'] or baseline['effort'] != delegated['effort']:
        raise ValueError('Compare the same task and frontier settings')
    if baseline['arm'] != 'baseline' or delegated['arm'] != 'delegated':
        raise ValueError('Expected baseline then delegated results')
    result = {'case': baseline['case'], 'sample_pairs': 1,
        'baseline': baseline, 'delegated': delegated, 'savings': None,
        'qualification': 'A single pair is a hookup smoke, not a speedup benchmark or billing estimate.'}
    if baseline.get('success') and delegated.get('success'):
        def reduction(a, b):
            return round(100 * (a-b) / a, 2) if a else None
        b, d = baseline['frontier_usage'], delegated['frontier_usage']
        result['savings'] = {'wall_time_percent': reduction(baseline['wall_ms'], delegated['wall_ms']),
            'frontier_input_percent': reduction(b['input_tokens'], d['input_tokens']),
            'frontier_uncached_input_percent': reduction(b['input_tokens']-b['cached_input_tokens'], d['input_tokens']-d['cached_input_tokens']),
            'frontier_output_percent': reduction(b['output_tokens'], d['output_tokens'])}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('delegated', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = compare(json.loads(args.baseline.read_text(encoding='utf-8')), json.loads(args.delegated.read_text(encoding='utf-8')))
    args.out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'case': result['case'], 'savings': result['savings'], 'qualification': result['qualification']}, indent=2))
