"""Read-only preflight and preregistration. No inference or controller edits."""
import ast,json,os,platform,random,shutil,subprocess,sys
from common import *
import environment as env
import httpx
from verification import nfrt_seed
import runtime_observer as observer

def command(args,timeout=30):
    cp=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    return {'command':args,'exit_code':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr}

def preflight():
    assert not (HERE/'FREEZE.json').exists(),'Freeze already exists'
    hist=json.loads((HIST/'FREEZE.json').read_bytes())
    config=json.loads((ROOT/'HIVE-TRANSITION-005/evidence/configuration.json').read_bytes())
    source=manifest(SOURCE);original=manifest(ROOT/'HIVE-REVIEWER-POLICY-001/repaired-workshop')
    assert source==original
    sealed=json.loads((ROOT/'HIVE-REVIEWER-POLICY-001/evidence/final-source-manifest.json').read_bytes())
    assert all(source[p]['sha256']==h for p,h in sealed.items())
    delivery=json.loads((ROOT/'HIVE-REVIEWER-POLICY-001/evidence/delivery-seal.json').read_bytes())
    assert all(sha(ROOT/'HIVE-REVIEWER-POLICY-001'/p)==h for p,h in delivery['files_sha256'].items())
    assert sha(ROOT/'HIVE-REVIEWER-POLICY-001-REPORT.md')==delivery['report_sha256']
    save(HERE/'evidence/source-inventory.json',source)
    production={p:r for p,r in source.items() if not set(Path(p).parts)&env.SOURCE_EXCLUDES}
    save(HERE/'evidence/production-inventory.json',production)
    # Seal all prior experiment artifacts in this workspace and historical study.
    prior={}
    for p in ROOT.rglob('*'):
        if p.is_file() and not p.is_symlink() and not p.is_relative_to(HERE):prior[str(p)]={'sha256':sha(p),'size':p.stat().st_size}
    for root in (HIST,TASK_SOURCE):
        prior.update({str(root/p):row for p,row in manifest(root).items()})
    history=json.loads((ROOT/'HIVE-REVIEWER-ANALYSIS-001/evidence/inventory.json').read_bytes())
    for row in [r for g in history['groups'] for r in g['records']]+history['other_result_files']:
        assert sha(row['path'])==row['sha256'];prior[row['path']]={'sha256':row['sha256'],'size':Path(row['path']).stat().st_size}
    save(HERE/'evidence/prior-inventory.json',prior)
    approved=env.approved_environment(env.reference_freeze());assert approved==config['approved']
    os.environ['HIVE_NFRT_SEED_MANIFEST']=config['manifest'];os.environ['HIVE_NFRT_SEED_SHA256']=config['manifest_sha256']
    assert sha(config['manifest'])==config['manifest_sha256']
    att=json.loads(Path(config['manifest']).read_bytes())
    seed=nfrt_seed.configured_seed(Path(hist['baseline']['root']),Path(approved['approved_cache_root']),approved['jvm_profile'],approved['baseline_sha256'],approved['verifier_image_id'],att['identity']['downloaded_manifest_sha256'])
    assert seed and seed['sha256']==config['manifest_sha256']
    assert env.external_root.tree_sha256(Path(hist['baseline']['root']))==hist['baseline']['sha256']
    env.no_cloud_key();assert env.providers.ollama_base()=='http://127.0.0.1:11434'
    with httpx.Client(timeout=10,trust_env=False) as client:
        tags=client.get(env.OLLAMA+'/api/tags').json()['models'];version=client.get(env.OLLAMA+'/api/version').json()
        models=[]
        for expected in hist['models']:
            entry=next(x for x in tags if x['name']==expected['name'])
            show=client.post(env.OLLAMA+'/api/show',json={'model':expected['name']}).json()
            assert entry['digest']==expected['digest'],f"Digest mismatch: {expected['name']}"
            models.append({'historical':expected,'current':entry,'show':show})
    for task in hist['tasks']:
        assert sha(TASK_SOURCE/'hidden-tests'/task['test_filename'])==task['test_sha256']
        assert hashlib.sha256(task['request'].encode()).hexdigest()==task['request_sha256']
    # Recover and validate the historical randomized block algorithm.
    rng=random.Random(20261004);blocks=[(t,r) for t in ('J001','J002','J003','J004') for r in (1,2)];rng.shuffle(blocks);order=[]
    for task,rep in blocks:
        cells=[(m,c) for m in ('qwen3:8b','qwen2.5-coder:14b') for c in ('single','hive')];rng.shuffle(cells)
        order.extend({'task_id':task,'replicate':rep,'model':m,'controller':c} for m,c in cells)
    assert order==hist['order']
    order=[{**c,'historical_ordinal':i} for i,c in enumerate(order,1) if c['controller']=='hive']
    # Extract the role limits as literal data without importing app/database.
    app_ast=ast.parse((SOURCE/'app.py').read_text(encoding='utf-8'))
    limits=next(ast.literal_eval(n.value) for n in app_ast.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='HIVE_LOCAL_OUTPUT_TOKEN_LIMITS' for t in n.targets))
    assert limits==OUTPUT_LIMITS
    assert env.hive.MAX_PLAN_CORRECTIONS==env.hive.MAX_EDIT_REPAIRS_PER_WORKER==env.hive.MAX_TARGETED_CORRECTIONS_PER_WORKER==1
    assert env.providers.OLLAMA_TOTAL_GENERATION_TIMEOUT==env.providers.OLLAMA_CHAT_TIMEOUT==900
    docker=shutil.which('docker');assert docker
    image=command([docker,'image','inspect',hist['verifier_image']]);assert image['exit_code']==0
    jdk=command([docker,'run','--rm','--network','none','--entrypoint','java',hist['verifier_image_id'],'-version']);assert jdk['exit_code']==0
    hardware=observer.snapshot('pre-freeze')
    extras=command(['powershell','-NoProfile','-Command',"[ordered]@{cpu=@(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors);os=Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber;disks=@(Get-PSDrive -PSProvider FileSystem | Select-Object Name,Free,Used)} | ConvertTo-Json -Depth 5"])
    freeze={'study':STUDY,'frozen_at':stamp(),'status':'preregistered','historical_freeze':{'path':str(HIST/'FREEZE.json'),'sha256':sha(HIST/'FREEZE.json')},
        'source':{'path':str(SOURCE),'origin':str(ROOT/'HIVE-REVIEWER-POLICY-001/repaired-workshop'),'files':len(source),'tree_hash':tree_hash(source),'tree_hash_method':'SHA256 canonical sorted JSON mapping path to SHA256 and byte size','inventory_sha256':sha(HERE/'evidence/source-inventory.json'),'production_files':production,'production_tree_hash':tree_hash(production)},
        'baseline':hist['baseline'],'tasks':hist['tasks'],'models':models,'ollama_version':version,'docker_image':image,'java_identity':jdk,'gradle_identity':approved['jvm_profile'],'verifier':approved,
        'nfrt':{'manifest':config['manifest'],'sha256':config['manifest_sha256'],'identity':att['identity'],'independent_java_sources':att['independent_java_sources'],'entries':att['entries'],'policy':'Existing fail-closed compatibility policy, unchanged. No broadened attestation.'},
        'provider':{'endpoint':env.OLLAMA+'/api/chat','temperature':0.1,'num_ctx':12288,'truncate':False,'stream':True,'output_limits':limits,'max_http_attempts':2,'per_attempt_generation_seconds':900,'read_timeout_seconds':900,'stop':None,'seed':None,'keep_alive':None,'num_gpu':None,'num_batch':None,'unspecified_options':'Provider/server defaults remain unchanged','environment':{k:os.environ.get(k) for k in ('OLLAMA_BASE_URL','OLLAMA_CONTEXT_LENGTH','OLLAMA_NUM_PARALLEL','OLLAMA_MAX_LOADED_MODELS','OLLAMA_KEEP_ALIVE')}},
        'budgets':{'planner_corrections':1,'structural_worker_corrections':1,'targeted_worker_corrections':1,'replans_per_worker':1,'observations_per_worker':6,'historical_aggregate_token_ceiling':250000,'historical_model_decision_wall_seconds':3600,'targeted_seconds':240,'full_outer_seconds':660,'full_inner_seconds':600},
        'order':order,'randomization':{'algorithm':'Historical random.Random(20261004), shuffled task/replicate blocks and model/controller cells, then filter Hive; identical relative Hive order','seed':20261004},
        'conditions':['hive'],'single_control_omission':'Historical single adapter invokes Hive.run_build; copying it onto repaired Hive violates the requested independent-control boundary. No newly invented control.',
        'runtime_policy':{'sequential_trials':True,'readiness':'One bounded synthetic non-task request per model before trials, planner settings; no additional warmups. Not scored as a task trial.','readiness_order':['qwen2.5-coder:14b','qwen3:8b'],'residency':'Observe actual state. No explicit load/unload/keep-alive changes; automatic Ollama residency remains unmanaged for all trials.','failed_trial_replacement':False,'runtime_failure':'Existing provider retry only. Unchanged normal Hive protocol; no manual retry, restart, tuning or process termination.','resource_sampling':'Before/after trial, asynchronous request/attempt boundaries and every 30 seconds.','promotion_authorization':'not_authorized','native_external_guard':'Controller may report blocked; retained independently from absence of human authorization.'},
        'hardware':hardware,'hardware_inventory':extras,'python':{'version':sys.version,'executable':sys.executable,'platform':platform.platform()},
        'known_limitations_before_trials':['Existing NFRT attestation permits source changes only to SnapshotFormatter.java. J002-J004 edits can fail compatibility validation; recorded as verifier/policy infrastructure failures, never repaired here.','Historical and current controller/context/verifier versions intentionally differ. No attribution to one repair.'],
        'safety':{'cloud':False,'inherited_cloud_credential_removed_from_study_process':INHERITED_CLOUD_CREDENTIAL_REMOVED,'promotion':False,'hidden_tests_in_model_context':False,'previous_candidates_in_context':False,'repairs_during_study':False,'rerun_tasks':True,'no_build_cache':True,'offline':True},
        'instrumentation_files':{p.name:sha(p) for p in HERE.glob('*.py')},'prior_inventory_sha256':sha(HERE/'evidence/prior-inventory.json')}
    save(HERE/'FREEZE.json',freeze);(HERE/'LOCK.sha256').write_text(sha(HERE/'FREEZE.json')+'\n')
    event('frozen',source_tree_hash=freeze['source']['tree_hash'],trials=16,model_digests_match=True,prior_files_sealed=len(prior))

if __name__=='__main__':preflight()
