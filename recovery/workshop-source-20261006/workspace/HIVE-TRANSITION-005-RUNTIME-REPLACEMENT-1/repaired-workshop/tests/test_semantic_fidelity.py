"""Host task transport and runtime-only correction evidence, without Ollama."""
import asyncio
import copy
import json
from pathlib import Path

import pytest
from workshop import hive
from verification import jvm_runner
from test_hive_observation_loop import _source, _plan, _implementation, _review

TASK = 'Implement the health summary. Preserve ordinary status values and existing serialization.'

@pytest.mark.parametrize('multi', [False, True])
def test_dispatched_workers_keep_host_task_and_local_contract(tmp_path, monkeypatch, multi):
    root = _source(tmp_path)
    plan = _plan()
    if multi:
        plan['ui_goal'] = 'Display the health summary'
        plan['worker_files']['ui'] = ['static/index.html']
        plan['worker_acceptance']['ui'] = ['The health summary is visible']
        plan['interface_contracts'] = [{'name':'summary', 'owner':'backend',
            'consumer_roles':['ui'], 'contract':'Read the health summary'}]
    monkeypatch.setattr(hive, 'targeted_verify', lambda *a: {'passed':True,'checks':[]})
    monkeypatch.setattr(hive, 'verify_tree', lambda *a: {'passed':True,'checks':[]})
    seen=[]
    async def call(role,prompt):
        if role=='planner':return json.dumps(plan)
        if role=='reviewer':return _review()
        seen.append(role)
        assert TASK in prompt
        assert plan[role+'_goal'] in prompt
        assert all(item in prompt for item in plan['worker_acceptance'][role])
        assert 'not additional write authority' in prompt
        assert 'hidden-test-source-sentinel' not in prompt
        if role=='backend':return _implementation()
        return json.dumps({'status':'implemented','summary':'Display the health summary',
            'edits':[{'path':'static/index.html','operation':'replace','find':'<h3>OpenAI</h3>',
                      'replace':'<h3>Health summary</h3>'}],'risks':[]})
    result=asyncio.run(hive.run_build(root,tmp_path/'runs',TASK,'local',call))
    assert result['status']=='ready',result.get('errors')
    assert set(seen)==({'backend','ui'} if multi else {'backend'})
    assert 'tests' not in seen  # inactive roles receive no dispatch/write authority

@pytest.mark.parametrize('kind',['targeted','structural','json'])
def test_every_repair_contract_keeps_original_task(kind):
    args=('backend','{}')
    common=dict(original_task=TASK,overall_objective='Local summary',team_plan=_plan())
    if kind=='targeted':
        prompt=hive._targeted_repair_prompt(*args,{'passed':False,'checks':[]},['app.py'],['Local criterion'],'Local goal','source',**common)
    elif kind=='structural':
        prompt=hive._structural_repair_prompt(*args,{'error':'missing anchor'},['app.py'],['Local criterion'],'Local goal','source',**common)
    else:
        prompt=hive._json_repair_prompt(*args,ValueError('bad JSON'),['app.py'],['Local criterion'],'Local goal','source',**common)
    assert TASK in prompt and 'Local criterion' in prompt and 'Local goal' in prompt

def test_real_targeted_correction_dispatch_preserves_task_and_runtime_diagnostic(tmp_path,monkeypatch):
    root=_source(tmp_path);calls=[]
    def targeted(*args):
        return {'passed':False,'checks':[{'name':'synthetic','passed':False,'detail':'runtime assertion: expected present, actual missing'}]}
    monkeypatch.setattr(hive,'targeted_verify',targeted)
    # The native-workshop branch retains its existing final check even after
    # worker failure; the external Gradle skip policy is covered by its suite.
    monkeypatch.setattr(hive,'verify_tree',lambda *args: {'passed':True,'checks':[]})
    async def call(role,prompt):
        if role=='planner':return json.dumps(_plan())
        if role=='reviewer':return _review()
        calls.append(prompt);assert TASK in prompt
        if len(calls)==2:
            assert 'runtime assertion: expected present, actual missing' in prompt
            assert "return {'ok': True}" in prompt  # rolled-back original source
        return _implementation()  # identical replacement must still fail closed
    result=asyncio.run(hive.run_build(root,tmp_path/'runs',TASK,'local',call))
    assert len(calls)==2 and result['status']=='rejected'
    assert result['agents']['backend']['failure']['exception_type']=='RepeatedFailedProposal'
    assert result['changed_files']==[]

@pytest.mark.parametrize('criteria',[
    ['Keep normal status output unchanged'],
    ['Preserve ordinary status values and existing serialization'],
    ['Local implementation criterion'],
    ['Change ordinary status values'],
])
def test_no_semantic_keyword_or_paraphrase_rejection(criteria):
    plan=_plan();plan['worker_acceptance']['backend']=criteria
    normalized,_=hive._normalize_plan(plan)
    prompt=hive._worker_prompt('backend',plan['backend_goal'],['app.py'],'source',criteria,
        original_task=TASK,team_plan=normalized)
    assert TASK in prompt and criteria[0] in prompt
    assert 'cannot weaken or contradict' in prompt
    # Transport fixes loss; arbitrary natural-language contradictions are not
    # misrepresented as deterministically detectable by this controller.

def test_malformed_plan_still_rejected():
    plan=_plan();del plan['worker_acceptance']
    with pytest.raises(hive.PlanValidationError):hive._normalize_plan(plan)

def test_run_owned_hidden_source_never_enters_task_or_worker_context(tmp_path):
    from workshop import hive_jvm
    root=_source(tmp_path)
    source='package example; class HiddenTest { String secret = "hidden-test-source-sentinel"; }'
    specs=hive_jvm.freeze_junit_tests(root,[{'path':'src/test/java/example/HiddenTest.java',
        'class_name':'example.HiddenTest','expected_cases':1,'source':source}])
    frozen=hive_jvm.store_frozen_junit_tests(specs,tmp_path/'run-evidence')
    token=hive._FROZEN_JVM_TESTS.set(tuple(frozen))
    try:
        bundle=hive._worker_context(root,'backend',TASK,['app.py'])
        prompt=hive._worker_prompt('backend','Implement health summary',['app.py'],bundle,
            ['Preserve status output'],original_task=TASK,team_plan=_plan())
        assert TASK in prompt and "return {'ok': True}" in prompt
        assert 'hidden-test-source-sentinel' not in prompt and 'class HiddenTest' not in prompt
        assert not (root/'src/test/java/example/HiddenTest.java').exists()
    finally:hive._FROZEN_JVM_TESTS.reset(token)

def test_runtime_xml_failure_diagnostics_preserve_counts_without_source_or_stack(tmp_path):
    path=tmp_path/'build/test-results/test/TEST-example.xml';path.parent.mkdir(parents=True)
    path.write_text('''<testsuite name="Example"><testcase name="publicBehavior" classname="Example">
      <failure type="AssertionFailedError" message="expected: &lt;true&gt; but was: &lt;false&gt;">SECRET_STACK_AND_SOURCE</failure>
      </testcase><testcase name="other" classname="Example"/></testsuite>''')
    reports,error=jvm_runner._reports(tmp_path)
    assert error is None
    assert reports[0]['tests']==2 and reports[0]['failures']==1
    detail=reports[0]['failure_diagnostics'][0]
    assert detail['message']=='expected: <true> but was: <false>'
    assert detail['test_name']=='publicBehavior'
    assert 'SECRET_STACK_AND_SOURCE' not in json.dumps(reports)
    report={'passed':False,'checks':[{'name':'frozen_junit_acceptance','passed':False,'detail':{
        'stdout_tail':'setup chatter '*8000,'stderr_tail':'HIVE_GRADLE_DIAGNOSTIC '+('inventory '*8000),
        'tests':reports,'returncode':1,'timed_out':False}}]}
    original=copy.deepcopy(report);wire=hive._targeted_diagnostic(report)
    assert len(wire)<=6000 and json.loads(wire)['passed'] is False
    assert 'publicBehavior' in wire and 'expected: <true> but was: <false>' in wire
    assert 'SECRET_STACK_AND_SOURCE' not in wire and 'inventory' not in wire
    assert report==original

def test_large_diagnostic_is_valid_json_and_omissions_are_explicit():
    report={'passed':False,'checks':[{'name':f'check-{i}','passed':False,'detail':{
        'stdout_tail':'x'*30000,'tests':[{'class_name':'Example','failure_diagnostics':[
            {'test_name':'t'*200,'type':'e'*200,'message':'m'*1000} for _ in range(20)]} for _ in range(20)]}}
        for i in range(20)]}
    wire=hive._targeted_diagnostic(report)
    assert len(wire)<=6000
    assert json.loads(wire)['passed'] is False and 'omitted' in wire

def test_timeout_remains_failure_and_no_diagnostics_are_invented():
    wire=hive._targeted_diagnostic({'passed':False,'checks':[{
        'name':'isolated_verifier','passed':False,'detail':'timed out after 240 seconds'}]})
    assert 'timed out after 240' in wire
    assert 'expected:' not in wire and json.loads(wire)['passed'] is False
    missing=hive._targeted_diagnostic({'passed':False,'checks':[{'name':'junit','passed':False,
        'detail':{'returncode':0,'report_error':'Gradle exited without fresh JUnit XML reports'}}]})
    assert json.loads(missing)['checks'][0]['detail']['report_error']=='Gradle exited without fresh JUnit XML reports'

def test_scope_context_ownership_verifier_policy_files_unchanged():
    import hashlib
    root=Path(__file__).resolve().parents[1]
    old=root.parent.parent/'HIVE-TRANSITION-004C/repaired-workshop'
    if not old.exists():pytest.skip('historical comparison available only in experiment workspace')
    for name in ['workshop/providers.py','workshop/hive_protocol.py','workshop/hive_verifier.py',
                 'workshop/external_root.py','workshop/hive_jvm.py','verification/nfrt_seed.py']:
        assert hashlib.sha256((root/name).read_bytes()).digest()==hashlib.sha256((old/name).read_bytes()).digest()
