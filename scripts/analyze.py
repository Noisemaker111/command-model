import json, re, collections, sys, io, os, datetime, statistics
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
D = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
R = [json.loads(l) for l in open(os.path.join(D, 'records.jsonl'), encoding='utf-8')]
TC = json.load(open(os.path.join(D, 'toolcounts.json'), encoding='utf-8'))

# ---------------- model families ----------------
def family(source, model):
    m = (model or 'unknown').lower()
    if 'astra' in m: return 'GPT-6 Astra'
    if 'gpt-5.6-sol' in m: return 'GPT-5.6 Sol'
    if 'gpt-5.6-luna' in m: return 'GPT-5.6 Luna'
    if 'gpt-5.6-terra' in m: return 'GPT-5.6 Terra'
    if 'gpt-5.4-mini' in m or 'gpt-5.3' in m or 'auto-review' in m: return 'GPT other'
    if 'fable-5-1' in m: return 'Claude Fable 5.1'
    if 'fable-5' in m: return 'Claude Fable 5'
    if 'opus-5' in m or m == 'claude-code/opus': return 'Claude Opus 5'
    if 'sonnet-5' in m or m == 'claude-code/sonnet': return 'Claude Sonnet 5'
    if 'opus-4' in m: return 'Claude Opus 4.x'
    if 'haiku' in m: return 'Claude Haiku 4.5'
    if 'sonnet-4' in m: return 'Claude Sonnet 4.x'
    if 'grok' in m: return 'Grok 4.x'
    if 'muse-spark' in m: return 'Muse Spark'
    if 'deepseek' in m: return 'DeepSeek V4'
    if 'glm' in m: return 'GLM 5.3'
    if 'kimi' in m: return 'Kimi K3'
    if 'hy3' in m: return 'HY3'
    if 'x-preview' in m: return 'x-preview-f'
    if 'omen' in m: return 'Omen alpha'
    if 'ox-alpha' in m: return 'Ox alpha'
    if 'gemini' in m: return 'Gemini 3.x'
    if 'big-pickle' in m: return 'Big Pickle'
    if 'longcat' in m: return 'LongCat'
    if 'mimo' in m: return 'MiMo'
    if 'laguna' in m: return 'Laguna'
    if 'gpt-oss' in m: return 'gpt-oss'
    return 'other'

def vendor(fam):
    if fam.startswith('GPT'): return 'OpenAI'
    if fam.startswith('Claude'): return 'Anthropic'
    if fam.startswith('Grok'): return 'xAI'
    if fam in ('Muse Spark',): return 'Meta'
    if fam in ('DeepSeek V4',): return 'DeepSeek'
    if fam in ('GLM 5.3',): return 'Zhipu'
    if fam in ('Kimi K3',): return 'Moonshot'
    if fam in ('Gemini 3.x',): return 'Google'
    return 'other'

# ---------------- host shell per tool ----------------
WINDOWS = sys.platform.startswith('win')
POSIX_HOSTS = {'git-bash', 'bash', 'zsh', 'sh'}
def host_shell(r):
    """Best-effort host shell per harness tool. Windows values come from observed spawn commands
    and error strings in this corpus; on macOS/Linux every harness runs the user's POSIX shell."""
    s, t = r['source'], r['tool']
    if not WINDOWS:
        if s == 'claude-code' and t == 'PowerShell': return 'pwsh7'
        return os.path.basename(os.environ.get('SHELL', 'bash')) or 'bash'
    if s == 'claude-code': return 'git-bash' if t == 'Bash' else 'pwsh7'
    if s == 'codex':
        sp = (r.get('shell_param') or '').lower()
        if 'cmd' in sp: return 'cmd.exe'
        if 'bash' in sp or 'sh' == sp: return 'bash'
        if 'pwsh' in sp or 'powershell' in sp: return 'powershell'
        return 'powershell'  # Codex Windows default
    if s == 'opencode':
        if t == 'shell': return 'cmd.exe'       # observed: cmd-style errors and `&` chains
        return 'powershell5'                    # observed: spawned powershell.EXE -Command (pwsh not resolved)
    if s == 'cursor': return 'powershell'
    return 'unknown'

# ---------------- dialect the model WROTE ----------------
PS_RX = re.compile(r'\b(Get|Set|Select|Remove|New|Test|Out|Write|Invoke|Start|Stop|Copy|Move|Add|Format|Where|ForEach|Measure|Sort|Group|Split|Join|Resolve|Push|Pop|Import|Export|ConvertTo|ConvertFrom|Read|Clear|Expand|Compress|Rename|Wait|Restart|Update|Register|Unregister|Enable|Disable|Send|Receive|Convert|Compare|Tee)-[A-Z][A-Za-z]+\b|\$env:|-LiteralPath|-ErrorAction|-Recurse|\$_\b|\| ?% ?\{|\[System\.|\[IO\.|-eq |-ne |-match |-replace |@\'|@"|Get-ChildItem|\$PSVersionTable|-Force\b|-Raw\b|Out-Null|-join |-split ')
CMD_RX = re.compile(r'(^|[;&|]\s*)(type|dir|findstr|del|rmdir|copy|move|ren|set|where|ver|cls|echo\.)\b|%[A-Za-z_]+%|2>nul\b|\bif exist\b|/s /q|\b& type\b', re.I)
POSIX_RX = re.compile(r'(^|[;&|(]\s*|\bxargs\s+)(cat|head|tail|sed|awk|grep|egrep|ls|wc|cut|sort|uniq|xargs|find|tr|tee|chmod|chown|mkdir|rm|cp|mv|touch|which|pwd|export|source|printf|basename|dirname|realpath|readlink|stat|du|df|date|sleep|true|false|test|nl|od|rev|paste|comm|diff|env|uname|whoami|kill|pkill|pgrep|ps|nohup|timeout|tac|less|more|zcat|curl|wget|sh|bash)\b|2>/dev/null|/dev/null|\$\(|<<-?\s*[\'"]?\w+|\[\[ |\[ -[fdez] |\bfor \w+ in\b|\bthen\b|\bfi\b|\bdone\b|\|\s*head\b|\|\s*tail\b|\|\s*grep\b|\|\s*wc\b|\|\s*sed\b|\|\s*awk\b|\|\s*sort\b|~/|\$HOME|\$\{?[A-Z_]{2,}\}?\b')
NEUTRAL_RX = re.compile(r'^\s*(git|gh|npm|npx|bun|bunx|pnpm|yarn|node|python|python3|py|tsc|tsx|deno|cargo|go|pip|uv|winget|docker|kubectl|rg|fd|jq|sqlite3|code|cursor|opencode|claude|codex)\b')

def dialect(cmd):
    if not cmd: return 'js-only'
    ps = len(PS_RX.findall(cmd)); cm = len(CMD_RX.findall(cmd)); px = len(POSIX_RX.findall(cmd))
    if ps and (px or cm): return 'mixed'
    if cm and px: return 'mixed'
    if ps: return 'powershell'
    if cm: return 'cmd'
    if px: return 'posix'
    if NEUTRAL_RX.match(cmd) or re.match(r'^\s*[\w.-]+(\s|$)', cmd): return 'neutral'
    return 'neutral'

# ---------------- inline interpreter ----------------
INTERP = [
    ('python -c', re.compile(r'\b(python3?|py)\s+-c\b')),
    ('python heredoc/stdin', re.compile(r'\b(python3?|py)\s+-\s*<<|\b(python3?|py)\s+-\s*$|\| ?(python3?|py)\s+-\b', re.M)),
    ('python script/module', re.compile(r'\b(python3?|py)\s+(-m\s+\w|[\w./\\-]+\.py\b)')),
    ('node -e/-p', re.compile(r'\bnode\s+(-e|--eval|-p|--print|--input-type)\b')),
    ('node stdin/heredoc', re.compile(r'\bnode\s+-\s*<<|\bnode\s+-\s*$|\| ?node\s+-\b', re.M)),
    ('node script', re.compile(r'\bnode\s+[\w./\\-]+\.(m?js|cjs)\b')),
    ('bun -e', re.compile(r'\bbun\s+(-e|--eval|-p|--print)\b')),
    ('bun script/run', re.compile(r'\bbun\s+(run\s+|x\s+|[\w./\\-]+\.(ts|tsx|m?js))|\bbunx\b')),
    ('npx/tsx', re.compile(r'\b(npx|tsx)\s+\S')),
    ('pwsh -Command (nested)', re.compile(r'\b(pwsh|powershell)(\.exe)?\s+(-\w+\s+)*-(c|Command|File|NoProfile)\b', re.I)),
    ('bash -c / sh -c', re.compile(r'\b(bash|sh|zsh)\s+(-l?c|-lc)\s')),
    ('cmd /c', re.compile(r'\bcmd(\.exe)?\s+/[cC]\b')),
    ('heredoc', re.compile(r'<<-?\s*[\'"]?\w+[\'"]?')),
    ('PS here-string', re.compile(r'@[\'"]\s*$', re.M)),
    ('Invoke-Expression', re.compile(r'\b(Invoke-Expression|iex)\b')),
    ('jq', re.compile(r'\bjq\b')),
    ('sqlite3', re.compile(r'\bsqlite3\b')),
    ('deno', re.compile(r'\bdeno\s+(eval|run)')),
    ('perl/awk one-liner', re.compile(r'\b(perl\s+-[pne]|awk\s+[\'"])')),
]
def interpreters(cmd):
    if not cmd: return []
    return [n for n, rx in INTERP if rx.search(cmd)]

# ---------------- category by segment ----------------
CAT_RULES = [
    ('write-file', re.compile(r'(^|\s)cat\s*>|<<\s*[\'"]?\w+[\'"]?\s*>|Set-Content|Out-File|Add-Content|\bNew-Item\b[^|]*-ItemType\s+File|WriteAllText|writeFileSync|writeFile\(|open\([^)]*[\'"]w[\'"]|>\s*[\'"]?[\w./\\~-]+\.(md|ts|tsx|js|mjs|json|py|txt|yml|yaml|toml|html|css|ps1|sh|env)\b|\btee\s+(-a\s+)?[\w./]|\bprintf\b[^|]*>\s*\S|\becho\b[^|]*>\s*[\w./]', re.I)),
    ('edit-file', re.compile(r'\bsed\s+-i|perl\s+-p?i|-replace\b[^|]*\|\s*Set-Content|\.replace\([^)]*\)[^|]*write|apply_patch|\bgit apply\b|\bpatch\s+-p|\bnpx?\s+prettier\s+--write|eslint\s+--fix', re.I)),
    ('build/test/check', re.compile(r'\b(tsc|vitest|jest|mocha|playwright|pytest|eslint|prettier --check|biome|cargo (build|test|check|clippy)|go (build|test|vet)|make\b)|\b(bun|npm|pnpm|yarn)\s+(run\s+)?(build|test|check|check-types|typecheck|lint|verify|e2e|ci|compile|tsc)\b|\bbun\s+test\b|--noEmit', re.I)),
    ('run/dev/daemon', re.compile(r'\b(bun|npm|pnpm|yarn)\s+(run\s+)?(dev|start|serve|preview|shoot|daemon)\b|\bnode\s+[\w./\\-]*(server|index|main|app)\.(m?js|ts)|Start-Process|Start-Job|\bnohup\b|\bsetsid\b|&\s*$|\bopencode2?\s+(serve|run|--|\S)|\bclaude\s+(-p|--print)|\bcodex\s+(exec|-)', re.I)),
    ('process-mgmt', re.compile(r'\b(kill|pkill|killall|taskkill|tasklist|Stop-Process|Get-Process|Wait-Process|netstat|Get-NetTCPConnection|lsof|pgrep|ps\s+(aux|-ef|-p)|Test-NetConnection|ss\s+-)\b', re.I)),
    ('git', re.compile(r'(^|[;&|(]\s*)git\s+\w', re.I)),
    ('github (gh)', re.compile(r'(^|[;&|(]\s*)gh\s+\w', re.I)),
    ('package-mgmt', re.compile(r'\b(npm|pnpm|yarn|bun)\s+(i|install|add|remove|uninstall|update|link|publish|ci|outdated|ls|why|pm)\b|\bbun\s+(install|add|pm)\b|\b(pip|pip3|uv)\s+(install|sync|add)|\bwinget\s|\bchoco\s|\bcargo\s+(add|install)|\bnpx?\s+create-|\bnpm\s+view\b|\bnpm\s+pack\b', re.I)),
    ('network/http', re.compile(r'\b(curl|wget|Invoke-WebRequest|Invoke-RestMethod|iwr|irm|http\.get|fetch\()\b', re.I)),
    ('data/json wrangling', re.compile(r'\bjq\b|ConvertFrom-Json|ConvertTo-Json|JSON\.parse|json\.load|import json|sqlite3|\.db\b|SELECT .* FROM', re.I)),
    ('search', re.compile(r'\b(grep|egrep|rg|ag|findstr|Select-String|sls)\b|\bfind\s+[\w./\\~"\']+.*-name|\bfd\b|Get-ChildItem[^|;]*(-Recurse|-Filter|-Include)|\bglob\b', re.I)),
    ('read-file', re.compile(r'(^|[;&|(]\s*)(cat|head|tail|less|more|bat|type|gc|Get-Content|nl|sed\s+-n|awk\s+[\'"]NR|Select-Object\s+-First|Format-Hex|od\s+-c|xxd|Get-Item)\b|\bcat\s+[\w./\\~"\'-]', re.I)),
    ('list/navigate', re.compile(r'(^|[;&|(]\s*)(ls|dir|tree|pwd|Get-Location|Get-ChildItem|gci|Resolve-Path|Test-Path|realpath|stat|du|df|wc\s+-l|Measure-Object|cd|pushd|popd)\b', re.I)),
    ('fs-ops', re.compile(r'(^|[;&|(]\s*)(mkdir|rm|rmdir|cp|mv|touch|ln|chmod|del|copy|move|robocopy|xcopy|Remove-Item|Copy-Item|Move-Item|Rename-Item|New-Item|ri|cpi|mi|Expand-Archive|Compress-Archive|tar|unzip|zip)\b', re.I)),
    ('env/diagnostics', re.compile(r'\b(which|where|where\.exe|Get-Command|--version|-v\b|-V\b|uname|ver\b|whoami|hostname|env\b|printenv|Get-Variable|\$PSVersionTable|node -v|bun --version|echo \$env|echo %)', re.I)),
    ('sleep/wait', re.compile(r'\b(sleep|Start-Sleep|timeout /t|wait)\b', re.I)),
    ('echo/print', re.compile(r'^\s*(echo|Write-Host|Write-Output|printf)\b', re.I)),
]
SEG_SPLIT = re.compile(r'\s*(?:&&|\|\||;|\n|\|)\s*')
def categories(cmd):
    if not cmd: return ['js-only'], 'js-only'
    segs = [s for s in SEG_SPLIT.split(cmd) if s.strip()]
    found = []
    for s in segs:
        c = None
        for name, rx in CAT_RULES:
            if rx.search(s): c = name; break
        found.append(c or 'other')
    whole = None
    for name, rx in CAT_RULES:
        if rx.search(cmd): whole = name; break
    cnt = collections.Counter(found)
    # prefer strong intents if present anywhere in the whole command
    for strong in ('write-file', 'edit-file', 'build/test/check', 'run/dev/daemon', 'process-mgmt', 'package-mgmt', 'github (gh)', 'git'):
        if strong in cnt: return sorted(set(found)), strong
    primary = cnt.most_common(1)[0][0]
    if primary == 'other' and whole: primary = whole
    return sorted(set(found)), primary

# ---------------- complexity ----------------
def complexity(cmd):
    if not cmd: return {'segs': 0, 'pipes': 0, 'len': 0, 'lines': 0, 'bucket': 'js-only'}
    segs = len([s for s in re.split(r'&&|\|\||;|\n', cmd) if s.strip()])
    pipes = cmd.count('|') - cmd.count('||') * 2
    lines = cmd.count('\n') + 1
    L = len(cmd)
    if lines >= 4 or L > 600: b = 'script (4+ lines or >600 chars)'
    elif segs >= 5: b = 'batch (5+ commands)'
    elif segs >= 2: b = 'chain (2-4 commands)'
    else: b = 'single command'
    return {'segs': segs, 'pipes': max(pipes, 0), 'len': L, 'lines': lines, 'bucket': b}

# ---------------- failure cause ----------------
POSIX_TOOLS = set('cat head tail sed awk grep egrep ls wc cut sort uniq xargs find tr tee chmod mkdir rm cp mv touch which pwd export source printf basename dirname realpath stat du df date sleep true false test nl tac less more curl wget sh bash timeout kill pkill pgrep ps nohup env uname whoami diff comm paste rev od xxd file ln'.split())
PS_CMDLETS = re.compile(r'^(Get|Set|Select|Remove|New|Test|Out|Write|Invoke|Start|Stop|Copy|Move|Add|Format|Where|ForEach|Measure|Sort|Group|Resolve|Push|Pop|Import|Export|ConvertTo|ConvertFrom|Read|Clear|Expand|Compress|Rename|Wait)-')
CAUSES = [
    ('not-found', re.compile(r"(?:The term '([^']+)' is not recognized|'([^']+)' is not recognized as an internal or external command|(?:bash|sh|zsh): (?:line \d+: )?([\w./-]+): command not found|([\w.-]+): command not found|CommandNotFoundException|is not recognized as the name of a cmdlet)")),
    ('powershell-syntax', re.compile(r"The token '&&' is not valid|token '\|\|' is not valid|Missing argument in parameter|positional parameter cannot be found|ParserError|Missing closing|Unexpected token .* in expression|The string is missing the terminator|Missing expression after|not valid in this version of|A parameter cannot be found that matches|Cannot bind argument|is not a valid|Missing '\)'|Missing ']'|Unrecognized token in source text")),
    ('cmd-syntax', re.compile(r'was unexpected at this time|The syntax of the command is incorrect')),
    ('bash-syntax', re.compile(r'syntax error near unexpected token|unexpected EOF|here-document at line|syntax error: unexpected|bad substitution|Syntax error:')),
    ('js-error', re.compile(r'ReferenceError|TypeError: |SyntaxError: (?!.*python)|is not defined|Cannot find module|ERR_MODULE_NOT_FOUND|ERR_REQUIRE_ESM|await is only valid|Unexpected identifier|Unexpected end of input|Unexpected token .*(JSON|import|export)|Cannot use import statement|ERR_UNKNOWN_FILE_EXTENSION|error: Script error|UnhandledPromiseRejection')),
    ('python-error', re.compile(r'Traceback \(most recent|ModuleNotFoundError|IndentationError|NameError:|KeyError:|AttributeError:|python: can\'t open file|\bSyntaxError: invalid syntax|unterminated string literal')),
    ('encoding', re.compile(r'UnicodeEncodeError|UnicodeDecodeError|charmap|cp1252|invalid start byte|codec can\'t|\\ufffd|Malformed UTF')),
    ('path-not-found', re.compile(r'No such file or directory|Cannot find path|ENOENT|does not exist|cannot find the (path|file) specified|Could not find a part of the path|PathNotFound|not found in path|Not Found\b')),
    ('permission/lock', re.compile(r'Permission denied|Access is denied|EPERM|EBUSY|EACCES|being used by another process|UnauthorizedAccess|Operation not permitted|cannot remove.*Device or resource busy')),
    ('timeout/abort', re.compile(r'timed out|Timed out|Tool execution aborted|interrupted|Command timed out|was killed|aborted|exceeded.*timeout|Timeout|ETIMEDOUT')),
    ('exec-policy', re.compile(r'running scripts is disabled|execution policy')),
    ('git-error', re.compile(r'\bfatal: |error: pathspec|not a git repository|nothing to commit|CONFLICT|rejected\b.*\(|Your branch is behind|error: failed to push|would be overwritten')),
    ('gh-error', re.compile(r'\bgh: |GraphQL: |HTTP 4\d\d|Could not resolve to a|requires authentication|gh auth')),
    ('package-error', re.compile(r'npm ERR|ELIFECYCLE|ERESOLVE|error: script "|No matching version|Cannot find package|Could not resolve|bun install.*error|EUSAGE|ENOTEMPTY')),
    ('network', re.compile(r'ECONNREFUSED|getaddrinfo|ENOTFOUND|connection refused|fetch failed|Unable to connect|ECONNRESET|remote:|SSL')),
    ('build/test failure', re.compile(r'error TS\d+|\bFAIL\b|Tests? failed|\d+ failed|AssertionError|✗|✖|×|expect\(|Error: Test|\berror\[E\d+\]|Build failed|build error|Type error|TypeScript error|lint error|\d+ errors?\b')),
    ('nonzero/other', re.compile(r'.')),
]
NAME_RX = re.compile(r"(?:The term '([^']+)'|'([^']+)' is not recognized as an internal|(?:bash|sh): (?:line \d+: )?([\w./-]+): command not found|([\w.-]+): command not found)")
def failure_cause(r):
    txt = (r.get('out') or '') + '\n' + (r.get('err') or '')
    for name, rx in CAUSES:
        if name == 'nonzero/other': return name, None
        if rx.search(txt):
            detail = None
            if name == 'not-found':
                m = NAME_RX.search(txt)
                term = next((g for g in (m.groups() if m else ()) if g), None)
                if term:
                    t = term.split('/')[-1].split('\\')[-1]
                    if t in POSIX_TOOLS: detail = 'unix tool in Windows shell: ' + t
                    elif PS_CMDLETS.match(t): detail = 'PowerShell cmdlet in non-PS shell: ' + t
                    else: detail = 'missing program: ' + t
            return name, detail
    return 'nonzero/other', None

HIDDEN_RX = re.compile(r"is not recognized as the name of a cmdlet|is not recognized as an internal or external command|command not found|Traceback \(most recent|syntax error near unexpected|The token '&&' is not valid|ReferenceError|SyntaxError|ModuleNotFoundError|No such file or directory|Cannot find path|was unexpected at this time|UnicodeEncodeError|Missing argument in parameter|positional parameter cannot be found|Access is denied|Permission denied")
def hidden_failure(r):
    if r.get('ok') is not True: return False
    return bool(HIDDEN_RX.search((r.get('out') or '')))

# ---------------- annotate ----------------
def ts_iso(r):
    t = r.get('ts')
    if t is None: return None
    if isinstance(t, (int, float)):
        try: return datetime.datetime.utcfromtimestamp(t / 1000).isoformat()
        except Exception: return None
    return t

for r in R:
    r['family'] = family(r['source'], r['model']); r['vendor'] = vendor(r['family'])
    r['host'] = host_shell(r)
    r['dialect'] = dialect(r.get('cmd'))
    r['interp'] = interpreters(r.get('cmd'))
    r['cats'], r['cat'] = categories(r.get('cmd'))
    r['cx'] = complexity(r.get('cmd'))
    r['iso'] = ts_iso(r)
    r['week'] = r['iso'][:10] if r['iso'] else None
    if r.get('ok') is False:
        r['cause'], r['cause_detail'] = failure_cause(r)
    else:
        r['cause'], r['cause_detail'] = None, None
    r['hidden'] = hidden_failure(r)
    r['mismatch'] = (r['dialect'] == 'posix' and r['host'] in ('powershell', 'powershell5', 'cmd.exe', 'pwsh7')) or (r['dialect'] in ('powershell', 'cmd') and r['host'] in POSIX_HOSTS)

# ---------------- aggregations ----------------
def rate(rs):
    n = len(rs); f = sum(1 for x in rs if x.get('ok') is False); h = sum(1 for x in rs if x.get('hidden'))
    return {'n': n, 'fail': f, 'hidden': h, 'fail_rate': round(f / n, 4) if n else None, 'hidden_rate': round(h / n, 4) if n else None}

def group(rs, key):
    g = collections.defaultdict(list)
    for x in rs: g[key(x)].append(x)
    return g

S = {}
S['generated'] = datetime.datetime.now().isoformat()
S['totals'] = {'records': len(R), 'sessions': len({(r['source'], r['session']) for r in R}),
               'sources': {k: len(v) for k, v in group(R, lambda r: r['source']).items()},
               'first': min(x['iso'] for x in R if x['iso']), 'last': max(x['iso'] for x in R if x['iso'])}

# tool share per family from toolcounts
SHELLISH = {'Bash', 'PowerShell', 'bash', 'shell', 'oc_bash', 'Shell', 'AwaitShell', 'fn:shell_command', 'fn:exec_command', 'jscell:exec_command', 'jscell:shell_command', 'execute'}
JSCELL = {'exec', 'execute'}
fam_tools = collections.defaultdict(collections.Counter)
for t in TC:
    fam = family(t['source'], t['model'])
    name = t['tool']
    if t['source'] == 'codex' and name == 'exec': continue  # the cell itself; count what's inside
    fam_tools[(t['source'], fam)][name] += t['n']
tool_share = []
for (src, fam), c in fam_tools.items():
    total = sum(c.values())
    shell = sum(v for k, v in c.items() if k in SHELLISH)
    js = sum(v for k, v in c.items() if k.startswith('jscell:') or k == 'execute')
    reads = sum(v for k, v in c.items() if k in ('Read', 'read', 'oc_read', 'jscell:read_file', 'Glob', 'glob', 'Grep', 'grep', 'ls', 'oc_ls', 'oc_glob'))
    edits = sum(v for k, v in c.items() if k in ('Edit', 'Write', 'edit', 'write', 'apply_patch', 'patch', 'jscell:apply_patch', 'StrReplace', 'oc_edit', 'oc_write', 'fn:apply_patch'))
    tool_share.append({'source': src, 'family': fam, 'total': total, 'shell': shell, 'js_cell_calls': js, 'dedicated_read_search': reads, 'dedicated_edit': edits,
                       'shell_share': round(shell / total, 4) if total else None, 'top': c.most_common(12)})
tool_share.sort(key=lambda x: -x['total'])
S['tool_share'] = tool_share

# per family stats
per_family = []
for (src, fam), rs in group(R, lambda r: (r['source'], r['family'])).items():
    d = rate(rs)
    d.update({'source': src, 'family': fam, 'vendor': vendor(fam),
              'dialects': {k: rate(v) for k, v in group(rs, lambda r: r['dialect']).items()},
              'interp_share': round(sum(1 for r in rs if r['interp']) / len(rs), 4),
              'js_cell_share': round(sum(1 for r in rs if r.get('via_js_cell')) / len(rs), 4),
              'buckets': {k: rate(v) for k, v in group(rs, lambda r: r['cx']['bucket']).items()},
              'median_len': statistics.median([r['cx']['len'] for r in rs if r['cx']['len']]) if any(r['cx']['len'] for r in rs) else 0,
              'mean_segs': round(statistics.mean([r['cx']['segs'] for r in rs if r['cx']['segs']]), 2) if any(r['cx']['segs'] for r in rs) else 0,
              'mismatch_rate': round(sum(1 for r in rs if r['mismatch']) / len(rs), 4),
              'exit_visible_rate': (round(sum(1 for r in rs if r.get('exit_visible')) / sum(1 for r in rs if 'exit_visible' in r), 4) if any('exit_visible' in r for r in rs) else None),
              'top_causes': collections.Counter(r['cause'] for r in rs if r['cause']).most_common(8),
              'cats': {k: rate(v) for k, v in group(rs, lambda r: r['cat']).items()},
              'sessions': len({r['session'] for r in rs})})
    per_family.append(d)
per_family.sort(key=lambda x: -x['n'])
S['per_family'] = per_family

# global cross tabs
S['by_dialect'] = {k: rate(v) for k, v in group(R, lambda r: r['dialect']).items()}
S['by_host'] = {k: rate(v) for k, v in group(R, lambda r: r['host']).items()}
S['by_dialect_host'] = {f'{k[0]} on {k[1]}': rate(v) for k, v in group(R, lambda r: (r['dialect'], r['host'])).items() if len(v) >= 30}
S['by_interp'] = {k: rate(v) for k, v in group([r for r in R if r['interp']], lambda r: r['interp'][0]).items()}
S['by_interp_family'] = {}
for (fam, it), v in group([r for r in R if r['interp']], lambda r: (r['family'], r['interp'][0])).items():
    if len(v) >= 10: S['by_interp_family'][f'{fam}|{it}'] = rate(v)
S['no_interp'] = rate([r for r in R if not r['interp'] and r['cmd']])
S['by_cat'] = {k: rate(v) for k, v in group(R, lambda r: r['cat']).items()}
S['by_bucket'] = {k: rate(v) for k, v in group(R, lambda r: r['cx']['bucket']).items()}
S['by_cause'] = collections.Counter(r['cause'] for r in R if r['cause']).most_common()
S['by_cause_detail'] = collections.Counter(r['cause_detail'] for r in R if r['cause_detail']).most_common(40)
S['by_cause_family'] = {}
for (fam, c), v in group([r for r in R if r['cause']], lambda r: (r['family'], r['cause'])).items():
    S['by_cause_family'][f'{fam}|{c}'] = len(v)
S['hidden_by_family'] = {k: rate(v) for k, v in group(R, lambda r: r['family']).items()}
S['mismatch'] = {'n': sum(1 for r in R if r['mismatch']), 'fail': rate([r for r in R if r['mismatch']]), 'ok_rate_when_matched': rate([r for r in R if not r['mismatch'] and r['cmd']])}

# category by family (shell used for reading/searching/writing instead of dedicated tools)
S['cat_by_family'] = {}
for (fam, c), v in group(R, lambda r: (r['family'], r['cat'])).items():
    S['cat_by_family'][f'{fam}|{c}'] = rate(v)

# time series (daily)
S['daily'] = {}
for (day, src), v in group([r for r in R if r['week']], lambda r: (r['week'], r['source'])).items():
    S['daily'][f'{day}|{src}'] = rate(v)

# retries / recovery: consecutive shell records per session
def sortkey(r):
    t = r.get('ts')
    if isinstance(t, (int, float)): return t / 1000
    if isinstance(t, str):
        try: return datetime.datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp()
        except Exception: return 0
    return 0
recov = collections.Counter(); recov_by_cause = collections.defaultdict(collections.Counter); identical_retries = 0; retry_examples = []
for (src, sid), rs in group(R, lambda r: (r['source'], r['session'])).items():
    rs = sorted(rs, key=sortkey)
    for i, r in enumerate(rs):
        if r.get('ok') is not False or not r.get('cmd'): continue
        nxt = rs[i + 1] if i + 1 < len(rs) else None
        if not nxt or not nxt.get('cmd'): recov['abandon/other-tool'] += 1; recov_by_cause[r['cause']]['abandon/other-tool'] += 1; continue
        if nxt['cmd'].strip() == r['cmd'].strip():
            kind = 'identical retry'; identical_retries += 1
        elif nxt['dialect'] != r['dialect']: kind = f"switched dialect {r['dialect']}->{nxt['dialect']}"
        elif nxt['tool'] != r['tool']: kind = f"switched tool {r['tool']}->{nxt['tool']}"
        elif (nxt['interp'][:1] or ['none'])[0] != (r['interp'][:1] or ['none'])[0]: kind = f"switched interpreter {(r['interp'][:1] or ['none'])[0]}->{(nxt['interp'][:1] or ['none'])[0]}"
        else: kind = 'rewrote same dialect'
        outcome = 'then ok' if nxt.get('ok') else 'still failing'
        recov[f'{kind} | {outcome}'] += 1
        recov_by_cause[r['cause']][f'{kind} | {outcome}'] += 1
        if len(retry_examples) < 60 and kind != 'identical retry':
            retry_examples.append({'family': r['family'], 'cause': r['cause'], 'detail': r['cause_detail'], 'first': r['cmd'][:300], 'first_out': (r.get('out') or r.get('err') or '')[:260], 'kind': kind, 'second': nxt['cmd'][:300], 'outcome': outcome})
S['recovery'] = recov.most_common(40)
S['recovery_by_cause'] = {k: v.most_common(6) for k, v in recov_by_cause.items()}
S['identical_retries'] = identical_retries
S['retry_examples'] = retry_examples

# examples per category / cause / interp / dialect
def ex(r, n=380):
    return {'family': r['family'], 'source': r['source'], 'tool': r['tool'], 'host': r['host'], 'dialect': r['dialect'], 'cat': r['cat'], 'interp': r['interp'],
            'ok': r.get('ok'), 'exit': r.get('exit'), 'hidden': r.get('hidden'), 'cause': r.get('cause'), 'detail': r.get('cause_detail'),
            'cmd': (r.get('cmd') or r.get('js') or '')[:n], 'out': (r.get('out') or r.get('err') or '')[:260], 'when': (r['iso'] or '')[:10], 'len': r['cx']['len']}
import random
random.seed(7)
def pick(rs, k):
    rs = list(rs); random.shuffle(rs); return [ex(r) for r in rs[:k]]
S['examples'] = {
    'by_cat': {c: pick(v, 5) for c, v in group(R, lambda r: r['cat']).items()},
    'by_cause': {c: pick(v, 8) for c, v in group([r for r in R if r['cause']], lambda r: r['cause']).items()},
    'by_detail': {c: pick(v, 4) for c, v in group([r for r in R if r['cause_detail']], lambda r: r['cause_detail']).items() if len(v) >= 3},
    'by_interp': {c: pick(v, 5) for c, v in group([r for r in R if r['interp']], lambda r: r['interp'][0]).items()},
    'hidden': pick([r for r in R if r['hidden']], 12),
    'mixed': pick([r for r in R if r['dialect'] == 'mixed'], 8),
    'js_only': pick([r for r in R if r['tool'].endswith('(js-only)')], 8),
    'js_cell_batches': [ex(r, 900) for r in sorted([r for r in R if r.get('n_in_cell', 0) >= 3], key=lambda r: -r['n_in_cell'])[:6]],
    'longest': [ex(r, 900) for r in sorted([r for r in R if r.get('cmd')], key=lambda r: -r['cx']['len'])[:8]],
    'by_family_typical': {},
}
for fam, v in group(R, lambda r: r['family']).items():
    S['examples']['by_family_typical'][fam] = pick([r for r in v if r.get('cmd')], 6)

# longest / output blowups
outlens = [r for r in R if r.get('out_len')]
S['output_blowups'] = {'n_over_10k': sum(1 for r in outlens if r['out_len'] > 10000), 'n_over_30k': sum(1 for r in outlens if r['out_len'] > 30000), 'measured': len(outlens)}

# unusual artifacts: files named nul, 2>nul in bash, etc.
S['oddities'] = {
    'nul_redirect_in_bash': len([r for r in R if r['host'] in ('git-bash', 'bash') and r.get('cmd') and re.search(r'2>\s*nul\b', r['cmd'])]),
    'dev_null_in_powershell': len([r for r in R if r['host'] in ('powershell', 'powershell5', 'pwsh7', 'cmd.exe') and r.get('cmd') and '/dev/null' in r['cmd']]),
    'and_and_on_ps5': len([r for r in R if r['host'] == 'powershell5' and r.get('cmd') and '&&' in r['cmd']]),
    'head_in_ps': len([r for r in R if r['host'] in ('powershell', 'powershell5', 'pwsh7') and r.get('cmd') and re.search(r'\|\s*head\b', r['cmd'])]),
    'cat_in_ps': len([r for r in R if r['host'] in ('powershell', 'powershell5', 'pwsh7', 'cmd.exe') and r.get('cmd') and re.search(r'(^|[;&|]\s*)cat\s', r['cmd'])]),
    'dynamic_cmd_in_js': len([r for r in R if r.get('dynamic')]),
    'r_output_only_hides_exit': len([r for r in R if r['source'] == 'codex' and 'exit_visible' in r and not r['exit_visible']]),
    'backgrounded_yield': len([r for r in R if r.get('backgrounded')]),
    'multi_cmd_cells': len([r for r in R if r.get('n_in_cell', 0) >= 2 and r.get('idx_in_cell') == 0]),
}

# ---------------- what embedded scripts do ----------------
PURPOSE = [
    ('json parse/transform', re.compile(r'import json|json\.(load|dump)|JSON\.(parse|stringify)|ConvertFrom-Json|ConvertTo-Json')),
    ('file rewrite/patch', re.compile(r'open\([^)]*[\'"][wa]|\.write\(|writeFileSync|writeFile\(|Set-Content|Out-File|re\.sub\([^)]*\)\s*\n?.*write|\.replace\([^)]*\)[\s\S]{0,200}write')),
    ('regex search/extract', re.compile(r'\bimport re\b|re\.(search|findall|sub|match|finditer)|new RegExp|\.match\(/|/[gmi]+\)|Select-String')),
    ('sqlite/db', re.compile(r'sqlite3|\.execute\(|SELECT |better-sqlite|Database\(')),
    ('fs walk/glob', re.compile(r'os\.walk|glob\.glob|import glob|readdirSync|fs\.readdir|Get-ChildItem -Recurse|pathlib|os\.listdir')),
    ('http/api', re.compile(r'requests\.|urllib|fetch\(|http\.request|Invoke-RestMethod|axios')),
    ('read & print file', re.compile(r'open\([^)]*\)\.read\(\)|readFileSync|Get-Content|\.read\(\)|print\(open')),
    ('stats/count/aggregate', re.compile(r'Counter\(|collections|statistics|\.reduce\(|Measure-Object|Group-Object|sum\(|len\(')),
    ('process/exec', re.compile(r'subprocess|child_process|execSync|spawn\(|os\.system|Start-Process')),
]
def purpose(cmd):
    if not cmd: return []
    return [n for n, rx in PURPOSE if rx.search(cmd)]
for r in R:
    r['purpose'] = purpose(r.get('cmd')) if r['interp'] else []
S['interp_purpose'] = {}
for (fam, it), v in group([r for r in R if r['interp']], lambda r: (r['family'], r['interp'][0])).items():
    if len(v) < 8: continue
    S['interp_purpose'][f'{fam}|{it}'] = {'n': len(v), 'purposes': collections.Counter(p for r in v for p in r['purpose']).most_common(8), 'fail_rate': rate(v)['fail_rate'], 'median_len': statistics.median([r['cx']['len'] for r in v])}
S['interp_purpose_global'] = collections.Counter(p for r in R if r['interp'] for p in r['purpose']).most_common()
S['interp_by_family'] = {}
for fam, v in group(R, lambda r: r['family']).items():
    withi = [r for r in v if r['interp']]
    S['interp_by_family'][fam] = {'n': len(v), 'with_interp': len(withi), 'share': round(len(withi)/len(v),4), 'kinds': collections.Counter(r['interp'][0] for r in withi).most_common(8),
                                  'fail_with': rate(withi)['fail_rate'], 'fail_without': rate([r for r in v if not r['interp'] and r['cmd']])['fail_rate']}
S['examples']['interp_purpose'] = {p: pick([r for r in R if p in r['purpose']], 4) for p, _ in PURPOSE}

json.dump(S, open(os.path.join(D, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
with open(os.path.join(D, 'records_annotated.jsonl'), 'w', encoding='utf-8') as w:
    for r in R: w.write(json.dumps(r, ensure_ascii=False, default=str) + '\n')
print(json.dumps(S['totals'], indent=1))
print('dialect', S['by_dialect'])
print('host', S['by_host'])
print('interp', S['by_interp'])
print('bucket', S['by_bucket'])
print('cause', S['by_cause'])
print('detail', S['by_cause_detail'][:15])
print('mismatch', S['mismatch'])
print('oddities', S['oddities'])
print('recovery', S['recovery'][:15])
for f in S['per_family'][:14]:
    print(f['source'], f['family'], f['n'], 'fail', f['fail_rate'], 'hidden', f['hidden_rate'], 'interp', f['interp_share'], 'mismatch', f['mismatch_rate'], 'exitvis', f['exit_visible_rate'], f['top_causes'][:4])
