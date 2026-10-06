"""Exactly one fresh local J001 trial, gated by regression and verifier readiness."""
import asyncio,json,os,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
os.environ.pop('OPENAI_API_KEY',None)
from bootstrap import HERE,sha,save
import diagnostic_runner as r
from diagnostic_capture import install

def main():
 config=json.loads((HERE/'evidence/configuration.json').read_text())
 readiness=json.loads((HERE/'evidence/readiness.json').read_text());assert readiness['ready'] is True
 regression=json.loads((HERE/'evidence/regression/complete-03/result.json').read_text());assert regression['exit_code']==0
 tested=json.loads((HERE/'evidence/regression/complete-03/source-manifest.json').read_text())
 assert all(sha(HERE/'repaired-workshop'/p)==h for p,h in tested.items() if not set(Path(p).parts)&r.prior.SOURCE_EXCLUDES)
 seal=json.loads((HERE/'evidence/pre-edit-seal.json').read_text());assert sha(HERE/'semantic-loss-diagnosis.md')==seal['diagnosis_sha256']
 assert r.prior.approved_environment(r.prior.reference_freeze())==config['approved']
 os.environ['HIVE_NFRT_SEED_MANIFEST']=config['manifest'];os.environ['HIVE_NFRT_SEED_SHA256']=config['manifest_sha256']
 assert sha(Path(config['manifest']))==config['manifest_sha256']
 r.prior.no_cloud_key();assert r.providers.ollama_base()=='http://127.0.0.1:11434'
 assert r.prior.disk_free_bytes()>=r.prior.MIN_FREE_BYTES
 task=config['freeze']['tasks'][0];assert task['id']=='J001'
 model=next(x for x in r.model_inventory() if x['name']=='qwen2.5-coder:14b')
 assert model==next(x for x in config['freeze']['models'] if x['name']==model['name'])
 out=HERE/'evidence/live-diagnostic';out.mkdir(exist_ok=False)
 r.EVIDENCE=out;r.RUNS=out/'runs';r.LOCK_PATH=HERE/'FREEZE.json'
 freeze={**config['freeze'],'study':'HIVE-TRANSITION-005','parent_study':'HIVE-TRANSITION-004C',
   'apparatus_change':'Original task independently propagated to worker contracts; bounded emitted verifier diagnostics',
   'order':[{'task_id':'J001','replicate':1,'model':model['name'],'controller':'hive'}],
   'context_window':12288,'targeted_timeout':240,'model_trials':1,'promotion':False,
   'source_manifest':r.prior.source_manifest(),'readiness_sha256':sha(HERE/'evidence/readiness.json'),
   'seed_sha256':config['manifest_sha256']}
 save(r.LOCK_PATH,freeze);(HERE/'LOCK.sha256').write_text(sha(r.LOCK_PATH)+'\n')
 save(out/'preflight.json',{'model':model,'approved':config['approved'],'task':task,'source_manifest':r.prior.source_manifest()})
 original=r.hive.targeted_verify;full=r.hive.verify_tree;counter=0
 def capture(tree,role,paths):
  nonlocal counter
  counter+=1;folder=out/'verifications'/f'targeted-{counter:02d}';folder.mkdir(parents=True,exist_ok=False)
  # Diagnostic snapshot of this newly generated candidate only; never fed back
  # through the model harness. Original proposal is supplied by normal Hive.
  for path in paths:
   dest=folder/'applied-source'/path;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((tree/path).read_bytes())
  save(folder/'candidate.json',{'tree_sha256':r.external_root.tree_sha256(tree),
       'files':{p:sha(tree/p) for p in paths},'role':role})
  (folder/'candidate.diff').write_text(r.hive.make_diff(Path(freeze['baseline']['root']),tree,paths),encoding='utf-8')
  start=time.monotonic();result=original(tree,role,paths)
  save(folder/'result.json',{'report':result,'host_elapsed_seconds':time.monotonic()-start})
  return result
 def capture_full(tree):
  start=time.monotonic();result=full(tree)
  save(out/'full-gate.json',{'report':result,'host_elapsed_seconds':time.monotonic()-start})
  return result
 r.hive.targeted_verify=capture;r.hive.verify_tree=capture_full
 restore=install(r.providers,out/'wire')
 # Exclusive invocation lock immediately before any inference-capable code.
 with (HERE/'evidence/J001-LIVE-STARTED.json').open('x') as f:json.dump({'study':'HIVE-TRANSITION-005','allowed_trials':1},f)
 print('Readiness and integrity passed. Starting the only fresh HIVE-TRANSITION-005 J001 trial.',flush=True)
 try:result=asyncio.run(r.run_one(freeze['order'][0],freeze,task,1))
 finally:restore();r.hive.targeted_verify=original;r.hive.verify_tree=full
 save(out/'raw_results.json',[result]);print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':main()
