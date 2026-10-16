import hashlib
import json
from pathlib import Path
from analysis import packet_resume_recover as recovery
from analysis.packet_resume_pilot import audit


def test_preserve_eight_outcomes_and_recover_only_last_episode(tmp_path, monkeypatch):
    archive=Path(__file__).resolve().parents[1]/'examples/resume-pilot-v2-evidence.zip'
    commitment={'sources':recovery.sources(),'archive_sha256':recovery.ARCHIVE_SHA}
    plan=tmp_path/'recovery.json'; plan.write_text(json.dumps(commitment))
    sha=hashlib.sha256(plan.read_bytes()).hexdigest()
    class FakeMeter:
        def __init__(self,model,key,cap,budget,output,observer):
            assert cap==2
            self.budget,self.observer=budget,observer
            self.usage={'calls':0,'prompt_tokens':0,'output_tokens':0}
        def __call__(self,messages):
            assert json.loads(messages[-1]['content'])=={'public_tests_passed':True}
            answer='{"action":"complete"}'
            self.budget.take()
            response={'model':recovery.MODEL,'status':'completed','service_tier':'default','error':None,
                      'usage':{'input_tokens':10,'output_tokens':5},
                      'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':answer}]}]}
            self.observer(self.budget.calls,{'input':messages},response,'offline-placeholder')
            self.budget.settle(recovery.MODEL,10,5,'default')
            self.usage={'calls':1,'prompt_tokens':10,'output_tokens':5}
            return answer
    monkeypatch.setattr(recovery,'OpenAIMeter',FakeMeter)
    monkeypatch.setattr(recovery,'load_api_key',lambda:'offline-placeholder')
    result=recovery.recover(archive,tmp_path/'restored',plan,sha)
    assert result['status']=='COMPLETED' and len(result['rows'])==9
    assert result['rows'][-1]['result']['outcome']=='correct'
    checked=audit(tmp_path/'restored/resume-evidence',recovery.ORIGINAL_PLAN_SHA)
    assert checked['totals']['history']['correct']==1
    assert checked['totals']['packet']['correct']==2
    assert checked['spending']['total_upper_nano_usd']==recovery.PRIOR_TOTAL+14000
