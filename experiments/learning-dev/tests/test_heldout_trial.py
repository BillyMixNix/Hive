import copy
import json
from pathlib import Path
import pytest
from analysis.heldout_capsule import compile_history
from analysis import heldout_trial as trial

ARCHIVE=Path(__file__).resolve().parents[1]/'examples/heldout-real-bugs-v1-20260909.zip'


@pytest.mark.parametrize('case',trial.read_archive(ARCHIVE)['cases'],ids=lambda c:c['id'])
def test_real_fixture_and_capsule_preflight(case):
    encoded,state=compile_history(case['history'])
    assert state==case['required_state']
    assert len(encoded.encode())<len(trial.canonical(case['history']).encode())
    packet=json.loads(encoded)
    assert packet['state']['verified'] is False
    assert packet['state']['failed_attempts']==['r1']
    assert 'test_hidden.py' not in encoded and 'test_retention.py' not in encoded
    baseline=trial.execute(case,[])
    assessment=trial.assess(case,baseline,[])
    assert not assessment['correct'] and not assessment['regression']
    # The real upstream repaired module passes both new bug tests and original API tests.
    repaired={**baseline,'files':case['reference_files'],'verified':True,'terminal':'submitted'}
    assessment=trial.assess(case,repaired,[{'state':case['required_state']}])
    assert assessment['correct'] and not assessment['regression'] and not assessment['lost_required_state']


def test_corrupt_checkpoint_and_scope_fail_closed():
    case=trial.read_archive(ARCHIVE)['cases'][0]
    history=copy.deepcopy(case['history']);history[6]['sha256']='0'*64
    with pytest.raises(AssertionError):compile_history(history)
    replay=trial.execute(case,[{'action':'replace','file':'test_public.py','revision':'r2','old':'x','new':'y'}])
    assert replay['files']==case['files'] and replay['revision']=='r2'
    replay=trial.execute(case,[{'action':'replace','file':case['file'],'revision':'r0','old':'import re','new':'import re'}])
    assert replay['files']==case['files'] and replay['revision']=='r2'


def test_mocked_end_to_end_cost_and_replay(tmp_path,monkeypatch):
    class FakeMeter:
        def __init__(self,model,key,cap,budget,output,observer):
            self.budget,self.observer=budget,observer
            self.usage={'calls':0,'prompt_tokens':0,'output_tokens':0}
        def __call__(self,messages):
            # Never repair a real task in this wiring test. All recipients abstain;
            # construction and recipient token costs must still be reconciled.
            if 'ordinary prose' in messages[0]['content']:
                answer=trial.canonical({'summary':'Current revision r2 is unverified after rollback. The r1 edit failed. Request additional context if needed.'})
            else: answer=trial.canonical({'action':'request_context','state':None})
            self.budget.take()
            response={'model':trial.MODEL,'status':'completed','service_tier':'default','error':None,
                      'usage':{'input_tokens':10,'output_tokens':5},
                      'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':answer}]}]}
            self.observer(self.budget.calls,{'input':messages},response,'offline-placeholder')
            self.budget.settle(trial.MODEL,10,5,'default')
            self.usage={'calls':1,'prompt_tokens':10,'output_tokens':5}
            return answer
    monkeypatch.setattr(trial,'OpenAIMeter',FakeMeter)
    monkeypatch.setattr(trial,'load_api_key',lambda:'offline-placeholder')
    plan=tmp_path/'plan.json';sha=trial.freeze(ARCHIVE,plan)
    report=trial.run(ARCHIVE,plan,sha,tmp_path/'evidence')
    assert report['status']=='COMPLETED'
    result=trial.audit(ARCHIVE,tmp_path/'evidence',sha)
    assert result['decision']=='DO_NOT_ADVANCE'
    assert result['spending']['measured_usage_upper_nano_usd']==16*14000
    assert result['totals']['summary']['nano_usd']==8*14000
    # A forged reported charge must not survive a newly generated checksum map.
    report['spending']['measured_usage_upper_nano_usd']+=1
    trial.save_json(tmp_path/'evidence/report.json',report)
    trial.save_json(tmp_path/'evidence/checksums.json',{p.relative_to(tmp_path/'evidence').as_posix():trial.sha(p) for p in (tmp_path/'evidence').rglob('*') if p.is_file() and p.name!='checksums.json'})
    with pytest.raises(AssertionError):trial.audit(ARCHIVE,tmp_path/'evidence',sha)
