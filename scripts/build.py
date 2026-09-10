import json, os, collections, random, statistics, re, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
SCRIPT = os.path.dirname(os.path.abspath(__file__))
D = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else SCRIPT
R = [json.loads(l) for l in open(os.path.join(D, 'records_annotated.jsonl'), encoding='utf-8')]
S = json.load(open(os.path.join(D, 'summary.json'), encoding='utf-8'))
TC = json.load(open(os.path.join(D, 'toolcounts.json'), encoding='utf-8'))
SC = json.load(open(os.path.join(D, 'scratch.json'), encoding='utf-8'))
random.seed(11)

MIN_FAM = 200
fam_n = collections.Counter(r['family'] for r in R)
FAMS = [f for f, n in fam_n.most_common() if n >= MIN_FAM]
def famkey(f): return f if f in FAMS else 'Other models'
for r in R: r['fam'] = famkey(r['family'])
FAMS = FAMS + ['Other models']
VENDOR = {}
for r in R: VENDOR.setdefault(r['fam'], r['vendor'] if r['fam'] != 'Other models' else 'other')

def pct_s(x): return f'{x*100:.0f}%'
def rate(rs):
    n = len(rs); f = sum(1 for x in rs if x.get('ok') is False); h = sum(1 for x in rs if x.get('hidden'))
    return {'n': n, 'fail': f, 'hidden': h, 'fr': round(f / n, 4) if n else None, 'hr': round(h / n, 4) if n else None}
def group(rs, key):
    g = collections.defaultdict(list)
    for x in rs: g[key(x)].append(x)
    return g

data = {}
data['generated'] = S['generated'][:16]
data['totals'] = {'records': len(R), 'sessions': len({(r['source'], r['session']) for r in R}), 'first': S['totals']['first'][:10], 'last': S['totals']['last'][:10],
                  'sources': collections.Counter(r['source'] for r in R), 'models': len({(r['source'], r['model']) for r in R}),
                  'fail': sum(1 for r in R if r.get('ok') is False), 'hidden': sum(1 for r in R if r.get('hidden')),
                  'js_cell': sum(1 for r in R if r.get('via_js_cell')), 'with_interp': sum(1 for r in R if r.get('interp'))}
WINDOWS = sys.platform.startswith('win')
USER_SHELL = os.path.basename(os.environ.get('SHELL', 'bash')) or 'bash'
SRC_META = {
    'codex': {'label': 'Codex (desktop + CLI)', 'tool': 'exec JS cell → tools.exec_command / shell_command', 'host': 'PowerShell (cmd.exe when shell:"cmd.exe")' if WINDOWS else USER_SHELL, 'path': '~/.codex/sessions/**/*.jsonl'},
    'claude-code': {'label': 'Claude Code', 'tool': 'Bash tool · PowerShell tool', 'host': 'Git Bash / pwsh 7' if WINDOWS else USER_SHELL, 'path': '~/.claude/projects/**/*.jsonl'},
    'opencode': {'label': 'OpenCode (v1 + v2 DB)', 'tool': 'bash tool · shell tool · execute JS cell', 'host': 'Windows PowerShell 5.1 / cmd.exe (observed)' if WINDOWS else USER_SHELL, 'path': '~/.local/share/opencode/opencode.db'},
    'cursor': {'label': 'Cursor CLI', 'tool': 'Shell tool', 'host': 'PowerShell (temp .ps1)' if WINDOWS else USER_SHELL, 'path': '~/.cursor/chats/*/*/store.db'},
}
OUT_DIR = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else D
NO_GALLERY = '--no-gallery' in sys.argv
POSTS = json.load(open(os.path.join(OUT_DIR, 'posts.json'), encoding='utf-8')) if os.path.exists(os.path.join(OUT_DIR, 'posts.json')) else None
data['sources'] = []
for src, rs in group(R, lambda r: r['source']).items():
    fams = collections.Counter(r['fam'] for r in rs)
    data["sources"].append(dict(SRC_META[src], key=src, sessions=len({r['session'] for r in rs}), first=min(r['iso'] for r in rs if r['iso'])[:10], last=max(r['iso'] for r in rs if r['iso'])[:10], families=fams.most_common(6), **rate(rs)))
data['sources'].sort(key=lambda x: -x['n'])

# per family
data['families'] = []
INSTRUCTED = {}
for fam in FAMS:
    rs = [r for r in R if r['fam'] == fam and r['source'] == 'claude-code']
    if rs and sum(1 for r in rs if r.get('instructed')) / len(rs) >= 0.8:
        INSTRUCTED[fam] = f'{pct_s(sum(1 for r in rs if r.get("instructed")) / len(rs))} of this model\'s Claude Code shell calls ran under an auto-mode instruction to work through Bash; its share is instructed, not chosen'
for fam in FAMS:
    rs = [r for r in R if r['fam'] == fam]
    if not rs: continue
    srcs = collections.Counter(r['source'] for r in rs)
    withi = [r for r in rs if r['interp']]
    ev = [r for r in rs if 'exit_visible' in r]
    cats = {k: len(v) for k, v in group(rs, lambda r: r['cat']).items()}
    data['families'].append({
        'fam': fam, 'vendor': VENDOR[fam], 'sources': srcs.most_common(), 'models': sorted({r['model'] or '?' for r in rs})[:8], 'sessions': len({r['session'] for r in rs}),
        **rate(rs), 'js_cell': round(sum(1 for r in rs if r.get('via_js_cell')) / len(rs), 4),
        'interp_share': round(len(withi) / len(rs), 4), 'interp_kinds': collections.Counter(r['interp'][0] for r in withi).most_common(6),
        'fail_with_interp': rate(withi)['fr'], 'fail_without': rate([r for r in rs if not r['interp'] and r['cmd']])['fr'],
        'purposes': collections.Counter(p for r in withi for p in r.get('purpose', [])).most_common(6),
        'dialects': {k: rate(v) for k, v in group(rs, lambda r: r['dialect']).items()},
        'hosts': {k: len(v) for k, v in group(rs, lambda r: r['host']).items()},
        'buckets': {k: rate(v) for k, v in group(rs, lambda r: r['cx']['bucket']).items()},
        'median_len': statistics.median([r['cx']['len'] for r in rs if r['cx']['len']]) if any(r['cx']['len'] for r in rs) else 0,
        'mean_segs': round(statistics.mean([r['cx']['segs'] for r in rs if r['cx']['segs']]), 1) if any(r['cx']['segs'] for r in rs) else 0,
        'mismatch': round(sum(1 for r in rs if r['mismatch']) / len(rs), 4),
        'exit_visible': round(sum(1 for r in ev if r['exit_visible']) / len(ev), 4) if ev else None,
        'causes': collections.Counter(r['cause'] for r in rs if r['cause']).most_common(8),
        'cats': cats, 'instructed': INSTRUCTED.get(fam),
        'scratch': SC['by_family'].get(fam, []), 'scratch_temp_share': SC['temp_share'].get(fam),
    })

# tool share per family (from toolcounts) merged across sources
def fam_of_tc(t):
    m = (t['model'] or '').lower()
    for k, v in [('astra', 'GPT-6 Astra'), ('gpt-5.6-sol', 'GPT-5.6 Sol'), ('gpt-5.6-luna', 'GPT-5.6 Luna'), ('gpt-5.6-terra', 'GPT-5.6 Terra'), ('fable-5-1', 'Claude Fable 5.1'), ('fable-5', 'Claude Fable 5'), ('opus-5', 'Claude Opus 5'), ('sonnet-5', 'Claude Sonnet 5'), ('opus-4', 'Claude Opus 4.x'), ('haiku', 'Claude Haiku 4.5'), ('grok', 'Grok 4.x'), ('muse-spark', 'Muse Spark'), ('deepseek', 'DeepSeek V4'), ('glm', 'GLM 5.3'), ('kimi', 'Kimi K3'), ('hy3', 'HY3'), ('x-preview', 'x-preview-f')]:
        if k in m: return famkey(v)
    return 'Other models'
SHELL = {'Bash', 'PowerShell', 'bash', 'shell', 'oc_bash', 'Shell', 'AwaitShell', 'fn:shell_command', 'fn:exec_command', 'jscell:exec_command', 'jscell:shell_command'}
READ = {'Read', 'read', 'oc_read', 'Glob', 'glob', 'Grep', 'grep', 'ls', 'oc_ls', 'oc_glob', 'stat', 'jscell:read_file', 'jscell:grep', 'jscell:list_dir'}
EDIT = {'Edit', 'Write', 'edit', 'write', 'apply_patch', 'patch', 'jscell:apply_patch', 'StrReplace', 'oc_edit', 'oc_write', 'fn:apply_patch', 'Delete', 'rm', 'oc_rm', 'mkdir'}
JS = {'jscell:mcp__node_repl__js', 'execute'}
AGENT = {'Agent', 'task', 'subagent', 'fn:spawn_agent', 'fn:wait_agent', 'jscell:spawn_agent', 'jscell:wait_agent', 'fn:wait', 'jscell:quest', 'mcp__mcp__quest', 'jscell:mcp__quest__quest', 'jscell:mcp__quest__quest_workspace'}
ts = collections.defaultdict(collections.Counter)
for t in TC:
    if t['source'] == 'codex' and t['tool'] == 'exec': continue
    f = fam_of_tc(t)
    k = t['tool']
    b = 'shell' if k in SHELL else 'read/search' if k in READ else 'edit/write' if k in EDIT else 'js/node repl' if k in JS else 'agents/quest' if k in AGENT else 'other'
    ts[f][b] += t['n']; ts[f]['_total'] += t['n']
data['tool_share'] = [{'fam': f, 'total': c['_total'], **{k: c[k] for k in ('shell', 'read/search', 'edit/write', 'js/node repl', 'agents/quest', 'other')}} for f, c in ts.items() if f in FAMS]
data['tool_share'].sort(key=lambda x: -x['total'])
data['instructed'] = INSTRUCTED
data['platform'] = 'windows' if WINDOWS else sys.platform
data['posts'] = POSTS

# category matrix
CATS = [c for c, n in collections.Counter(r['cat'] for r in R).most_common() if n >= 100]
data['cats'] = CATS
data['cat_matrix'] = {f: {c: rate([r for r in R if r['fam'] == f and r['cat'] == c]) for c in CATS} for f in FAMS}
data['cat_totals'] = {c: rate([r for r in R if r['cat'] == c]) for c in CATS}

# dialect × host
DIAL = ['posix', 'powershell', 'cmd', 'neutral', 'mixed', 'js-only']
HOSTS = [h for h, n in collections.Counter(r['host'] for r in R).most_common() if n >= 100]
data['dialects'] = DIAL; data['hosts'] = HOSTS
data['dh'] = {d: {h: rate([r for r in R if r['dialect'] == d and r['host'] == h]) for h in HOSTS} for d in DIAL}
data['by_dialect'] = {d: rate([r for r in R if r['dialect'] == d]) for d in DIAL}
data['by_host'] = {h: rate([r for r in R if r['host'] == h]) for h in HOSTS}
data['dialect_by_family'] = {f: {d: len([r for r in R if r['fam'] == f and r['dialect'] == d]) for d in DIAL} for f in FAMS}
data['mismatch'] = S['mismatch']
data['oddities'] = S['oddities']

# interpreters
INT = [k for k, v in sorted(S['by_interp'].items(), key=lambda x: -x[1]['n']) if v['n'] >= 40]
data['interp_kinds'] = [{'kind': k, **rate([r for r in R if r['interp'] and r['interp'][0] == k]), 'median_len': statistics.median([r['cx']['len'] for r in R if r['interp'] and r['interp'][0] == k]),
                         'fams': collections.Counter(r['fam'] for r in R if r['interp'] and r['interp'][0] == k).most_common(4)} for k in INT]
data['no_interp'] = rate([r for r in R if not r['interp'] and r['cmd']])
data['purpose_global'] = S['interp_purpose_global']
data['purpose_by_fam'] = {f: collections.Counter(p for r in R if r['fam'] == f and r['interp'] for p in r.get('purpose', [])).most_common(8) for f in FAMS}
data['scratch'] = SC['rows'][:60]
data['scratch_examples'] = SC['examples']
data['node_repl'] = SC['node_repl_cells']

# failures
data['causes'] = [{'cause': c, 'n': n, 'fams': collections.Counter(r['fam'] for r in R if r['cause'] == c).most_common(5)} for c, n in S['by_cause']]
data['cause_detail'] = S['by_cause_detail'][:24]
data['cause_by_fam'] = {f: collections.Counter(r['cause'] for r in R if r['fam'] == f and r['cause']).most_common(6) for f in FAMS}
data['hidden_by_fam'] = {f: rate([r for r in R if r['fam'] == f]) for f in FAMS}
data['exit_vis'] = [{'fam': f, 'visible': sum(1 for r in R if r['fam'] == f and r.get('exit_visible')), 'hidden': sum(1 for r in R if r['fam'] == f and 'exit_visible' in r and not r['exit_visible'])} for f in FAMS if any(r['fam'] == f and 'exit_visible' in r for r in R)]
data['recovery'] = S['recovery'][:24]
data['recovery_by_cause'] = S['recovery_by_cause']
data['identical_retries'] = S['identical_retries']
data['output'] = S['output_blowups']
data['out_by_fam'] = {f: {'measured': len([r for r in R if r['fam'] == f and r.get('out_len')]), 'over10k': len([r for r in R if r['fam'] == f and (r.get('out_len') or 0) > 10000])} for f in FAMS}

# daily timeline
daily = collections.defaultdict(lambda: collections.Counter())
for r in R:
    if r['week']: daily[r['week']][r['source']] += 1
data['daily'] = [{'d': d, **c} for d, c in sorted(daily.items())]

# complexity
data['buckets'] = {b: rate([r for r in R if r['cx']['bucket'] == b]) for b in ['single command', 'chain (2-4 commands)', 'batch (5+ commands)', 'script (4+ lines or >600 chars)', 'js-only']}

# gallery
def ex(r, n=520):
    return {'f': r['fam'], 's': r['source'], 't': r['tool'], 'h': r['host'], 'd': r['dialect'], 'c': r['cat'], 'i': (r['interp'][:1] or [''])[0],
            'ok': r.get('ok'), 'hid': bool(r.get('hidden')), 'cause': r.get('cause') or '', 'det': r.get('cause_detail') or '',
            'cmd': (r.get('cmd') or r.get('js') or '')[:n], 'out': (r.get('out') or r.get('err') or '')[:300], 'w': (r['iso'] or '')[:10], 'len': r['cx']['len'], 'ncell': r.get('n_in_cell') or 0}
gallery = []
for f in FAMS:
    rs = [r for r in R if r['fam'] == f and (r.get('cmd') or r.get('js'))]
    fails = [r for r in rs if r.get('ok') is False]; hid = [r for r in rs if r.get('hidden')]; oks = [r for r in rs if r.get('ok') and not r.get('hidden')]
    bycause = group(fails, lambda r: r['cause'])
    pickf = []
    for c, v in bycause.items():
        random.shuffle(v); pickf += v[:6]
    random.shuffle(pickf); random.shuffle(hid); random.shuffle(oks)
    # ensure interpreter examples present
    interp_ok = [r for r in oks if r['interp']]; random.shuffle(interp_ok)
    chosen = pickf[:40] + hid[:8] + interp_ok[:20] + oks[:45]
    seen = set()
    for r in chosen:
        k = id(r)
        if k in seen: continue
        seen.add(k); gallery.append(ex(r))
data['gallery'] = [] if NO_GALLERY else gallery
data['retry_examples'] = [] if NO_GALLERY else S['retry_examples'][:40]
data['js_batches'] = S['examples']['js_cell_batches'][:4]
data['longest'] = S['examples']['longest'][:4]
data['js_only'] = S['examples']['js_only'][:6]

tpl = open(os.path.join(SCRIPT, 'template.html'), encoding='utf-8').read()
js = json.dumps(data, ensure_ascii=False, default=str).replace('</', '<\\/').replace('�', '?')
html = tpl.replace('__DATA__', js)
open(os.path.join(OUT_DIR, 'shell-analysis.html'), 'w', encoding='utf-8').write(html)
json.dump(data, open(os.path.join(OUT_DIR, 'page-data.json'), 'w', encoding='utf-8'), ensure_ascii=False, default=str)
print('gallery', len(gallery), 'html bytes', len(html.encode('utf-8')))
print('families', [(f['fam'], f['n']) for f in data['families']])
print('tool_share', [(t['fam'], t['total'], t['shell']) for t in data['tool_share']])
print('exit_vis', data['exit_vis'])
print('cats', CATS); print('hosts', HOSTS)
