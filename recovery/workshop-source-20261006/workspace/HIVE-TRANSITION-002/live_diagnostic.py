"""Exactly one new J001 diagnostic; synthetic retrieval probes are separate."""
import asyncio, hashlib, json, os, sys
from pathlib import Path
os.environ.pop('OPENAI_API_KEY',None)
sys.dont_write_bytecode=True
import diagnostic_runner as r
from diagnostic_capture import install

HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent/'HIVE-TRANSITION-001'
ORIGINAL=Path(r'C:\Users\billy\Documents\Codex\2026-09-13\referenced-chatgpt-conversation-this-is-an\work\HIVE-FACTORIAL-002')

def main():
    out=HERE/'evidence/live'
    # Fixtures live in a differently named directory; this is an invocation lock.
    marker=HERE/'evidence/J001-LIVE-STARTED.json'
    with marker.open('x') as file: json.dump({'study':'HIVE-TRANSITION-002','allowed_trials':1},file)
    # The legacy regression fixture uses evidence/live/01-...; never touch it.
    out=HERE/'evidence/live-diagnostic'
    out.mkdir(exist_ok=False)
    r.EVIDENCE=out; r.RUNS=out/'runs'; r.LOCK_PATH=HERE/'FREEZE.json'
    original=json.loads((ORIGINAL/'FREEZE.json').read_text())
    assert r.sha(ORIGINAL/'FREEZE.json')==(ORIGINAL/'LOCK.sha256').read_text().strip()
    r.prior.no_cloud_key()
    assert r.providers.ollama_base()=='http://127.0.0.1:11434'
    assert r.prior.disk_free_bytes()>=r.prior.MIN_FREE_BYTES
    print('Checking sealed baseline, verifier and approved offline caches',flush=True)
    approved=r.prior.approved_environment(r.prior.reference_freeze())
    assert approved['baseline_sha256']==original['baseline']['sha256']
    assert approved['verifier_image_id']==original['verifier_image_id']
    assert r.prior.hive_verifier.JVM_CONTAINER_LIMITS==original['verifier_limits']
    model=next(x for x in r.model_inventory() if x['name']=='qwen2.5-coder:14b')
    assert model==next(x for x in original['models'] if x['name']==model['name'])
    tasks=r.task_specs()
    assert [{k:v for k,v in t.items() if k!='test_source'} for t in tasks]==original['tasks']
    task=next(t for t in tasks if t['id']=='J001')
    production=[]
    for item in r.prior.source_manifest():
        old=PRIOR/'repaired-workshop'/item['path']
        if old.exists() and r.sha(old)!=item['sha256'] and not item['path'].startswith('tests/'):
            production.append(item['path'])
    assert sorted(production)==['app.py','workshop/hive_protocol.py','workshop/providers.py'],production
    # All validation, edit execution, isolation, and deterministic gates remain byte-identical to T001.
    assert r.sha(r.prior.WORKSHOP/'workshop/hive.py')==r.sha(PRIOR/'repaired-workshop/workshop/hive.py')
    assert json.loads((HERE/'evidence/regression.json').read_text())['exit_code']==0
    files=['live_diagnostic.py','diagnostic_runner.py','diagnostic_environment.py','diagnostic_capture.py']
    files += ['repaired-workshop/'+p for p in production]
    freeze={**original,'study':'HIVE-TRANSITION-002','status':'diagnostic-preregistered',
      'parent_study':'HIVE-TRANSITION-001','parent_freeze_sha256':r.sha(PRIOR/'FREEZE-revision2.json'),
      'apparatus_change':'Explicit measured context_window=12288 and truncate=false; reject in-stream provider errors',
      'production_changes_from_transition_001':production,'context_window':12288,
      'diagnostic_policy':'Exactly one J001 trial; no success-rate inference. Synthetic sentinel probes are separate.',
      'order':[{'task_id':'J001','replicate':1,'model':model['name'],'controller':'hive'}],
      'parent_files_sha256':original['files_sha256'],'files_sha256':{p:r.sha(HERE/p) for p in files},
      'source_manifest_sha256':hashlib.sha256(json.dumps(r.prior.source_manifest(),sort_keys=True).encode()).hexdigest()}
    r.save_json(r.LOCK_PATH,freeze)
    (HERE/'LOCK.sha256').write_text(r.sha(r.LOCK_PATH)+'\n')
    r.save_json(out/'preflight.json',{'approved':approved,'model':model,'scope':task['files'],
              'production_changes':production,'source_manifest':r.prior.source_manifest()})
    restore=install(r.providers,out/'wire')
    print('Preflight passed. Starting the only HIVE-TRANSITION-002 J001 trial.',flush=True)
    try: result=asyncio.run(r.run_one(freeze['order'][0],freeze,task,1))
    finally: restore()
    r.save_json(out/'raw_results.json',[result])
    (HERE/'wire-request.json').write_bytes((out/'wire/01/wire-request.json').read_bytes())
    r.save_json(HERE/'wire-request-metadata.json',json.loads((out/'wire/01/transport.json').read_text()))
    print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__': main()
