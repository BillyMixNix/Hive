"""Summarize observed phase boundaries; never infer starts from task markers."""
import json
from pathlib import Path
from setup_study import HERE,save
rows=[]
for root in sorted((HERE/'evidence/verifier-replays').iterdir()):
 path=root/'diagnostics/verification-events.jsonl'
 if not path.exists():continue
 events=[json.loads(s) for s in path.read_text().splitlines()]
 def event(name):return next((e for e in events if e['phase']==name),None)
 def elapsed(a,b):
  x,y=event(a),event(b)
  if not x or not y:return None
  if x.get('origin')==y.get('origin')=='container':return round((y['source_event']['elapsed_ms']-x['source_event']['elapsed_ms'])/1000,3)
  return round((y['elapsed_ms']-x['elapsed_ms'])/1000,3)
 child={label:''.join(e['source_event'].get('text','') for e in events if e['phase']=='process_output' and e.get('source_event',{}).get('stream')==label) for label in ('stdout','stderr')}
 for label,data in child.items():(root/'diagnostics'/('child-'+label+'.log')).write_bytes(data.encode())
 exit_result=json.loads((root/'result.json').read_text()) if (root/'result.json').exists() else None
 markers=[e['source_event']['marker'] for e in events if e['phase']=='gradle_output_marker']
 row={'case':root.name,'complete':exit_result is not None,
 'host_preflight_s':elapsed('verification_requested','verifier_launch_requested'),
 'launch_to_container_event_s':elapsed('verifier_launch_requested','container_verifier_started'),
 'project_copy_s':elapsed('project_materialization_started','project_available'),
 'wrapper_copy_s':elapsed('wrapper_copy_started','wrapper_copy_complete'),
 'native_inputs_copy_s':elapsed('external_inputs_copy_started','external_inputs_copy_complete'),
 'outer_budget_before_gradle_s':elapsed('verifier_launch_requested','gradle_invoked'),
 'gradle_wall_s':elapsed('gradle_invoked','gradle_returned'),
 'gradle_exposure_before_outer_timeout_s':elapsed('gradle_invoked','timeout_fired'),
 'docker_total_s':elapsed('verifier_launch_requested','timeout_fired') or elapsed('verifier_launch_requested','verifier_process_exit'),
 'post_process_to_return_s':elapsed('timeout_fired' if event('timeout_fired') else 'verifier_process_exit','verification_returned'),
 'last_phase':events[-1]['phase'],'task_markers':markers,'stdout_tail':child['stdout'][-2500:],
 'stderr_tail':child['stderr'][-1500:], 'result':exit_result,
 'process_samples':[e for e in events if e['phase']=='process_state']}
 rows.append(row)
save(HERE/'evidence/timing-comparison.json',rows)
for r in rows:
 print(json.dumps({k:v for k,v in r.items() if k not in ('result','process_samples','stderr_tail','stdout_tail')},indent=2))
