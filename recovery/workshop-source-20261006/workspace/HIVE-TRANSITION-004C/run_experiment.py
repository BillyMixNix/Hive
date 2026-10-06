"""Model-free production-verifier controls. Every invocation has a fresh name/tree."""
import argparse,json,os,sys,time,uuid,hashlib
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;OUT=HERE/'evidence';PRIOR=HERE.parent/'HIVE-TRANSITION-004'
sys.path.insert(0,str(HERE/'repaired-workshop'))
from bootstrap import save,sha
import diagnostic_environment as environment
from workshop import external_root,hive_jvm,hive_verifier
from verification import nfrt_seed

def prepare():
 approved=environment.approved_environment(environment.reference_freeze())
 original=json.loads((HERE.parent/'HIVE-TRANSITION-004B/evidence/inputs.json').read_text())
 assert approved==original['approved']
 freeze=original['freeze'];base=Path(freeze['baseline']['root']);task=freeze['tasks'][0]
 cache=Path(approved['approved_cache_root']);proof=cache/'.hive-priming-provenance'/cache.name
 native=json.loads((HERE.parent/'HIVE-TRANSITION-004B/evidence/seed-manifest.json').read_text())
 observed=json.loads((HERE.parent/'HIVE-TRANSITION-004B/evidence/runs/inputs/baseline-inputs.json').read_text())
 independent=task['files']
 inventory=[{'path':r.as_posix(),'sha256':external_root._file_digest(p,base.resolve(),s)} for p,r,s in external_root._inventory(base)]
 # This is an explicit approval for the previously measured source-only scope,
 # NOT an automatic generalization of arbitrary Java/build edits.
 attestation={'schema':'hive-nfrt-seed-v1','kind':'dependency-intermediates',
   'identity':{'baseline_sha256':freeze['baseline']['sha256'],'image_id':approved['verifier_image_id'],
     'jvm_profile':approved['jvm_profile'],
     'downloaded_manifest_sha256':sha(cache.parent.parent/cache.name/'external-build-inputs.manifest.json'),
     'artifacts.manifest.json':sha(proof/'artifacts.manifest.json'),'provenance.json':sha(proof/'provenance.json')},
   'entries':native['entries'],'source_inventory':inventory,'independent_java_sources':independent,
   'forbidden_packages':['dev/atmcompanion/'],'reconstruction_inputs':observed,
   'approval_basis':{'study':'HIVE-TRANSITION-004B','candidate_input_comparison_sha256':sha(HERE.parent/'HIVE-TRANSITION-004B/evidence/input-comparison.json'),
                    'cache_key_audit_sha256':sha(HERE.parent/'HIVE-TRANSITION-004B/evidence/cache-key-audit.json')}}
 manifest=OUT/'approved-nfrt-seed.json';save(manifest,attestation)
 os.environ['HIVE_NFRT_SEED_MANIFEST']=str(manifest);os.environ['HIVE_NFRT_SEED_SHA256']=sha(manifest)
 nfrt_seed.configured_seed(base,cache,approved['jvm_profile'],freeze['baseline']['sha256'],
     approved['verifier_image_id'],attestation['identity']['downloaded_manifest_sha256'])
 save(OUT/'configuration.json',{'approved':approved,'freeze':freeze,'manifest':str(manifest),'manifest_sha256':sha(manifest),
    'policy_sha256':sha(HERE/'cache-policy.md'),'model_calls':0,'timeout_seconds':240})
 print('Attestation prepared and validated.',flush=True)

def run(label,case):
 config=json.loads((OUT/'configuration.json').read_text());approved=config['approved'];freeze=config['freeze'];task=freeze['tasks'][0]
 assert environment.approved_environment(environment.reference_freeze())==approved
 os.environ['HIVE_NFRT_SEED_MANIFEST']=config['manifest'];os.environ['HIVE_NFRT_SEED_SHA256']=config['manifest_sha256']
 root=OUT/'runs'/label;root.mkdir(parents=True,exist_ok=False);candidate=root/'candidate'
 external_root.copy_candidate_tree(Path(freeze['baseline']['root']),candidate,root)
 if case=='preserved':
  src=PRIOR/'evidence/transition-003/applied-stage/first-applied-SnapshotFormatter.java'
  assert sha(src)=='a3219f4e0b65847123f6cebc150dbe1a026690bf9887062c25c2941747fef242'
  (candidate/task['files'][0]).write_bytes(src.read_bytes())
 source=PRIOR/'evidence/verifier-replays/post-regression-baseline/frozen-junit'/task['test_path']
 specs=hive_jvm.freeze_junit_tests(candidate,[{'path':task['test_path'],'class_name':task['test_class'],
       'expected_cases':task['test_cases'],'source':source.read_text()}])
 frozen=hive_jvm.store_frozen_junit_tests(specs,root)
 before=external_root.tree_sha256(candidate)
 save(root/'input.json',{'case':case,'candidate_sha256':before,'candidate_file_sha256':sha(candidate/task['files'][0]),
       'frozen':frozen,'source_manifest':{p.relative_to(HERE/'repaired-workshop').as_posix():sha(p)
           for p in (HERE/'repaired-workshop').rglob('*.py') if '__pycache__' not in p.parts}})
 t=time.monotonic();print('Starting production verifier:',label,flush=True)
 result=hive_verifier.run_isolated(candidate,'targeted',[task['test_path']],timeout=240,
   external_root=True,frozen_junit_tests=frozen,expected_jvm_profile=approved['jvm_profile'],
   expected_external_baseline_sha256=freeze['baseline']['sha256'],diagnostics_dir=root/'diagnostics')
 elapsed=time.monotonic()-t
 save(root/'result.json',{'report':result,'total_host_elapsed_seconds':elapsed,'model_calls':0,
   'post_hoc_candidate_verification':case=='preserved','candidate_unchanged':external_root.tree_sha256(candidate)==before})
 print(json.dumps({'label':label,'passed':result['passed'],'elapsed':elapsed,'checks':result['checks']}),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['prepare','baseline','preserved']);p.add_argument('--label')
 args=p.parse_args()
 if args.mode=='prepare':prepare()
 else:run(args.label or args.mode,args.mode)
