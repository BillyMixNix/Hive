import asyncio
import ast
import hashlib
import json
from pathlib import Path
import httpx
import pytest
from workshop import providers, thinking_policy as policy
from test_ollama_structured_output import mock_http, ollama_response

MODEL='synthetic-switchable'
TEMPLATE='synthetic boolean switch template'
SCHEMA={'type':'object','properties':{'status':{'type':'string'}},'required':['status']}

@pytest.fixture
def profile(monkeypatch):
    p={'provider_version':'test-version','model_digest':'a'*64,'template_sha256':hashlib.sha256(TEMPLATE.encode()).hexdigest(),
       'values':[True,False],'bounded_worker_think':False}
    monkeypatch.setattr(policy,'PROFILES',{MODEL:p})
    return p

def handler(profile,chat=None,overrides=None):
    values={'/api/version':{'version':profile['provider_version']},
        '/api/tags':{'models':[{'name':MODEL,'digest':profile['model_digest']}]},
        '/api/show':{'template':TEMPLATE,'capabilities':['completion','thinking']}}
    values.update(overrides or {})
    def dispatch(req):
        if req.url.path=='/api/chat':return chat(req) if chat else ollama_response('{"status":"ok"}')
        return httpx.Response(200,json=values[req.url.path])
    return dispatch

def invoke(**kw):
    return asyncio.run(providers.ollama_chat(MODEL,[{'role':'user','content':'unchanged source and task'}],'unchanged system',
        response_format=SCHEMA,temperature=.1,max_output_tokens=6000,context_window=12288,total_timeout=900,**kw))

@pytest.mark.parametrize('value',[False,True])
def test_supported_exact_wire_value_and_unchanged_settings(profile,mock_http,value):
    requests,_=mock_http(handler(profile));result=invoke(think=value)
    body=json.loads(requests[-1].content)
    assert body['think'] is value
    assert body['format']==SCHEMA and body['truncate'] is False
    assert body['options']=={'temperature':.1,'num_predict':6000,'num_ctx':12288}
    assert body['messages']==[{'role':'system','content':'unchanged system'},{'role':'user','content':'unchanged source and task'}]
    assert result['thinking_policy']['requested'] is value
    assert result['text']=='{"status":"ok"}'
    assert [r.url.path for r in requests]==['/api/version','/api/tags','/api/show','/api/chat']

@pytest.mark.parametrize('kwargs',[{}, {'think':None}])
def test_default_no_capability_requests_or_wire_change(profile,mock_http,kwargs):
    requests,_=mock_http(handler(profile));invoke(**kwargs)
    assert len(requests)==1 and 'think' not in json.loads(requests[0].content)

@pytest.mark.parametrize('bad',[0,1,'false','true',{},[]])
def test_wrong_types_fail_before_generation(profile,mock_http,bad):
    requests,_=mock_http(handler(profile))
    with pytest.raises(providers.OllamaRequestError,match='think must be boolean'):invoke(think=bad)
    assert not requests

def test_unattested_model_fails_explicitly(profile,mock_http,monkeypatch):
    monkeypatch.setattr(policy,'PROFILES',{});requests,_=mock_http(handler(profile))
    with pytest.raises(providers.OllamaRequestError,match='not attested'):invoke(think=False)
    assert not requests

@pytest.mark.parametrize('override',[
    {'/api/version':{'version':'other'}},
    {'/api/tags':{'models':[{'name':MODEL,'digest':'changed'}]}},
    {'/api/show':{'template':'changed','capabilities':['thinking']}},
    {'/api/show':{'template':TEMPLATE,'capabilities':['completion']}},
])
def test_identity_drift_no_chat_or_silent_fallback(profile,mock_http,override):
    requests,_=mock_http(handler(profile,overrides=override))
    with pytest.raises(providers.OllamaRequestError,match='identity mismatch'):invoke(think=False)
    assert all(r.url.path!='/api/chat' for r in requests)

def test_provider_capability_error_is_error(profile,mock_http):
    requests,_=mock_http(lambda r:httpx.Response(500,text='discovery failed'))
    with pytest.raises(providers.OllamaRequestError,match='validation failed'):invoke(think=False)
    assert all(r.url.path!='/api/chat' for r in requests)

def test_retry_same_request_no_mode_switch(profile,mock_http):
    bodies=[]
    def chat(req):
        bodies.append(req.content)
        return httpx.Response(500,text='allocation failure') if len(bodies)==1 else ollama_response('{}')
    requests,_=mock_http(handler(profile,chat));result=invoke(think=False)
    assert len(bodies)==2 and bodies[0]==bodies[1]
    assert json.loads(bodies[0])['think'] is False
    assert result['text']=='{}'
    assert sum(r.url.path=='/api/show' for r in requests)==1

def test_exhausted_provider_errors_remain_errors(profile,mock_http):
    bodies=[]
    def chat(req):bodies.append(req.content);return httpx.Response(500,text='allocation failed')
    mock_http(handler(profile,chat))
    with pytest.raises(providers.OllamaRequestError,match='allocation failed'):invoke(think=False)
    assert len(bodies)==2 and bodies[0]==bodies[1]

def test_generation_deadline_does_not_switch_or_retry(profile,mock_http,monkeypatch):
    mock_http(handler(profile));bodies=[]
    async def timeout(body,**kw):
        bodies.append(body.copy());assert kw['total_timeout']==900
        raise providers.OllamaRequestError('900-second total limit',retryable=False)
    monkeypatch.setattr(providers,'_ollama_chat_once',timeout)
    with pytest.raises(providers.OllamaRequestError,match='900-second'):invoke(think=False)
    assert len(bodies)==1 and bodies[0]['think'] is False

@pytest.mark.parametrize('role',['backend','ui','tests'])
@pytest.mark.parametrize('turn',['initial','structural correction','targeted correction'])
def test_all_worker_turns_use_same_preselected_policy(profile,role,turn):
    # No prompt inspection: semantic/structural correction text cannot switch policy.
    assert policy.worker_options(MODEL,role,response_format=SCHEMA,max_output_tokens=6000,total_timeout=900)=={'think':False}

@pytest.mark.parametrize('role',['planner','reviewer'])
def test_nonworker_policy_unchanged(profile,role):
    assert policy.worker_options(MODEL,role,response_format=SCHEMA,max_output_tokens=2048,total_timeout=900)=={}

@pytest.mark.parametrize('override',[
    {'provider':'openai'},{'model':'unrelated'}, {'response_format':None},
    {'max_output_tokens':None},{'max_output_tokens':0},{'total_timeout':None},{'total_timeout':float('inf')},
])
def test_unrelated_or_unbounded_retains_defined_default(profile,override):
    args=dict(model=MODEL,role='backend',provider='ollama',response_format=SCHEMA,max_output_tokens=6000,total_timeout=900)
    args.update(override);assert policy.worker_options(**args)=={}

def test_application_uses_same_policy_and_retains_role_schema():
    tree=ast.parse((Path(__file__).parents[1]/'app.py').read_text(encoding='utf-8'))
    fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='hive_agent_call')
    calls=[n for n in ast.walk(fn) if isinstance(n,ast.Call)]
    request=next(n for n in calls if ast.unparse(n.func)=='providers.ollama_chat')
    assert any(k.arg is None and ast.unparse(k.value.func)=='providers.thinking_policy.worker_options' for k in request.keywords)
    assert any(ast.unparse(n.func)=='hive.response_schema_for_prompt' for n in calls)
    assert next(k.value.id for k in request.keywords if k.arg=='context_window')=='LOCAL_CONTEXT_WINDOW'

def test_context_guard_still_fails(profile,mock_http):
    requests,_=mock_http(handler(profile))
    with pytest.raises(ValueError,match='must exceed'):
        asyncio.run(providers.ollama_chat(MODEL,[],'x',max_output_tokens=6000,context_window=6000,think=False))
    assert not requests

@pytest.mark.parametrize('structural_first',[False,True])
def test_real_app_worker_and_correction_dispatch_use_frozen_mode(profile,tmp_path,monkeypatch,structural_first):
    import time
    from types import SimpleNamespace
    from workshop import hive
    from test_hive_observation_loop import _source,_plan,_implementation,_review
    root=_source(tmp_path);seen=[]
    async def status():return True,[MODEL]
    async def chat(model,messages,instructions,**kwargs):
        role=instructions.split('bounded ',1)[1].split(' agent',1)[0]
        seen.append({'role':role,'kwargs':kwargs,'prompt':messages[0]['content']})
        if role=='planner':text=json.dumps(_plan())
        elif role=='reviewer':text=_review()
        elif structural_first and sum(s['role']=='backend' for s in seen)==1:
            obj=json.loads(_implementation());obj['edits'][0]['find']='nonexistent synthetic anchor';text=json.dumps(obj)
        else:text=_implementation()
        return {'text':text,'input_tokens':10,'output_tokens':10}
    tree=ast.parse((Path(__file__).parents[1]/'app.py').read_text(encoding='utf-8'))
    fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='hive_agent_call')
    ns={'time':time,'json':json,'hive':hive,'LOCAL_CONTEXT_WINDOW':12288,
        'HIVE_LOCAL_OUTPUT_TOKEN_LIMITS':{'planner':2048,'backend':6000,'reviewer':1536},
        'providers':SimpleNamespace(ollama_status=status,ollama_chat=chat,thinking_policy=policy,OLLAMA_TOTAL_GENERATION_TIMEOUT=900),
        'db':SimpleNamespace(add_ledger=lambda *a:None)}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'app.py','exec'),ns)
    async def call(role,prompt):return await ns['hive_agent_call'](role,prompt,MODEL,False,'local',{})
    monkeypatch.setattr(hive,'targeted_verify',lambda *a:{'passed':False,'checks':[{'name':'synthetic','passed':False,'detail':'synthetic failure'}]})
    monkeypatch.setattr(hive,'verify_tree',lambda *a:{'passed':True,'checks':[]})
    result=asyncio.run(hive.run_build(root,tmp_path/'runs','Preserve task semantics',MODEL,call))
    workers=[s for s in seen if s['role']=='backend']
    assert len(workers)==(3 if structural_first else 2),result.get('errors')
    assert all(s['kwargs']['think'] is False and s['kwargs']['max_output_tokens']==6000 for s in workers)
    assert all('think' not in s['kwargs'] for s in seen if s['role'] in ('planner','reviewer'))
    assert all('Preserve task semantics' in s['prompt'] for s in workers)
    assert len(result['targeted_repairs'])==1
    assert len(result['edit_repairs'])==(1 if structural_first else 0)
    assert result['agents']['backend']['failure']['exception_type']=='RepeatedFailedProposal'
    assert result['changed_files']==[]
