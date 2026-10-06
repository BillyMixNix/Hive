"""Derive report tables from the completed single trial. No inference."""
import json,re,sys
from datetime import datetime,timezone
from pathlib import Path
sys.dont_write_bytecode=True
from bootstrap import HERE,save,sha
import diagnostic_environment as env
E=HERE/'evidence';LIVE=E/'live-diagnostic'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def utc(t):return datetime.fromtimestamp(t,timezone.utc).isoformat()
def main():
 result=read(LIVE/'raw_results.json')[0];rid=result['run_id'];run=read(LIVE/'runs'/rid/'run.json')
 assert result['classification']=='LOCAL_RUNTIME_FAILURE' and result['status']=='rejected'
 assert len(run['plan_attempts'])==1 and run['plan_attempts'][0]['status']=='accepted'
 assert not run['targeted_repairs'] and not run['edit_repairs'] and not run['replans']
 save(E/'normalized-plan.json',run['plan']);save(E/'initial-worker-operation.json',run['agents']['backend']['parsed'])
 (E/'initial-candidate.diff').write_text(run['diff'],encoding='utf-8')
 target=read(LIVE/'verifications/targeted-01/result.json');full=read(LIVE/'full-gate.json')
 verification=[]
 for name,entry in [('targeted',target),('full',full)]:
  report=entry['report'];diag=report['diagnostics'];diag=diag[0] if isinstance(diag,list) else diag
  folder=Path(diag['directory']);events=[json.loads(l) for l in (folder/'verification-events.jsonl').read_text().splitlines()]
  invocation=read(folder/'invocation.json')
  cmds=[e['source_event'] for e in events if e['phase']=='gradle_invoked']
  checks=[]
  for check in report['checks']:
   detail=check.get('detail');detail=detail if isinstance(detail,dict) else {}
   tests=detail.get('tests',[])
   checks.append({'name':check['name'],'passed':check['passed'],'returncode':detail.get('returncode'),
    'timed_out':detail.get('timed_out'),'gradle_wall_seconds':detail.get('wall_seconds'),
    'junit_classes':len(tests),'junit_totals':{key:sum(t[key] for t in tests) for key in ('tests','failures','errors','skipped')}})
  selected=[e for e in events if e['phase'] in ('verification_requested','host_preflight_started','source_staging_complete',
    'host_preflight_complete','verifier_launch_requested','verifier_process_exit','cleanup_complete','container_removed','gradle_invoked','gradle_returned','verification_returned')]
  text=''.join(e['source_event'].get('text','') for e in events if e['phase']=='process_output' and e.get('source_event',{}).get('stream')=='stdout')
  gametests=re.findall(r'(\d+) GAME TESTS COMPLETE IN ([\d.]+) s',text)
  verification.append({'mode':name,'passed':report['passed'],'host_elapsed_seconds':entry['host_elapsed_seconds'],
   'finished_at':entry['finished_at'],'diagnostic_directory':diag['directory'],'invocation':invocation,
   'launch_to_exit_seconds':next(e['monotonic'] for e in events if e['phase']=='verifier_process_exit')-next(e['monotonic'] for e in events if e['phase']=='verifier_launch_requested'),
   'checks':checks,'gradle_invocations':cmds,'selected_phase_events':selected,'game_test_completion_messages':gametests})
 save(E/'verification-summary.json',verification)
 calls=read(E/'runtime/calls.json')
 for call in calls:
  folder=E/'runtime/calls'/f"{call['number']:02d}-{call['role']}"
  for attempt in call['attempts']:
   a=folder/f"attempt-{attempt['attempt']:02d}";chunks=[json.loads(l) for l in (a/'response.ndjson').read_text().splitlines() if l]
   attempt['terminal_metadata']=[c for c in chunks if c.get('done')]
   attempt['provider_errors']=[c['error'] for c in chunks if c.get('error')]
   body=read(a/'wire-request.json');attempt['context_configuration']={'options':body['options'],'truncate':body['truncate'],'stream':body['stream']}
   assert body['model']=='qwen2.5-coder:14b' and body['options']=={'temperature':0.1,'num_predict':2048,'num_ctx':12288} and body['truncate'] is False
 save(E/'model-runtime-summary.json',calls)
 samples=[]
 for p in (E/'runtime').glob('*.json'):
  s=read(p)
  if not isinstance(s,dict) or 'host_memory' not in s:continue
  host=s.get('host_memory',{}).get('data',{}).get('host',{})
  gpu=s.get('gpu_memory',{}).get('stdout','').strip().split(',')
  models=s.get('/api/ps',{}).get('models',[])
  samples.append({'file':p.relative_to(HERE).as_posix(),'label':s['label'],'started_at':s['started_at'],
   'finished_at':s['finished_at'],'free_host_gib':host.get('free_physical_kib',0)/1024**2,
   'free_virtual_gib':host.get('free_virtual_kib',0)/1024**2,'commit_limit_bytes':host.get('commit_limit_bytes'),
   'committed_bytes':host.get('committed_bytes'),'gpu_free_mib':int(gpu[-1]) if len(gpu)>=6 else None,
   'gpu_used_mib':int(gpu[-2]) if len(gpu)>=6 else None,'resident':any(m.get('name')=='qwen2.5-coder:14b' for m in models),
   'model_runtime':[{k:m.get(k) for k in ('name','digest','context_length','size','size_vram','expires_at')} for m in models]})
 samples.sort(key=lambda r:r['started_at'])
 resource={'samples':samples,'sample_count':len(samples),'minimum_observed_free_host_gib':min(s['free_host_gib'] for s in samples),
  'minimum_observed_free_virtual_gib':min(s['free_virtual_gib'] for s in samples),
  'minimum_observed_free_gpu_mib':min(s['gpu_free_mib'] for s in samples if s['gpu_free_mib'] is not None),
  'limitations':'Read-only asynchronous boundary and approximately 30-second samples; not continuous extrema or a causal resource diagnosis.'}
 save(E/'resource-summary.json',resource)
 stage=LIVE/'runs'/rid/'stage';frozen=read(HERE/'FREEZE.json');task=frozen['tasks'][0]
 hashes={'baseline_sha256':env.external_root.tree_sha256(Path(frozen['baseline']['root'])),
  'unpromoted_external_candidate_sha256':env.external_root.tree_sha256(Path(run['metadata']['external_root']['candidate_root'])),
  'verified_stage_sha256':env.external_root.tree_sha256(stage),'verified_source_sha256':sha(stage/task['files'][0]),
  'stage_path':str(stage),'applied':run['applied'],'promotion_allowed':run['metadata']['external_root']['promotion_allowed']}
 assert hashes['baseline_sha256']==frozen['baseline']['sha256']==hashes['unpromoted_external_candidate_sha256']
 assert hashes['verified_stage_sha256']==read(LIVE/'verifications/targeted-01/candidate.json')['tree_sha256']
 save(E/'candidate-integrity.json',hashes)
 summary={'study':HERE.name,'run_id':rid,'classification':'LOCAL_RUNTIME_FAILURE','failure_role':'reviewer',
  'hive_status':run['status'],'frozen_acceptance':True,'full_gate_passed':True,'reviewer_approved':False,'promoted':False,
  'planner_attempts':len(run['plan_attempts']),'logical_model_calls':len(calls),'http_attempts':sum(len(c['attempts']) for c in calls),
  'http_500_errors':2,'planner_corrections':0,'worker_structural_corrections':0,'worker_targeted_corrections':0,
  'revised_proposal_classification':'NOT_APPLICABLE: initial edit passed; no correction or second proposal',
  'furthest_verified_transition':'FULL GATE; subsequent reviewer runtime failure',
  'trajectory':[{'transition':n,'status':'REACHED'} for n in ['TASK','PLANNER CALL','PLAN','PLAN VALIDATION','OWNERSHIP','WORKER DISPATCH','WORKER RESPONSE','EDIT PREFLIGHT','EXECUTABLE EDIT','TARGETED VERIFICATION','TARGETED RESULT','FROZEN ACCEPTANCE','FULL GATE']]+
   [{'transition':n,'status':'NOT_NEEDED'} for n in ['WORKER CORRECTION','REVISED WORKER RESPONSE','REVISED EDIT','TARGETED REVERIFICATION']]+
   [{'transition':'REVIEWER','status':'LOCAL_RUNTIME_FAILURE_AFTER_TWO_HTTP_500_ATTEMPTS'},{'transition':'PROMOTION','status':'NOT_AUTHORIZED_OR_PERFORMED'}],
  'stage_events':[{**e,'at_utc':utc(e['at'])} for e in run['stage_events']],
  'trial_wall_seconds':result['wall_seconds'],'complete_usage_only':{'input_tokens':sum(c.get('input_tokens',0) for c in calls),'output_tokens':sum(c.get('output_tokens',0) for c in calls)},
  'aggregate_usage':'UNKNOWN: reviewer did not complete; known completed usage must not be called total usage',
  'model_request_elapsed_seconds':sum(c['elapsed_seconds'] for c in calls),'original_task_delivered':read(E/'semantic-fidelity.json')['exact_original_task_present']}
 save(E/'trajectory.json',summary)
 print(json.dumps({'trajectory':summary,'resources':{k:v for k,v in resource.items() if k!='samples'},'hashes':hashes},indent=2))
if __name__=='__main__':main()
