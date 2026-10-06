"""Verifier-only comparison. No provider/model calls and no promotion path."""
import argparse,datetime,json,os,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
os.environ.pop('OPENAI_API_KEY',None)
from setup_study import HERE,PRIOR,save,sha
import diagnostic_environment as env
from workshop import external_root,hive_jvm,hive_verifier

ASTRA=Path(r'C:\Users\billy\Documents\Codex\2026-09-13\referenced-chatgpt-conversation-this-is-an\work\HIVE-ASTRA-J001-INDEPENDENT-VERIFY')
def main():
 parser=argparse.ArgumentParser();parser.add_argument('phase');parser.add_argument('cases',nargs='+',choices=['baseline','preserved','known-good'])
 args=parser.parse_args()
 freeze=json.loads((PRIOR/'FREEZE.json').read_text())
 baseline=Path(freeze['baseline']['root']); task=next(t for t in freeze['tasks'] if t['id']=='J001')
 print('Checking unchanged baseline, image and approved caches',flush=True)
 approved=env.approved_environment(env.reference_freeze())
 assert approved['baseline_sha256']==freeze['baseline']['sha256']
 assert approved['verifier_image_id']==freeze['verifier_image_id']
 assert hive_verifier.JVM_CONTAINER_LIMITS==freeze['verifier_limits']
 frozen_source=PRIOR/'evidence/live-diagnostic/runs/45ad10e6dd49/frozen-junit'/task['test_path']
 assert sha(frozen_source)==task['test_sha256']
 for case in args.cases:
  root=HERE/'evidence/verifier-replays'/f'{args.phase}-{case}';root.mkdir(parents=True,exist_ok=False)
  candidate=root/'candidate'
  source=ASTRA/'HIVE-ASTRA-J001/candidate' if case=='known-good' else baseline
  source_hash=external_root.tree_sha256(source)
  if case=='known-good':assert source_hash=='ecb294b3b7b9a0bd87e365e9f30d2b07ca083f65734abe0a433f1b69b700d4a6'
  external_root.copy_candidate_tree(source,candidate,root)
  if case=='preserved':
   saved=HERE/'evidence/transition-003/applied-stage/first-applied-SnapshotFormatter.java'
   assert sha(saved)=='a3219f4e0b65847123f6cebc150dbe1a026690bf9887062c25c2941747fef242'
   (candidate/task['files'][0]).write_bytes(saved.read_bytes())
  candidate_hash=external_root.tree_sha256(candidate)
  frozen=hive_jvm.freeze_junit_tests(candidate,[{'path':task['test_path'],'class_name':task['test_class'],
       'expected_cases':task['test_cases'],'source':frozen_source.read_text()}])
  artifacts=hive_jvm.store_frozen_junit_tests(frozen,root)
  start=datetime.datetime.now(datetime.timezone.utc).isoformat();timer=time.monotonic()
  save(root/'preflight.json',{'study':'HIVE-TRANSITION-004','phase':args.phase,'case':case,'started_at':start,
   'candidate_sha256':candidate_hash,'source_sha256':source_hash,'approved':approved,'frozen_tests':artifacts,
   'timeout_seconds':240,'model_calls':0,'production_manifest':{str(p.relative_to(HERE/'repaired-workshop')):sha(p)
      for p in (HERE/'repaired-workshop').rglob('*.py') if '__pycache__' not in p.parts}})
  print(f'Starting {args.phase}-{case}: targeted budget 240 seconds',flush=True)
  report=hive_verifier.run_isolated(candidate,'targeted',[],timeout=240,external_root=True,
      frozen_junit_tests=artifacts,expected_jvm_profile=approved['jvm_profile'],
      expected_external_baseline_sha256=freeze['baseline']['sha256'],diagnostics_dir=root/'diagnostics')
  elapsed=time.monotonic()-timer
  save(root/'result.json',{'report':report,'wall_seconds':round(elapsed,3),'model_calls':0,
   'candidate_unchanged':external_root.tree_sha256(candidate)==candidate_hash,
   'baseline_unchanged':external_root.tree_sha256(baseline)==freeze['baseline']['sha256'],
   'historical_source_unchanged':external_root.tree_sha256(source)==source_hash,
   'disposition':'POST_HOC_CANDIDATE_VERIFICATION' if case=='preserved' else 'VERIFIER_ONLY_CONTROL',
   'historical_classification_unchanged':True,'applied':False})
  print(f'Completed {args.phase}-{case}: passed={report["passed"]}, wall={elapsed:.3f}s, checks='+str([(c['name'],c['passed']) for c in report['checks']]),flush=True)
if __name__=='__main__':main()
