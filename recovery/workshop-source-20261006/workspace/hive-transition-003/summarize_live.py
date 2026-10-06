"""Read-only analysis of the one completed live trial; no model or verifier calls."""
import difflib, hashlib, json
from pathlib import Path
from setup_study import save
HERE=Path(__file__).resolve().parent
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

root=HERE/'evidence/live-diagnostic'
results=read(root/'raw_results.json'); assert len(results)==1
result=results[0]
trial=root/'01-J001-r1-qwen2.5-coder-14b-hive'
run=read(trial/'run.json'); calls=read(trial/'calls.json')
freeze=read(HERE/'FREEZE.json')
path='src/main/java/dev/atmcompanion/state/SnapshotFormatter.java'
baseline=Path(freeze['baseline']['root'])/path
stage=root/'runs'/run['id']/'stage'/path
snapshot=HERE/'evidence/live-stage-observation/first-applied-SnapshotFormatter.java'
bodies=[read(root/'wire'/f'{i:02}'/'wire-request.json') for i in range(1,5)]
measurements=read(HERE/'evidence/live-input-measurements.json')
prior=read(HERE/'evidence/transition-002/wire/02/wire-request.json')
first=run['targeted_repairs'][0]
assert first['original_raw']==first['repair_raw']
assert len(run['plan_attempts'])==1 and run['plan_attempts'][0]['status']=='accepted'
assert [c['role'] for c in calls]==['planner','backend','backend','reviewer']
assert all(m['full_input_count_matches'] and m['schema_valid'] for m in measurements)
prompt_equal=bodies[0]['messages']==prior['messages']
other_fields_equal={k:v for k,v in bodies[0].items() if k!='format'}=={k:v for k,v in prior.items() if k!='format'}
assert prompt_equal and other_fields_equal
patch=''.join(difflib.unified_diff(baseline.read_text().splitlines(True), snapshot.read_text().splitlines(True),
 fromfile='baseline/'+path,tofile='temporary-stage/'+path))
(HERE/'evidence/live-stage-observation/first-applied.patch').write_bytes(patch.encode())
summary={
 'run_id':run['id'],'classification':result['classification'],'status':result['status'],
 'exactly_one_trial':len(results)==1,'model_calls':[c['role'] for c in calls],
 'planner_first_attempt_valid':True,'planner_corrections':result['planner_corrections'],
 'first_request_equal_to_transition_002_except_format':other_fields_equal,
 'ownership':run['plan']['worker_files'],'skipped_roles':{r:run['agents'][r] for r in ('ui','tests')},
 'worker_source_grounding':{
  'entire_owned_baseline_file_in_initial_prompt':baseline.read_text() in bodies[1]['messages'][-1]['content'],
  'entire_owned_baseline_file_in_correction_prompt':baseline.read_text() in bodies[2]['messages'][-1]['content'],
  'exact_original_ascii_requirement_in_planner_prompt':'unchanged behavior for ordinary ASCII lines' in bodies[0]['messages'][-1]['content'],
  'ascii_requirement_explicit_in_worker_prompt':'ASCII' in bodies[1]['messages'][-1]['content'],
  'note':'Complete source grounding does not prove complete semantic preservation of planner-derived acceptance.'},
 'input_tokens':[m['rendered_tokens'] for m in measurements],
 'output_cap_slack':[m['full_output_cap_slack'] for m in measurements],
 'temporary_scoped_edit_applied':sha(snapshot)!=sha(baseline),
 'targeted_verification_attempted':True,'targeted_verification':first['diagnostic']['targeted_verification'],
 'targeted_corrections':len(run['targeted_repairs']),'identical_correction_rejected':True,
 'final_error':run['errors'][0]['exception_type']+': '+run['errors'][0]['exception_message'],
 'frozen_acceptance':'No result; reaching individual JUnit cases is not observable after verifier timeout.',
 'full_gate_executed':not run['verification'].get('full_gate_skipped',False),
 'final_changed_files':run['changed_files'],'final_stage_file_restored_to_baseline':sha(stage)==sha(baseline),
 'external_candidate_hash_matches_baseline':result['candidate_sha256']==freeze['baseline']['sha256'],
 'applied':run['applied'],
 'furthest_verified_transition':'Executable scoped edit -> targeted deterministic verifier invocation (240-second timeout; no acceptance).',
 'wall_seconds':result['wall_seconds']}
assert summary['worker_source_grounding']['entire_owned_baseline_file_in_initial_prompt']
assert summary['worker_source_grounding']['entire_owned_baseline_file_in_correction_prompt']
assert summary['final_stage_file_restored_to_baseline'] and summary['external_candidate_hash_matches_baseline']
save(HERE/'evidence/live-summary.json',summary)
print(json.dumps(summary,indent=2))
