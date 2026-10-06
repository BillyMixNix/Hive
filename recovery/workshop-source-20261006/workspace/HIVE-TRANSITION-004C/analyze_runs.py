import json,re,sys
from pathlib import Path
from bootstrap import HERE,save
rows=[]
for root in sorted((HERE/'evidence/runs').glob('*')):
 if not (root/'result.json').exists():continue
 events=[json.loads(x) for x in (root/'diagnostics/verification-events.jsonl').read_text().splitlines()]
 phases={r['phase']:r for r in events}
 launch=phases.get('verifier_launch_requested',{}).get('monotonic')
 times={r['phase']:round(r['monotonic']-launch,3) for r in events if launch and r['phase']!='process_output'}
 streams={s:''.join(r['source_event']['text'] for r in events if r['phase']=='process_output' and r['source_event'].get('stream')==s) for s in ['stdout','stderr']}
 for s,text in streams.items():(root/f'child-{s}.log').write_text(text,encoding='utf-8')
 diagnostics=[]
 for text in streams.values():
  for line in text.splitlines():
   if line.startswith('HIVE_GRADLE_DIAGNOSTIC '):
    try:diagnostics.append(json.loads(line.split(' ',1)[1]))
    except ValueError:pass
 save(root/'gradle-diagnostics.json',diagnostics)
 output='\n'.join(streams.values());plain=re.sub(r'\x1b\[[0-9;]*m','',output);tasks=re.findall(r'^> Task (.*)$',plain,re.M)
 def duration(a,b):
  if a in phases and b in phases:return round(phases[b]['monotonic']-phases[a]['monotonic'],3)
 result=json.loads((root/'result.json').read_text())
 row={'run':root.name,'passed':result['report']['passed'],'times_since_launch':times,
      'durations':{'source':duration('project_materialization_started','project_available'),
                   'wrapper':duration('wrapper_copy_started','wrapper_copy_complete'),
                   'downloaded_inputs':duration('external_inputs_copy_started','external_inputs_copy_complete'),
                   'nfrt_seed':duration('nfrt_seed_copy_started','nfrt_seed_copy_complete'),
                   'gradle':duration('gradle_invoked','gradle_returned')},
      'tasks':tasks,'native_runtime_messages':re.findall(r'^.*(?:Total runtime|Used cache of).*$',plain,re.M),
      'full_compilation_policy_installed':'fresh_full_compilation_policy_installed' in phases,
      'task_markers':[{'marker':r['source_event']['marker'],'seconds_since_launch':round(r['monotonic']-launch,3)} for r in events if r['phase']=='gradle_output_marker'],
      'java_actions':[{'task':d['task'],'source_count':len(d.get('sources',[])),
                       'classpath_count':len(d.get('classpath',[])),
                       'classpath_bytes':sum(x['bytes'] for x in d.get('classpath',[])),
                       'wall_timestamp':d['wallTimestamp'],'incremental':d.get('incremental'),
                       'fork':d.get('fork'),'annotationProcessorPath':d.get('annotationProcessorPath'),
                       'compilerArgs':d.get('compilerArgs')} for d in diagnostics if d['event']=='java_compile_actions_entered'],
      'checks':result['report']['checks']}
 row['durations']['input_inventory']=duration('external_input_inventory_started','external_input_inventory_complete')
 row['input_families']=[]
 for r in events:
  if r['phase']=='external_input_family_complete':
   family=r['source_event']['family'];start=next(e for e in events if e['phase']=='external_input_family_started' and e['source_event']['family']==family)
   row['input_families'].append({'family':family,'seconds':round(r['monotonic']-start['monotonic'],3),'bytes':r['source_event']['bytes'],'files':r['source_event']['files']})
 row['compile_action_durations']=[]
 for d in diagnostics:
  if d['event']=='java_compile_actions_complete':
   start=next(x for x in diagnostics if x['event']=='java_compile_actions_entered' and x['task']==d['task'])
   row['compile_action_durations'].append({'task':d['task'],'seconds':round((d['nanoTime']-start['nanoTime'])/1e9,3)})
 rows.append(row)
save(HERE/'evidence/timings.json',rows)
print(json.dumps([{k:v for k,v in r.items() if k not in ['checks','times_since_launch','native_runtime_messages']} for r in rows],indent=2))
