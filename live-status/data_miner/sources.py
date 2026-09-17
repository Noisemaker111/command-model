"""Transcript source discovery and per-format command extraction.

Add a format by writing `discover() -> list[Path]` and `extract(path) -> Iterator[dict]`
and registering both with @source. Every source opens files read-only; SQLite
stores are copied through the backup API so live WAL databases are never touched.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

HOME = Path(os.path.expanduser("~"))
CTX = 600


@dataclass
class Source:
    name: str
    description: str
    discover: Callable[[], list[Path]]
    extract: Callable[[Path], Iterator[dict]]


REGISTRY: dict[str, Source] = {}


def source(name: str, description: str, discover: Callable[[], list[Path]]):
    def wrap(fn):
        REGISTRY[name] = Source(name, description, discover, fn)
        return fn
    return wrap


def _glob(*patterns: str) -> Callable[[], list[Path]]:
    def run() -> list[Path]:
        out: list[Path] = []
        for p in patterns:
            out += [Path(x) for x in glob.glob(str(HOME / p), recursive=True)]
        return sorted(set(out))
    return run


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        secs = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(secs, timezone.utc).isoformat()
    return str(value)


def _head(text, n: int = CTX) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    text = text.strip()
    return text if len(text) <= n else text[:n] + "…"


def _tail(text, n: int = CTX) -> str:
    if not text:
        return ""
    text = str(text).strip()
    return text if len(text) <= n else "…" + text[-n:]


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(x.get("text", "") for x in content if isinstance(x, dict) and isinstance(x.get("text"), str))
    return ""


def _command_from(value) -> str | None:
    """Commands arrive as strings or argv lists like ["bash", "-lc", "..."]."""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and all(isinstance(x, str) for x in value):
        if len(value) >= 3 and value[1] in ("-lc", "-c", "-Command", "-command", "/c", "/C"):
            return value[-1]
        return " ".join(value)
    return None


def _shell_from_tool(tool: str | None, param: str | None = None) -> str | None:
    t = f"{tool or ''} {param or ''}".lower()
    if "powershell" in t or "pwsh" in t:
        return "powershell"
    if "bash" in t or " sh" in t:
        return "bash"
    if "cmd" in t:
        return "cmd"
    return None


def _record(**kw) -> dict:
    base = {"id": None, "source_file": None, "source_type": None, "timestamp": None, "shell": None,
            "command_raw": None, "working_directory": None, "preceding_context": "",
            "following_context": "", "existing_model_text": None, "exit_code": None, "tags": [],
            "tool": None, "model": None, "session": None}
    base.update(kw)
    return base


def _rec(base: dict, **kw) -> dict:
    return _record(**{**base, **kw})


def _exit_from_text(text: str) -> int | None:
    m = re.search(r"(?:Exit code:?|exited with code|\"exit_code\"\s*:)\s*(-?\d+)", text or "")
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------- Claude Code
@source("claude-code", "Claude Code session transcripts (~/.claude/projects/**/*.jsonl)",
        _glob(".claude/projects/**/*.jsonl"))
def claude_code(path: Path) -> Iterator[dict]:
    pending: dict[str, dict] = {}
    last_text = ""
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if '"tool_use"' not in line and '"tool_result"' not in line and '"text"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            msg = o.get("message")
            if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
                continue
            if o.get("type") == "assistant":
                for b in msg["content"]:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text":
                        last_text = b.get("text") or last_text
                    elif b.get("type") == "tool_use" and b.get("name") in ("Bash", "PowerShell"):
                        inp = b.get("input") or {}
                        tags = ["sidechain"] if o.get("isSidechain") else []
                        if inp.get("run_in_background"):
                            tags.append("background")
                        pending[b.get("id")] = _record(
                            id=f"claude:{b.get('id')}", source_file=str(path), source_type="claude-code",
                            timestamp=o.get("timestamp"), shell="powershell" if b["name"] == "PowerShell" else None,
                            command_raw=inp.get("command"), working_directory=o.get("cwd"),
                            preceding_context=_tail(last_text), existing_model_text=inp.get("description"),
                            tags=tags, tool=b["name"], model=msg.get("model"), session=o.get("sessionId"))
            elif o.get("type") == "user":
                for b in msg["content"]:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        rec = pending.pop(b.get("tool_use_id"), None)
                        if rec is None:
                            continue
                        text = _text_of(b.get("content"))
                        m = re.match(r"Exit code (-?\d+)", text or "")
                        rec["exit_code"] = int(m.group(1)) if m else (None if b.get("is_error") else 0)
                        rec["following_context"] = _head(text)
                        if b.get("is_error"):
                            rec["tags"].append("error")
                        yield rec
    yield from pending.values()


# --------------------------------------------------------------------- Codex
_CODEX_SHELL_FNS = {"shell", "shell_command", "exec_command", "container.exec", "local_shell"}
_JS_CALL = re.compile(r"tools\.(exec_command|shell_command|shell)\s*\(")


def _js_calls(js: str) -> list[tuple[str, str]]:
    out = []
    for m in _JS_CALL.finditer(js):
        i = j = m.end(); depth = 1; quote = None
        while j < len(js) and depth:
            ch = js[j]
            if quote:
                if ch == "\\":
                    j += 2; continue
                if ch == quote:
                    quote = None
            elif ch in "\"'`":
                quote = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            j += 1
        out.append((m.group(1), js[i:j - 1]))
    return out


def _js_string_field(argtext: str, key: str) -> str | None:
    m = re.search(r"[\"']?" + key + r"[\"']?\s*:\s*(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)", argtext, re.S)
    if not m:
        return None
    lit = m.group(1)
    if lit[0] == '"':
        try:
            return json.loads(lit)
        except ValueError:
            return lit[1:-1]
    if lit[0] == "`" and "${" in lit:
        return None  # dynamic template: command not recoverable
    return lit[1:-1].replace("\\'", "'").replace("\\n", "\n").replace("\\\\", "\\")


@source("codex", "Codex CLI sessions (~/.codex/sessions, archived_sessions)",
        _glob(".codex/sessions/**/*.jsonl", ".codex/archived_sessions/**/*.jsonl"))
def codex(path: Path) -> Iterator[dict]:
    meta: dict = {}
    model = None
    pending: dict[str, list[dict]] = {}
    last_text = ""
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not any(k in line for k in ('"session_meta"', '"turn_context"', "_call", '"message"', "agent_message", "reasoning")):
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            t = o.get("type"); p = o.get("payload") or {}
            if t == "session_meta":
                meta = p
            elif t == "turn_context":
                model = p.get("model") or model
                meta["cwd"] = p.get("cwd") or meta.get("cwd")
            elif t == "event_msg" and p.get("type") == "agent_message":
                last_text = p.get("message") or last_text
            elif t != "response_item":
                continue
            pt = p.get("type")
            if pt == "message" and p.get("role") == "assistant":
                last_text = _text_of(p.get("content")) or last_text
            elif pt in ("function_call", "custom_tool_call", "local_shell_call"):
                cid = p.get("call_id") or p.get("id")
                recs = []
                base = dict(source_file=str(path), source_type="codex", timestamp=o.get("timestamp"),
                            working_directory=meta.get("cwd"), preceding_context=_tail(last_text),
                            model=model, session=meta.get("id"))
                if pt == "local_shell_call":
                    action = p.get("action") or {}
                    recs.append(_rec(base, id=f"codex:{cid}", command_raw=_command_from(action.get("command")),
                                        working_directory=action.get("working_directory") or meta.get("cwd"), tool="local_shell"))
                elif pt == "function_call" and p.get("name") in _CODEX_SHELL_FNS:
                    try:
                        a = json.loads(p.get("arguments") or "{}")
                    except ValueError:
                        a = {}
                    recs.append(_rec(base, id=f"codex:{cid}", command_raw=_command_from(a.get("cmd") or a.get("command")),
                                        shell=_shell_from_tool(None, a.get("shell")), tool=p.get("name"),
                                        working_directory=a.get("workdir") or meta.get("cwd"),
                                        existing_model_text=a.get("justification")))
                elif pt == "custom_tool_call" and p.get("name") == "exec":
                    js = p.get("input") or ""
                    for k, (fn, argtext) in enumerate(_js_calls(js)):
                        cmd = _js_string_field(argtext, "cmd") or _js_string_field(argtext, "command")
                        if cmd:
                            recs.append(_rec(base, id=f"codex:{cid}:{k}", command_raw=cmd, tool=f"exec>{fn}",
                                                shell=_shell_from_tool(None, _js_string_field(argtext, "shell")),
                                                tags=["js_cell"]))
                if recs:
                    pending[cid] = [r for r in recs if r["command_raw"]]
            elif pt in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
                recs = pending.pop(p.get("call_id"), None)
                if not recs:
                    continue
                out = p.get("output")
                if isinstance(out, dict):
                    out = out.get("output") or json.dumps(out)
                text = _text_of(out) if not isinstance(out, str) else out
                try:  # older sessions wrap output in JSON
                    j = json.loads(text)
                    if isinstance(j, dict):
                        text = j.get("output", text)
                        code = (j.get("metadata") or {}).get("exit_code")
                    else:
                        code = None
                except (ValueError, TypeError):
                    code = None
                for r in recs:
                    r["exit_code"] = code if code is not None else (_exit_from_text(text) if len(recs) == 1 else None)
                    r["following_context"] = _head(text)
                    yield r
    for recs in pending.values():
        yield from recs


# --------------------------------------------------------------------- OpenCode / OpenCode2
def _sqlite_snapshot(path: Path) -> sqlite3.Connection:
    src = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    dst = sqlite3.connect(":memory:")
    src.backup(dst)
    src.close()
    return dst


def _tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("select name from sqlite_master where type='table'")}


def _opencode_part(part: dict, *, path: Path, model: str | None, session: str | None, cwd: str | None,
                   ts, prev_text: str, source_type: str) -> Iterator[dict]:
    name = part.get("tool") or part.get("name")
    st = part.get("state") or {}
    inp = st.get("input") or {}
    meta = st.get("metadata") or {}
    text = _text_of(st.get("content")) or (st.get("output") if isinstance(st.get("output"), str) else "")
    tm = part.get("time") or st.get("time") or {}
    ts = tm.get("start") or tm.get("created") or ts
    base = dict(source_file=str(path), source_type=source_type, timestamp=_iso(ts), model=model, session=session,
                working_directory=inp.get("workdir") or cwd, preceding_context=_tail(prev_text), tool=name)
    pid = part.get("callID") or part.get("id")
    if name in ("bash", "shell", "powershell"):
        code = meta.get("exit")
        if code is None:
            code = _exit_from_text(text)
        tags = [] if st.get("status") == "completed" else [str(st.get("status"))]
        yield _rec(base, id=f"{source_type}:{pid}", command_raw=inp.get("command"),
                      shell="powershell" if name == "powershell" else None,
                      existing_model_text=inp.get("description"), exit_code=code,
                      following_context=_head(text), tags=tags)
    elif name == "execute":
        js = inp.get("code") or ""
        for k, (fn, argtext) in enumerate(_js_calls(js)):
            cmd = _js_string_field(argtext, "cmd") or _js_string_field(argtext, "command")
            if cmd:
                yield _rec(base, id=f"{source_type}:{pid}:{k}", command_raw=cmd, tool=f"execute>{fn}",
                              following_context=_head(text), tags=["js_cell"])


def _opencode_db(path: Path, source_type: str) -> Iterator[dict]:
    con = _sqlite_snapshot(path)
    tables = _tables(con)
    dirs = {}
    for t in ("session", "session_v2"):
        if t in tables:
            dirs.update(dict(con.execute(f"select id, directory from {t}")))
    if "session_message" in tables:
        prev: dict[str, str] = {}
        for sid, data in con.execute("select session_id, data from session_message order by session_id, seq"):
            try:
                o = json.loads(data)
            except ValueError:
                continue
            mm = o.get("model") or {}
            model = f"{mm.get('providerID', '')}/{mm.get('id') or mm.get('modelID') or ''}" if isinstance(mm, dict) else str(mm)
            for part in o.get("content") or []:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in ("text", "reasoning") and part.get("text"):
                    prev[sid] = part["text"]
                elif part.get("type") == "tool":
                    yield from _opencode_part(part, path=path, model=model, session=sid, cwd=dirs.get(sid),
                                              ts=o.get("time"), prev_text=prev.get(sid, ""), source_type=source_type)
    if "part" in tables and "message" in tables:
        models = {}
        for mid, data in con.execute("select id, data from message"):
            try:
                o = json.loads(data)
            except ValueError:
                continue
            models[mid] = f"{o.get('providerID', '')}/{o.get('modelID', '')}"
        prev = {}
        for mid, sid, data in con.execute("select message_id, session_id, data from part order by session_id, id"):
            try:
                part = json.loads(data)
            except ValueError:
                continue
            if part.get("type") in ("text", "reasoning") and part.get("text"):
                prev[sid] = part["text"]
            elif part.get("type") == "tool":
                yield from _opencode_part(part, path=path, model=models.get(mid), session=sid, cwd=dirs.get(sid),
                                          ts=None, prev_text=prev.get(sid, ""), source_type=source_type)
    con.close()


@source("opencode", "OpenCode SQLite store (~/.local/share/opencode/opencode.db)",
        _glob(".local/share/opencode/opencode.db"))
def opencode(path: Path) -> Iterator[dict]:
    yield from _opencode_db(path, "opencode")


@source("opencode2", "OpenCode2 host stores (~/.config/opencode/.channels/**/host.db)",
        _glob(".config/opencode/.channels/**/host.db"))
def opencode2(path: Path) -> Iterator[dict]:
    yield from _opencode_db(path, "opencode2")


# --------------------------------------------------------------------- Cursor
@source("cursor", "Cursor agent chats (~/.cursor/chats/*/*/store.db)", _glob(".cursor/chats/*/*/store.db"))
def cursor(path: Path) -> Iterator[dict]:
    try:
        meta = json.loads((path.parent / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    con = _sqlite_snapshot(path)
    if "blobs" not in _tables(con):
        return
    calls, results, texts = {}, {}, {}
    last = ""
    for _, data in con.execute("select id, data from blobs"):
        try:
            o = json.loads(data)
        except (ValueError, TypeError, UnicodeDecodeError):
            continue
        if not isinstance(o, dict) or not isinstance(o.get("content"), list):
            continue
        for p in o["content"]:
            if not isinstance(p, dict):
                continue
            if o.get("role") == "assistant" and p.get("type") == "text":
                last = p.get("text") or last
            if o.get("role") == "assistant" and p.get("type") == "tool-call":
                calls[p.get("toolCallId")] = p
                texts[p.get("toolCallId")] = last
            if o.get("role") == "tool" and p.get("type") == "tool-result":
                results[p.get("toolCallId")] = p
    for cid, p in calls.items():
        if p.get("toolName") != "Shell":
            continue
        args = p.get("args") or {}
        res = results.get(cid, {}).get("result")
        res = res if isinstance(res, str) else json.dumps(res) if res is not None else ""
        yield _record(id=f"cursor:{cid}", source_file=str(path), source_type="cursor", timestamp=_iso(meta.get("createdAtMs")),
                      command_raw=args.get("command"), working_directory=args.get("workingDirectory") or meta.get("cwd"),
                      preceding_context=_tail(texts.get(cid)), following_context=_head(res),
                      existing_model_text=args.get("description") or args.get("explanation"),
                      exit_code=_exit_from_text(res), tool="Shell")
    con.close()


# --------------------------------------------------------------------- Grok CLI
@source("grok", "Grok CLI chat histories (~/.grok/sessions/**/chat_history.jsonl)",
        _glob(".grok/sessions/**/chat_history.jsonl"))
def grok(path: Path) -> Iterator[dict]:
    pending: dict[str, dict] = {}
    try:
        cwd = re.sub(r"%([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), path.parent.parent.name)
    except ValueError:
        cwd = None
    with open(path, encoding="utf-8", errors="replace") as handle:
        for n, line in enumerate(handle):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get("type") == "assistant":
                for tc in o.get("tool_calls") or []:
                    name = tc.get("name") or (tc.get("function") or {}).get("name")
                    if name != "run_terminal_command":
                        continue
                    raw = tc.get("arguments") or (tc.get("function") or {}).get("arguments") or "{}"
                    try:
                        a = json.loads(raw) if isinstance(raw, str) else raw
                    except ValueError:
                        continue
                    pending[tc.get("id")] = _record(
                        id=f"grok:{tc.get('id')}", source_file=str(path), source_type="grok",
                        command_raw=a.get("command"), working_directory=a.get("cwd") or cwd,
                        preceding_context=_tail(o.get("content")), existing_model_text=a.get("description"),
                        tool=name, tags=["background"] if a.get("is_background") or a.get("background") else [])
            elif o.get("type") == "tool_result":
                rec = pending.pop(o.get("tool_call_id"), None)
                if rec:
                    text = _text_of(o.get("content"))
                    rec["following_context"] = _head(text)
                    rec["exit_code"] = _exit_from_text(text)
                    yield rec
    yield from pending.values()


# --------------------------------------------------------------------- Human shell history
@source("psreadline", "PowerShell PSReadLine history (human-typed)",
        _glob("AppData/Roaming/Microsoft/Windows/PowerShell/PSReadLine/*_history.txt"))
def psreadline(path: Path) -> Iterator[dict]:
    buf: list[str] = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for n, line in enumerate(handle):
            line = line.rstrip("\r\n")
            if line.endswith("`"):
                buf.append(line[:-1]); continue
            buf.append(line)
            cmd = "\n".join(buf).strip(); buf = []
            if cmd:
                yield _record(id=f"psreadline:{path.name}:{n}", source_file=str(path), source_type="psreadline",
                              shell="powershell", command_raw=cmd, tags=["human_typed"], tool="terminal")


@source("bash-history", "Bash/Zsh history files (human-typed)", _glob(".bash_history", ".zsh_history"))
def bash_history(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8", errors="replace") as handle:
        for n, line in enumerate(handle):
            cmd = re.sub(r"^: \d+:\d+;", "", line.strip())
            if cmd and not cmd.startswith("#"):
                yield _record(id=f"bash-history:{path.name}:{n}", source_file=str(path), source_type="bash-history",
                              shell="bash", command_raw=cmd, tags=["human_typed"], tool="terminal")


# Known locations with no parser yet; listed in the inventory so gaps stay visible.
UNPARSED = {
    "t3": ".t3/dev/state.sqlite",
    "opencode-legacy": ".opencode",
    "opencode-cursor": ".opencode-cursor",
    "opencode2-request-ledger": ".config/opencode/.channels/state/dev/requests.jsonl",
    "ollama-history": ".ollama/history",
}
