"""Create a fresh replication harness; never edit prior evidence or production."""
from pathlib import Path
import shutil
ROOT=Path(__file__).resolve().parent
NEW=ROOT/'HIVE-FACTORIAL-003R1';OLD=ROOT/'HIVE-FACTORIAL-003';QUAL=ROOT/'HARNESS-QUALIFICATION-001'
NEW.mkdir(exist_ok=False)
shutil.copytree(ROOT/'HIVE-NFRT-ATTESTATION-002/repaired-workshop',NEW/'repaired-workshop')
for name in ('common.py','environment.py','runtime_observer.py','results_analysis.py','final_integrity.py'):
    text=(OLD/name).read_text(encoding='utf-8')
    if name in ('common.py','results_analysis.py'):text=text.replace("'HIVE-FACTORIAL-003'","'HIVE-FACTORIAL-003R1'")
    if name=='final_integrity.py':text=text.replace("ROOT/'HIVE-REVIEWER-POLICY-001/repaired-workshop'","ROOT/'HIVE-NFRT-ATTESTATION-002/repaired-workshop'")
    (NEW/name).write_text(text,encoding='utf-8')
for name in ('recorder.py','cell_harness.py','test_recorder.py','test_cell_harness.py','test_orchestration.py','scripted_fixture.py'):
    shutil.copyfile(QUAL/name,NEW/name)
common=NEW/'common.py';common.write_text(common.read_text()+"\ndef read(path):return json.loads(Path(path).read_bytes())\n",encoding='utf-8')
(NEW/'qcommon.py').write_text('''"""Bind the unchanged qualified harness to this isolated replication source."""
from common import *
import environment as env
hive,hive_jvm,hive_verifier,external_root,providers=env.hive,env.hive_jvm,env.hive_verifier,env.external_root,env.providers
FREEZE=read(HERE/'FREEZE.json') if (HERE/'FREEZE.json').exists() else read(ROOT/'HIVE-FACTORIAL-003/FREEZE.json')
def forbid_models():
    async def forbidden(*args,**kwargs):raise AssertionError('No inference in scripted qualification')
    providers.ollama_chat=forbidden;providers.openai_chat=forbidden
''',encoding='utf-8')
text=(OLD/'execute.py').read_text(encoding='utf-8')
text=text.replace('class TrialBudget(RuntimeError):pass','class TrialBudget(RuntimeError):pass\nfrom recorder import VerifierRecorder\nfrom cell_harness import record_verifiers, capture_candidate')
text=text.replace('async def run_trial(cell,lock,ordinal,resume=None):','async def run_trial(cell,lock,ordinal):\n    resume=None  # Fresh cells only; replacement/restart is forbidden.')
start=text.index('    original_target=hive.targeted_verify;')
end=text.index('    async def agent_call(role,prompt):',start)
text=text[:start]+"    recorder=VerifierRecorder(folder/'verifications',capture=capture_candidate)\n"+text[end:]
text=text.replace("        run=await hive.run_build(candidate,RUNS,task['request'],cell['model'],agent_call,metadata=metadata,run_id=runid,external_root_mode=True,allowed_write_files=task['files'])", "        with record_verifiers(recorder):\n            run=await hive.run_build(candidate,RUNS,task['request'],cell['model'],agent_call,metadata=metadata,run_id=runid,external_root_mode=True,allowed_write_files=task['files'])")
text=text.replace('restore();hive.targeted_verify=original_target;hive.verify_tree=original_full;monitor.stop();observer.snapshot(\'post-run\')',"restore();monitor.stop();observer.snapshot('post-run')\n        save(folder/'measurement-records.json',recorder.records);save(folder/'measurement.json',recorder.summary())\n    if not recorder.summary()['scoring_permitted']:raise IntegrityFailure('MEASUREMENT_FAILURE: native outcomes preserved separately')\n    records=[{**r,'kind':r['verifier_kind'],**({'report':r['result']} if 'result' in r else {}),\n              **({'exception':r['verifier_exception']} if 'verifier_exception' in r else {})} for r in recorder.records]")
text=text.replace("'verification_seconds':sum(v['host_elapsed_seconds'] for v in records)","'verification_seconds':recorder.summary()['known_verification_seconds'],'measurement_status':recorder.summary()['measurement_status']")
text=text[:text.index('def main():')]+'''def main():
    lock=read(HERE/'FREEZE.json');check(lock,full=True)
    assert not (HERE/'evidence/STUDY-STARTED.json').exists(),'One execution only; no replacement cells'
    assert not list((HERE/'evidence/trials').glob('*/STARTED.json'))
    save(HERE/'evidence/STUDY-STARTED.json',{'at':stamp(),'freeze_sha256':sha(HERE/'FREEZE.json')})
    results=[]
    try:
        asyncio.run(readiness(lock))
        for ordinal,cell in enumerate(lock['order'],1):
            check(lock);event('trial_started',ordinal=ordinal,**cell)
            result=asyncio.run(run_trial(cell,lock,ordinal));results.append(result);save(HERE/'evidence/raw-results.json',results)
            event('trial_finished',ordinal=ordinal,outcome=result['primary_outcome'],semantic_review=result['semantic_review'],wall_seconds=result['wall_seconds'])
        check(lock,full=True);save(HERE/'evidence/COMPLETED.json',{'at':stamp(),'trials':len(results)})
        event('completed',trials=len(results))
    except BaseException as exc:
        save(HERE/'evidence/STOPPED.json',{'at':stamp(),'type':type(exc).__name__,'message':str(exc),'completed':len(results)})
        event('stopped',type=type(exc).__name__,message=str(exc),completed=len(results));raise

if __name__=='__main__':main()
'''
(NEW/'execute.py').write_text(text,encoding='utf-8')
print(NEW)
