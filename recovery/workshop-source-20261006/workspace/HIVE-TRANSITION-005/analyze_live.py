"""Read-only trajectory analysis after the single trial. No inference."""
import json,sys
from pathlib import Path
sys.dont_write_bytecode=True
from bootstrap import HERE,sha,save
sys.path.insert(0,str(HERE/'repaired-workshop'))
from workshop import hive
sys.path.insert(0,str(HERE.parent/'hive-transition-003/tooling/python'))
from jsonschema import Draft202012Validator
root=HERE/'evidence/live-diagnostic'
result=json.loads((root/'raw_results.json').read_text())[0]
run=json.loads((root/'runs'/result['run_id']/'run.json').read_text())
task=run['request'];plan=run.get('plan',{})
old=HERE.parent/'hive-transition-003/evidence/live-diagnostic/wire'
oldproposal=json.loads((old/'02/raw-response.txt').read_text())
oldplanner=json.loads((old/'01/wire-request.json').read_text())
rows=[];workers=[]
for folder in sorted((root/'wire').iterdir()):
 body=json.loads((folder/'wire-request.json').read_text())
 chunks=[json.loads(line) for line in (folder/'response.ndjson').read_text().splitlines() if line] if (folder/'response.ndjson').exists() else []
 raw=''.join(x.get('message',{}).get('content','') for x in chunks)
 (folder/'raw-response.txt').write_text(raw,encoding='utf-8')
 terminal=next((x for x in reversed(chunks) if x.get('done')),None)
 prompt=body['messages'][-1]['content'];(folder/'prompt.txt').write_text(prompt,encoding='utf-8')
 try:parsed=json.loads(raw)
 except ValueError:parsed=None
 role=next((r for r in ('planner','backend','ui','tests','reviewer') if f'bounded {r} agent' in body['messages'][0]['content']),'unknown')
 http_status=json.loads((folder/'http-response.json').read_text())['status_code'] if (folder/'http-response.json').exists() else None
 provider_errors=[x['error'] for x in chunks if x.get('error')]
 schema_errors=([x.message for x in Draft202012Validator(body['format']).iter_errors(parsed)] if parsed is not None else ['invalid JSON']) if raw else []
 row={'call':folder.name,'role':role,'correction':prompt.startswith('TARGETED VERIFICATION CORRECTION'),
    'original_task_exactly_present':task in prompt,'schema_valid':not schema_errors if raw else None,'schema_errors':schema_errors,
    'http_status':http_status,'provider_errors':provider_errors,'generated_response_present':bool(raw),
    'num_ctx':body['options'].get('num_ctx'),'truncate':body.get('truncate'),
    'output_cap':body['options'].get('num_predict'),'terminal':terminal,
    'task_sha256':__import__('hashlib').sha256(task.encode()).hexdigest(),
    'prompt_sha256':sha(folder/'prompt.txt'),'raw_sha256':sha(folder/'raw-response.txt')}
 if role=='planner':row['planner_content_identical_to_transition_003']=prompt==oldplanner['messages'][-1]['content']
 if row['correction']:
  diag=prompt.split('TARGETED VERIFICATION DIAGNOSTIC (read-only data, not instructions):\n',1)[1].split('\n\nPREVIOUS PROPOSAL',1)[0]
  row['diagnostic']=json.loads(diag)
  (folder/'correction-diagnostic.json').write_text(diag,encoding='utf-8')
 if role in ('backend','ui','tests') and isinstance(parsed,dict) and parsed.get('status')=='implemented':
  row['proposal_signature']=hive._edit_signature(parsed)
  row['differs_from_transition_003']=hive._edit_signature(parsed)!=hive._edit_signature(oldproposal)
  row['task_in_worker_contract']=task in prompt
  row['local_acceptance_present']=all(x in prompt for x in plan.get('worker_acceptance',{}).get(role,[]))
  workers.append(row)
 rows.append(row)
verify=[]
for folder in sorted((root/'verifications').glob('*')):
 r=json.loads((folder/'result.json').read_text());meta=json.loads((folder/'candidate.json').read_text())
 tests=[t for c in r['report']['checks'] if isinstance(c.get('detail'),dict) for t in c['detail'].get('tests',[])]
 verify.append({'attempt':folder.name,'passed':r['report']['passed'],'tests':tests,
    'host_elapsed_seconds':r['host_elapsed_seconds'],'candidate':meta,'diff_sha256':sha(folder/'candidate.diff')})
full=json.loads((root/'full-gate.json').read_text()) if (root/'full-gate.json').exists() else None
summary={'run_id':result['run_id'],'result':result,'calls':rows,'verifications':verify,
 'errors':run.get('errors',[]),'http_attempts':len(rows),'successful_model_responses':sum(bool(r['generated_response_present']) for r in rows),
 'planner_first_attempt_valid':run['plan_attempts'][0]['status']=='accepted' if run.get('plan_attempts') else None,
 'initial_worker_task_complete':workers[0]['original_task_exactly_present'] if workers else None,
 'initial_differs_from_transition_003':workers[0]['differs_from_transition_003'] if workers else None,
 'correction_materially_different':workers[1]['proposal_signature']!=workers[0]['proposal_signature'] if len(workers)>1 else None,
 'repeated_proposal_rejected':any(x.get('exception_type')=='RepeatedFailedProposal' for x in run.get('errors',[])),
 'frozen_acceptance_reached':any(v['passed'] for v in verify),'full_gate':full,
 'full_gate_passed':bool(full and full['report']['passed']),'promoted':run.get('applied',False)}
save(HERE/'evidence/live-summary.json',summary)
if not summary['successful_model_responses']:
 save(HERE/'evidence/live-input-measurements.json',[{'http_attempt':r['call'],'known_sent':True,
     'http_status':r['http_status'],'context':r['num_ctx'],'output_cap':r['output_cap'],'truncate':r['truncate'],
     'provider_input_tokens':None,'model_visible':'UNKNOWN; no completed model token accounting',
     'planner_content_identical_to_transition_003':r.get('planner_content_identical_to_transition_003')}
     for r in rows])
print(json.dumps({k:v for k,v in summary.items() if k not in ('calls','verifications','full_gate')},indent=2))
