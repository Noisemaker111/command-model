"""Scoped stdio MCP bridge for trusted Python English handoffs."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from delegate import delegate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--allow-execute', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    server = FastMCP('command-specialist', log_level='WARNING')
    lock = asyncio.Lock()

    @server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True,
                                            idempotentHint=False, openWorldHint=True))
    async def run_python_task(task: str, target: str, expected_stdout: str,
                              context: str = '', constraints: list[str] | None = None) -> dict:
        """Delegate English Python write/run/repair work to one fresh local FP16 worker.

        Supply intent, an exact relative .py target, relevant file/API context and
        required stdout (including newlines). Do not supply source code or shell
        commands. Executes generated Python with the caller's account privileges
        in this server's fixed trusted workspace; this is not a sandbox. Returns
        observed exits/output, verified status and reopenable raw evidence. Failed
        work is not success; any frontier repair must be reported as fallback.
        """
        async with lock:
            handoff = {'task': task, 'targets': {'program': target}, 'context': context,
                       'constraints': constraints or [],
                       'completion': {'target': 'program', 'stdout': expected_stdout}}
            # A separate process owns each lifecycle, including its model history.
            import uuid
            args.artifacts.mkdir(parents=True, exist_ok=True)
            request = args.artifacts / (uuid.uuid4().hex + '-handoff.json')
            request.write_text(json.dumps(handoff), encoding='utf-8')
            command = [sys._base_executable, '-S', str(Path(__file__).resolve().parents[1] / 'delegate.py'),
                       '--task-file', str(request.resolve()), '--root', str(root),
                       '--artifacts', str(args.artifacts.resolve())]
            if args.allow_execute:
                command.append('--allow-execute')
            process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                                                           stderr=asyncio.subprocess.PIPE)
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=310)
            except (asyncio.CancelledError, TimeoutError):
                # Terminate the worker tree, never start an alternative executor.
                if process.returncode is None:
                    killer = await asyncio.create_subprocess_exec('taskkill', '/PID', str(process.pid), '/T', '/F',
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                    await killer.wait()
                    await process.wait()
                raise
            if not stdout:
                return {'status': 'failed', 'verified': False, 'worker_exit': process.returncode,
                        'error': stderr.decode('utf-8', errors='replace')[-2000:]}
            packet = json.loads(stdout.decode('utf-8'))
            raw = json.loads(Path(packet['raw_result']).read_text(encoding='utf-8'))
            packet['local_usage'] = {
                'input_tokens': sum(c['response'].get('prompt_eval_count', 0) for c in raw['model_calls']),
                'output_tokens': sum(c['response'].get('eval_count', 0) for c in raw['model_calls']),
                'model_calls': len(raw['model_calls']), 'actions': len(raw['actions']),
                'failed_executions': sum(a.get('result', {}).get('exit_code', 0) != 0 for a in raw['actions'])}
            return packet

    server.run(transport='stdio')


if __name__ == '__main__':
    main()
