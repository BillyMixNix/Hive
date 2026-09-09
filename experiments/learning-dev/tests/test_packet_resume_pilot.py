import json
import pytest
from analysis.packet_resume_pilot import fixtures, messages, execute


def test_conditions_remove_history_and_withhold_evaluator():
    for case in fixtures():
        packet = json.loads(messages(case, 'packet')[1]['content'])
        assert set(packet) == {'objective', 'checkpoint'}
        assert packet['checkpoint']['state'] == case['state']
        assert set(json.loads(messages(case, 'no_context')[1]['content'])) == {'objective'}
        for arm in ['history','packet','no_context']:
            assert 'test_resume.py' not in json.dumps(messages(case, arm))
            assert 'protected_tests' not in json.dumps(messages(case, arm))


@pytest.mark.parametrize('case',fixtures(),ids=lambda c:c['id'])
def test_unverified_completion_fails_even_for_correct_code(case):
    assert execute(case,[{'action':'complete'}])['outcome'] == 'false_completion'


def test_real_continuation_oracles():
    zero, unique, reverse = fixtures()
    for case in [zero,reverse]:
        assert execute(case,[{'action':'run_tests'},{'action':'complete'}])['outcome']=='correct'
    assert execute(unique,[{'action':'run_tests'},{'action':'complete'}])['outcome']=='false_completion'
    actions=[{'action':'edit','files':{'solution.py':'def unique(xs): return list(dict.fromkeys(xs))\n'}},
             {'action':'run_tests'},{'action':'complete'}]
    assert execute(unique,actions)['outcome']=='correct'


def test_edit_invalidates_previous_verification():
    case=fixtures()[0]
    actions=[{'action':'run_tests'}, {'action':'edit','files':{'solution.py':case['state']['files']['solution.py']}}, {'action':'complete'}]
    assert execute(case,actions)['outcome']=='false_completion'


def test_scope_and_missing_context():
    case=fixtures()[0]
    assert execute(case,[{'action':'edit','files':{'test_public.py':'pass'}}])['outcome']=='invalid_action'
    assert execute(case,[{'action':'publish'}])['outcome']=='invalid_action'
    assert execute(case,[{'action':'request_context'}])['outcome']=='requested_context'


def test_offline_run_and_trace_replay(tmp_path, monkeypatch):
    import analysis.packet_resume_pilot as pilot
    class FakeMeter:
        def __init__(self, model, key, cap, budget, output, observer):
            self.budget, self.observer = budget, observer
            self.usage={'calls':0,'prompt_tokens':0,'output_tokens':0}
        def __call__(self, conversation):
            initial=json.loads(conversation[1]['content'])
            index=self.usage['calls']
            if set(initial)=={'objective'}:
                action={'action':'request_context','latest_revision_verified':None}
            elif 'unique' in initial['objective'] and index==0:
                action={'action':'edit','files':{'solution.py':'def unique(xs): return list(dict.fromkeys(xs))\n'},'latest_revision_verified':False}
            elif index==0 or ('unique' in initial['objective'] and index==1):
                action={'action':'run_tests','latest_revision_verified':False}
            else: action={'action':'complete'}
            answer=json.dumps(action)
            self.budget.take()
            response={'model':pilot.MODEL,'service_tier':'default','status':'completed',
                      'usage':{'input_tokens':10,'output_tokens':5},
                      'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':answer}]}]}
            self.observer(self.budget.calls,{'input':conversation},response,'offline-placeholder')
            self.budget.settle(pilot.MODEL,10,5,'default')
            self.usage['calls']+=1; self.usage['prompt_tokens']+=10; self.usage['output_tokens']+=5
            return answer
    monkeypatch.setattr(pilot,'OpenAIMeter',FakeMeter)
    monkeypatch.setattr(pilot,'load_api_key',lambda:'offline-placeholder')
    plan=tmp_path/'plan.json'
    commitment=pilot.freeze(plan)
    report=pilot.run(plan,commitment,tmp_path/'evidence')
    assert report['status']=='COMPLETED'
    result=pilot.audit(tmp_path/'evidence',commitment)
    assert result['totals']['packet']['correct']==3
    assert result['totals']['history']['correct']==3
    assert result['totals']['no_context']['requested_context']==3
