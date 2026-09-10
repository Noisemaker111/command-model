"""Run one ten-stage job in one fresh Codex session with three execution strategies."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from bench import run, write_json
from ten_step_workload import STEPS, inputs, assess

HERE = Path(__file__).resolve().parent


def prepare(out, arm):
    directory = out.resolve() / (arm + '-' + uuid.uuid4().hex[:8])
    root = directory / 'workspace'
    root.mkdir(parents=True)
    inputs(root)
    subprocess.run(['git', 'init', '--quiet', str(root)], check=True)
    scripts = ['build_packet.py'] if arm == 'baseline' else ([f'step{i:02}.py' for i in range(1, 11)] if arm == 'chained' else ['group01.py', 'group02.py'])
    guidance = ('This is a synthetic benchmark fixture, not a source project. Do the requested incident investigation. '
        f'Installed Python 3.12 interpreter: {sys._base_executable}. Use it directly; runtime readiness is already checked. '
        'Use Python 3.12 standard library only. Modify only the named Python scripts and out/*.json. '
        'Do not edit inputs. No commits, PRs, installs or unrelated research. Inspect real outcomes; never fabricate success. '
        'All work belongs to one session. Keep data references explicit.\n')
    if arm == 'baseline':
        guidance += 'Use normal native shell/file tools and build_packet.py. Batch work as efficiently as you judge useful; there is no required number of shell calls. Do not use a local model.\n'
    else:
        guidance += ('Use command_model.run_python_task with English intent, exact script target, relevant context and exact expected stdout. '
            'Do not write source or command sequences yourself. Call serially; each call is a fresh worker. '
            'After a failure, preserve it and continue later requested groups when possible; do not switch to native execution or silently retry in another worker.\n')
        guidance += ('Make exactly ten handoffs, one per numbered stage.\n' if arm == 'chained' else 'Make exactly two handoffs: stages 1–5 together, then stages 6–10 together.\n')
    (root / 'AGENTS.md').write_text(guidance, encoding='utf-8')
    task = ('Build a reproducible incident evidence packet from synthetic files under inputs. '
        'Complete these ten stages in order and report which saved outputs were actually verified. '
        'Later stages consume earlier outputs. Each generated script must create out if missing. '
        'Read the input files rather than hardcoding their data.\n\n' +
        '\n'.join(f'{i}. {step}' for i, step in enumerate(STEPS, 1)))
    if arm == 'baseline':
        task += '\nUse build_packet.py to produce all ten outputs and print JOB OK followed by a newline only when complete. You may batch native work.'
    elif arm == 'chained':
        task += '\nFor stage N use target stepNN.py (01–10), save its requested output, and print exactly STEP NN OK followed by a newline. The expected_stdout field uses Windows CRLF. Supply the relevant stage and dependency filenames to each fresh worker.'
    else:
        task += '\nUse group01.py for stages 1–5 and group02.py for stages 6–10. Each group saves all five requested outputs and prints exactly GROUP 01 OK or GROUP 02 OK followed by a newline. expected_stdout uses Windows CRLF. Pass all stage requirements and dependency filenames for that group.'
    (directory / 'prompt.txt').write_text(task, encoding='utf-8')
    if arm != 'baseline':
        (root / '.codex').mkdir()
        (root / '.codex/config.toml').write_text('[mcp_servers.command_model]\ncommand = '+json.dumps(sys.executable)+'\nargs = '+json.dumps([str(HERE/'server.py'),'--root',str(root),'--artifacts',str(directory/'local'),'--allow-execute'])+'\nrequired = true\nstartup_timeout_sec = 30\ntool_timeout_sec = 330\ndefault_tools_approval_mode = "prompt"\n', encoding='utf-8')
    write_json(directory/'fixture.json', {'case':'ten-stage-incident','arm':arm,'scripts':scripts,
        'input_hashes':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'inputs').rglob('*') if p.is_file()}})
    return directory


def replay(directory, scripts):
    root = directory/'workspace'
    target = directory/'alternate'
    if target.exists():
        raise ValueError('Alternate evidence already exists; do not overwrite a measured run')
    target.mkdir()
    inputs(target, alternate=True)
    executions=[]
    for script in scripts:
        source=root/script
        if not source.exists():
            executions.append({'script':script,'exit_code':None,'error':'missing script'})
            continue
        shutil.copyfile(source,target/script)
        try:
            result=subprocess.run([sys._base_executable,'-S',str(target/script)],cwd=target,capture_output=True,timeout=20)
            executions.append({'script':script,'exit_code':result.returncode})
            (target/(script+'.stdout')).write_bytes(result.stdout)
            (target/(script+'.stderr')).write_bytes(result.stderr)
        except subprocess.TimeoutExpired:
            executions.append({'script':script,'exit_code':124})
    return {'executions':executions,'checks':assess(target)}


def collect(directory):
    root=directory/'workspace'
    fixture=json.loads((directory/'fixture.json').read_text(encoding='utf-8'))
    run_info=json.loads((directory/'run.json').read_text(encoding='utf-8'))
    events=[json.loads(line) for line in (directory/'events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    times=[json.loads(line) for line in (directory/'event-times.jsonl').read_text(encoding='utf-8').splitlines()]
    timestamps={r['line']:r['elapsed_ms'] for r in times}
    turns=[e for e in events if e.get('type')=='turn.completed']
    completed=[e['item'] for e in events if e.get('type')=='item.completed']
    timings={}
    for index,event in enumerate(events):
        item=event.get('item',{})
        if item.get('type') not in ('command_execution','mcp_tool_call'): continue
        row=timings.setdefault(item['id'],{'type':item['type']})
        if event['type']=='item.started': row['start_ms']=timestamps.get(index)
        if event['type']=='item.completed': row['end_ms']=timestamps.get(index)
    intervals=[v for v in timings.values() if v.get('start_ms') is not None and v.get('end_ms') is not None]
    spans=sorted((v['start_ms'],v['end_ms']) for v in intervals)
    merged=[]
    for start,end in spans:
        if merged and start<=merged[-1][1]: merged[-1][1]=max(merged[-1][1],end)
        else: merged.append([start,end])
    tool_wall=sum(end-start for start,end in merged)
    checks=assess(root)
    alternate=replay(directory,fixture['scripts'])
    local=[]
    for path in (directory/'local').glob('*/result.json'):
        r=json.loads(path.read_text(encoding='utf-8'))
        local.append({'verified':r['verified'],'status':r['status'],'wall_ms':r['wall_ms'],
            'model_calls':len(r['model_calls']),'input_tokens':sum(c['response'].get('prompt_eval_count',0) for c in r['model_calls']),
            'output_tokens':sum(c['response'].get('eval_count',0) for c in r['model_calls']),
            'failed_executions':sum(a.get('result',{}).get('exit_code',0)!=0 for a in r['actions'])})
    expected_calls={'baseline':0,'chained':10,'grouped':2}[fixture['arm']]
    mcp=[i for i in completed if i.get('type')=='mcp_tool_call' and i.get('server')=='command_model']
    inputs_unchanged=all((root/name).exists() and hashlib.sha256((root/name).read_bytes()).hexdigest()==value for name,value in fixture['input_hashes'].items())
    success=bool(turns and run_info['exit_code']==0 and not run_info['source_changed_during_run'] and inputs_unchanged
        and all(c['passed'] for c in checks) and all(c['passed'] for c in alternate['checks'])
        and all(e['exit_code']==0 for e in alternate['executions']) and len(mcp)==expected_calls
        and len(local)==expected_calls and all(r['verified'] for r in local))
    summary={'arm':fixture['arm'],'success':success,'wall_ms':run_info['wall_ms'],
        'tool_span_ms':tool_wall,'outside_tool_span_ms':run_info['wall_ms']-tool_wall,
        'local_worker_ms':sum(r['wall_ms'] for r in local),'frontier_usage':{k:sum(t.get('usage',{}).get(k,0) for t in turns) for k in ('input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens')},
        'native_commands':sum(i.get('type')=='command_execution' for i in completed),'delegations':len(mcp),
        'completed_stages':sum(c['passed'] for c in checks),'alternate_stages':sum(c['passed'] for c in alternate['checks']),
        'checks':checks,'alternate':alternate,'local':local,'tool_intervals':intervals,'input_unchanged':inputs_unchanged,
        'model':run_info['model'],'effort':run_info['effort'],'raw_events':str(directory/'events.jsonl')}
    write_json(directory/'summary.json',summary)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['prepare','run'])
    parser.add_argument('--arm',choices=['baseline','chained','grouped'],required=True)
    parser.add_argument('--out',type=Path,default=Path('work/ten-stage'))
    parser.add_argument('--model',default='gpt-6-astra')
    parser.add_argument('--effort',default='low')
    args=parser.parse_args()
    directory=prepare(args.out,args.arm)
    if args.operation=='prepare': print(directory); return
    result=run(directory,args.model,args.effort,collector=collect,timeout=1800,
               extra_sources=[Path(__file__),HERE/'ten_step_workload.py'])
    print(json.dumps({k:v for k,v in result.items() if k not in ('checks','alternate','tool_intervals','local')},indent=2))


if __name__=='__main__': main()
