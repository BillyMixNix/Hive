"""Summarize completed bounded diagnostics and audit immutable inputs."""
import ast,hashlib,json,re,sys
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;E=HERE/'evidence';P=HERE.parent/'HIVE-TRANSITION-004'
assert all((E/'runs'/case/'result.json').exists() for case in ['baseline','preserved']), 'Wait until both replays have exited before integrity hashing.'
def read(p):return json.loads(p.read_text())
def save(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
inputs=[]
for case in ['baseline','preserved']:
 raw=read(E/'runs/inputs/probe-results.json')
 row=next(x for x in raw if x['case']==case)
 text=next(line.removeprefix('HIVE_ARTIFACT_INPUTS ') for line in row['result']['stdout'].splitlines() if line.startswith('HIVE_ARTIFACT_INPUTS '))
 value=json.loads(text);save(E/'runs/inputs'/f'{case}-inputs.json',value)
 inputs.append(json.loads(json.dumps(value).replace('/work/'+case,'<project>')))
assert inputs[0]==inputs[1]
paths=inputs[0]['inputProperties']['artifacts']+inputs[0]['inputFiles']
assert all(not x['path'].startswith('<project>/src/') for x in paths)
assert inputs[0]['enableNativeCache'] is True
save(E/'input-comparison.json',{'identical':True,'normalization':'Only /work/baseline or /work/preserved replaced by <project>.',
 'artifact_manifest_entries':len(inputs[0]['inputProperties']['artifactManifestEntries']),
 'artifact_files_hashed':len(inputs[0]['inputProperties']['artifacts']),
 'application_source_in_declared_reconstruction_inputs':False,'graph':inputs[0]['graph'],
 'native_cache_enabled':True,'output_files':inputs[0]['outputFiles']})
timings=[]
for case in ['baseline','preserved']:
 root=E/'runs'/case
 if not (root/'result.json').exists():continue
 events=[json.loads(line) for line in (root/'diagnostics/verification-events.jsonl').read_text().splitlines()]
 def evt(phase):return next((x for x in events if x['phase']==phase),None)
 def span(a,b):
  x,y=evt(a),evt(b)
  if not x or not y:return None
  if x.get('origin')==y.get('origin')=='container':return round((y['source_event']['elapsed_ms']-x['source_event']['elapsed_ms'])/1000,3)
  return round((y['elapsed_ms']-x['elapsed_ms'])/1000,3)
 stdout=''.join(x['source_event']['text'] for x in events if x['phase']=='process_output' and x['source_event']['stream']=='stdout')
 plain=re.sub(r'\x1b\[[0-9;]*m','',stdout)
 stderr=''.join(x['source_event']['text'] for x in events if x['phase']=='process_output' and x['source_event']['stream']=='stderr')
 (root/'child-stdout.log').write_text(stdout,encoding='utf-8');(root/'child-stdout-plain.log').write_text(plain,encoding='utf-8');(root/'child-stderr.log').write_text(stderr,encoding='utf-8')
 gate=read(root/'gate-report.json') if (root/'gate-report.json').exists() else None
 summary={'case':case,'result':read(root/'result.json'),
  'launch_to_container_s':span('verifier_launch_requested','container_verifier_started'),
  'native_input_copy_s':span('external_inputs_copy_started','diagnostic_intermediate_seed_started'),
  'seed_copy_s':span('diagnostic_intermediate_seed_started','diagnostic_intermediate_seed_complete'),
  'before_gradle_s':span('verifier_launch_requested','gradle_invoked'),
  'gradle_s':span('gradle_invoked','gradle_returned'),
  'gradle_exposure_to_timeout_s':span('gradle_invoked','timeout_fired'),
  'nfrt_reported_runtime_s':[float(v) for v in re.findall(r'Total runtime: ([0-9.]+)s',plain)],
  'cached_nodes':re.findall(r'Used cache of (\w+)',plain),
  'cache_hits':[line for line in plain.splitlines() if 'cache' in line.lower()],
  'tasks':[line for line in plain.splitlines() if line.startswith('> Task')],
  'gate_checks':gate['checks'] if gate else None}
 timings.append(summary)
save(E/'timings.json',timings)
original=P/'repaired-workshop/verification/jvm_runner.py';overlay=E/'seeded_jvm_runner.py'
def functions(p):return {x.name:ast.dump(x) for x in ast.parse(p.read_text()).body if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef))}
a,b=functions(original),functions(overlay)
changed=[k for k in a if a[k]!=b[k]]
assert changed==['_copy_external_build_inputs'],changed
state=read(E/'inputs.json');cache=Path(state['approved']['approved_cache_root']);baseline=Path(state['freeze']['baseline']['root'])
sys.path.insert(0,str(P/'repaired-workshop'))
from workshop import external_root
source_checks={}
for case in ['baseline','preserved']:
 previous=read(E/'prepared'/case/'integrity-before.json')
 source_checks[case]={'candidate_unchanged':external_root.tree_sha256(E/'prepared'/case/'candidate')==previous['candidate_sha256'],
   'sanitized_unchanged':external_root.tree_sha256(E/'prepared/sanitized'/case)==previous['sanitized_sha256']}
historical=cache/'.hive-priming-provenance/e5a7c314b902/artifacts.manifest.json'
manifest=read(historical)
cache_unchanged=all(sha(cache/r['path'])==r['sha256'] for r in manifest['artifacts'])
prior=read(E/'prior-before.json')
prior_unchanged=all(sha(HERE.parent/name)==expected for name,expected in prior.items())
audit={'existing_evidence_files_unchanged':prior_unchanged,'prior_count':len(prior),
 'approved_cache_manifested_files_checked':len(manifest['artifacts']),'approved_cache_unchanged':cache_unchanged,
 'baseline_unchanged':external_root.tree_sha256(baseline)==state['freeze']['baseline']['sha256'],
 'source_checks':source_checks,'diagnostic_runner_changed_functions':changed,
 'frozen_verifier_gate_functions_identical':all(a[k]==b[k] for k in a if k!='_copy_external_build_inputs'),
 'model_calls':0,'timeout_seconds':240,'production_edits':0,
 'new_targeted_runs':len(timings),'task_input_probe_containers':1}
save(E/'integrity-audit.json',audit)
assert prior_unchanged and cache_unchanged and audit['baseline_unchanged']
assert all(all(c.values()) for c in source_checks.values())
print(json.dumps({'timings':[{k:v for k,v in row.items() if k not in ('gate_checks',)} for row in timings],'audit':audit},indent=2))
