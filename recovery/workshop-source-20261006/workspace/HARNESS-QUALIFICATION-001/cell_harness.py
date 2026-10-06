"""Harness-only candidate setup, observational wrappers and safe result collection."""
from contextlib import contextmanager
from pathlib import Path
import asyncio,copy,json,uuid
from qcommon import *
from recorder import VerifierRecorder

def prepare_cell(runs,task,run_id=None):
    run_id=run_id or uuid.uuid4().hex[:12];run_dir=Path(runs)/run_id
    external=external_root.prepare_candidate(FREEZE['baseline']['root'],Path(runs)/'external_candidates'/run_id,SOURCE,Path(runs))
    candidate=Path(external['candidate_root']);profile=hive_jvm.inspect_gradle_project(candidate)
    assert profile==FREEZE['verifier']['jvm_profile']
    spec=hive_jvm.freeze_junit_tests(candidate,[{'path':task['test_path'],'class_name':task['test_class'],'expected_cases':task['test_cases'],
        'source':(TASK_SOURCE/'hidden-tests'/task['test_filename']).read_text(encoding='utf-8')}])
    external['jvm_profile']=profile;external['frozen_junit_tests']=hive_jvm.store_frozen_junit_tests(spec,run_dir)
    assert external['frozen_junit_tests'][0]['sha256']==task['test_sha256']
    save(run_dir/'qualification-input.json',{'task':task,'external':external,'qualification_only':True,'model_calls':0})
    return run_id,run_dir,candidate,external

@contextmanager
def external_context(external,run_dir):
    bindings=[(hive._EXTERNAL_ROOT_MODE,True),(hive._EXTERNAL_RUN_METADATA,{**external,'run_dir':str(run_dir)}),
        (hive._FROZEN_JVM_TESTS,tuple(external['frozen_junit_tests'])),(hive._ACTIVE_AGENT_SCOPES,hive.EXTERNAL_AGENT_SCOPES)]
    tokens=[(v,v.set(value)) for v,value in bindings]
    try:yield
    finally:
        for v,token in reversed(tokens):v.reset(token)

def capture_candidate(destination,verifier_kind,args,kwargs):
    tree=Path(args[0] if args else kwargs['tree'])
    paths=(args[2] if len(args)>2 else kwargs['changed_files']) if verifier_kind=='targeted' else [r.as_posix() for _,r,_ in external_root._inventory(tree)]
    destination.mkdir(parents=True,exist_ok=True)
    before=external_root.tree_sha256(tree)
    # Exact source paths come from Hive's already validated invocation.
    for rel in paths:
        source=tree/rel;target=destination/'applied-source'/rel
        source.resolve().relative_to(tree.resolve());target.resolve().relative_to(destination.resolve())
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes())
    save(destination/'candidate.json',{'candidate_sha256':before,'files':{p:sha(tree/p) for p in paths}})
    assert external_root.tree_sha256(tree)==before

@contextmanager
def record_verifiers(recorder):
    target,full=hive.targeted_verify,hive.verify_tree
    hive.targeted_verify=recorder.wrap(target,'targeted');hive.verify_tree=recorder.wrap(full,'full')
    try:yield
    finally:hive.targeted_verify=target;hive.verify_tree=full

def collect_cell(run,recorder):
    observation=recorder.summary()
    return {'measurement':observation,'measurement_status':observation['measurement_status'],
        'qualification_only':True,'software_trial_scored':False,'model_calls':0,
        'native_status':run.get('status'),'semantic_review':(run.get('semantic_review') or {}).get('disposition','not_run'),
        'native_verification':copy.deepcopy(run.get('verification')),'software_outcome':None,
        'promotion_authorization':'not_authorized','applied':run.get('applied',False)}

async def scripted_cell(output,task,plan,worker,review,recorder_options=None):
    """Complete normal Hive execution; callback supplies fixtures, never inference."""
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    runs=output/'runs';rid,run_dir,candidate,external=prepare_cell(runs,task)
    calls=[]
    async def scripted(role,prompt):
        calls.append({'role':role,'prompt':prompt,'at':stamp(),'provider':'scripted_fixture'})
        payload=plan if role=='planner' else review if role=='reviewer' else worker
        return json.dumps(payload)
    rec=VerifierRecorder(output/'measurement',capture=capture_candidate,**(recorder_options or {}))
    with record_verifiers(rec):
        run=await hive.run_build(candidate,runs,task['request'],'qwen2.5-coder:14b',scripted,
            metadata={'external_root':external,'max_tier':'local','max_cost':0,'cloud_spend':0,'experiment':{'study_id':'HARNESS-QUALIFICATION-001','qualification_only':True}},
            run_id=rid,external_root_mode=True,allowed_write_files=task['files'])
    save(output/'scripted-calls.json',calls);save(output/'run.json',run)
    save(output/'measurement-records.json',rec.records);save(output/'measurement-errors.json',rec.failures)
    row=collect_cell(run,rec);row.update(run_id=rid,stage_root=str(run_dir/'stage'),candidate_root=str(candidate))
    save(output/'aggregate-row.json',row)
    return row,run,rec
