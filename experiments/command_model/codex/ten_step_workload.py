"""Synthetic ten-stage incident investigation derived from private command patterns."""
import hashlib
import json
from pathlib import Path


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def inputs(root, alternate=False):
    directory = root / 'inputs'
    directory.mkdir(parents=True, exist_ok=True)
    lines = ['INFO start', 'ERROR compiler: module missing', 'WARN retry', 'ERROR tests: failed', 'INFO stop']
    if alternate:
        lines += ['WARN slow disk', 'ERROR packaging: failed']
    (directory / 'build.log').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    write_json(directory / 'desired.json', {'model': 'local-f16', 'context': 32768, 'output': 8192})
    write_json(directory / 'actual.json', {'model': 'local-f16' if not alternate else 'other-f16', 'context': 8192, 'output': 1024})
    write_json(directory / 'tests.json', [{'name': 'parser', 'status': 'failed'},
        {'name': 'paths', 'status': 'passed' if not alternate else 'failed'}, {'name': 'schema', 'status': 'passed'}])
    (directory / 'git-status.txt').write_text(' M src/parser.py\n?? run/check.py\n M docs/notes.md\n', encoding='utf-8')
    commands = [{'name': 'compile', 'exit_code': 1, 'duration_ms': 1400, 'stderr': 'module missing'},
                {'name': 'tests', 'exit_code': 1, 'duration_ms': 2300, 'stderr': 'parser failed'},
                {'name': 'inspect', 'exit_code': 0, 'duration_ms': 300, 'stderr': ''}]
    if alternate:
        commands.append({'name': 'package', 'exit_code': 2, 'duration_ms': 800, 'stderr': 'archive failed'})
    write_json(directory / 'commands.json', commands)
    (directory / "naïve team's notes.txt").write_text('Ticket SYNTH-42\nNo real customer data.\n', encoding='utf-8')


STEPS = [
    'Inventory every regular file recursively under inputs. Save out/01.json as an object with files: a lexicographically sorted list of paths relative to inputs, using forward slashes.',
    'Read inputs/build.log. Count each first whitespace-delimited log level. Save out/02.json as an object mapping each observed level to its count.',
    'Read inputs/build.log. Save out/03.json as an object with errors: a list of the ERROR messages in original order, excluding the ERROR prefix and following space.',
    'Compare inputs/desired.json with inputs/actual.json. Save out/04.json as an object with mismatched_keys: a sorted list of keys whose values differ.',
    'Read inputs/tests.json. Save out/05.json with passed: the number whose status is passed, and failed: a sorted list of names whose status is failed.',
    'Read inputs/git-status.txt in Git porcelain format (first two characters are status, character three is a space, remaining text is the path). Save out/06.json with changed_paths: the sorted paths and untracked_paths: the sorted paths whose status is ??.',
    'Read inputs/commands.json. Save out/07.json with total_duration_ms: the sum of all duration_ms, and failed_commands: a sorted list of names with nonzero exit_code.',
    'Read out/07.json and inputs/commands.json. For each failed command named by out/07.json, look up its stderr. Save out/08.json as an object mapping those command names to their stderr strings.',
    'Read out/02.json, out/04.json, out/05.json and out/07.json. Save out/09.json with error_count: the ERROR count, config_mismatch_count: length of mismatched_keys, failed_test_count: length of failed, failed_command_count: length of failed_commands, and total_duration_ms: the value from out/07.json.',
    'Read all nine out/01.json through out/09.json files and confirm they parse as JSON. Save out/10.json as an object mapping each filename (01.json through 09.json, without directory) to the lowercase SHA-256 hex digest of its exact file bytes.'
]


def expected(root):
    directory = root / 'inputs'
    lines = (directory / 'build.log').read_text(encoding='utf-8').splitlines()
    counts = {}
    for line in lines:
        level = line.split()[0]
        counts[level] = counts.get(level, 0) + 1
    desired = json.loads((directory / 'desired.json').read_text(encoding='utf-8'))
    actual = json.loads((directory / 'actual.json').read_text(encoding='utf-8'))
    mismatches = sorted(k for k in desired if desired[k] != actual.get(k))
    tests = json.loads((directory / 'tests.json').read_text(encoding='utf-8'))
    failed_tests = sorted(t['name'] for t in tests if t['status'] == 'failed')
    status = (directory / 'git-status.txt').read_text(encoding='utf-8').splitlines()
    commands = json.loads((directory / 'commands.json').read_text(encoding='utf-8'))
    failed = sorted(c['name'] for c in commands if c['exit_code'] != 0)
    total = sum(c['duration_ms'] for c in commands)
    values = [
        {'files': sorted(p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file())},
        counts, {'errors': [line[6:] for line in lines if line.startswith('ERROR ')]},
        {'mismatched_keys': mismatches}, {'passed': sum(t['status'] == 'passed' for t in tests), 'failed': failed_tests},
        {'changed_paths': sorted(line[3:] for line in status), 'untracked_paths': sorted(line[3:] for line in status if line[:2] == '??')},
        {'total_duration_ms': total, 'failed_commands': failed},
        {c['name']: c['stderr'] for c in commands if c['name'] in failed},
        {'error_count': counts.get('ERROR', 0), 'config_mismatch_count': len(mismatches),
         'failed_test_count': len(failed_tests), 'failed_command_count': len(failed), 'total_duration_ms': total}]
    return values


def assess(root):
    checks = []
    for index, value in enumerate(expected(root), 1):
        path = root / 'out' / f'{index:02}.json'
        try:
            actual = json.loads(path.read_text(encoding='utf-8-sig'))
            checks.append({'step': index, 'passed': actual == value})
        except (OSError, ValueError) as error:
            checks.append({'step': index, 'passed': False, 'error': str(error)})
    try:
        actual = json.loads((root / 'out/10.json').read_text(encoding='utf-8-sig'))
        hashes = {f'{index:02}.json': hashlib.sha256((root / 'out' / f'{index:02}.json').read_bytes()).hexdigest() for index in range(1, 10)}
        checks.append({'step': 10, 'passed': actual == hashes})
    except (OSError, ValueError) as error:
        checks.append({'step': 10, 'passed': False, 'error': str(error)})
    return checks
