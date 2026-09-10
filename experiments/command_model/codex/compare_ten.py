"""Compare whole-session ten-stage evidence without rewarding failed work."""
import argparse
import json
from pathlib import Path


def compare(rows):
    baseline = next(r for r in rows if r['arm'] == 'baseline')
    results = []
    for row in rows:
        usage = row['frontier_usage']
        result = {k: row[k] for k in ('arm', 'success', 'wall_ms', 'delegations', 'native_commands',
            'completed_stages', 'alternate_stages', 'local_worker_ms', 'outside_tool_span_ms')}
        result['frontier_input_tokens'] = usage['input_tokens']
        result['frontier_cached_input_tokens'] = usage['cached_input_tokens']
        result['frontier_uncached_input_tokens'] = usage['input_tokens'] - usage['cached_input_tokens']
        result['frontier_output_tokens'] = usage['output_tokens']
        result['local_input_tokens'] = sum(r['input_tokens'] for r in row['local'])
        result['local_output_tokens'] = sum(r['output_tokens'] for r in row['local'])
        result['local_model_calls'] = sum(r['model_calls'] for r in row['local'])
        result['failed_local_executions'] = sum(r['failed_executions'] for r in row['local'])
        matched = all(row[k] == baseline[k] for k in ('model', 'effort', 'benchmark_identity'))
        eligible = row['success'] and baseline['success'] and matched
        result['savings_eligible'] = eligible
        if eligible:
            result['saved_ms'] = baseline['wall_ms'] - row['wall_ms']
            result['saved_percent'] = 100 * result['saved_ms'] / baseline['wall_ms']
            result['instant_worker_floor_ms'] = row['wall_ms'] - row['local_worker_ms']
            result['instant_worker_saved_ms'] = baseline['wall_ms'] - result['instant_worker_floor_ms']
        results.append(result)
    return {'results': results, 'limits': [
        'Each row is one whole Codex CLI session, not a latency distribution or billing estimate.',
        'Only successful matching-model runs receive savings. Verify matching source/config and fixtures before pooling.',
        'Instant-worker floor subtracts observed serial local worker wall time only; all other costs are held fixed.',
        'Outside-tool span is observed event timing, including startup and frontier work, not pure model inference.',
        'Independent changed-input evaluation happens after the timed chat.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('summaries', nargs='+', type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    rows = []
    for path in args.summaries:
        row = json.loads(path.read_text(encoding='utf-8'))
        run = json.loads((path.parent/'run.json').read_text(encoding='utf-8'))
        fixture = json.loads((path.parent/'fixture.json').read_text(encoding='utf-8'))
        row['benchmark_identity'] = {'source': run['source_sha256'], 'inputs': fixture['input_hashes'], 'case': fixture['case']}
        rows.append(row)
    report = compare(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
