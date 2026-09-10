"""Paired live-model benchmark for bound versus copied paths on fresh fixtures.

The caller supplies targets in both arms. No model training or historical test
partition access occurs. Candidate order alternates; schema has two valid refs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import time
import uuid

from benchmark import equivalent_output, percentile
from bindings import bind_request
from contract import execute_plan
from run import inspect_request


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    root = out / 'fixtures'
    root.mkdir()
    cases = []
    specs = []
    for op in ('read_head', 'read_tail'):
        for limit in (1, 4, 9, 16, 27, 43, 58, 73, 91, 100):
            for wording in range(2):
                edge = 'opening' if op == 'read_head' else 'trailing'
                side = 'top' if op == 'read_head' else 'bottom'
                request = (f'Please fetch no more than {limit} {edge} lines from file {{{{source}}}}.' if wording == 0 else
                           f'{{{{source}}}} is the log to inspect. Give me {limit} lines starting at its {side}.')
                specs.append((op, '', limit, request))
    for _ in range(8):
        specs.append(('find_literal', 'ERROR', 3, 'Find up to 3 lines containing literal "ERROR" in {{source}}.'))
        specs.append(('json_field', 'state', 20, 'Get the top-level JSON field "state" from {{source}}.'))
    for _ in range(4):
        specs.append(('list_files', '*.log', 3, 'List up to 3 filenames matching "*.log" in directory {{source}}.'))
    for i, (op, value, limit, request) in enumerate(specs):
        suffix = '.json' if op == 'json_field' else '.log'
        token = uuid.uuid4().hex[:16]
        name = f"sample {token} [draft] can't caf\u00e9 \u6f22\u5b57"
        name += ' {{unbound}} file_1' if i % 4 == 0 else ''
        if op != 'list_files':
            name += suffix
        decoy = f'decoy {uuid.uuid4().hex[:16]}' + suffix
        if op == 'list_files':
            for directory in (name, decoy):
                (root/directory).mkdir()
                (root/directory/(token+'.log' if directory == name else 'wrong.log')).write_text('fixture')
        elif op == 'json_field':
            (root/name).write_text(json.dumps({'state':token}), encoding='utf-8')
            (root/decoy).write_text('{"state":"wrong"}', encoding='utf-8')
        else:
            content = '\n'.join(f'{token} row {j}' + (' ERROR exact' if j in (2,9) else '') for j in range(113))
            (root/name).write_text(content+'\n', encoding='utf-8')
            (root/decoy).write_text('wrong target\n', encoding='utf-8')
        targets = {'source':name,'other':decoy} if i % 2 == 0 else {'other':decoy,'source':name}
        cases.append({'id':f'bound-{i}', 'kind':'plan', 'request':request, 'targets':targets,
                      'expected':{'op':op,'path':name,'value':value,'limit':limit}})
    raw = ''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in cases).encode('utf-8')
    (out/'cases.jsonl').write_bytes(raw)
    (out/'manifest.json').write_text(json.dumps({'cases':len(cases),'sha256':hashlib.sha256(raw).hexdigest(),
        'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope':'Fresh synthetic caller-bound tasks; not historical validation/final-test or file-discovery accuracy.'},indent=2),encoding='utf-8')
    return cases, root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--model', default='shell-specialist-pilot')
    parser.add_argument('--base-url', default='http://127.0.0.1:11434')
    parser.add_argument('--backend', choices=['native','powershell'], default='native')
    args = parser.parse_args()
    cases, root = prepare(args.out)
    root = root.resolve()
    kwargs = dict(model=args.model,base_url=args.base_url,backend=args.backend,artifacts=args.out/'runs')
    # Record a real warm-up through each arm, then exclude it from warm metrics.
    first = cases[0]
    bound = bind_request(root, first['request'], first['targets'])
    warm = [inspect_request(root,bound.display_request,**kwargs),
            inspect_request(root,first['request'],targets=first['targets'],**kwargs)]
    rows=[]
    with (args.out/'results.jsonl').open('w',encoding='utf-8') as handle:
        for i, case in enumerate(cases):
            reference=execute_plan(case['expected'],root,backend='powershell')
            assert reference['exit_code']==0,reference
            binding=bind_request(root,case['request'],case['targets'])
            for arm in (('bound','literal') if i%2==0 else ('literal','bound')):
                started=time.perf_counter()
                row={'id':case['id'],'op':case['expected']['op'],'arm':arm}
                try:
                    packet=inspect_request(root,case['request'] if arm=='bound' else binding.display_request,
                                           targets=case['targets'] if arm=='bound' else None,**kwargs)
                    saved=json.loads(Path(packet['raw_result']).read_text(encoding='utf-8'))
                    result=saved['result']
                    row.update({'passed':result['exit_code']==0 and equivalent_output(case,result['stdout'],reference['stdout']),
                                'path_correct':packet['plan']['path']==case['expected']['path'],
                                'plan':packet['plan'],'packet':packet,
                                'eval_count':saved['planning'].get('eval_count'),
                                'prompt_eval_count':saved['planning'].get('prompt_eval_count')})
                except Exception as error:
                    row.update({'passed':False,'error':str(error)})
                row['wall_ms']=(time.perf_counter()-started)*1000
                rows.append(row)
                handle.write(json.dumps(row,ensure_ascii=False)+'\n');handle.flush()
            if (i+1)%10==0:
                print(json.dumps({'cases_complete':i+1,'bound_passed':sum(r['passed'] for r in rows if r['arm']=='bound')}),flush=True)
    summary={}
    for arm in ('literal','bound'):
        group=[r for r in rows if r['arm']==arm]
        successful=[r for r in group if r['passed']]
        generated=[r['eval_count'] for r in group if r.get('eval_count') is not None]
        summary[arm]={'cases':len(group),'passed':sum(r['passed'] for r in group),
                      'median_all_attempts_ms':statistics.median(r['wall_ms'] for r in group),
                      'p95_all_attempts_ms':percentile([r['wall_ms'] for r in group],.95),
                      'median_successful_ms':statistics.median(r['wall_ms'] for r in successful) if successful else None,
                      'mean_generated_tokens_returned':statistics.mean(generated) if generated else None,
                      'returned_predictions':sum(r.get('eval_count') is not None for r in group),
                      'by_operation':{op:{'cases':sum(r['op']==op for r in group),
                                         'passed':sum(r['passed'] for r in group if r['op']==op)}
                                      for op in sorted({r['op'] for r in group})}}
    report={'model':args.model,'backend':args.backend,'warmup':warm,'summary':summary,
            'conditions':{'thinking':False,'temperature':0,'context':4096,'max_new_tokens':160,
                          'order':'paired alternating','candidate_count':2,'training':'unchanged existing adapter',
                          'wall_includes':'binding, inference, validation, execution, raw artifact save, packet construction and reload',
                          'reference_execution':'PowerShell, outside measured operation',
                          'limitations':'Synthetic tasks with caller-supplied target identity. Errors remain in all-attempt latency; token statistics include only returned successful executions.'}}
    (args.out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report['summary'],indent=2))


if __name__ == '__main__':
    main()
