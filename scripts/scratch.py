import json, glob, os, re, sqlite3, collections, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
HOME = os.path.expanduser('~')
D = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
SCRIPT_EXT = re.compile(r'\.(py|mjs|cjs|js|ts|tsx|ps1|sh|bat|cmd)$', re.I)
TEMPISH = re.compile(r'(Temp|tmp|scratch|\.tmp-|[\\/]scripts?[\\/]|\.codex[\\/]visualizations)', re.I)
out = collections.Counter(); ex = collections.defaultdict(list)

def fam(model):
    m = (model or '').lower()
    for k, v in [('astra', 'GPT-6 Astra'), ('gpt-5.6-sol', 'GPT-5.6 Sol'), ('gpt-5.6-luna', 'GPT-5.6 Luna'), ('gpt-5.6-terra', 'GPT-5.6 Terra'), ('fable-5-1', 'Claude Fable 5.1'), ('fable-5', 'Claude Fable 5'), ('opus-5', 'Claude Opus 5'), ('sonnet-5', 'Claude Sonnet 5'), ('opus-4', 'Claude Opus 4.x'), ('haiku', 'Claude Haiku 4.5'), ('grok', 'Grok 4.x'), ('muse-spark', 'Muse Spark'), ('deepseek', 'DeepSeek V4'), ('glm', 'GLM 5.3'), ('kimi', 'Kimi K3'), ('hy3', 'HY3'), ('x-preview', 'x-preview-f')]:
        if k in m: return v
    return 'other'

def note(src, model, path, body):
    m = SCRIPT_EXT.search(path or '')
    if not m: return
    ext = m.group(1).lower(); temp = bool(TEMPISH.search(path))
    out[(src, fam(model), ext, 'temp/scratch' if temp else 'in repo')] += 1
    key = (src, fam(model), ext)
    if len(ex[key]) < 3: ex[key].append({'path': path[-100:], 'head': (body or '')[:220]})

# claude Write tool
for f in glob.glob(HOME + '/.claude/projects/**/*.jsonl', recursive=True):
    for line in open(f, encoding='utf-8', errors='replace'):
        if '"name":"Write"' not in line: continue
        try: o = json.loads(line)
        except Exception: continue
        m = o.get('message', {})
        for b in m.get('content', []) if isinstance(m.get('content'), list) else []:
            if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('name') == 'Write':
                note('claude-code', m.get('model'), b['input'].get('file_path'), b['input'].get('content'))
# opencode write tool
class _NoDB:
    def execute(self, *a): return []
_db = HOME + '/.local/share/opencode/opencode.db'
con = sqlite3.connect('file:' + _db.replace('\\', '/') + '?mode=ro', uri=True) if os.path.exists(_db) else _NoDB()
mm = {}
for (i, d) in con.execute("select id,data from message"):
    try: o = json.loads(d); mm[i] = (o.get('providerID') or '') + '/' + (o.get('modelID') or '')
    except Exception: pass
seen = set()
for (mid, d) in con.execute("select message_id,data from part where data like '%\"tool\":\"write\"%'"):
    try: p = json.loads(d)
    except Exception: continue
    seen.add(p.get('callID'))
    inp = (p.get('state') or {}).get('input') or {}; note('opencode', mm.get(mid, '?'), inp.get('filePath'), inp.get('content'))
for (d,) in con.execute("select data from session_message where type='assistant' and data like '%\"name\":\"write\"%'"):
    try: o = json.loads(d)
    except Exception: continue
    model = (o.get('model') or {}); model = (model.get('providerID') or '') + '/' + (model.get('id') or '')
    for p in o.get('content', []):
        if p.get('type') == 'tool' and p.get('name') == 'write' and p.get('id') not in seen:
            inp = (p.get('state') or {}).get('input') or {}; note('opencode', model, inp.get('filePath'), inp.get('content'))
# codex apply_patch Add File inside exec cells, and node_repl js usage
repl = collections.Counter()
for f in glob.glob(HOME + '/.codex/sessions/**/*.jsonl', recursive=True) + glob.glob(HOME + '/.codex/archived_sessions/**/*.jsonl', recursive=True):
    last = None
    for line in open(f, encoding='utf-8', errors='replace'):
        if '"turn_context"' in line:
            try: o = json.loads(line); last = o['payload'].get('model')
            except Exception: pass
            continue
        if '"custom_tool_call"' not in line: continue
        try: o = json.loads(line); p = o['payload']
        except Exception: continue
        if p.get('name') != 'exec': continue
        js = p.get('input', '')
        for m in re.finditer(r'\*\*\* Add File: ([^\n]+)', js):
            note('codex', last, m.group(1).strip(), '')
        repl[(fam(last), 'uses node_repl' if 'tools.mcp__node_repl__js(' in js else 'no repl')] += 1
# cursor Write
for f in glob.glob(HOME + '/.cursor/chats/*/*/store.db'):
    c2 = sqlite3.connect('file:' + f + '?mode=ro', uri=True)
    for (i, d) in c2.execute('select id,data from blobs'):
        try: o = json.loads(d)
        except Exception: continue
        if isinstance(o, dict) and o.get('role') == 'assistant' and isinstance(o.get('content'), list):
            for p in o['content']:
                if p.get('type') == 'tool-call' and p.get('toolName') == 'Write':
                    a = p.get('args') or {}; note('cursor', 'grok-4.5', a.get('path'), a.get('contents'))

rows = [{'source': k[0], 'family': k[1], 'ext': k[2], 'where': k[3], 'n': v} for k, v in out.items()]
rows.sort(key=lambda r: -r['n'])
by_fam = collections.defaultdict(lambda: collections.Counter())
for r in rows: by_fam[r['family']][r['ext']] += r['n']
res = {'rows': rows, 'by_family': {k: v.most_common() for k, v in by_fam.items()},
       'temp_share': {k: round(sum(r['n'] for r in rows if r['family'] == k and r['where'] == 'temp/scratch') / max(1, sum(r['n'] for r in rows if r['family'] == k)), 3) for k in by_fam},
       'examples': {f'{k[0]}|{k[1]}|{k[2]}': v for k, v in ex.items()},
       'node_repl_cells': [{'family': k[0], 'kind': k[1], 'n': v} for k, v in repl.items()]}
json.dump(res, open(os.path.join(D, 'scratch.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
for r in rows[:40]: print(r)
print({k: v[:6] for k, v in res['by_family'].items()})
print(res['temp_share'])
print(res['node_repl_cells'])
for k, v in list(res['examples'].items())[:12]: print(k, v[0]['path'], '|', v[0]['head'][:100].replace('\n', ' '))
