"""Prepare or run paired, fresh Codex chats; retain raw events and external checks."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import threading
import uuid

HERE = Path(__file__).resolve().parent
CASES = {
    'csv': {
        'task': 'Create report.py that reads orders.csv, sums quantity times unit_price for rows whose status is paid, and prints the total as exactly two decimal places. Run it and verify the actual result. Use decimal arithmetic.',
        'files': {'orders.csv': 'status,quantity,unit_price\npaid,3,19.95\nrefunded,5,100.00\npaid,2,7.50\npaid,1,0.10\n'},
        'stdout': '74.95\r\n',
        'alternate': {'file': 'orders.csv', 'content': 'status,quantity,unit_price\npaid,2,0.15\nrefunded,10,9.00\n', 'stdout': '0.30\r\n'},
        'context': 'Python 3.12 standard library. orders.csv is UTF-8 CSV with status, quantity, unit_price columns. The file is in the working directory.'},
    'repair': {
        'task': 'Run the existing report.py to observe its failure. Fix it so it sums the values in values.json and prints the sum. Rerun and verify the actual result.',
        'files': {'values.json': '[4, 9, 15]\n', 'report.py': 'import json\nfrom pathlib import Path\nvalues = json.loads(Path("values.json").read_text())\nprint(sum(valuez))\n'},
        'stdout': '28\r\n', 'alternate': {'file': 'values.json', 'content': '[2, 7, -1]\n', 'stdout': '8\r\n'}, 'context': 'Python 3.12 standard library. values.json is a JSON array of integers in the working directory.'},
}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def prepare(out, case, arm):
    directory = out.resolve() / (case + '-' + arm + '-' + uuid.uuid4().hex[:8])
    root = directory / 'workspace'
    root.mkdir(parents=True)
    data = CASES[case]
    for name, content in data['files'].items():
        (root / name).write_text(content, encoding='utf-8', newline='')
    # An independent repository prevents inheriting shell-forensics release chores.
    subprocess.run(['git', 'init', '--quiet', str(root)], check=True)
    instructions = ('This is an isolated command-specialist benchmark fixture, not an implementation project. '
        'Do only the requested operation; no commits, PRs, dependency installs or unrelated browsing. '
        'Modify only report.py. Read the provided input file. Use Python 3.12 standard library. '
        'Report observed failures and any fallback honestly. Do not fabricate results.\n')
    instructions += ('Use normal native shell/file tools. Do not invoke a local model or command-specialist.\n'
        if arm == 'baseline' else
        'Call command_specialist.run_python_task once with English intent, exact target report.py, '
        'known context and expected stdout. Do not write source or command sequences in that handoff. '
        'If it fails, report failure; do not silently use another executor.\n')
    (root / 'AGENTS.md').write_text(instructions, encoding='utf-8')
    prompt = data['task'] + '\n' + data['context'] + '\nExpected stdout: ' + json.dumps(data['stdout'])
    (directory / 'prompt.txt').write_text(prompt, encoding='utf-8')
    if arm == 'delegated':
        config = ('[mcp_servers.command_specialist]\n'
            f'command = {json.dumps(sys.executable)}\n'
            f'args = {json.dumps([str(HERE / "server.py"), "--root", str(root), "--artifacts", str(directory / "local"), "--allow-execute"])}\n'
            'required = true\nstartup_timeout_sec = 30\ntool_timeout_sec = 330\n'
            'default_tools_approval_mode = "prompt"\n')
        (root / '.codex').mkdir()
        (root / '.codex' / 'config.toml').write_text(config, encoding='utf-8')
    write_json(directory / 'fixture.json', {'case': case, 'arm': arm, 'expected_stdout': data['stdout'],
        'created_at': datetime.now(timezone.utc).isoformat(),
        'input_hashes': {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                         for name in data['files'] if name != 'report.py'}})
    return directory


def codex_command():
    path = shutil.which('codex')
    if not path:
        raise RuntimeError('Codex CLI is not installed')
    if Path(path).suffix.lower() in {'.cmd', '.ps1'}:
        entry = Path(path).parent / 'node_modules' / '@openai' / 'codex' / 'bin' / 'codex.js'
        if not entry.exists():
            raise RuntimeError('Cannot resolve installed Codex CLI entry point')
        return [shutil.which('node'), str(entry)]
    return [path]


def run(directory, model, effort, *, collector=None, timeout=600, extra_sources=()):
    if (directory / 'events.jsonl').exists():
        raise ValueError('Run evidence already exists; prepare a fresh workspace')
    sources = [HERE / 'server.py', HERE / 'bench.py', HERE.parent / 'delegate.py', *extra_sources]
    source_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    root = directory / 'workspace'
    command = codex_command() + ['exec', '--json', '--approve-for-me', '-C', str(root),
        '-m', model, '-c', 'model_reasoning_effort=' + json.dumps(effort),
        '-c', 'projects.' + json.dumps(str(root)) + '.trust_level="trusted"',
        '--output-last-message', str(directory / 'final.txt'), '-']
    start = time.perf_counter()
    timed_out = False
    with (directory / 'events.jsonl').open('wb') as output, (directory / 'stderr.txt').open('wb') as errors, (directory / 'prompt.txt').open('rb') as prompt:
        process = subprocess.Popen(command, stdin=prompt, stdout=subprocess.PIPE, stderr=errors)
        def capture():
            with (directory / 'event-times.jsonl').open('w', encoding='utf-8') as times:
                for index, line in enumerate(iter(process.stdout.readline, b'')):
                    output.write(line)
                    output.flush()
                    times.write(json.dumps({'line': index, 'elapsed_ms': round((time.perf_counter()-start)*1000)})+'\n')
                    times.flush()
        reader = threading.Thread(target=capture, daemon=True)
        reader.start()
        try:
            process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            timed_out = True
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
            process.wait(timeout=15)
        reader.join(timeout=15)
        if reader.is_alive():
            raise RuntimeError('Event capture did not close after Codex exit')
    write_json(directory / 'run.json', {'source_sha256': source_hashes, 'source_changed_during_run': any(hashlib.sha256(p.read_bytes()).hexdigest() != source_hashes[p.name] for p in sources), 'model': model, 'effort': effort, 'exit_code': process.returncode, 'timed_out_or_cancelled': timed_out,
        'wall_ms': round((time.perf_counter()-start)*1000), 'command': command,
        'billing': 'Existing Codex login; tokens are usage, not a dollar charge estimate'})
    return (collector or collect)(directory)


def collect(directory):
    fixture = json.loads((directory / 'fixture.json').read_text(encoding='utf-8'))
    run_info = json.loads((directory / 'run.json').read_text(encoding='utf-8'))
    events = []
    for line in (directory / 'events.jsonl').read_text(encoding='utf-8').splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    turns = [event for event in events if event.get('type') == 'turn.completed']
    items = [event['item'] for event in events if event.get('type') == 'item.completed']
    usage = {key: sum(turn.get('usage', {}).get(key, 0) for turn in turns)
             for key in ['input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens']}
    root = directory / 'workspace'
    checks = {'input_unchanged': all(hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
                                   for name, expected in fixture['input_hashes'].items())}
    if (root / 'report.py').exists():
        try:
            actual = subprocess.run([sys.executable, str(root / 'report.py')], cwd=root,
                                    capture_output=True, timeout=20)
        except subprocess.TimeoutExpired:
            actual = subprocess.CompletedProcess([], 124, b'', b'External verification timed out')
        (directory / 'verification-stdout.txt').write_bytes(actual.stdout)
        (directory / 'verification-stderr.txt').write_bytes(actual.stderr)
        checks.update(exit_code=actual.returncode,
                      stdout_matches=actual.stdout.decode('utf-8', errors='replace') == fixture['expected_stdout'])
    else:
        checks.update(exit_code=None, stdout_matches=False)
    alternate = CASES[fixture['case']]['alternate']
    source = root / alternate['file']
    original = source.read_bytes()
    checks['alternate_input_matches'] = False
    if (root / 'report.py').exists():
        try:
            source.write_text(alternate['content'], encoding='utf-8', newline='')
            try:
                probe = subprocess.run([sys.executable, str(root / 'report.py')], cwd=root,
                                       capture_output=True, timeout=20)
            except subprocess.TimeoutExpired:
                probe = subprocess.CompletedProcess([], 124, b'', b'Alternate verification timed out')
            checks['alternate_input_matches'] = probe.returncode == 0 and probe.stdout.decode('utf-8', errors='replace') == alternate['stdout']
            (directory / 'alternate-stdout.txt').write_bytes(probe.stdout)
        finally:
            source.write_bytes(original)
    local = []
    for path in (directory / 'local').glob('*/result.json'):
        record = json.loads(path.read_text(encoding='utf-8'))
        local.append({'status': record['status'], 'verified': record['verified'], 'wall_ms': record['wall_ms'],
            'input_tokens': sum(c['response'].get('prompt_eval_count', 0) for c in record['model_calls']),
            'output_tokens': sum(c['response'].get('eval_count', 0) for c in record['model_calls']),
            'failed_executions': sum(a.get('result', {}).get('exit_code', 0) != 0 for a in record['actions'])})
    result = {'case': fixture['case'], 'arm': fixture['arm'], 'model': run_info['model'],
        'effort': run_info['effort'], 'wall_ms': run_info['wall_ms'], 'frontier_usage': usage,
        'turn_completed': bool(turns), 'codex_exit': run_info['exit_code'], 'local': local, 'checks': checks,
        'accurate': checks['input_unchanged'] and checks['exit_code'] == 0 and checks['stdout_matches'] and checks['alternate_input_matches'],
        'command_calls': sum(i.get('type') == 'command_execution' for i in items),
        'mcp_calls': sum(i.get('type') == 'mcp_tool_call' for i in items),
        'raw_events': str(directory / 'events.jsonl')}
    result['success'] = bool(result['accurate'] and turns and run_info['exit_code'] == 0 and not run_info.get('source_changed_during_run', False) and
        (fixture['arm'] == 'baseline' or (result['mcp_calls'] == 1 and len(local) == 1 and local[0]['verified'])))
    write_json(directory / 'summary.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'run', 'collect'])
    parser.add_argument('--case', choices=list(CASES), default='csv')
    parser.add_argument('--arm', choices=['baseline', 'delegated'], default='delegated')
    parser.add_argument('--out', type=Path, default=Path('work/codex-bench'))
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--model', default='gpt-6-astra')
    parser.add_argument('--effort', default='low')
    args = parser.parse_args()
    directory = args.directory.resolve() if args.directory else prepare(args.out, args.case, args.arm)
    if args.operation == 'prepare':
        print(str(directory))
    elif args.operation == 'run':
        print(json.dumps(run(directory, args.model, args.effort), indent=2))
    else:
        print(json.dumps(collect(directory), indent=2))


if __name__ == '__main__':
    main()
