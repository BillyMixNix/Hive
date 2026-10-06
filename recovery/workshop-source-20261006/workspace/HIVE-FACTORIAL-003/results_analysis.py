"""Read-only postprocessing. Not imported by the frozen trial executor."""
import collections,json,math,re,sys
from pathlib import Path
from common import HERE,HIST,ROOT,save,stamp
def read(p):return json.loads(Path(p).read_bytes())
def exact_interval(x,n,alpha=.05):
    if not n:return [None,None]
    def cdf(k,p):return sum(math.comb(n,i)*p**i*(1-p)**(n-i) for i in range(k+1))
    def bisect(fn,target,increasing):
        lo,hi=0.,1.
        for _ in range(100):
            mid=(lo+hi)/2
            if (fn(mid)<target)==increasing:lo=mid
            else:hi=mid
        return (lo+hi)/2
    return [0. if x==0 else bisect(lambda p:1-cdf(x-1,p),alpha/2,True),
            1. if x==n else bisect(lambda p:cdf(x,p),alpha/2,False)]
def fisher(x,n,hist_n=16):
    denominator=math.comb(n+hist_n,x)
    probs={k:math.comb(n,k)*math.comb(hist_n,x-k)/denominator for k in range(max(0,x-hist_n),min(n,x)+1)}
    return min(1.,sum(p for p in probs.values() if p<=probs[x]+1e-14))
def resources(folder):
    out=[]
    for p in (folder/'runtime').glob('*.json'):
        r=read(p)
        if not isinstance(r,dict) or 'host_memory' not in r:continue
        mem=r['host_memory'].get('data',{}).get('host',{});gpu=r.get('gpu_memory',{}).get('stdout','').strip().split(',')
        out.append({'file':str(p),'label':r['label'],'at':r['started_at'],
            'free_host_gib':mem.get('free_physical_kib',0)/1024**2 if mem else None,
            'free_virtual_gib':mem.get('free_virtual_kib',0)/1024**2 if mem else None,
            'gpu_free_mib':int(gpu[-1]) if len(gpu)==6 else None,
            'models':r.get('/api/ps',{}),'docker':r.get('docker',{})})
    return sorted(out,key=lambda r:r['at'])
def summarize():
    lock=read(HERE/'FREEZE.json');results=read(HERE/'evidence/raw-results.json') if (HERE/'evidence/raw-results.json').exists() else []
    enriched=[];cases=[]
    for result in results:
        row=dict(result);folder=Path(row['evidence']);run=read(folder/'run.json')
        row['errors']=[{k:e.get(k) for k in ('role','stage','exception_type','exception_message')} if isinstance(e,dict) else e for e in run.get('errors',[])]
        row['plan_failures']=[a.get('failure') for a in run.get('plan_attempts',[]) if a.get('status')=='rejected']
        row['ownership']=(run.get('plan') or {}).get('worker_files')
        calls=read(folder/'runtime/calls.json') if (folder/'runtime/calls.json').exists() else []
        row['provider_calls']=calls
        row['attempt_evidence']=[]
        for p in (folder/'runtime/calls').glob('*/*/transport.json'):
            attempt=read(p);stream=p.parent/'response.ndjson';terminal=[];provider_errors=[]
            if stream.exists():
                for line in stream.read_text(encoding='utf-8',errors='replace').splitlines():
                    try:chunk=json.loads(line)
                    except json.JSONDecodeError:continue
                    if chunk.get('done'):terminal.append({k:v for k,v in chunk.items() if k not in ('message','response','context')})
                    if chunk.get('error'):provider_errors.append(chunk['error'])
            attempt.update(path=str(p),terminal_metadata=terminal,provider_errors=provider_errors)
            row['attempt_evidence'].append(attempt)
        row['resources']=resources(folder)
        row['original_task_in_worker_prompts']=[]
        task=next(t for t in lock['tasks'] if t['id']==row['task_id'])
        for p in (folder/'runtime/calls').glob('*/*/wire-request.json'):
            body=read(p);role=p.parent.parent.name.split('-',1)[1]
            if role in ('ui','backend','tests'):
                row['original_task_in_worker_prompts'].append({'wire_request':str(p),'present':task['request'] in '\n'.join(m['content'] for m in body['messages'])})
        row['repeated_proposals']=sum('repeat' in str(e).casefold() or 'identical' in str(e).casefold() for e in row['errors'])
        row['malformed_response_evidence']=[]
        for e in row['errors']+[f for f in row['plan_failures'] if f]:
            if isinstance(e,dict) and any(k in str(e).casefold() for k in ('jsondecodeerror','invalid json','json object','json syntax','failed to parse','json parse')):
                row['malformed_response_evidence'].append(e)
        for record in read(folder/'verification-records.json'):
            report=record.get('report',{})
            for check in report.get('checks',[]):
                detail=check.get('detail') or {};detail=detail if isinstance(detail,dict) else {}
                tests=detail.get('tests') or []
                cases.append({'ordinal':row['ordinal'],'mode':record['kind'],'check':check.get('name'),'passed':check.get('passed'),
                    'counts':{k:sum(t.get(k,0) for t in tests) for k in ('tests','failures','errors','skipped')},'test_results':tests,
                    'diagnostics':report.get('diagnostics'),'host_seconds':record['host_elapsed_seconds']})
        enriched.append(row)
    x=sum(r['verified_software_success'] for r in results);n=len(results)
    grouped={}
    for field in ('controller','model','task_id','replicate'):
        grouped[field]={}
        for value in sorted(set(str(r[field]) for r in results)):
            cells=[r for r in results if str(r[field])==value];wins=sum(r['verified_software_success'] for r in cells)
            grouped[field][value]={'successes':wins,'trials':len(cells),'rate':wins/len(cells)}
    transitions={k:sum(r['transitions'].get(k,False) for r in results) for k in (results[0]['transitions'] if results else [])}
    total={k:sum(r.get(k,0) for r in results) for k in ('model_calls','provider_attempts','input_tokens_known','output_tokens_known','model_seconds','verification_seconds','wall_seconds','planner_corrections','worker_structural_corrections','worker_targeted_corrections','observation_requests')}
    total.update(usage_complete=all(r['usage_complete'] for r in results),successes_per_model_call=x/total['model_calls'] if total['model_calls'] else None,
        successes_per_trial_hour=x/(total['wall_seconds']/3600) if total['wall_seconds'] else None)
    total['active_execution_seconds']=sum(r.get('active_execution_wall_seconds',r['wall_seconds']) for r in results)
    total['setup_interruption_seconds']=sum(r.get('setup_interruption_seconds',0) for r in results)
    total['all_attempt_token_accounting_complete']=bool(enriched) and all(a['terminal_metadata'] for r in enriched for a in r['attempt_evidence'])
    total['usage_interpretation']='Known completed logical-call token counts; not full attempted-generation totals when any attempt lacks final accounting.'
    historical=read(HIST/'evidence/raw_results.json')
    historical_hive=[r for r in historical if r['controller']=='hive']
    paired=[{'task_id':r['task_id'],'model':r['model'],'replicate':r['replicate'],'current_ordinal':r['ordinal'],'current_outcome':r['primary_outcome'],
        'historical':next(h for h in historical_hive if (h['task_id'],h['model'],h['replicate'])==(r['task_id'],r['model'],r['replicate']))} for r in results]
    complete=n==16 and (HERE/'evidence/COMPLETED.json').exists()
    summary={'study':'HIVE-FACTORIAL-003','generated_at':stamp(),'completed':complete,'trials_observed':n,'planned_trials':16,'successes':x,'success_rate_observed':x/n if n else None,
        'groups':grouped,'transitions':transitions,'primary_outcomes':dict(collections.Counter(r['primary_outcome'] for r in results)),
        'reviews':dict(collections.Counter(r['semantic_review'] for r in results)),'runtime_failure_trials':sum(bool(r['runtime_events']) for r in results),
        'provider_attempt_error_trials':sum(any(a.get('http_status',200)>=400 or a.get('transport_error') or a['provider_errors'] or a.get('stream_error') for a in r['attempt_evidence']) for r in enriched),
        'provider_attempt_errors':sum(bool(a.get('http_status',200)>=400 or a.get('transport_error') or a['provider_errors'] or a.get('stream_error')) for r in enriched for a in r['attempt_evidence']),
        'verifier_runtime_failure_trials':sum(r['verifier_runtime_failure'] for r in results),'usage':total,
        'malformed_response_trials':sum(bool(r['malformed_response_evidence']) for r in enriched),'repeated_proposal_trials':sum(bool(r['repeated_proposals']) for r in enriched),
        'statistics':{'descriptive_only_until_complete':not complete,'confidence_level':.95,'interval_method':'Two-sided Clopper-Pearson exact binomial','interval':exact_interval(x,n),
            'fisher_exact_two_sided_p':fisher(x,n) if n else None,'table':[[0,16],[x,n-x]],'absolute_rate_difference':x/n if n else None},
        'paired_historical_cells':paired,'historical_not_rescored':True,'no_current_single_control':True}
    save(HERE/'evidence/analysis-summary.json',summary);save(HERE/'evidence/per-trial-analysis.json',enriched);save(HERE/'evidence/verification-case-summary.json',cases)
    print(json.dumps({k:summary[k] for k in ('completed','trials_observed','successes','primary_outcomes','reviews','transitions','usage','statistics')},indent=2))
    return summary
if __name__=='__main__':summarize()
