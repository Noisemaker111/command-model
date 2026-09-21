"""Heuristic structure for PowerShell, Bash and CMD commands.

Not a shell parser: it splits on top-level separators, recognises executables and
cmdlets, and maps them to coarse action types with their most useful targets.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

PS_VERB = re.compile(r"\b(Get|Set|New|Remove|Start|Stop|Wait|Invoke|Test|Select|Where|ForEach|Sort|Measure|"
                     r"Out|Write|Read|Import|Export|Convert(?:To|From)|Copy|Move|Rename|Add|Clear|Resolve|Split|Join|Format|Group|Expand|Compress|Push|Pop|Register|Unregister|Restart|Update|Install|Uninstall|Enable|Disable)-[A-Z][A-Za-z]+")
PS_HINT = re.compile(r"\$env:|\$_\b|\$PSScriptRoot|\[System\.|\[IO\.|-ErrorAction\b|\bforeach\s*\(|\$null\b|@\{|\|\s*%\s*\{|\bparam\s*\(")
CMD_HINT = re.compile(r"(?i)(^|&\s*)(cmd(\.exe)?\s+/[ck]\b|dir\s+/[a-z]|set\s+\w+=|%\w+%|\bif\s+exist\b|\bcopy\s+/y\b|\bdel\s+/[fqs]\b)")
BASH_HINT = re.compile(r"(\bexport\s+\w+=|\$\{\w+|\bthen\b|\bfi\b|\bdone\b|\besac\b|\|\s*(grep|sed|awk|head|tail|xargs|wc)\b|\b(sudo|chmod|chown|apt(-get)?|brew)\s|\bsource\s|/dev/null|2>&1|\[\[)")

# executable/cmdlet (lowercase) -> action type
ACTIONS: dict[str, str] = {}
def _reg(kind: str, *names: str) -> None:
    for n in names:
        ACTIONS[n.lower()] = kind

_reg("read_file", "cat", "type", "get-content", "gc", "head", "tail", "less", "more", "bat", "nl", "import-csv", "get-filehash", "sha256sum", "md5sum", "od", "xxd", "hexdump", "strings", "jq", "yq")
_reg("list_dir", "ls", "dir", "get-childitem", "gci", "tree", "find", "fd", "du", "stat", "get-item", "gi", "get-itempropertyvalue", "test-path", "resolve-path", "file", "realpath", "readlink", "where", "which", "get-command", "command")
_reg("search", "grep", "rg", "select-string", "sls", "findstr", "ag", "ack", "git-grep")
_reg("write_file", "set-content", "out-file", "add-content", "tee", "tee-object", "new-item", "ni", "touch", "export-csv", "sed", "awk", "perl")
_reg("delete", "rm", "del", "rmdir", "rd", "remove-item", "ri", "erase", "unlink", "shred")
_reg("move_copy", "cp", "copy", "copy-item", "mv", "move", "move-item", "rename-item", "robocopy", "xcopy", "rsync", "ln", "mkdir", "md", "expand-archive", "compress-archive", "tar", "zip", "unzip", "7z")
_reg("process_check", "get-process", "ps", "tasklist", "pgrep", "top", "htop", "get-ciminstance", "get-wmiobject", "wmic", "pidof", "netstat", "get-nettcpconnection", "lsof", "ss", "get-service", "nvidia-smi")
_reg("process_start", "start-process", "saps", "start", "nohup", "invoke-item", "ii", "explorer", "code", "cursor")
_reg("process_stop", "stop-process", "kill", "taskkill", "pkill", "killall", "stop-service", "restart-service")
_reg("wait", "sleep", "start-sleep", "timeout", "wait-process", "wait-job", "wait-event")
_reg("network", "curl", "wget", "invoke-webrequest", "iwr", "invoke-restmethod", "irm", "http", "httpie", "ping", "test-netconnection", "nslookup", "dig", "ssh", "scp", "sftp", "nc", "telnet", "cloudflared", "ngrok")
_reg("git", "git")
_reg("github", "gh")
_reg("package", "npm", "pnpm", "yarn", "bun", "bunx", "npx", "pip", "pip3", "uv", "uvx", "poetry", "pipx", "conda", "cargo", "go", "gem", "bundle", "composer", "dotnet", "nuget", "winget", "choco", "scoop", "apt", "apt-get", "brew", "dnf", "yum", "pacman", "vcpkg")
_reg("build", "make", "cmake", "ninja", "msbuild", "gradle", "gradlew", "mvn", "tsc", "vite", "webpack", "esbuild", "rollup", "gcc", "g++", "clang", "rustc", "javac", "cl", "zig")
_reg("test", "pytest", "jest", "vitest", "mocha", "playwright", "cypress", "ctest", "phpunit", "rspec", "tox", "nox")
_reg("container", "docker", "docker-compose", "podman", "kubectl", "helm", "minikube", "kind", "wsl")
_reg("run_script", "python", "python3", "py", "node", "deno", "ts-node", "tsx", "ruby", "php", "java", "pwsh", "powershell", "bash", "sh", "zsh", "cmd", "invoke-expression", "iex", "&", ".", "ruby", "lua", "Rscript")
_reg("model", "ollama", "llama-server", "llama-cli", "vllm", "huggingface-cli", "hf")
_reg("env", "set-location", "cd", "sl", "pushd", "popd", "push-location", "pop-location", "export", "set", "setx", "source", "env", "printenv", "get-variable", "get-location", "pwd", "whoami", "hostname", "uname", "get-date", "date", "$psversiontable", "systeminfo", "get-computerinfo")
_reg("format", "select-object", "select", "where-object", "where", "?", "foreach-object", "%", "sort-object", "sort", "measure-object", "measure", "format-table", "ft", "format-list", "fl", "out-string", "convertto-json", "convertfrom-json", "group-object", "uniq", "wc", "cut", "tr", "xargs", "column", "out-null", "write-output", "echo", "write-host", "printf", "select-xml", "join-string")
_reg("agent_tool", "opencode", "opencode2", "claude", "codex", "grok", "aider", "gemini")
_reg("registry", "reg", "get-itemproperty", "set-itemproperty", "new-itemproperty")
_reg("database", "sqlite3", "psql", "mysql", "mongosh", "redis-cli", "convex")
_reg("deploy", "vercel", "netlify", "wrangler", "fly", "flyctl", "railway", "firebase", "terraform", "pulumi", "aws", "az", "gcloud")

READ_EXT = re.compile(r"[\w.\-/\\:~]+\.(?:json|jsonl|md|txt|ts|tsx|js|mjs|cjs|py|ps1|psm1|sh|toml|ya?ml|log|csv|xml|html|css|rs|go|java|cs|cpp|c|h|lock|ini|cfg|conf|env|sql|db|sqlite|ndjson|gradle|kt|swift|rb|php|vue|svelte|bat|cmd|zip|gguf|safetensors|png|jpg)\b", re.I)
PROC_NAMES = re.compile(r"(?i)get-process\s+(?:-name\s+)?([\w.*\-]+(?:\s*,\s*[\w.*\-]+)*)")
WINDOWS_PATH = re.compile(r"(?i)\b[a-z]:[\\/][^\s\"'|;,)]*")
QUOTED = re.compile(r"'(?:''|[^'])*'|\"(?:\\.|[^\"\\])*\"")


@dataclass
class Action:
    type: str
    exe: str
    targets: list[str] = field(default_factory=list)
    sub: str | None = None  # git/npm subcommand
    args: list[str] = field(default_factory=list, repr=False)


@dataclass
class Structure:
    shell: str
    actions: list[Action]
    loops: int = 0
    conditionals: int = 0
    pipelines: int = 0
    segments: int = 0
    cwd_changes: list[str] = field(default_factory=list)
    has_heredoc: bool = False
    has_inline_script: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        for a in d["actions"]:
            a.pop("args", None)
        d["action_types"] = sorted({a.type for a in self.actions})
        return d


def detect_shell(command: str, hint: str | None = None) -> str:
    h = (hint or "").lower()
    if "powershell" in h or "pwsh" in h:
        return "powershell"
    if h in ("bash", "sh", "zsh", "git-bash", "wsl"):
        return "bash"
    if h in ("cmd", "cmd.exe"):
        return "cmd"
    if re.match(r"^\s*(powershell|pwsh)(\.exe)?\b", command, re.I):
        return "powershell"
    ps = len(PS_VERB.findall(command)) * 2 + len(PS_HINT.findall(command))
    bash = len(BASH_HINT.findall(command))
    cmd = len(CMD_HINT.findall(command))
    if cmd > max(ps, bash):
        return "cmd"
    if ps > bash:
        return "powershell"
    if bash > 0:
        return "bash"
    return h if h in ("powershell", "bash", "cmd") else "other"


def split_top_level(command: str) -> tuple[list[str], int]:
    """Split on ; && || newlines outside quotes/brackets. Returns (segments, pipe_count)."""
    segs: list[str] = []
    buf: list[str] = []
    depth = 0
    quote: str | None = None
    pipes = 0
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(command[i + 1]); i += 2; continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch; buf.append(ch)
        elif ch in "({[":
            depth += 1; buf.append(ch)
        elif ch in ")}]":
            depth = max(0, depth - 1); buf.append(ch)
        elif depth == 0 and (ch in ";\n" or command.startswith("&&", i) or command.startswith("||", i)):
            segs.append("".join(buf)); buf = []
            if ch in "&|":
                i += 1
        else:
            if ch == "|" and not command.startswith("||", i):
                pipes += 1
            buf.append(ch)
        i += 1
    segs.append("".join(buf))
    return [s.strip() for s in segs if s.strip() and not s.strip().startswith("#")], pipes


def _words(segment: str) -> list[str]:
    return re.findall(r"'(?:''|[^'])*'|\"(?:\\.|[^\"\\])*\"|[^\s|]+", segment)


def _strip(word: str) -> str:
    return word.strip("\"'`()")


HEREDOC = re.compile(r"(<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n)[\s\S]*?\n\s*\2\b")
HERESTRING = re.compile(r"@(['\"])\s*\n[\s\S]*?\n\1@")
CONTROL = re.compile(r"^\s*(?:if|elseif|else|foreach|for|while|do|try|catch|finally|switch|until|function\s+[\w-]+)\b\s*(\([\s\S]*?\))?\s*\{([\s\S]*)\}\s*$", re.I)
REDIRECT = re.compile(r"(?<![0-9&2])>>?\s*(?!&|\$null|/dev/null|nul\b)([^\s;|&<>]+)", re.I)
ASSIGN = re.compile(r"^\s*\$[\w:.\[\]]+\s*[+\-]?=\s*(?!=)")
DOTNET = re.compile(r"^\[[\w.]+\]::(\w+)", re.I)
SKIP_WORDS = {"{", "}", "if", "else", "elif", "fi", "then", "do", "done", "for", "foreach", "while", "try", "catch",
              "finally", "return", "function", "param", "@(", "[", "]", "exit", "break", "continue", "throw", "end",
              "esac", "case", "until", "}", ")", "@{", "begin", "process"}


def strip_bodies(command: str) -> str:
    """Replace heredoc and here-string bodies (script/data text) with placeholders."""
    command = HEREDOC.sub(lambda m: m.group(1) + "<HEREDOC>", command)
    return HERESTRING.sub("'<HERESTRING>'", command)


def _exe_candidates(segment: str) -> list[tuple[str, list[str]]]:
    """Executables in pipeline stages, skipping env-assignments and wrappers."""
    out = []
    for stage in re.split(r"(?<!\|)\|(?!\|)", segment):
        stage = ASSIGN.sub("", stage.strip()).lstrip("{(&. ").strip()
        words = _words(stage)
        while words and (re.match(r"^\w+=", words[0]) or words[0].lower() in ("sudo", "time", "exec", "env", "nohup", "call", "&", "try", "{", "(", "do", "then", "else", "!", "-not")):
            words = words[1:]
        if words:
            exe = _strip(words[0]).rstrip(";,")
            base = re.split(r"[\/]", exe)[-1].lower() if not exe.startswith("[") else exe.lower()
            base = re.sub(r"\.(exe|cmd|bat|ps1)$", "", base)
            if base:
                out.append((base, words[1:]))
    return out


def _flat_segments(command: str, depth: int = 0) -> list[str]:
    segs, _ = split_top_level(command)
    out = []
    for seg in segs:
        m = CONTROL.match(seg)
        if m and depth < 4:
            if m.group(1):
                out += _flat_segments(m.group(1)[1:-1], depth + 1)
            out += _flat_segments(m.group(2), depth + 1)
            continue
        m = re.match(r"^\s*(?:if|elseif|while|foreach|switch)\s*\(([\s\S]*?)\)\s*(.*)$", seg, re.I)
        if m and depth < 4:
            out += _flat_segments(m.group(1), depth + 1) + _flat_segments(m.group(2).strip("{} "), depth + 1)
            continue
        out.append(seg)
    return out


def _targets(kind: str, exe: str, args: list[str], segment: str) -> list[str]:
    cleaned = [_strip(a) for a in args if not a.startswith("-") or kind == "process_check"]
    if kind == "process_check":
        m = PROC_NAMES.search(segment)
        if m:
            return [p.strip() for p in m.group(1).split(",") if p.strip()]
    if kind in ("read_file", "write_file", "delete", "move_copy", "list_dir", "search"):
        files = READ_EXT.findall(segment)
        paths = [p.rstrip("\\/") for p in WINDOWS_PATH.findall(segment)]
        vals = files or paths or [c for c in cleaned if c and not c.startswith("$")][:2]
        return [re.split(r"[\\/]", v)[-1] or v for v in vals][:4]
    if kind == "network":
        urls = re.findall(r"https?://[^\s\"'`)]+|\b(?:localhost|127\.0\.0\.1):\d+[^\s\"'`)]*", segment)
        return [re.sub(r"^https?://", "", u).split("?")[0] for u in urls][:3]
    if kind in ("run_script", "test", "build"):
        files = READ_EXT.findall(segment)
        return [re.split(r"[\\/]", f)[-1] for f in files][:3]
    if kind == "wait":
        m = re.search(r"(\d+(?:\.\d+)?)", " ".join(args))
        return [m.group(1)] if m else []
    return [c for c in cleaned[:2] if c and len(c) < 60]


def analyze(command: str, shell_hint: str | None = None) -> Structure:
    shell = detect_shell(command, shell_hint)
    body = strip_bodies(command)
    _, pipes = split_top_level(body)
    segments = _flat_segments(body)
    lower = body.lower()
    st = Structure(shell=shell, actions=[], pipelines=pipes, segments=len(segments))
    st.loops = len(re.findall(r"\b(for|foreach|while|until)\b\s*[\s(${]", lower)) + lower.count("foreach-object") + len(re.findall(r"\|\s*%\s*\{", lower))
    st.conditionals = len(re.findall(r"\b(if|elif|elseif)\b\s*[\s(\[]", lower))
    st.conditionals += len(re.findall(r"\bcase\b[^\n;]*\bin\b", lower))
    st.conditionals += len(re.findall(r"\bswitch\b(?:\s+-[\w:]+)*\s*\(", lower))
    st.has_heredoc = body != command
    st.has_inline_script = bool(re.search(r"\b(python3?|py|node|bun|deno)\s+(-c|-e|--eval|-)(\s|$)|\bpython3?\s*-\s*<<", command))
    for seg in segments:
        for exe, args in _exe_candidates(seg):
            kind = ACTIONS.get(exe)
            dn = DOTNET.match(exe)
            if dn:
                method = dn.group(1).lower()
                kind = ("read_file" if "read" in method else "write_file" if "write" in method or "append" in method
                        else "list_dir" if method.startswith(("get", "exists", "enumerate")) else "dotnet_call")
                exe = exe.split("(")[0]
            elif kind is None:
                if exe.startswith(("$", "#", "'", '"', "<", "@")) or exe in SKIP_WORDS or not re.match(r"^[\w.\-:]+$", exe):
                    continue
                kind = "powershell_cmdlet" if PS_VERB.fullmatch(exe.title()) else "other"
            if kind == "env" and exe in ("cd", "set-location", "sl", "pushd", "push-location") and args:
                st.cwd_changes.append(_strip(args[-1]))
            sub = None
            if kind in ("git", "github", "package", "container", "model", "agent_tool", "deploy", "database") and args:
                pos = [_strip(x) for x in args if not x.startswith("-")]
                sub = pos[0] if pos else None
                if kind == "package" and sub in ("run", "exec", "x") and len(pos) > 1:
                    sub = f"{sub} {pos[1]}"
                if kind == "package" and sub and re.match(r"^(test|vitest|jest)\b", sub.split()[-1]):
                    kind = "test"
                elif kind == "package" and sub and re.match(r"^(run )?(build|compile|typecheck|tsc|lint|check-types)\b", sub):
                    kind = "build"
                elif kind == "package" and sub and re.match(r"^(run )?(test|check)", sub):
                    kind = "test"
            if kind == "run_script" and re.search(r"\b(pytest|unittest)\b", seg):
                kind = "test"
            redirect = REDIRECT.search(seg)
            if redirect and kind in ("read_file", "format"):
                target = re.split(r"[\\/]", _strip(redirect.group(1)))[-1]
                st.actions.append(Action("write_file", exe, [target]))
                continue
            st.actions.append(Action(kind, exe, _targets(kind, exe, args, seg), sub, [_strip(x) for x in args[:8]]))
    return st


def complexity(st: Structure, command: str) -> str:
    score = len(st.actions) + st.loops * 2 + st.conditionals * 2 + (2 if st.has_inline_script else 0) + (1 if len(command) > 400 else 0) + (2 if len(command) > 1500 else 0)
    return "simple" if score <= 1 else "moderate" if score <= 4 else "complex"
