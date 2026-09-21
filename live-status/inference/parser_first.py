"""CPU-only PowerShell AST backend with conservative deterministic rendering."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

ABSTENTION = "Running a PowerShell command."
_SIMPLE_NAME = re.compile(r"^[A-Za-z0-9_.+-]+$")
_COMMAND_ACTIONS = {
    "add-content": "appending to a file", "compare-object": "comparing objects",
    "compress-archive": "creating an archive", "convertfrom-json": "parsing JSON",
    "convertto-json": "formatting JSON", "copy-item": "copying an item",
    "expand-archive": "extracting an archive", "findstr": "searching text",
    "foreach-object": "processing pipeline items",
    "format-list": "formatting output as a list",
    "format-table": "formatting output as a table",
    "get-ciminstance": "reading system information",
    "get-childitem": "listing directory contents", "get-content": "reading a file",
    "get-command": "inspecting available commands",
    "get-date": "reading the current date and time",
    "get-filehash": "calculating a file hash",
    "get-item": "inspecting an item", "get-process": "listing processes",
    "get-nettcpconnection": "listing network connections",
    "get-service": "listing services", "group-object": "grouping objects",
    "invoke-restmethod": "calling a REST endpoint",
    "invoke-webrequest": "making an HTTP request",
    "join-path": "building a path",
    "measure-object": "measuring objects", "move-item": "moving an item",
    "new-item": "creating an item", "out-file": "writing a file",
    "out-null": "discarding output", "pop-location": "restoring the previous directory",
    "push-location": "saving and changing directories",
    "remove-item": "removing an item", "rename-item": "renaming an item",
    "resolve-path": "resolving a path", "select-object": "selecting object properties",
    "select-string": "searching text", "set-content": "writing a file",
    "set-location": "changing directories", "sort-object": "sorting objects",
    "start-process": "starting a process", "stop-process": "stopping a process",
    "start-sleep": "waiting",
    "split-path": "extracting part of a path",
    "tee-object": "copying pipeline output", "test-path": "checking whether a path exists",
    "where-object": "filtering pipeline items", "write-error": "writing an error",
    "write-output": "writing output", "write-warning": "writing a warning",
}
_ALIASES = {
    "%": "foreach-object", "?": "where-object", "cat": "get-content",
    "cd": "set-location", "cp": "copy-item", "del": "remove-item",
    "dir": "get-childitem", "echo": "write-output", "gc": "get-content",
    "gci": "get-childitem", "gi": "get-item", "ls": "get-childitem",
    "mi": "move-item", "mv": "move-item", "ni": "new-item",
    "pwd": "get-location", "ren": "rename-item", "rg.exe": "rg",
    "ri": "remove-item", "rm": "remove-item", "sls": "select-string",
    "select": "select-object", "type": "get-content", "curl.exe": "curl",
}
_GIT_ACTIONS = {
    "add": "staging Git changes", "branch": "inspecting Git branches",
    "checkout": "switching Git revisions", "clean": "cleaning the Git worktree",
    "clone": "cloning a Git repository", "commit": "committing Git changes",
    "diff": "inspecting Git changes", "fetch": "fetching Git updates",
    "log": "reading Git history", "merge": "merging Git changes",
    "ls-files": "listing tracked Git files",
    "pull": "pulling Git updates", "push": "pushing Git changes",
    "rebase": "rebasing Git changes", "remote": "inspecting Git remotes",
    "reset": "resetting Git state", "restore": "restoring Git files",
    "rev-parse": "inspecting Git revision data", "show": "showing a Git revision",
    "status": "checking Git status", "switch": "switching Git branches",
    "tag": "inspecting Git tags", "worktree": "managing Git worktrees",
}
_GH_ACTIONS = {
    ("pr", "checks"): "checking pull request status",
    ("pr", "create"): "creating a pull request",
    ("pr", "diff"): "inspecting a pull request diff",
    ("pr", "list"): "listing pull requests",
    ("pr", "merge"): "merging a pull request",
    ("pr", "view"): "viewing a pull request",
    ("run", "view"): "viewing a workflow run",
    ("run", "watch"): "watching a workflow run",
}
_RUNTIME_ACTIONS = {
    "bun": "running Bun", "bun.exe": "running Bun", "bunx": "running Bun",
    "cargo": "running Cargo",
    "cmd": "running Command Prompt", "cmd.exe": "running Command Prompt",
    "deno": "running Deno", "dotnet": "running .NET", "go": "running Go",
    "java": "running Java", "make": "running Make", "node": "running Node.js",
    "node.exe": "running Node.js", "npm": "running npm", "npx": "running npx",
    "pnpm": "running pnpm", "pwsh": "running PowerShell",
    "pwsh.exe": "running PowerShell", "powershell": "running Windows PowerShell",
    "powershell.exe": "running Windows PowerShell", "python": "running Python",
    "python.exe": "running Python", "python3": "running Python",
    "pytest": "running Python tests", "uv": "running uv", "yarn": "running Yarn",
}


def _clean(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _subcommands(elements: list[str]) -> list[str]:
    values: list[str] = []
    skip_value = False
    for raw in elements[1:]:
        value = _clean(raw)
        if skip_value:
            skip_value = False
            continue
        if value in ("-C", "--git-dir", "--work-tree"):
            skip_value = True
            continue
        if value.startswith("-"):
            continue
        values.append(value.lower())
    return values


def _describe(node: dict[str, Any]) -> tuple[str | None, bool]:
    raw_name = node.get("name")
    if not raw_name:
        return None, False
    basename = Path(str(raw_name)).name.lower()
    name = _ALIASES.get(basename, basename)
    elements = [str(item) for item in node.get("elements", [])]
    if name == "git":
        args = _subcommands(elements)
        if args:
            return _GIT_ACTIONS.get(args[0], f"running git {args[0]}"), args[0] in _GIT_ACTIONS
        return "running Git", False
    if name == "gh":
        args = _subcommands(elements)
        pair = tuple(args[:2])
        if pair in _GH_ACTIONS:
            return _GH_ACTIONS[pair], True
        return (f"running gh {args[0]}" if args else "running GitHub CLI"), False
    if name in ("rg", "ripgrep"):
        return "searching text", True
    if name == "curl":
        return "making an HTTP request", True
    if name in _COMMAND_ACTIONS:
        return _COMMAND_ACTIONS[name], True
    if name == "get-location":
        return "reading the current directory", True
    if name in _RUNTIME_ACTIONS:
        return _RUNTIME_ACTIONS[name], True
    if _SIMPLE_NAME.fullmatch(name):
        return f"running {name}", False
    return None, False


def _metrics(nodes, errors, abstained, facts, semantic, literal, total_actions=0):
    return {
        "abstained": abstained,
        "fully_mapped": not abstained and literal == 0 and semantic > 0,
        "literal_fallback": literal > 0,
        "mapped_actions": semantic, "literal_actions": literal,
        "facts": facts, "parse_errors": errors, "ast_nodes": len(nodes),
        "total_actions": total_actions,
    }


def render(parsed: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    nodes = list(parsed.get("nodes") or [])
    errors = list(parsed.get("errors") or [])
    if not parsed.get("ok") or errors or any(node.get("dynamic") for node in nodes):
        return ABSTENTION, _metrics(nodes, errors, True, [], 0, 0)
    facts: list[dict[str, str]] = []
    semantic = literal = 0
    seen: set[str] = set()
    for node in nodes:
        if node.get("kind") != "command":
            continue
        action, known = _describe(node)
        if not action or action in seen:
            continue
        seen.add(action)
        facts.append({"text": action, "evidence": str(node.get("evidence", ""))})
        semantic += int(known)
        literal += int(not known)
    if not facts:
        return ABSTENTION, _metrics(nodes, [], True, [], 0, 0)
    total_actions = len(facts)
    rendered_facts = facts[:3]
    phrases = [fact["text"] for fact in rendered_facts]
    if len(phrases) == 1:
        body = phrases[0]
    elif len(phrases) == 2:
        body = f"{phrases[0]} and {phrases[1]}"
    else:
        body = ", ".join(phrases[:-1]) + f", and {phrases[-1]}"
    if total_actions > len(rendered_facts):
        body += f", plus {total_actions - len(rendered_facts)} more parsed steps"
    return body[0].upper() + body[1:] + ".", _metrics(
        nodes, [], False, rendered_facts, semantic, literal, total_actions
    )


class PowerShellAstBackend:
    """Persistent PowerShell parser process; performs no model inference."""

    name = "parser:powershell"
    source = "parser"

    def __init__(self, executable: str | None = None):
        self.executable = executable or shutil.which("pwsh") or shutil.which("powershell")
        if not self.executable:
            raise RuntimeError("PowerShell is required for parser:powershell")
        self.host = Path(__file__).with_name("powershell_ast_host.ps1")
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._request_id = 0

    def _start(self) -> None:
        if self._process and self._process.poll() is None:
            return
        self._process = subprocess.Popen(
            [self.executable, "-NoLogo", "-NoProfile", "-NonInteractive",
             "-File", str(self.host)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1,
        )

    def parse(self, command: str) -> dict[str, Any]:
        with self._lock:
            self._start()
            assert self._process and self._process.stdin and self._process.stdout
            self._request_id += 1
            self._process.stdin.write(json.dumps(
                {"id": self._request_id, "command": command}, ensure_ascii=False
            ) + "\n")
            self._process.stdin.flush()
            line = self._process.stdout.readline()
            if not line:
                raise RuntimeError(
                    f"PowerShell AST host exited unexpectedly ({self._process.poll()})"
                )
            response = json.loads(line)
            if response.get("id") != self._request_id:
                raise RuntimeError("PowerShell AST host returned a mismatched response")
            return response

    def generate(self, command: str) -> tuple[str, dict[str, Any]]:
        started = time.perf_counter()
        status, metrics = render(self.parse(command))
        metrics["wall_s"] = time.perf_counter() - started
        metrics["backend"] = "parser:powershell"
        return status, metrics

    def warm(self) -> None:
        self.parse("Get-Location")

    def close(self) -> None:
        process, self._process = self._process, None
        if not process:
            return
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=2)
        if process.stdout:
            process.stdout.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
