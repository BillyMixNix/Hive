"""Exactly one authorized replacement. Unchanged Hive source and normal protocol."""
import asyncio,json,os,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
os.environ.pop('OPENAI_API_KEY',None)
from bootstrap import HERE,PRIOR,STUDY,sha,save,manifest
import diagnostic_runner as r
from runtime_observer import Monitor,install,snapshot,stamp
from verification import nfrt_seed

def main():
 assert not (HERE/'evidence/J001-LIVE-STARTED.json').exists(),'Only one trial authorized'
 config=json.loads((PRIOR/'evidence/configuration.json').read_text())
 snapshot('before-integrity-checks')
 original=json.loads((HERE/'evidence/source-before.json').read_text())
 assert manifest(PRIOR/'repaired-workshop')==original==manifest(HERE/'repaired-workshop')
 tested=json.loads((PRIOR/'evidence/regression/complete-03/source-manifest.json').read_text())
 assert all(sha(HERE/'repaired-workshop'/p)==h for p,h in tested.items() if not set(Path(p).parts)&r.prior.SOURCE_EXCLUDES)
 assert json.loads((PRIOR/'evidence/regression/complete-03/result.json').read_text())['exit_code']==0
 assert json.loads((PRIOR/'evidence/readiness.json').read_text())['ready'] is True
 delivery=json.loads((PRIOR/'evidence/delivery-seal.json').read_text())
 assert all(sha(PRIOR/p)==h for p,h in delivery['files_sha256'].items())
 assert sha(HERE.parent/'HIVE-TRANSITION-005-REPORT.md')==delivery['report_sha256']
 print('Source, prior delivery and deterministic prerequisites verified.',flush=True)
 approved=r.prior.approved_environment(r.prior.reference_freeze());assert approved==config['approved']
 os.environ['HIVE_NFRT_SEED_MANIFEST']=config['manifest'];os.environ['HIVE_NFRT_SEED_SHA256']=config['manifest_sha256']
 assert sha(Path(config['manifest']))==config['manifest_sha256']
 attestation=json.loads(Path(config['manifest']).read_text())
 seed=nfrt_seed.configured_seed(Path(config['freeze']['baseline']['root']),Path(approved['approved_cache_root']),
  approved['jvm_profile'],approved['baseline_sha256'],approved['verifier_image_id'],attestation['identity']['downloaded_manifest_sha256'])
 assert seed and seed['sha256']==config['manifest_sha256']
 r.prior.no_cloud_key();assert r.providers.ollama_base()=='http://127.0.0.1:11434'
 assert r.prior.disk_free_bytes()>=r.prior.MIN_FREE_BYTES
 assert r.providers.OLLAMA_TOTAL_GENERATION_TIMEOUT==900 and r.providers.OLLAMA_CHAT_TIMEOUT==900
 assert r.LOCAL_CONTEXT_WINDOW==12288 and r.hive.LOCAL_TEMPERATURE==0.1
 assert set(r.OUTPUT_LIMITS.values())=={2048}
 assert (r.hive.MAX_PLAN_CORRECTIONS,r.hive.MAX_EDIT_REPAIRS_PER_WORKER,r.hive.MAX_TARGETED_CORRECTIONS_PER_WORKER)==(1,1,1)
 task=config['freeze']['tasks'][0];assert task['id']=='J001'
 assert sha(r.SOURCE_STUDY/'hidden-tests'/task['test_filename'])==task['test_sha256']
 model=next(x for x in r.model_inventory() if x['name']=='qwen2.5-coder:14b')
 assert model==next(x for x in config['freeze']['models'] if x['name']==model['name'])
 out=HERE/'evidence/live-diagnostic';out.mkdir(exist_ok=False)
 r.EVIDENCE=out;r.RUNS=out/'runs';r.LOCK_PATH=HERE/'FREEZE.json'
 freeze={**config['freeze'],'study':STUDY,'parent_study':'HIVE-TRANSITION-005',
  'apparatus_change':'No production changes; isolated identical source; resource/request observation; explicit all-role 2048 cap',
  'order':[{'task_id':'J001','replicate':1,'model':model['name'],'controller':'hive'}],
  'context_window':12288,'output_limits':r.OUTPUT_LIMITS,'temperature':0.1,'truncate':False,
  'targeted_timeout':240,'provider_generation_limit':900,'model_trials':1,'promotion':False,
  'source_manifest':r.prior.source_manifest(),'seed_sha256':config['manifest_sha256']}
 save(r.LOCK_PATH,freeze);(HERE/'LOCK.sha256').write_text(sha(r.LOCK_PATH)+'\n')
 save(HERE/'evidence/configuration.json',{'study':STUDY,'model':model,'source':str(HERE/'repaired-workshop'),
  'endpoint':'http://127.0.0.1:11434/api/chat','options':{'temperature':0.1,'num_predict':2048,'num_ctx':12288},
  'truncate':False,'stream':True,'schema':'unchanged Hive response_schema_for_prompt(role,prompt)',
  'provider_generation_limit_seconds':900,'read_timeout_seconds':900,'existing_max_http_attempts':2,
  'planner_corrections':1,'structural_worker_corrections':1,'targeted_worker_corrections':1,
  'targeted_timeout_seconds':240,'full_outer_timeout_seconds':660,'full_inner_timeout_seconds':600,
  'full_tasks':approved['jvm_profile']['full_tasks'],'seed_manifest':config['manifest'],'seed_sha256':config['manifest_sha256'],
  'output_cap_interpretation':'Latest user explicitly requires 2048; applied to every role. Historical T005 harness used planner2048/workers6000/reviewer1536. No Hive production source changed.',
  'unspecified_provider_settings':'seed, stop, keep_alive, num_gpu, num_batch and other unspecified options remain unspecified',
  'client_environment':{k:os.environ.get(k) for k in ('OLLAMA_BASE_URL','OLLAMA_CONTEXT_LENGTH','OLLAMA_NUM_PARALLEL','OLLAMA_MAX_LOADED_MODELS','OLLAMA_KEEP_ALIVE')},
  'provider_retry_scope':'Unchanged implementation applies generation limit to each _ollama_chat_once; existing retry at most two attempts. No manual retries.',
  'stop_policy':'After a logical provider call fails, no further inference is allowed; normal existing retry stays inside that call.'})
 save(out/'preflight.json',{'at':stamp(),'approved':approved,'task':task,'model':model,'source_files_equal':len(original),
  'final_T005_tested_source_equal':True,'test_identity_verified':True,'seed_attestation_verified':True,
  'seed_entries':len(attestation['entries']),'seed_bytes':sum(x['size'] for x in attestation['entries']),
  'regression_evidence_sha256':sha(PRIOR/'evidence/regression/complete-03/result.json'),
  'verifier_readiness_sha256':sha(PRIOR/'evidence/readiness.json'),'readiness_model_sha256':sha(HERE.parent/'HIVE-MODEL-RUNTIME-READINESS-001/evidence/result.json')})
 original_target=r.hive.targeted_verify;original_full=r.hive.verify_tree;counter=0
 def capture(tree,role,paths):
  nonlocal counter
  counter+=1;folder=out/'verifications'/f'targeted-{counter:02d}';folder.mkdir(parents=True,exist_ok=False)
  for path in paths:
   dest=folder/'applied-source'/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((tree/path).read_bytes())
  save(folder/'candidate.json',{'at':stamp(),'tree_sha256':r.external_root.tree_sha256(tree),
   'before_baseline_file_hashes':{p:sha(Path(freeze['baseline']['root'])/p) for p in paths},
   'files':{p:sha(tree/p) for p in paths},'role':role})
  (folder/'candidate.diff').write_text(r.hive.make_diff(Path(freeze['baseline']['root']),tree,paths),encoding='utf-8')
  print(f'Targeted verification {counter} starting under unchanged 240-second budget.',flush=True)
  start=time.monotonic();result=original_target(tree,role,paths)
  save(folder/'result.json',{'report':result,'host_elapsed_seconds':time.monotonic()-start,'finished_at':stamp()})
  print(f'Targeted verification {counter} returned passed={result.get("passed")}.',flush=True);return result
 def capture_full(tree):
  print('Normal Hive full gate invoked.',flush=True);start=time.monotonic();result=original_full(tree)
  save(out/'full-gate.json',{'report':result,'host_elapsed_seconds':time.monotonic()-start,'finished_at':stamp()});return result
 r.hive.targeted_verify=capture;r.hive.verify_tree=capture_full
 # Record actual residency after read-only integrity checks. No warmup/reload.
 snapshot('pre-run')
 monitor=Monitor();restore=install(r.providers,monitor)
 with (HERE/'evidence/J001-LIVE-STARTED.json').open('x') as f:
  json.dump({'study':STUDY,'started_at':stamp(),'allowed_trials':1,'freeze_sha256':sha(r.LOCK_PATH)},f)
 monitor.start()
 print('Integrity passed. Launching exactly one replacement J001 trial.',flush=True)
 try:
  result=asyncio.run(r.run_one(freeze['order'][0],freeze,task,1))
  save(out/'raw_results.json',[result]);print(json.dumps(result,indent=2),flush=True)
 finally:
  restore();r.hive.targeted_verify=original_target;r.hive.verify_tree=original_full
  monitor.stop();snapshot('post-run')

if __name__=='__main__':main()
