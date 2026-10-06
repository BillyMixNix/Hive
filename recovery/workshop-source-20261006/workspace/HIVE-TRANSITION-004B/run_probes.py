"""Bounded, offline artifact-input/cache experiments; no model or promotion path."""
import argparse,hashlib,json,os,shutil,subprocess,sys,time,uuid
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;PRIOR=HERE.parent/'HIVE-TRANSITION-004';OUT=HERE/'evidence'
sys.path.insert(0,str(PRIOR));sys.path.insert(0,str(PRIOR/'repaired-workshop'))
import diagnostic_environment as environment
from workshop import external_root,hive_jvm
from workshop.verifier_trace import VerificationTrace

def save(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2)+'\n')
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def prepare():
 approved=environment.approved_environment(environment.reference_freeze())
 before=json.loads((OUT/'inputs.json').read_text());assert approved==before['approved']
 freeze=before['freeze'];base=Path(freeze['baseline']['root']);task=freeze['tasks'][0];assert task['id']=='J001'
 prepared=OUT/'prepared';prepared.mkdir(exist_ok=False)
 for case in ['baseline','preserved']:
  root=prepared/case;candidate=root/'candidate'
  external_root.copy_candidate_tree(base,candidate,root)
  if case=='preserved':
   source=PRIOR/'evidence/transition-003/applied-stage/first-applied-SnapshotFormatter.java'
   assert sha(source)=='a3219f4e0b65847123f6cebc150dbe1a026690bf9887062c25c2941747fef242'
   (candidate/task['files'][0]).write_bytes(source.read_bytes())
  frozen_source=PRIOR/'evidence/verifier-replays/post-regression-baseline/frozen-junit'/task['test_path']
  tests=hive_jvm.freeze_junit_tests(candidate,[{'path':task['test_path'],'class_name':task['test_class'],
    'expected_cases':task['test_cases'],'source':frozen_source.read_text()}])
  artifacts=hive_jvm.store_frozen_junit_tests(tests,root)
  hive_jvm.copy_external_verification_input(candidate,prepared/'sanitized'/case,artifacts)
  assert hive_jvm.inspect_gradle_project(candidate)==approved['jvm_profile']
  save(root/'integrity-before.json',{'candidate_sha256':external_root.tree_sha256(candidate),
       'sanitized_sha256':external_root.tree_sha256(prepared/'sanitized'/case),'frozen_tests':artifacts})
 cache=Path(approved['approved_cache_root'])
 historical=cache/'.hive-priming-provenance/e5a7c314b902'
 inventory=json.loads((historical/'artifacts.manifest.json').read_text())
 provenance=json.loads((historical/'provenance.json').read_text())
 assert provenance['candidate_sha256']==freeze['baseline']['sha256']
 assert sha(historical/'artifacts.manifest.json')==provenance['artifact_manifest_sha256']
 entries=[{**r,'path':Path(r['path']).name} for r in inventory['artifacts'] if r['path'].startswith('caches/neoformruntime/intermediate_results/')]
 assert len(entries)==22 and sum(r['size'] for r in entries)==163178447
 native=cache/'caches/neoformruntime/intermediate_results'
 assert {p.name for p in native.iterdir()}=={r['path'] for r in entries}
 for row in entries:
  p=native/row['path'];assert not p.is_symlink() and sha(p)==row['sha256'] and p.stat().st_size==row['size']
 save(OUT/'seed-manifest.json',{'entries':entries,'priming_manifest_sha256':provenance['artifact_manifest_sha256'],
    'baseline_sha256':freeze['baseline']['sha256'],'source':str(native),'scope':'Native NFRT intermediate outputs only. No mod outputs or test results.'})
 save(OUT/'priming-provenance.json',provenance)
 source=PRIOR/'repaired-workshop/verification/jvm_runner.py'
 appended=(HERE/'seed_hook.py').read_bytes()
 (OUT/'seeded_jvm_runner.py').write_bytes(source.read_bytes()+b'\n\n'+appended)
 save(OUT/'preparation.json',{'approved':approved,'seed_manifest_sha256':sha(OUT/'seed-manifest.json'),
    'original_runner_sha256':sha(source),'overlay_sha256':sha(OUT/'seeded_jvm_runner.py'),
    'diagnosis_sha256':sha(HERE/'diagnosis-before-probes.md'),'model_calls':0,'timeout_seconds':240})
 print('Prepared immutable-source candidates and sealed-baseline native intermediate seed.',flush=True)

def command_for(case,graph=False):
 inv=json.loads((PRIOR/'evidence/verifier-replays/post-regression-baseline/diagnostics/invocation.json').read_text())
 name='hive-004b-'+uuid.uuid4().hex[:12];cmd=list(inv['argv']);cmd[cmd.index('--name')+1]=name
 for i,arg in enumerate(cmd):
  if arg.startswith('type=bind,source=') and ',target=/source,readonly' in arg:
   src=OUT/'prepared/sanitized' if graph else OUT/'prepared/sanitized'/case
   cmd[i]=f'type=bind,source={src},target=/source,readonly'
  elif arg.startswith('type=bind,source=') and ',target=/opt/verifier/jvm_runner.py,readonly' in arg and not graph:
   cmd[i]=f'type=bind,source={OUT/"seeded_jvm_runner.py"},target=/opt/verifier/jvm_runner.py,readonly'
  elif arg.startswith('HIVE_VERIFICATION_RUN_ID='):cmd[i]=f'HIVE_VERIFICATION_RUN_ID=004B-{case}'
 image_index=len(cmd)-3
 extras=['--mount',f'type=bind,source={HERE},target=/probe,readonly']
 if graph:
  extras+=['--entrypoint','python3'];cmd[-2]='/probe/probe_container.py'
 else:
  manifest=json.loads((OUT/'seed-manifest.json').read_text())
  extras+=['--mount',f'type=bind,source={manifest["source"]},target=/diagnostic-intermediates,readonly',
           '--env',f'HIVE_DIAGNOSTIC_SEED_MANIFEST_SHA256={sha(OUT/"seed-manifest.json")}']
 cmd[image_index:image_index]=extras
 return cmd,name

def run(case,graph=False):
 preparation=json.loads((OUT/'preparation.json').read_text())
 # Revalidate immutable baseline, image and approved cache before every bounded container.
 assert environment.approved_environment(environment.reference_freeze())==preparation['approved']
 root=OUT/'runs'/case;root.mkdir(parents=True,exist_ok=False)
 cmd,name=command_for(case,graph)
 trace=VerificationTrace(root/'candidate','input-probe' if graph else 'diagnostic-seeded-targeted',root/'diagnostics')
 result={'case':case,'model_calls':0,'verification':not graph,'diagnostic_only':True,'promoted':False,'timeout_seconds':240}
 timer=time.monotonic()
 try:
  cp=trace.capture(cmd,timeout=240,docker=cmd[0],container=name)
  result.update(returncode=cp.returncode,timed_out=False)
  if graph:
   probe_rows=[json.loads(line) for line in cp.stdout.splitlines() if line.startswith('{')]
   save(root/'probe-results.json',probe_rows)
   assert cp.returncode==0 and len(probe_rows)==2
  else:
   report=json.loads(cp.stdout);report['passed']=bool(report.get('passed')) and cp.returncode==0
   save(root/'gate-report.json',report);result['gate_passed']=report['passed']
 except subprocess.TimeoutExpired:
  result.update(timed_out=True,gate_passed=False)
 finally:
  result['outer_elapsed_seconds']=round(time.monotonic()-timer,3)
  removed=subprocess.run([cmd[0],'rm','-f',name],capture_output=True,text=True,timeout=10)
  check=subprocess.run([cmd[0],'inspect',name],capture_output=True,text=True,timeout=8)
  result['cleanup']={'removal_returncode':removed.returncode,'removal_stdout':removed.stdout,'removal_stderr':removed.stderr,
                     'inspect_returncode':check.returncode,'inspect_stdout':check.stdout,'inspect_stderr':check.stderr,
                     'container_absent':check.returncode!=0 and 'no such' in check.stderr.casefold()}
  trace.event('diagnostic_cleanup_complete',container_absent=result['cleanup']['container_absent'])
  save(root/'result.json',result)
 print(json.dumps(result),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','inputs','seeded-baseline','seeded-preserved'])
 mode=parser.parse_args().mode
 if mode=='prepare':prepare()
 elif mode=='inputs':run('inputs',True)
 else:run(mode.removeprefix('seeded-'))
