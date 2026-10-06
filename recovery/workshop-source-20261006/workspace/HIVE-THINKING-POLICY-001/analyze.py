"""Read-only analysis of completed cells. Not imported by the frozen executor."""
import collections,statistics
from common import *
sys.path.insert(0,str(ROOT/'hive-transition-003/tooling/python'))
from jsonschema import Draft202012Validator
import environment as env

def resources(folder):
    rows=[]
    for p in (folder/'runtime').glob('*.json'):
        r=read(p)
        if not isinstance(r,dict) or 'host_memory' not in r:continue
        h=r['host_memory'].get('data',{}).get('host',{});g=r.get('gpu_memory',{}).get('stdout','').strip().split(',')
        rows.append({'path':str(p),'label':r['label'],'at':r['started_at'],
            'free_host_gib':h.get('free_physical_kib',0)/1024**2 if h else None,
            'free_virtual_gib':h.get('free_virtual_kib',0)/1024**2 if h else None,
            'gpu_free_mib':int(g[-1]) if len(g)==6 else None,'residency':r.get('/api/ps'),'docker':r.get('docker')})
    return sorted(rows,key=lambda r:r['at'])

def inspect_call(call,folder,task):
    row=dict(call);path=folder/'runtime/calls'/f"{call['number']:02d}-{call['role']}"
    attempts=[];body=None
    for p in sorted(path.glob('attempt-*/transport.json')):
        tr=read(p);body=read(p.parent/'wire-request.json');stream=p.parent/'response.ndjson'
        start=datetime.fromisoformat(tr['started_at']);ch={k:{'characters':0,'chunks':0,'first_seconds':None} for k in ('thinking','content')};terminal=None;errors=[]
        if stream.exists():
            for line in stream.read_text(encoding='utf-8',errors='replace').splitlines():
                try:c=json.loads(line)
                except ValueError:continue
                t=(datetime.fromisoformat(c['created_at'].replace('Z','+00:00'))-start).total_seconds() if c.get('created_at') else None
                for k in ch:
                    v=(c.get('message') or {}).get(k,'')
                    if v:
                        ch[k]['characters']+=len(v);ch[k]['chunks']+=1
                        if ch[k]['first_seconds'] is None:ch[k]['first_seconds']=t
                if c.get('done'):terminal={k:v for k,v in c.items() if k!='message'}
                if c.get('error'):errors.append(c['error'])
        attempts.append({'transport':tr,'wire_request':str(p.parent/'wire-request.json'),'think_sent':body.get('think','OMITTED'),
            'channels':ch,'terminal':terminal,'stream_provider_errors':errors})
    row['attempt_details']=attempts
    prompt='\n'.join(m['content'] for m in body['messages']) if body else ''
    row['kind']=('targeted correction' if 'TARGETED VERIFICATION CORRECTION' in prompt else
        'structural correction' if 'STRUCTURAL EDIT REPAIR' in prompt else
        'JSON repair' if 'Repair the previous ' in prompt or 'ONE JSON FORMAT REPAIR:' in prompt else 'initial')
    row['original_task_present']=task['request'] in prompt
    row['response_complete']=call.get('status')=='completed' and bool(attempts) and attempts[-1]['terminal'] is not None
    row['parseable']=False;row['schema_valid']=False;row['valid_worker_status']=False;row['actionable']=False
    response=path/'response.txt'
    if response.exists():
        raw=response.read_text(encoding='utf-8');row['response_sha256']=sha(response)
        try:
            obj=env.hive._extract_json(raw);row['parseable']=True
            errors=list(Draft202012Validator(body['format']).iter_errors(obj)) if isinstance(body.get('format'),dict) else []
            row['schema_valid']=not errors;row['schema_errors']=[e.message for e in errors]
            if isinstance(obj,dict):
                row['worker_status']=obj.get('status');row['valid_worker_status']=not errors and 'status' in obj
                edits=obj.get('edits') or []
                row['operations']=[{'path':e.get('path'),'operation':e.get('operation')} for e in edits if isinstance(e,dict)]
                row['actionable']=bool(row['schema_valid'] and obj.get('status')=='implemented' and edits and
                    all(isinstance(e,dict) and e.get('path') in task['files'] and env.hive.hive_edits.operation_supported(e.get('path',''),e.get('operation')) for e in edits))
                row['edit_payload_sha256']=hashlib.sha256(json.dumps(edits,sort_keys=True,separators=(',',':')).encode()).hexdigest() if edits else None
        except Exception as exc:row['parse_error']={'type':type(exc).__name__,'message':str(exc)}
    row['complete_structured_worker_response']=row['response_complete'] and row['parseable'] and row['schema_valid'] and row['valid_worker_status']
    return row

def main():
    lock=read(HERE/'FREEZE.json');results=read(HERE/'evidence/raw-results.json') if (HERE/'evidence/raw-results.json').exists() else []
    old={r['ordinal']:r for r in read(ROOT/'HIVE-FACTORIAL-003R1/evidence/raw-results.json')}
    rows=[]
    for r in results:
        folder=Path(r['evidence']);run=read(folder/'run.json');task=next(t for t in lock['tasks'] if t['id']==r['task_id'])
        calls=[inspect_call(c,folder,task) for c in read(folder/'runtime/calls.json')]
        workers=[c for c in calls if c['role'] in ('ui','backend','tests')]
        row={**r,'calls':calls,'workers':workers,'resources':resources(folder),'errors':run.get('errors',[]),
            'ownership':(run.get('plan') or {}).get('worker_files'),
            'complete_structured_worker_response':any(c['complete_structured_worker_response'] for c in workers),
            'actionable_response':any(c['actionable'] for c in workers),
            'targeted_corrections':run.get('targeted_repairs'),'structural_corrections':run.get('edit_repairs'),
            'historical':old[r['historical_cell']]}
        verification=[]
        for rec in read(folder/'verification-records.json'):
            report=rec.get('report',{});checks=[]
            for c in report.get('checks',[]):
                d=c.get('detail',{});d=d if isinstance(d,dict) else {}
                stdout=d.get('stdout_tail','');tests=d.get('tests') or []
                checks.append({'name':c.get('name'),'passed':c.get('passed'),'returncode':d.get('returncode'),'timed_out':d.get('timed_out'),
                    'tests':tests,'counts':{k:sum(t.get(k,0) for t in tests) for k in ('tests','failures','errors','skipped')},
                    'acceptance_mismatches':d.get('acceptance_mismatches'),
                    'compilation_marker_observed':'> Task :compileJava' in stdout,'compilation_failed':':compileJava FAILED' in stdout,
                    'compile_test_marker_observed':'> Task :compileTestJava' in stdout,
                    'diagnostic_excerpt':stdout[-7000:],'stderr':d.get('stderr_tail','')[-2000:]})
            verification.append({'kind':rec['kind'],'elapsed_seconds':rec.get('host_elapsed_seconds'),'passed':report.get('passed'),'checks':checks})
        row['verification']=verification
        row['correction_comparison']=[]
        for first,later in zip(workers,workers[1:]):
            category='UNAVAILABLE'
            if first.get('response_sha256') and later.get('response_sha256'):
                category=('BYTE_IDENTICAL' if first['response_sha256']==later['response_sha256'] else
                    'IDENTICAL_EDIT_PAYLOAD' if first.get('edit_payload_sha256') and first.get('edit_payload_sha256')==later.get('edit_payload_sha256') else 'DIFFERENT_EDIT_PAYLOAD_REQUIRES_SEMANTIC_INSPECTION')
            row['correction_comparison'].append({'earlier_call':first['number'],'later_call':later['number'],'later_kind':later['kind'],'comparison':category})
        row['quality_flags']={'malformed_worker_responses':sum(c['response_complete'] and not c['parseable'] for c in workers),
            'schema_invalid_workers':sum(c['parseable'] and not c['schema_valid'] for c in workers),
            'unauthorized_operation_responses':sum(any(op['path'] not in task['files'] for op in c.get('operations',[])) for c in workers),
            'compilation_failures':sum(any(c['compilation_failed'] for c in v['checks']) for v in verification),
            'behavioral_fails':sum(any(c['counts']['tests']>0 and not c['passed'] for c in v['checks']) for v in verification)}
        levels=[('WORKER_RESPONSE_COMPLETED',row['complete_structured_worker_response']),('ACTIONABLE_RESPONSE',row['actionable_response']),
            ('EXECUTABLE_EDIT',r['transitions']['executable_edit']),('TARGETED_VERIFICATION_REACHED',r['transitions']['targeted_verification']),
            ('FROZEN_ACCEPTANCE_REACHED',r['transitions']['frozen_acceptance']),('FULL_GATE_VERIFIED',r['verified_software_success'])]
        row['highest_level']=next((name for name,reached in reversed(levels) if reached),'WORKER_TIMEOUT' if workers and any(c.get('status')=='failed' for c in workers) else 'WORKER_NOT_REACHED')
        rows.append(row)
    aggregates={k:sum(r.get(k,False) for r in rows) for k in ('complete_structured_worker_response','actionable_response','verified_software_success')}
    aggregates['transitions']={k:sum(r['transitions'][k] for r in rows) for k in (rows[0]['transitions'] if rows else [])}
    aggregates['worker_call_counts']={k:sum(bool(c.get(k)) for r in rows for c in r['workers']) for k in ('response_complete','parseable','schema_valid','complete_structured_worker_response','actionable')}
    aggregates['worker_calls']=sum(len(r['workers']) for r in rows)
    aggregates['worker_timeouts']=sum(c.get('status')=='failed' and 'total limit' in str(c.get('error')) for r in rows for c in r['workers'])
    aggregates['runtime_failure_cells']=sum(bool(r['runtime_events']) for r in rows)
    aggregates['verifier_runtime_failure_cells']=sum(r['verifier_runtime_failure'] for r in rows)
    aggregates['reviews']=dict(collections.Counter(r['semantic_review'] for r in rows))
    aggregates['quality']={k:sum(r['quality_flags'][k] for r in rows) for k in (rows[0]['quality_flags'] if rows else [])}
    completed_times=[c['elapsed_seconds'] for r in rows for c in r['workers'] if c['response_complete']]
    aggregates['median_completed_worker_seconds']=statistics.median(completed_times) if completed_times else None
    aggregates['totals']={k:sum(r[k] for r in rows) for k in ('model_calls','provider_attempts','input_tokens_known','output_tokens_known','model_seconds','verification_seconds','wall_seconds')}
    summary={'at':stamp(),'completed_cells':len(rows),'complete':len(rows)==6 and (HERE/'evidence/COMPLETED.json').exists(),'aggregates':aggregates,
        'historical_selected_failed_calls_completed':0,'historical_any_worker_response_cells':1,'historical_executable_edits_cells':1,
        'historical_targeted_verification_cells':1,'historical_acceptance_cells':0,'historical_full_gate_success_cells':0}
    save(HERE/'evidence/paired-analysis.json',rows);save(HERE/'evidence/analysis-summary.json',summary)
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
