"""Qualify assembled live orchestration without model or verifier inference."""
import asyncio,json
import execute as runner
from common import ROOT,save,read
from scripted_fixture import fixtures

def test_assembled_executor_uses_qualified_wrapper_once(tmp_path,monkeypatch):
    lock=read(ROOT/'HIVE-FACTORIAL-003/FREEZE.json')
    save(tmp_path/'FREEZE.json',lock)
    task,plan,worker,review=fixtures();seen=[]
    async def provider(model,messages,instructions,**kwargs):
        role=instructions.split('bounded ',1)[1].split(' agent',1)[0]
        return {'text':json.dumps(plan if role=='planner' else review if role=='reviewer' else worker),'input_tokens':10,'output_tokens':10}
    def verifier(tree,role,paths):
        seen.append((str(tree),role,list(paths)))
        return {'passed':False,'checks':[{'name':'scripted_failure','passed':False,'detail':'scripted qualification only'}]}
    class Monitor:
        def start(self):pass
        def stop(self):pass
    monkeypatch.setattr(runner,'HERE',tmp_path);monkeypatch.setattr(runner,'RUNS',tmp_path/'runs')
    monkeypatch.setattr(runner.env.providers,'ollama_chat',provider)
    monkeypatch.setattr(runner.hive,'targeted_verify',verifier)
    monkeypatch.setattr(runner.observer,'snapshot',lambda *a:None)
    monkeypatch.setattr(runner.observer,'Monitor',Monitor)
    monkeypatch.setattr(runner.observer,'install',lambda *a:lambda:None)
    monkeypatch.setattr(runner,'event',lambda *a,**kw:None)
    row=asyncio.run(runner.run_trial({'task_id':task['id'],'replicate':1,'model':'qwen2.5-coder:14b','controller':'hive','historical_ordinal':27},lock,1))
    assert len(seen)==1 and row['measurement_status']=='MEASURED'
    assert row['verified_software_success'] is False and row['applied'] is False
    assert row['candidate_identity']['stage_tree_sha256']==lock['baseline']['sha256']
    assert row['verification_seconds']>=0
    assert read(__import__('pathlib').Path(row['evidence'])/'measurement.json')['invocations_observed']==1
