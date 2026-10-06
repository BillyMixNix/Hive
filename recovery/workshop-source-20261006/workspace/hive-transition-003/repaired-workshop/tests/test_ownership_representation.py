"""One-file ownership capacity is encoded without choosing a role or accepting bad plans."""
import copy
import itertools
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from workshop import hive, hive_context
from test_host_write_scope import ALLOWED, OUTSIDE, plan, run_fixture

ROLES=('ui','backend','tests')

@pytest.fixture
def scoped():
    values=[(hive._HOST_WRITE_SCOPE,hive._HOST_WRITE_SCOPE.set((ALLOWED,))),
            (hive._ACTIVE_AGENT_SCOPES,hive._ACTIVE_AGENT_SCOPES.set(hive.EXTERNAL_AGENT_SCOPES)),
            (hive._EXTERNAL_ROOT_MODE,hive._EXTERNAL_ROOT_MODE.set(True))]
    yield
    for var,token in reversed(values):var.reset(token)

def accept(schema,p):return Draft202012Validator(schema).is_valid(p)

@pytest.mark.parametrize('members',list(itertools.product((False,True),repeat=3)))
def test_single_file_generation_excludes_every_duplicate_owner_subset(scoped,members):
    p=plan()
    active=[r for r,b in zip(ROLES,members) if b]
    for role in ROLES:
        p[role+'_goal']='Implement assigned behavior' if role in active else 'no change needed'
        p['worker_files'][role]=[ALLOWED] if role in active else []
        p['worker_acceptance'][role]=['Assigned behavior works'] if role in active else []
    if len(active)>1:p['interface_contracts']=[{'name':'coordination','owner':active[0],
        'consumer_roles':active[1:],'contract':'Coordinate distinct responsibilities'}]
    schema=hive._planner_response_schema();Draft202012Validator.check_schema(schema)
    assert accept(schema,p)==(len(active)<=1)
    if len(active)>1:
        with pytest.raises(hive.HostWriteScopeError,match='assigned to both'):hive._normalize_plan(p)
    else:
        normalized,_=hive._normalize_plan(p);hive._validate_host_write_scope(normalized)

@pytest.mark.parametrize('path',['lib/math.js','src/domain/Thing.java','component.py','docs/manual.md'])
def test_single_file_capacity_is_path_and_language_independent(scoped,path):
    token=hive._HOST_WRITE_SCOPE.set((path,))
    try:
        schema=hive._planner_response_schema()
        for role in ROLES:
            p=plan()
            for r in ROLES:
                p[r+'_goal']='Implement assigned change' if r==role else 'no change needed'
                p['worker_files'][r]=[path] if r==role else []
                p['worker_acceptance'][r]=['Change works'] if r==role else []
            assert accept(schema,p)
    finally:hive._HOST_WRITE_SCOPE.reset(token)

def test_no_arbitrary_priority_and_role_intersections_retained():
    token=hive._HOST_WRITE_SCOPE.set(('app.py',))
    try:
        schema=hive._planner_response_schema()
        assert len(schema['anyOf'])==2  # backend or none; UI/tests scopes do not include app.py
        assert all(b['properties']['worker_files']['properties']['ui']['maxItems']==0 for b in schema['anyOf'])
        assert all(b['properties']['worker_files']['properties']['tests']['maxItems']==0 for b in schema['anyOf'])
    finally:hive._HOST_WRITE_SCOPE.reset(token)

def test_unauthorized_and_inactive_claims_still_rejected(scoped):
    bad=plan([OUTSIDE])
    assert not accept(hive._planner_response_schema(),bad)
    with pytest.raises(hive.HostWriteScopeError):hive._normalize_plan(bad)
    bad=plan();bad['backend_goal']='no change needed'
    # Even a selected branch's freeform goal cannot evade the normal validator.
    with pytest.raises(hive.PlanValidationError,match='no change needed'):hive._normalize_plan(bad)
    bad=plan();bad['worker_files']['tests']=[ALLOWED]
    assert not accept(hive._planner_response_schema(),bad)
    with pytest.raises(hive.HostWriteScopeError):hive._normalize_plan(bad)

def test_context_access_is_not_write_ownership(scoped,tmp_path):
    source=tmp_path/ALLOWED;source.parent.mkdir(parents=True)
    source.write_text('class Widget { int value() { return 1; } }')
    observed=hive_context.observe(tmp_path,'read_file_excerpt',{'path':ALLOWED})
    assert 'return 1' in json.dumps(observed)
    okay,reason=hive.validate_edit('tests',{'path':ALLOWED,'operation':'replace','find':'return 1;','replace':'return 2;'},[OUTSIDE])
    assert not okay and 'unplanned' in reason

def test_genuine_disjoint_multi_role_plan_unchanged(scoped):
    token=hive._HOST_WRITE_SCOPE.set((ALLOWED,OUTSIDE))
    try:
        p=plan();p['tests_goal']='Add regression coverage';p['worker_files']['tests']=[OUTSIDE]
        p['worker_acceptance']['tests']=['Regression covers behavior']
        p['interface_contracts']=[{'name':'api','owner':'backend','consumer_roles':['tests'],'contract':'Widget value is available'}]
        schema=hive._planner_response_schema();assert 'anyOf' not in schema
        assert accept(schema,p)
        normalized,_=hive._normalize_plan(p);hive._validate_host_write_scope(normalized)
    finally:hive._HOST_WRITE_SCOPE.reset(token)

def test_correction_schema_retains_single_owner_and_independent_intent_contract(scoped):
    bad=plan();bad['tests_goal']='Add coverage';bad['worker_files']['tests']=[ALLOWED]
    bad['worker_acceptance']['tests']=['Coverage exists']
    with pytest.raises(hive.HostWriteScopeError) as failure:hive._normalize_plan(bad)
    prompt=hive._plan_correction_prompt('Change behavior','map',json.dumps(bad),failure.value,external_mode=True)
    assert not accept(prompt.response_schema,bad)
    assert all('minItems' not in b['properties']['interface_contracts'] for b in prompt.response_schema['anyOf'])
    intent={'requirements':[{'consumer_role':'ui','require_tests':False,
                            'existing_interface':{'method':'GET','path':'/api/value','response_keys':['value']}}]}
    prompt=hive._plan_correction_prompt('Read existing API','map',json.dumps(bad),failure.value,intent_envelope=intent,external_mode=True)
    assert all(b['properties']['interface_contracts']['minItems']==1 for b in prompt.response_schema['anyOf'])

def test_single_owner_dispatch_and_conflicting_output_containment(tmp_path,monkeypatch):
    bad=plan();bad['tests_goal']='Add tests';bad['worker_files']['tests']=[ALLOWED];bad['worker_acceptance']['tests']=['Tests work']
    result,roles,_,checks,_=run_fixture(tmp_path,monkeypatch,[bad,plan()])
    assert roles==['planner','planner','backend','reviewer']
    assert result['plan_attempts'][0]['status']=='rejected'
    assert len(checks)==1

def test_schema_alternatives_are_independent_and_global_contract_unmodified(scoped):
    from workshop.hive_protocol import PLAN_SCHEMA
    before=copy.deepcopy(PLAN_SCHEMA)
    schema=hive._planner_response_schema()
    schema['anyOf'][0]['properties']['worker_files']['properties']['backend']['maxItems']=999
    assert hive._planner_response_schema()['anyOf'][0]['properties']['worker_files']['properties']['backend']['maxItems']!=999
    assert PLAN_SCHEMA==before

def test_all_historically_invalid_outputs_remain_invalid():
    artifact=Path(__file__).resolve().parents[2]/'evidence/historical-replay.json'
    result=json.loads(artifact.read_text())
    for before,after in zip(result['before'],result['after'],strict=True):
        assert before['id']==after['id']
        assert before['accepted']==after['accepted']
        assert before.get('error')==after.get('error')
        if not before['accepted']:assert not after['dispatch_eligible']
