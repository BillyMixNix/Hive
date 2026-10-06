"""Frozen serial factorial execution; observer wrappers do not alter decisions."""
import asyncio,json,os,sys,time,uuid,threading
from common import *
import environment as env
import runtime_observer as observer
import httpx
from workshop.hive_protocol import LOCAL_CONTEXT_WINDOW
from verification import nfrt_seed
hive=env.hive
RUNS=HERE/'evidence/runs'
class IntegrityFailure(RuntimeError):pass
class TrialBudget(RuntimeError):pass
from recorder import VerifierRecorder
from cell_harness import record_verifiers, capture_candidate

def check(lock,full=False):
    assert sha(HERE/'FREEZE.json')==(HERE/'LOCK.sha256').read_text().strip()
    if manifest(SOURCE)!=json.loads((HERE/'evidence/source-inventory.json').read_bytes()):raise IntegrityFailure('Frozen controller bytes changed')
    for name,digest in lock['instrumentation_files'].items():
        if sha(HERE/name)!=digest:raise IntegrityFailure('Frozen instrumentation changed: '+name)
    if env.external_root.tree_sha256(Path(lock['baseline']['root']))!=lock['baseline']['sha256']:raise IntegrityFailure('Frozen baseline changed')
    for task in lock['tasks']:
        if sha(TASK_SOURCE/'hidden-tests'/task['test_filename'])!=task['test_sha256']:raise IntegrityFailure('Frozen acceptance changed')
    if sha(lock['nfrt']['manifest'])!=lock['nfrt']['sha256']:raise IntegrityFailure('NFRT attestation changed')
    env.no_cloud_key()
    assert env.providers.ollama_base()=='http://127.0.0.1:11434'
    tags=httpx.get(env.OLLAMA+'/api/tags',timeout=10,trust_env=False).json()['models']
    for expected in lock['models']:
        assert next(m['digest'] for m in tags if m['name']==expected['historical']['name'])==expected['historical']['digest']
    if full:
        approved=env.approved_environment(env.reference_freeze());assert approved==lock['verifier']
    os.environ['GRADLE_USER_HOME']=lock['verifier']['approved_cache_root']
    os.environ['HIVE_NFRT_SEED_MANIFEST']=lock['nfrt']['manifest'];os.environ['HIVE_NFRT_SEED_SHA256']=lock['nfrt']['sha256']

def checks(report):return {c.get('name'):c for c in (report or {}).get('checks',[]) if isinstance(c,dict)}

def classify(run,calls,verification_records,integrity):
    full=run.get('verification') or {};index=checks(full)
    targets=[v['report'] for v in verification_records if v['kind']=='targeted' and 'report' in v]
    target_checks=[c for r in targets for c in r.get('checks',[])]
    accepted=any(c.get('name')=='frozen_junit_acceptance' and c.get('passed') is True for c in target_checks+list(index.values()))
    deterministic=(bool(run.get('changed_files')) and full.get('passed') is True and all(c.get('passed') is True for c in index.values())
        and index.get('frozen_junit_acceptance',{}).get('passed') is True and index.get('full_gradle_check',{}).get('passed') is True
        and integrity.get('verified_stage_identity_matches') is True and integrity.get('exact_write_scope') is True
        and not any(not isinstance(e,dict) or e.get('role')!='reviewer' for e in run.get('errors',[])))
    failures=[c for c in calls if c.get('status')=='failed']
    errors=run.get('errors',[])
    evidence=json.dumps({'errors':errors,'targets':targets,'verification':full},default=str).casefold()
    # Successful seed events/logs are not evidence of infrastructure failure.
    failed_checks=[c for c in target_checks+list(index.values()) if c.get('passed') is False]
    diagnostics=[e.get('exception_message','') for e in errors if isinstance(e,dict)]
    diagnostics.extend(v.get('exception',{}).get('message','') for v in verification_records)
    diagnostics.extend(json.dumps(c.get('detail',''),default=str) for c in failed_checks)
    diagnostic_text='\n'.join(diagnostics).casefold()
    infra_markers=('timed out','timeout','nfrt reconstruction input changed','nfrt build/tool identity mismatch','nfrt seed','cache integrity','cache_integrity','missing dependency','docker is unavailable','verifier image missing','unable to create native thread','pthread_create failed','external build-input cache','no space left')
    infra=any(x in diagnostic_text for x in infra_markers)
    if deterministic:primary='VERIFIED SOFTWARE SUCCESS'
    elif any(c.get('role')!='reviewer' for c in failures):primary='LOCAL_RUNTIME_FAILURE'
    elif infra:primary='VERIFIER_RUNTIME_FAILURE'
    elif not run.get('plan'):
        primary='OWNERSHIP_FAILURE' if 'ownership' in evidence or 'owned by' in evidence else 'PLANNER_FAILURE'
    elif index.get('full_gradle_check',{}).get('passed') is False:primary='FULL_GATE_FAILURE'
    elif any(c.get('name')=='frozen_junit_acceptance' and c.get('passed') is False for c in target_checks+list(index.values())):primary='FROZEN_ACCEPTANCE_FAILURE'
    elif targets:primary='TARGETED_VERIFICATION_FAILURE'
    elif any(e.get('stage') in ('edit_preflight','edit_apply','edit_structure','edit_validation') for e in errors if isinstance(e,dict)):primary='EDIT_PREFLIGHT_FAILURE'
    else:primary='WORKER_FAILURE'
    roles={'ui','backend','tests'}
    plan=bool(run.get('plan'))
    reached={'task':True,'planner_call':any(c['role']=='planner' for c in calls),'valid_plan':plan,'ownership_valid':plan,
        'worker':any(c['role'] in roles for c in calls),'worker_response':any(c['role'] in roles and c.get('status')=='completed' for c in calls),
        'executable_edit':bool(verification_records),'targeted_verification':any(v['kind']=='targeted' for v in verification_records),
        'worker_correction':bool(run.get('targeted_repairs')),'revised_edit':sum(v['kind']=='targeted' for v in verification_records)>1,
        'frozen_acceptance':accepted,'full_gate':any(v['kind']=='full' for v in verification_records),
        'full_gate_passed':index.get('full_gradle_check',{}).get('passed') is True,
        'semantic_review':any(c['role']=='reviewer' for c in calls),'human_review_eligibility':run.get('human_review_eligible') is True}
    return {'primary_outcome':primary,'verified_software_success':deterministic,'semantic_review':(run.get('semantic_review') or {}).get('disposition','not_run'),
        'runtime_events':[{'role':c['role'],'error':c.get('error',c.get('error_message'))} for c in failures],
        'verifier_runtime_failure':infra,'transitions':reached,'furthest_transition':next((k for k,v in reversed(list(reached.items())) if v),'task'),
        'software_frontier':next((k for k,v in reversed(list(reached.items())) if v and k not in ('semantic_review','human_review_eligibility')),'task')}

async def run_trial(cell,lock,ordinal):
    resume=None  # Fresh cells only; replacement/restart is forbidden.
    task=next(t for t in lock['tasks'] if t['id']==cell['task_id'])
    runid=resume['run_id'] if resume else uuid.uuid4().hex[:12]
    folder=HERE/'evidence/trials'/f'{ordinal:02d}-{task["id"]}-r{cell["replicate"]}-{cell["model"].replace(":","_")}'
    if not resume:folder.mkdir(parents=True,exist_ok=False)
    start=time.monotonic();started=stamp();records=[];calls=[];reserved=0;actual=0;first=None;observations=0
    if not resume:save(folder/'STARTED.json',{'run_id':runid,'ordinal':ordinal,**cell,'started_at':started,'freeze_sha256':sha(HERE/'FREEZE.json')})
    else:save(folder/'SETUP-RESUMED.json',{'at':stamp(),'run_id':runid,'no_task_model_request_before_resume':True})
    observer.OUT=folder/'runtime';observer.snapshot('pre-run-after-setup-amendment' if resume else 'pre-run')
    if resume:
        baseline=env.external_root.resolve_external_root(lock['baseline']['root'],SOURCE,RUNS)
        candidate=(RUNS/'external_candidates'/runid).resolve(strict=True)
        assert candidate.parent== (RUNS/'external_candidates').resolve(strict=True)
        assert env.external_root.tree_sha256(candidate)==lock['baseline']['sha256']
        external={'external_root_mode':'candidate_only','baseline_root':str(baseline),'baseline_revision':env.external_root._git_revision(baseline),
            'baseline_sha256':lock['baseline']['sha256'],'candidate_root':str(candidate),'snapshot_excludes':sorted(env.external_root.EXCLUDED_DIRECTORIES),'promotion_allowed':False}
    else:
        external=env.external_root.prepare_candidate(lock['baseline']['root'],RUNS/'external_candidates'/runid,SOURCE,RUNS)
    candidate=Path(external['candidate_root']);assert env.external_root.tree_sha256(candidate)==lock['baseline']['sha256']
    profile=env.hive_jvm.inspect_gradle_project(candidate);assert profile==lock['verifier']['jvm_profile']
    # Hidden acceptance is host-only storage outside the model-visible candidate.
    hidden=(TASK_SOURCE/'hidden-tests'/task['test_filename']).read_text(encoding='utf-8')
    frozen=env.hive_jvm.freeze_junit_tests(candidate,[{'path':task['test_path'],'class_name':task['test_class'],'expected_cases':task['test_cases'],'source':hidden}])
    external['jvm_profile']=profile
    external['frozen_junit_tests']=env.hive_jvm.store_frozen_junit_tests(frozen,RUNS/runid)
    save(folder/'candidate-metadata.json',external)
    monitor=observer.Monitor();restore=observer.install(env.providers,monitor)
    recorder=VerifierRecorder(folder/'verifications',capture=capture_candidate)
    async def agent_call(role,prompt):
        nonlocal first,reserved,actual,observations
        if env.providers.openai_key() or env.providers.ollama_base()!=env.OLLAMA:raise IntegrityFailure('Local-only boundary changed')
        if first is None:first=time.monotonic()
        limit=OUTPUT_LIMITS[role];reservation=len(prompt.encode())+1000+limit
        if reserved+reservation>250000:raise TrialBudget('Historical aggregate token reservation ceiling reached')
        if time.monotonic()-first>=3600:raise TrialBudget('Historical model-decision wall ceiling reached')
        reserved+=reservation
        call={'role':role,'provider':'ollama','model':cell['model'],'started_at':stamp(),'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'prompt_bytes':len(prompt.encode())}
        calls.append(call);t0=time.monotonic()
        event('model_call_started',ordinal=ordinal,run_id=runid,role=role,call=len(calls))
        try:
            schema=hive.response_schema_for_prompt(role,prompt)
            deadline=min(900.0,max(1.0,3600-(time.monotonic()-first)))
            thinking_options=env.providers.thinking_policy.worker_options(
                cell['model'],role,response_format=schema,max_output_tokens=limit,total_timeout=deadline)
            result=await env.providers.ollama_chat(cell['model'],[{'role':'user','content':prompt}],
                f'You are the bounded {role} agent inside Nix Workshop Hive Build Mode. Follow the role contract exactly.',
                response_format=schema,temperature=hive.LOCAL_TEMPERATURE,
                max_output_tokens=limit,context_window=LOCAL_CONTEXT_WINDOW,
                total_timeout=deadline,**thinking_options)
            if not all(isinstance(result.get(k),int) and result[k]>0 for k in ('input_tokens','output_tokens')):raise IntegrityFailure('Missing provider usage for completed request')
            actual+=result['input_tokens']+result['output_tokens']
            if actual>250000:raise IntegrityFailure('Actual aggregate token ceiling exceeded')
            call.update(status='completed',input_tokens=result['input_tokens'],output_tokens=result['output_tokens'],response_sha256=hashlib.sha256(result['text'].encode()).hexdigest())
            if time.monotonic()-first>3600:raise TrialBudget('Historical model-decision wall ceiling exceeded')
            if role in ('ui','backend','tests'):
                try:
                    obj=hive._extract_json(result['text'])
                    if isinstance(obj,dict) and obj.get('status')=='observe':
                        hive._validate_worker_observation(obj);observations+=1
                except (ValueError,TypeError,KeyError):pass
                if observations>6:raise TrialBudget('Historical aggregate observation ceiling reached')
            return result['text']
        except Exception as exc:
            call.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)});raise
        finally:
            call.update(ended_at=stamp(),wall_seconds=time.monotonic()-t0);save(folder/'calls.json',calls)
            event('model_call_finished',ordinal=ordinal,role=role,status=call.get('status'),seconds=call['wall_seconds'])
    metadata={'max_tier':'local','max_cost':0.0,'cloud_spend':0.0,'agent_calls':calls,'external_root':external,
        'experiment':{'study_id':STUDY,'condition_id':'hive','task_id':task['id'],'replicate_index':cell['replicate'],'condition_spec_sha256':sha(HERE/'FREEZE.json')},
        'inference':{'temperature':0.1,'seed':None,'output_token_limits':OUTPUT_LIMITS}}
    monitor.start();run=None
    try:
        with record_verifiers(recorder):
            run=await hive.run_build(candidate,RUNS,task['request'],cell['model'],agent_call,metadata=metadata,run_id=runid,external_root_mode=True,allowed_write_files=task['files'])
        hive.save_run(RUNS,run);save(folder/'run.json',run)
    finally:
        restore();monitor.stop();observer.snapshot('post-run')
        save(folder/'measurement-records.json',recorder.records);save(folder/'measurement.json',recorder.summary())
    if not recorder.summary()['scoring_permitted']:raise IntegrityFailure('MEASUREMENT_FAILURE: native outcomes preserved separately')
    records=[{**r,'kind':r['verifier_kind'],**({'report':r['result']} if 'result' in r else {}),
              **({'exception':r['verifier_exception']} if 'verifier_exception' in r else {})} for r in recorder.records]
    stage=RUNS/runid/'stage';_,stage_identity=hive._source_manifest(stage)
    baseline=Path(lock['baseline']['root']);base_inventory={r.as_posix():env.external_root._file_digest(p,baseline.resolve(),info) for p,r,info in env.external_root._inventory(baseline)}
    stage_inventory={r.as_posix():env.external_root._file_digest(p,stage.resolve(),info) for p,r,info in env.external_root._inventory(stage)}
    actual_changed=sorted(p for p in set(base_inventory)|set(stage_inventory) if base_inventory.get(p)!=stage_inventory.get(p))
    integrity={'baseline_sha256':env.external_root.tree_sha256(baseline),'candidate_origin_sha256':env.external_root.tree_sha256(candidate),
        'stage_tree_sha256':env.external_root.tree_sha256(stage),'stage_source_sha256':stage_identity,'recorded_verified_stage_sha256':run.get('verified_stage_sha256'),
        'verified_stage_identity_matches':bool(run.get('verified_stage_sha256')) and stage_identity==run['verified_stage_sha256'],
        'actual_changed_files':actual_changed,'exact_write_scope':set(actual_changed)<=set(task['files']),
        'applied':run.get('applied'),'promotion_allowed':external['promotion_allowed'],'candidate_root':str(candidate),'stage_root':str(stage)}
    if integrity['baseline_sha256']!=lock['baseline']['sha256'] or integrity['candidate_origin_sha256']!=lock['baseline']['sha256'] or run.get('applied') or external['promotion_allowed'] is not False or not integrity['exact_write_scope']:
        save(folder/'integrity.json',integrity);raise IntegrityFailure('Candidate/baseline containment failed')
    save(folder/'integrity.json',integrity);save(folder/'verification-records.json',records)
    if any(c.get('error',{}).get('type')=='IntegrityFailure' for c in calls):raise IntegrityFailure('Inference integrity boundary failed; see call evidence')
    observed=json.loads((folder/'runtime/calls.json').read_bytes()) if (folder/'runtime/calls.json').exists() else []
    result={'ordinal':ordinal,'run_id':runid,**cell,'started_at':started,'finished_at':stamp(),'wall_seconds':time.monotonic()-start,
        **classify(run,calls,records,integrity),'status':run['status'],'model_calls':len(calls),'provider_attempts':sum(len(c['attempts']) for c in observed),
        'input_tokens_known':sum(c.get('input_tokens',0) for c in observed),'output_tokens_known':sum(c.get('output_tokens',0) for c in observed),'usage_complete':all(c.get('status')=='completed' for c in observed),
        'model_seconds':sum(c['elapsed_seconds'] for c in observed),'verification_seconds':recorder.summary()['known_verification_seconds'],'measurement_status':recorder.summary()['measurement_status'],
        'planner_corrections':max(0,len(run['plan_attempts'])-1),'worker_structural_corrections':len(run['edit_repairs']),'worker_targeted_corrections':len(run['targeted_repairs']),
        'observation_requests':observations,'candidate_disposition':run.get('candidate_disposition'),'promotion_authorization':'not_authorized','native_promotion_authorization':run.get('promotion_authorization'),
        'applied':False,'evidence':str(folder),'candidate_identity':integrity}
    if resume:
        result['active_execution_wall_seconds']=result['wall_seconds']
        result['setup_interruption_seconds']=(datetime.fromisoformat(started)-datetime.fromisoformat(resume['started_at'])).total_seconds()
        result['started_at']=resume['started_at'];result['wall_seconds']+=result['setup_interruption_seconds']
    save(folder/'result.json',result);return result

async def readiness(lock):
    assert not (HERE/'evidence/READINESS-STARTED.json').exists(),'Readiness cannot be repeated'
    save(HERE/'evidence/READINESS-STARTED.json',{'at':stamp(),'order':lock['runtime_policy']['readiness_order']})
    rows=[]
    for model in lock['runtime_policy']['readiness_order']:
        observer.OUT=HERE/'evidence/readiness'/model.replace(':','_');observer.snapshot('before')
        monitor=observer.Monitor();restore=observer.install(env.providers,monitor);monitor.start();t0=time.monotonic()
        row={'model':model,'started_at':stamp()}
        event('readiness_started',model=model)
        try:
            r=await env.providers.ollama_chat(model,[{'role':'user','content':'Non-task runtime diagnostic. Return exactly the JSON object {"diagnostic":"ready"}. No software task is being requested.'}],
                'You are the bounded planner agent inside Nix Workshop Hive Build Mode. Follow the role contract exactly.',
                response_format={'type':'object','properties':{'diagnostic':{'type':'string','enum':['ready']}},'required':['diagnostic'],'additionalProperties':False},
                temperature=0.1,max_output_tokens=2048,context_window=12288,total_timeout=900)
            row.update(status='completed',response=r,valid_json=json.loads(r['text'])=={'diagnostic':'ready'})
        except Exception as exc:row.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)})
        finally:
            restore();monitor.stop();observer.snapshot('after');row.update(ended_at=stamp(),elapsed_seconds=time.monotonic()-t0);save(observer.OUT/'result.json',row)
        rows.append(row);event('readiness_finished',model=model,status=row['status'],seconds=row['elapsed_seconds'])
    save(HERE/'evidence/readiness-results.json',rows)

def main():
    lock=read(HERE/'FREEZE.json');check(lock,full=True)
    assert not (HERE/'evidence/STUDY-STARTED.json').exists(),'One execution only; no replacement cells'
    assert not list((HERE/'evidence/trials').glob('*/STARTED.json'))
    save(HERE/'evidence/STUDY-STARTED.json',{'at':stamp(),'freeze_sha256':sha(HERE/'FREEZE.json')})
    results=[]
    try:
        # Capability probes were the only pre-study non-task calls. No warmups.
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
