"""Single-use English delegation CLI for explicitly trusted local Python tasks.

This prototype is not a sandbox or an OpenCode2 permission adapter.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import uuid

MODEL = 'shell-specialist-f16'
ACTION_SCHEMA = {
    'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['write', 'run', 'read', 'finish']},
        'target': {'type': 'string'}, 'instruction': {'type': 'string'}},
    'required': ['action', 'target', 'instruction'], 'additionalProperties': False}


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(task, root):
    if not isinstance(task, dict):
        raise ValueError('handoff must be an object')
    if not isinstance(task.get('task'), str) or not task['task'].strip():
        raise ValueError('task must contain English intent')
    targets = task.get('targets')
    if not isinstance(targets, dict) or not targets:
        raise ValueError('targets must bind names to exact relative .py paths')
    resolved = {}
    for name, value in targets.items():
        if not isinstance(name, str) or not name or not isinstance(value, str):
            raise ValueError('target names and paths must be strings')
        path = (root / value).resolve()
        if not path.is_relative_to(root) or Path(value).is_absolute() or path.suffix != '.py':
            raise ValueError('target must be a relative .py file inside root')
        resolved[name] = path
    check = task.get('completion', {})
    if not isinstance(check, dict):
        raise ValueError('completion must be an object')
    if check.get('target') not in resolved or not isinstance(check.get('stdout'), str):
        raise ValueError('completion requires a bound target and exact stdout')
    return resolved


def completion_matches(status, path, written_hash, actual, expected):
    return bool(status == 'unverified' and written_hash and path.exists()
                and written_hash == digest(path)
                and actual.get('sha256_before') == written_hash
                and actual.get('exit_code') == 0 and not actual.get('limit')
                and actual.get('stdout') == expected)


def kill_tree(process):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    else:
        import signal
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=10)


def execute(path, root, directory, remaining, output_limit):
    stdout, stderr = directory / 'stdout.txt', directory / 'stderr.txt'
    started = time.monotonic()
    reason = None
    with stdout.open('wb') as out, stderr.open('wb') as err:
        process = subprocess.Popen([sys.executable, str(path)], cwd=root, stdout=out,
                                   stderr=err, start_new_session=os.name != 'nt')
        try:
            while process.poll() is None:
                if time.monotonic() - started >= remaining:
                    reason = 'execution_timeout'
                if stdout.stat().st_size + stderr.stat().st_size > output_limit:
                    reason = 'output_limit'
                if reason:
                    kill_tree(process)
                    break
                time.sleep(.02)
        except BaseException:
            kill_tree(process)
            raise
    if stdout.stat().st_size + stderr.stat().st_size > output_limit:
        reason = 'output_limit'
    return {'exit_code': process.returncode, 'limit': reason,
            'stdout': stdout.read_bytes()[:output_limit].decode('utf-8', errors='replace'),
            'stderr': stderr.read_bytes()[:output_limit].decode('utf-8', errors='replace'),
            'raw_stdout': str(stdout), 'raw_stderr': str(stderr)}


def delegate(task, root, artifacts, *, max_actions=12, seconds=300, output_limit=65536,
             num_ctx=32768, num_predict=8192,
             base_url='http://127.0.0.1:11434', allow_execute=False):
    if not 1 <= max_actions <= 20 or not 1 <= seconds <= 600 or not 1 <= output_limit <= 1048576:
        raise ValueError('invalid lifecycle limits')
    if not 1 <= num_predict < num_ctx <= 32768:
        raise ValueError('require 1 <= output tokens < context <= 32768')
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError('root must be a directory')
    targets = validate(task, root)
    run_dir = artifacts.resolve() / uuid.uuid4().hex
    run_dir.mkdir(parents=True)
    artifact = run_dir / 'result.json'
    started = time.monotonic()
    deadline = started + seconds
    record = {'model': MODEL, 'task': task, 'root': str(root), 'actions': [], 'model_calls': [],
              'status': 'running', 'verified': False, 'limits': {
                  'actions': max_actions, 'seconds': seconds, 'output_bytes': output_limit,
                  'num_ctx': num_ctx, 'num_predict': num_predict}}
    messages = [{'role': 'system', 'content':
        'You are a fresh local Python worker. Complete one English task. Choose one action: '
        'write (instruction describes file content), run (execute a target with Python), '
        'read (inspect a target), finish (explain outcome). Use only supplied target names. '
        'After write, run; after a failure, repair using actual stderr. Do not repeat successful '
        'work. Return action, target, instruction JSON. Never claim observations you lack. '
        'A missing file requires write, not another run.'},
        {'role': 'user', 'content': json.dumps(task, ensure_ascii=False)}]
    written = {}
    latest = {}

    def persist():
        record['wall_ms'] = round((time.monotonic() - started) * 1000)
        save(artifact, record)

    def infer(context, schema=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('worker time exhausted')
        # Conservative UTF-8 byte upper bound reserves the output budget rather than
        # silently allowing the inference server to discard earlier instructions.
        prompt_upper_bound = sum(len(m['content'].encode('utf-8')) + 64 for m in context)
        if prompt_upper_bound + num_predict > num_ctx:
            raise ValueError('context budget exhausted; history was not silently truncated')
        body = {'model': MODEL, 'messages': context, 'stream': False, 'think': False,
                'keep_alive': '5m', 'options': {'temperature': 0, 'seed': 20260909,
                                             'num_ctx': num_ctx, 'num_predict': num_predict}}
        if schema:
            body['format'] = schema
        request = urllib.request.Request(base_url + '/api/chat', json.dumps(body).encode(),
                                         {'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=remaining) as response:
            result = json.load(response)
        record['model_calls'].append({'request': body, 'response': result})
        persist()
        if result.get('done_reason') == 'length':
            raise ValueError('model output limit reached')
        if time.monotonic() >= deadline:
            raise TimeoutError('worker time exhausted after inference')
        return result['message']['content']

    persist()
    try:
        if not allow_execute:
            record['status'] = 'denied'
            record['error'] = 'trusted local execution was not authorized; no alternative executor'
        else:
            request = urllib.request.Request(base_url + '/api/show',
                json.dumps({'model': MODEL}).encode(), {'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=min(10, seconds)) as response:
                identity = json.load(response)
            record['model_identity'] = identity
            if identity.get('details', {}).get('quantization_level') not in {'BF16', 'F16', 'F32'}:
                raise ValueError('non-quantized model required; refusing quantized or unknown weights')
            for index in range(max_actions):
                state = {name: {'exists': path.exists(), 'written': name in written,
                                'last_exit': latest.get(name, {}).get('exit_code'),
                                'stdout_matches': latest.get(name, {}).get('stdout') == task['completion']['stdout']}
                         for name, path in targets.items()}
                raw = infer(messages + [{'role': 'user', 'content':
                    'Current observed state: ' + json.dumps(state) +
                    '. Decide the NEXT action using the latest result. '
                    'A saved file that has not run needs action run. '
                    'A failed run needs action write to repair. '
                    'A successful matching run needs action finish. '
                    'Do not copy earlier actions.'}], ACTION_SCHEMA)
                messages.append({'role': 'assistant', 'content': raw})
                action = json.loads(raw)
                if (not isinstance(action, dict) or set(action) != {'action', 'target', 'instruction'}
                        or not all(isinstance(value, str) for value in action.values())):
                    raise ValueError('malformed worker action')
                entry = {'selection': action}
                record['actions'].append(entry)
                persist()
                if action.get('action') == 'finish':
                    check = task['completion']
                    name = check['target']
                    if completion_matches('unverified', targets[name], written.get(name),
                                          latest.get(name, {}), check['stdout']):
                        record['worker_explanation'] = action.get('instruction', '')
                        record['status'] = 'unverified'
                        break
                    entry['result'] = {'error': 'Completion rejected: need a written file, a run of those bytes, '
                                       'exit zero, and exact required stdout. Inspect the last result and repair.'}
                    messages.append({'role': 'user', 'content': json.dumps(entry['result'])})
                    persist()
                    continue
                name = action.get('target')
                if name not in targets:
                    entry['result'] = {'error': 'unknown target; use a supplied binding name'}
                else:
                    path = targets[name]
                    # Recheck exact binding immediately before every native operation.
                    if path.resolve() != path or not path.resolve().is_relative_to(root):
                        raise PermissionError('target binding changed')
                    operation = action.get('action')
                    if operation == 'write':
                        generation_context = (
                            task['task'] + '\nRuntime/API context: ' + str(task.get('context', '')) +
                            '\nConstraints: ' + str(task.get('constraints', [])) +
                            '\nRequired stdout exactly (JSON string): ' + json.dumps(task['completion']['stdout']) +
                            '\nTarget binding: ' + name + ' = ' + str(path) +
                            '\nCurrent saved source:\n' + (path.read_text(encoding='utf-8') if path.exists() else '(missing)') +
                            '\nActual last execution result: ' + json.dumps(latest.get(name, {}), ensure_ascii=False) +
                            '\nReturn only the complete Python source to save. Do not return the task description or JSON.')
                        content = infer([{'role': 'system', 'content':
                            'Write executable Python source only. No JSON wrapper, markdown fences or prose.'},
                            {'role': 'user', 'content': generation_context}])
                        if content.startswith('```'):
                            entry['result'] = {'error': 'raw file content required; markdown rejected'}
                        else:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_text(content, encoding='utf-8', newline='')
                            written[name] = digest(path)
                            latest.pop(name, None)
                            entry['result'] = {'saved_file': str(path), 'sha256': written[name], 'content': content}
                    elif operation == 'run':
                        directory = run_dir / str(index)
                        directory.mkdir()
                        before = digest(path) if path.exists() else None
                        entry['result'] = execute(path, root, directory,
                                                  max(.01, min(20, deadline-time.monotonic())), output_limit)
                        entry['result']['sha256_before'] = before
                        latest[name] = entry['result']
                    elif operation == 'read':
                        entry['result'] = {'content': path.read_bytes()[:output_limit].decode('utf-8', errors='replace')}
                    else:
                        entry['result'] = {'error': 'unknown action'}
                persist()
                messages.append({'role': 'user', 'content': 'Observed native result: ' +
                                 json.dumps(entry['result'], ensure_ascii=False)})
            else:
                record['status'] = 'exhausted'
            check = task['completion']
            name = check['target']
            actual = latest.get(name, {})
            record['verified'] = completion_matches(record['status'], targets[name],
                written.get(name), actual, check['stdout'])
            if record['verified']:
                record['status'] = 'verified'
    except KeyboardInterrupt:
        record['status'] = 'cancelled'
    except PermissionError as error:
        record.update(status='denied', error=str(error))
    except (OSError, ValueError, KeyError, TypeError) as error:
        record.update(status='failed', error=str(error))
    finally:
        persist()
    return {'status': record['status'], 'verified': record['verified'],
            'worker_explanation': (record.get('worker_explanation') or '')[:2000],
            'packet_limit_chars': 2000,
            'truncated': any(len(latest.get(task['completion']['target'], {}).get(k, '')) > 2000
                             for k in ('stdout', 'stderr')),
            'observed': {key: value[:2000] if key in ('stdout', 'stderr') else value
                         for key, value in latest.get(task['completion']['target'], {}).items()},
            'raw_result': str(artifact), 'wall_ms': record['wall_ms']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-file', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, default=Path('work/english-delegation'))
    parser.add_argument('--allow-execute', action='store_true',
                        help='Authorize generated Python with your account privileges in a trusted task')
    parser.add_argument('--max-actions', type=int, default=12)
    parser.add_argument('--seconds', type=int, default=300)
    parser.add_argument('--num-ctx', type=int, default=32768)
    parser.add_argument('--num-predict', type=int, default=8192)
    args = parser.parse_args()
    task = json.loads(args.task_file.read_text(encoding='utf-8-sig'))
    packet = delegate(task, args.root, args.artifacts, allow_execute=args.allow_execute,
                      max_actions=args.max_actions, seconds=args.seconds,
                      num_ctx=args.num_ctx, num_predict=args.num_predict)
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(packet, ensure_ascii=False, indent=2))
    return 0 if packet['verified'] else 1


if __name__ == '__main__':
    sys.exit(main())
