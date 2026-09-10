import json, glob, os, re, sqlite3, sys, collections, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
HOME = os.path.expanduser('~')
OUT = sys.argv[1]
recs = []
toolcounts = collections.Counter()   # (source, model, tool) -> n
HEAD = 700

def head(s, n=HEAD):
    if s is None: return ''
    if not isinstance(s, str): s = json.dumps(s)
    return s[:n]

# ---------- JS cell parsing (Codex exec / OpenCode execute) ----------
def scan_calls(js):
    """yield (toolname, argtext) for tools.NAME( ... ) with balanced parens, string-aware"""
    out = []
    for m in re.finditer(r'tools\.([A-Za-z_][\w]*)\s*\(', js):
        name = m.group(1); i = m.end(); depth = 1; j = i; n = len(js)
        q = None
        while j < n and depth > 0:
            ch = js[j]
            if q:
                if ch == '\\': j += 2; continue
                if ch == q: q = None
            else:
                if ch in '"\'`': q = ch
                elif ch in '([{': depth += 1
                elif ch in ')]}': depth -= 1
            j += 1
        out.append((name, js[i:j-1].strip()))
    return out

STR = r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'|`((?:[^`\\]|\\.)*)`'
def js_str(m):
    if m.group(1) is not None:
        try: return json.loads('"' + m.group(1) + '"')
        except Exception: return m.group(1)
    if m.group(2) is not None: return m.group(2).replace("\\'", "'")
    return m.group(3)

def parse_args(argtext):
    """return dict-ish of interesting fields from a JS object literal"""
    d = {}
    try:
        o = json.loads(argtext)
        if isinstance(o, dict): return o
    except Exception: pass
    for key in ('cmd', 'command', 'shell', 'workdir', 'yield_time_ms', 'timeout_ms', 'code'):
        m = re.search(r'(?:^|[{,\s])["\']?' + key + r'["\']?\s*:\s*(' + STR + ')', argtext)
        if m:
            d[key] = js_str(re.match(STR, m.group(1)))
        elif re.search(r'(?:^|[{,\s])' + key + r'\s*(?:,|})', argtext):
            d[key] = None; d[key + '_dynamic'] = True
    if re.search(r'(?:^|[{,\s])["\']?(cmd|command)["\']?\s*:\s*[A-Za-z_$]', argtext) or re.search(r'\$\{', argtext):
        d['_dynamic'] = True
    return d

SHELLISH = {'exec_command', 'shell_command', 'shell', 'bash', 'oc_bash'}

def cell_records(js, base):
    """turn one JS cell into shell records (+ counts of every tools.* call)."""
    calls = scan_calls(js)
    shell = []
    for name, argtext in calls:
        toolcounts[(base['source'], base['model'], 'jscell:' + name)] += 1
        if name in SHELLISH:
            a = parse_args(argtext)
            cmd = a.get('cmd') if a.get('cmd') is not None else a.get('command')
            shell.append({'cmd': cmd, 'shell_param': a.get('shell'), 'workdir': a.get('workdir'),
                          'dynamic': bool(a.get('_dynamic') or a.get('cmd_dynamic') or a.get('command_dynamic')),
                          'yield_ms': a.get('yield_time_ms')})
    return calls, shell

def exit_codes_from_output(txt):
    return [int(x) for x in re.findall(r'"exit_code"\s*:\s*(-?\d+)', txt)]

# ---------- CODEX ----------
def do_codex():
    files = glob.glob(HOME + '/.codex/sessions/**/*.jsonl', recursive=True) + glob.glob(HOME + '/.codex/archived_sessions/**/*.jsonl', recursive=True)
    seen_calls = set()
    for f in files:
        sid = os.path.basename(f)[:-6]
        turn_model = {}; meta = {}
        pending = {}  # call_id -> record stub
        try:
            lines = open(f, encoding='utf-8', errors='replace').read().splitlines()
        except Exception as e:
            print('skip', f, e); continue
        for line in lines:
            try: o = json.loads(line)
            except Exception: continue
            t = o.get('type'); p = o.get('payload') or {}
            ts = o.get('timestamp')
            if t == 'session_meta':
                meta = {'cwd': p.get('cwd'), 'originator': p.get('originator'), 'cli': p.get('cli_version')}
            elif t == 'turn_context':
                turn_model[p.get('turn_id')] = p.get('model')
            elif t == 'response_item':
                pt = p.get('type')
                if pt in ('custom_tool_call', 'function_call'):
                    cid = p.get('call_id')
                    if cid in seen_calls: continue
                    seen_calls.add(cid)
                    tid = (p.get('internal_chat_message_metadata_passthrough') or {}).get('turn_id')
                    model = turn_model.get(tid) or (list(turn_model.values())[-1] if turn_model else None)
                    base = {'source': 'codex', 'model': model, 'session': sid, 'ts': ts, 'cwd': meta.get('cwd'), 'originator': meta.get('originator')}
                    name = p.get('name')
                    toolcounts[('codex', model, ('exec' if pt == 'custom_tool_call' else 'fn:') + ('' if pt == 'custom_tool_call' else name))] += 1
                    if pt == 'custom_tool_call' and name == 'exec':
                        js = p.get('input') or ''
                        calls, shell = cell_records(js, base)
                        pending[cid] = dict(base, kind='jscell', js=js, calls=[c[0] for c in calls], shell=shell)
                    elif pt == 'function_call' and name in ('shell_command', 'exec_command'):
                        try: a = json.loads(p.get('arguments') or '{}')
                        except Exception: a = {}
                        pending[cid] = dict(base, kind='fn', tool=name, shell=[{'cmd': a.get('cmd') or a.get('command'), 'shell_param': a.get('shell'), 'workdir': a.get('workdir'), 'dynamic': False, 'yield_ms': a.get('yield_time_ms')}], js=None, calls=[name])
                elif pt in ('custom_tool_call_output', 'function_call_output'):
                    cid = p.get('call_id'); stub = pending.pop(cid, None)
                    if not stub: continue
                    outp = p.get('output')
                    if isinstance(outp, list): txt = '\n'.join(x.get('text', '') for x in outp if isinstance(x, dict))
                    else: txt = str(outp or '')
                    failed = txt.startswith('Script failed') or txt.startswith('Script error')
                    codes = exit_codes_from_output(txt)
                    wall = re.search(r'Wall time:? ([\d.]+)', txt)
                    emit_codex(stub, txt, failed, codes, wall.group(1) if wall else None)
        # unmatched pending (no output recorded)
        for cid, stub in pending.items():
            emit_codex(stub, '', None, [], None, unmatched=True)

def emit_codex(stub, txt, failed, codes, wall, unmatched=False):
    shell = stub['shell']
    if stub['kind'] == 'jscell' and not shell:
        # a pure-JS cell (no shell call): record it as a js-only action
        recs.append({'source': 'codex', 'model': stub['model'], 'session': stub['session'], 'ts': stub['ts'], 'cwd': stub['cwd'],
                     'tool': 'exec(js-only)', 'via_js_cell': True, 'js_tools': stub['calls'], 'cmd': None, 'js': head(stub['js'], 1200),
                     'shell_param': None, 'dynamic': False, 'ok': (None if unmatched else (not failed)), 'exit': None,
                     'out': head(txt), 'wall': wall, 'unmatched': unmatched})
        return
    for i, s in enumerate(shell):
        code = codes[i] if i < len(codes) and len(codes) == len(shell) else (codes[0] if len(codes) == 1 and len(shell) == 1 else None)
        if unmatched: ok = None
        elif failed: ok = False
        elif code is not None: ok = (code == 0)
        else: ok = True  # script completed; exit code not surfaced by the model
        recs.append({'source': 'codex', 'model': stub['model'], 'session': stub['session'], 'ts': stub['ts'], 'cwd': stub['cwd'],
                     'tool': ('exec>' + 'exec_command' if stub['kind'] == 'jscell' else stub['tool']), 'via_js_cell': stub['kind'] == 'jscell',
                     'js_tools': stub['calls'], 'cmd': s['cmd'], 'js': head(stub['js'], 1200) if stub['kind'] == 'jscell' else None,
                     'shell_param': s['shell_param'], 'workdir': s['workdir'], 'dynamic': s['dynamic'], 'yield_ms': s['yield_ms'],
                     'ok': ok, 'exit': code, 'exit_visible': code is not None, 'script_failed': failed,
                     'out': head(txt), 'wall': wall, 'unmatched': unmatched, 'n_in_cell': len(shell), 'idx_in_cell': i,
                     'backgrounded': ('"session_id"' in txt and code is None)})

# ---------- CLAUDE CODE ----------
def do_claude():
    files = glob.glob(HOME + '/.claude/projects/**/*.jsonl', recursive=True)
    seen = set()
    for f in files:
        sid = os.path.basename(f)[:-6]
        proj = f.split('projects')[1].split(os.sep)[1] if 'projects' in f else ''
        pending = {}
        try: instructed = 'Do your work through the Bash tool' in open(f, encoding='utf-8', errors='replace').read()
        except Exception: instructed = False
        for line in open(f, encoding='utf-8', errors='replace'):
            try: o = json.loads(line)
            except Exception: continue
            m = o.get('message')
            if not isinstance(m, dict): continue
            cont = m.get('content')
            if not isinstance(cont, list): continue
            if o.get('type') == 'assistant':
                model = m.get('model')
                for b in cont:
                    if not isinstance(b, dict) or b.get('type') != 'tool_use': continue
                    tid = b.get('id')
                    if tid in seen: continue
                    seen.add(tid)
                    name = b.get('name')
                    toolcounts[('claude-code', model, name)] += 1
                    if name in ('Bash', 'PowerShell'):
                        inp = b.get('input') or {}
                        pending[tid] = {'source': 'claude-code', 'model': model, 'session': sid, 'project': proj, 'ts': o.get('timestamp'), 'cwd': o.get('cwd'),
                                        'tool': name, 'via_js_cell': False, 'cmd': inp.get('command'), 'desc': inp.get('description'),
                                        'sidechain': bool(o.get('isSidechain')), 'bg': bool(inp.get('run_in_background')), 'timeout': inp.get('timeout'), 'instructed': instructed}
            elif o.get('type') == 'user':
                for b in cont:
                    if not isinstance(b, dict) or b.get('type') != 'tool_result': continue
                    stub = pending.pop(b.get('tool_use_id'), None)
                    if not stub: continue
                    cc = b.get('content')
                    txt = cc if isinstance(cc, str) else '\n'.join(x.get('text', '') for x in cc if isinstance(x, dict) and x.get('type') == 'text') if isinstance(cc, list) else ''
                    err = bool(b.get('is_error'))
                    mcode = re.match(r'Exit code (\d+)', txt or '')
                    code = int(mcode.group(1)) if mcode else (0 if not err else None)
                    tur = o.get('toolUseResult') or {}
                    interrupted = bool(tur.get('interrupted')) if isinstance(tur, dict) else False
                    stub.update({'ok': (not err) and not interrupted, 'exit': code, 'out': head(txt), 'is_error': err, 'interrupted': interrupted,
                                 'out_len': len(txt or '')})
                    recs.append(stub)
        for tid, stub in pending.items():
            stub.update({'ok': None, 'exit': None, 'out': '', 'unmatched': True}); recs.append(stub)

# ---------- OPENCODE ----------
def oc_tool_record(part, model, sid, cwd, source_tag):
    name = part.get('tool') or part.get('name')
    st = part.get('state') or {}
    toolcounts[('opencode', model, name)] += 1
    inp = st.get('input') or {}
    status = st.get('status')
    tm = st.get('time') or part.get('time') or {}
    start = tm.get('start') or tm.get('created'); end = tm.get('end') or tm.get('completed')
    ts = start
    err = st.get('error')
    if isinstance(err, dict): err = err.get('message')
    content = st.get('content')
    txt = ''
    if isinstance(content, list): txt = '\n'.join(x.get('text', '') for x in content if isinstance(x, dict))
    elif isinstance(st.get('output'), str): txt = st.get('output')
    meta = st.get('metadata') or {}
    base = {'source': 'opencode', 'model': model, 'session': sid, 'ts': ts, 'cwd': inp.get('workdir') or cwd, 'callid': part.get('callID') or part.get('id'), 'store': source_tag,
            'dur_ms': (end - start) if (isinstance(start, (int, float)) and isinstance(end, (int, float))) else None}
    if name in ('bash', 'shell', 'oc_bash'):
        code = meta.get('exit')
        if code is None:
            mm = re.search(r'\[Exit code: (-?\d+)\]', txt or '') or re.search(r'Exit code: (-?\d+)', txt or '')
            if mm: code = int(mm.group(1))
        ok = (status == 'completed') and (code in (None, 0))
        recs.append(dict(base, tool=name, via_js_cell=False, cmd=inp.get('command'), desc=inp.get('description'), timeout=inp.get('timeout'),
                         ok=ok, exit=code, status=status, err=head(err), out=head(txt), interrupted=bool(meta.get('interrupted')) or (err == 'Tool execution aborted'),
                         out_len=len(txt or '')))
    elif name == 'execute':
        js = inp.get('code') or ''
        calls, shell = cell_records(js, {'source': 'opencode', 'model': model})
        failed = status == 'error'
        codes = exit_codes_from_output(txt or '')
        if not shell:
            recs.append(dict(base, tool='execute(js-only)', via_js_cell=True, js_tools=[c[0] for c in calls], cmd=None, js=head(js, 1200), ok=(not failed), exit=None, status=status, err=head(err), out=head(txt)))
        for i, s in enumerate(shell):
            code = codes[i] if len(codes) == len(shell) else None
            recs.append(dict(base, tool='execute>' + 'shell', via_js_cell=True, js_tools=[c[0] for c in calls], cmd=s['cmd'], js=head(js, 1200), dynamic=s['dynamic'],
                             ok=(not failed) and code in (None, 0), exit=code, exit_visible=code is not None, status=status, err=head(err), out=head(txt), n_in_cell=len(shell), idx_in_cell=i))

def do_opencode():
    db = HOME + '/.local/share/opencode/opencode.db'
    if not os.path.exists(db): print('opencode db not found'); return
    con = sqlite3.connect('file:' + db.replace('\\', '/') + '?mode=ro', uri=True)
    cur = con.cursor()
    sess_dir = {}
    for t in ('session', 'session_v2'):
        for (i, d) in cur.execute(f'select id, directory from {t}'): sess_dir[i] = d
    seen = set()
    # v2
    msg_model = {}
    for (mid, sid, d) in cur.execute("select id, session_id, data from session_message where type='assistant'"):
        try: o = json.loads(d)
        except Exception: continue
        mm = o.get('model') or {}
        model = (mm.get('providerID') or '') + '/' + (mm.get('id') or mm.get('modelID') or '')
        msg_model[mid] = model
        for part in o.get('content') or []:
            if not isinstance(part, dict) or part.get('type') != 'tool': continue
            key = part.get('id') or part.get('callID')
            if key in seen: continue
            seen.add(key)
            oc_tool_record(part, model, sid, sess_dir.get(sid), 'v2')
    # v1
    for (mid, sid, d) in cur.execute("select id, session_id, data from message"):
        try: o = json.loads(d)
        except Exception: continue
        if o.get('role') == 'assistant':
            msg_model[mid] = (o.get('providerID') or '') + '/' + (o.get('modelID') or '')
    for (pid, mid, sid, d) in cur.execute("select id, message_id, session_id, data from part"):
        try: part = json.loads(d)
        except Exception: continue
        if part.get('type') != 'tool': continue
        key = part.get('callID') or pid
        if key in seen: continue
        seen.add(key)
        oc_tool_record(part, msg_model.get(mid, 'unknown'), sid, sess_dir.get(sid), 'v1')

# ---------- CURSOR ----------
def do_cursor():
    for f in glob.glob(HOME + '/.cursor/chats/*/*/store.db'):
        sid = f.split(os.sep)[-2]
        try: meta = json.load(open(os.path.join(os.path.dirname(f), 'meta.json')))
        except Exception: meta = {}
        con = sqlite3.connect('file:' + f + '?mode=ro', uri=True)
        model = None; calls = {}; results = {}
        rows = list(con.execute('select id, data from blobs'))
        for (i, d) in rows:
            try: o = json.loads(d)
            except Exception: continue
            if not isinstance(o, dict): continue
            r = o.get('role'); cont = o.get('content')
            if r == 'system' and isinstance(cont, str):
                m = re.search(r'powered by (.+?)\. ', cont); model = m.group(1) if m else model
            if r == 'assistant' and isinstance(cont, list):
                for p in cont:
                    if p.get('type') == 'tool-call': calls[p.get('toolCallId')] = p
            if r == 'tool' and isinstance(cont, list):
                for p in cont:
                    if p.get('type') == 'tool-result': results[p.get('toolCallId')] = p
        for cid, p in calls.items():
            name = p.get('toolName')
            toolcounts[('cursor', model, name)] += 1
            if name in ('Shell', 'AwaitShell'):
                res = results.get(cid, {}); rtxt = res.get('result')
                if not isinstance(rtxt, str): rtxt = json.dumps(rtxt) if rtxt is not None else ''
                mcode = re.search(r'Exit code: (-?\d+)', rtxt)
                code = int(mcode.group(1)) if mcode else None
                args = p.get('args') or {}
                recs.append({'source': 'cursor', 'model': model, 'session': sid, 'ts': meta.get('createdAtMs'), 'cwd': meta.get('cwd'), 'tool': name, 'via_js_cell': False,
                             'cmd': args.get('command') if name == 'Shell' else None, 'ok': (code == 0) if code is not None else None, 'exit': code, 'out': head(rtxt), 'out_len': len(rtxt)})

for fn in (do_codex, do_claude, do_opencode, do_cursor):
    n0 = len(recs)
    try: fn()
    except Exception as e: print(fn.__name__, 'skipped:', type(e).__name__, str(e)[:200])
    print(fn.__name__, len(recs) - n0, 'records')
if not recs:
    print('No transcripts found. Looked in ~/.codex/sessions, ~/.claude/projects, ~/.local/share/opencode/opencode.db, ~/.cursor/chats'); sys.exit(1)

with open(os.path.join(OUT, 'records.jsonl'), 'w', encoding='utf-8') as w:
    for r in recs: w.write(json.dumps(r, ensure_ascii=False) + '\n')
with open(os.path.join(OUT, 'toolcounts.json'), 'w', encoding='utf-8') as w:
    json.dump([{'source': k[0], 'model': k[1], 'tool': k[2], 'n': v} for k, v in toolcounts.items()], w, ensure_ascii=False, indent=0)
print('total', len(recs))
