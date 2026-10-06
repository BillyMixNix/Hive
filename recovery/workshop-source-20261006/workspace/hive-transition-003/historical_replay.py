"""No models: compare original T002 and repaired deterministic planner pipelines."""
import json,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
if len(sys.argv)==1:
    from setup_study import save
    result={variant:json.loads(subprocess.check_output([sys.executable,str(Path(__file__).resolve()),variant],text=True)) for variant in ('before','after')}
    for a,b in zip(result['before'],result['after'],strict=True):
        assert a['id']==b['id'] and a['accepted']==b['accepted'] and a.get('error')==b.get('error')
    save(HERE/'evidence/historical-replay.json',result)
    print(len(result['after']),'historical plans replayed; no controller decision/rejection changed.')
    raise SystemExit
sys.path.insert(0,str(HERE/'tooling/python'))
sys.path.insert(0,str((HERE.parent/'HIVE-TRANSITION-002' if sys.argv[1]=='before' else HERE)/'repaired-workshop'))
from jsonschema import Draft202012Validator
from workshop import hive
runs=[('factorial-'+str(t['ordinal']),Path(t['run_artifact'])) for t in json.loads((HERE.parent/'HIVE-TRANSITION-001/failure-taxonomy.json').read_text())['trials']]
runs += [('transition-001-rev1',HERE.parent/'HIVE-TRANSITION-001/evidence/live/01-J001-r1-qwen2.5-coder-14b-hive/run.json'),
         ('transition-001-rev2',HERE.parent/'HIVE-TRANSITION-001/evidence/live-revision2/02-J001-r2-qwen2.5-coder-14b-hive/run.json'),
         ('transition-002',HERE/'evidence/transition-002/run.json')]
results=[]
for label,path in runs:
    run=json.loads(path.read_text());scope=run['metadata']['host_write_scope']
    tokens=[(hive._HOST_WRITE_SCOPE,hive._HOST_WRITE_SCOPE.set(tuple(scope))),
       (hive._ACTIVE_AGENT_SCOPES,hive._ACTIVE_AGENT_SCOPES.set(hive.EXTERNAL_AGENT_SCOPES)),
       (hive._EXTERNAL_ROOT_MODE,hive._EXTERNAL_ROOT_MODE.set(True))]
    try:
        schema=hive._planner_response_schema()
        for attempt in run['plan_attempts']:
            row={'id':label+'-'+str(attempt['attempt']),'dispatch_eligible':[]}
            try:
                parsed=hive._extract_json(attempt['raw']);row['schema_valid']=Draft202012Validator(schema).is_valid(parsed)
                normalized,_=hive._normalize_plan(parsed);hive._validate_host_write_scope(normalized)
                hive._validate_intent_coverage(normalized,run['intent_envelope'])
                row['accepted']=True
                row['dispatch_eligible']=[r for r in hive.AGENT_SCOPES if normalized['worker_files'][r] and not hive._no_change_goal(normalized[r+'_goal'])]
            except Exception as exc:
                row.update(accepted=False,error_type=type(exc).__name__,error=str(exc))
                correction=hive._plan_correction_prompt(run['request'],run['repository_map'],attempt['raw'],exc,run['repository_facts'],run['intent_envelope'],external_mode=True)
                import hashlib
                row['correction_text_sha256']=hashlib.sha256(str(correction).encode()).hexdigest()
                row['correction_schema']=correction.response_schema
            results.append(row)
    finally:
        for var,token in reversed(tokens):var.reset(token)
print(json.dumps(results))
