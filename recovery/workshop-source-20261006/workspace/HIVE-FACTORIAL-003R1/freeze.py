"""Seal qualified controller, attestation and protocol before any inference."""
import ast,copy,platform,random,shutil,subprocess,xml.etree.ElementTree as ET
from common import *
import environment as env
import runtime_observer as observer
import httpx
from verification import nfrt_seed

def command(args,timeout=30):
    p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    return {'command':args,'exit_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr}

def main():
    assert not (HERE/'FREEZE.json').exists()
    prior_study=read(ROOT/'HIVE-FACTORIAL-003/FREEZE.json')
    audit=read(ROOT/'HIVE-NFRT-ATTESTATION-002/evidence/final-audit.json');assert audit['classification']=='FACTORIAL_READY'
    config=read(ROOT/'HIVE-NFRT-ATTESTATION-002/evidence/attestation-configuration.json')
    src=manifest(SOURCE);origin=ROOT/'HIVE-NFRT-ATTESTATION-002/repaired-workshop'
    assert src==manifest(origin)==read(ROOT/'HIVE-NFRT-ATTESTATION-002/evidence/final-source-inventory.json')
    assert tree_hash(src)==audit['final_source_tree_hash']
    save(HERE/'evidence/source-inventory.json',src)
    production={p:r for p,r in src.items() if not set(Path(p).parts)&env.SOURCE_EXCLUDES}
    save(HERE/'evidence/production-inventory.json',production)
    qualified=('recorder.py','cell_harness.py')
    assert all(sha(HERE/p)==sha(ROOT/'HARNESS-QUALIFICATION-001'/p) for p in qualified)
    suites=ET.parse(HERE/'evidence/harness-tests.xml').getroot().findall('testsuite')
    counts={k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
    assert counts=={'tests':52,'failures':0,'errors':0,'skipped':0},counts
    env.no_cloud_key();assert env.providers.ollama_base()==env.OLLAMA
    approved=env.approved_environment(env.reference_freeze());assert approved==prior_study['verifier']
    os.environ['GRADLE_USER_HOME']=approved['approved_cache_root']
    os.environ['HIVE_NFRT_SEED_MANIFEST']=config['manifest'];os.environ['HIVE_NFRT_SEED_SHA256']=config['sha256']
    assert sha(config['manifest'])==config['sha256']
    att=read(config['manifest']);baseline=Path(prior_study['baseline']['root'])
    assert env.external_root.tree_sha256(baseline)==prior_study['baseline']['sha256']
    assert nfrt_seed.configured_seed(baseline,Path(approved['approved_cache_root']),approved['jvm_profile'],approved['baseline_sha256'],approved['verifier_image_id'],att['identity']['downloaded_manifest_sha256'])
    scopes=read(ROOT/'HIVE-NFRT-ATTESTATION-002/evidence/scope-preflight/matrix.json')
    assert all(r['compatible'] and r['candidate_unchanged'] for r in scopes['tasks']) and len(scopes['tasks'])==4
    with httpx.Client(timeout=15,trust_env=False) as client:
        tags=client.get(env.OLLAMA+'/api/tags').json()['models'];version=client.get(env.OLLAMA+'/api/version').json();models=[]
        for previous in prior_study['models']:
            expected=previous['historical'];entry=next(x for x in tags if x['name']==expected['name'])
            assert entry['digest']==expected['digest'],f"Model digest mismatch: {expected['name']}"
            models.append({'historical':expected,'current':entry,'show':client.post(env.OLLAMA+'/api/show',json={'model':expected['name']}).json()})
    for task in prior_study['tasks']:
        assert sha(TASK_SOURCE/'hidden-tests'/task['test_filename'])==task['test_sha256']
        assert hashlib.sha256(task['request'].encode()).hexdigest()==task['request_sha256']
    hist=read(HIST/'FREEZE.json');rng=random.Random(20261004)
    blocks=[(t,r) for t in ('J001','J002','J003','J004') for r in (1,2)];rng.shuffle(blocks);all_order=[]
    for task,rep in blocks:
        cells=[(m,c) for m in ('qwen3:8b','qwen2.5-coder:14b') for c in ('single','hive')];rng.shuffle(cells)
        all_order.extend({'task_id':task,'replicate':rep,'model':m,'controller':c} for m,c in cells)
    assert all_order==hist['order']
    order=[{**c,'historical_ordinal':i} for i,c in enumerate(all_order,1) if c['controller']=='hive']
    assert order==prior_study['order']
    app_ast=ast.parse((SOURCE/'app.py').read_text(encoding='utf-8'))
    limits=next(ast.literal_eval(n.value) for n in app_ast.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='HIVE_LOCAL_OUTPUT_TOKEN_LIMITS' for t in n.targets))
    assert limits==OUTPUT_LIMITS and env.hive.MAX_PLAN_CORRECTIONS==env.hive.MAX_EDIT_REPAIRS_PER_WORKER==env.hive.MAX_TARGETED_CORRECTIONS_PER_WORKER==1
    assert env.providers.OLLAMA_TOTAL_GENERATION_TIMEOUT==env.providers.OLLAMA_CHAT_TIMEOUT==900
    docker=shutil.which('docker');image=command([docker,'image','inspect',approved['verifier_image_id']]);assert image['exit_code']==0
    jdk=command([docker,'run','--rm','--network','none','--entrypoint','java',approved['verifier_image_id'],'-version']);assert jdk['exit_code']==0
    hardware=observer.snapshot('pre-freeze')
    hardware_inventory=command(['powershell','-NoProfile','-Command',"[ordered]@{cpu=@(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors);os=Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber;disks=@(Get-PSDrive -PSProvider FileSystem | Select-Object Name,Free,Used)} | ConvertTo-Json -Depth 5"])
    # Preserve all earlier evidence, including qualification and attestation work.
    prior=read(ROOT/'HIVE-NFRT-ATTESTATION-002/evidence/prior-before.json')
    for path,row in prior.items():assert Path(path).is_file() and sha(path)==row['sha256'],path
    for root in (ROOT/'HIVE-NFRT-ATTESTATION-002',):prior.update({str(root/p):r for p,r in manifest(root).items()})
    for path in ROOT.glob('*REPORT.md'):prior[str(path)]={'sha256':sha(path),'size':path.stat().st_size}
    save(HERE/'evidence/prior-inventory.json',prior)
    freeze=copy.deepcopy(prior_study)
    freeze.update(study=STUDY,frozen_at=stamp(),status='preregistered',source={'path':str(SOURCE),'origin':str(origin),'files':len(src),'tree_hash':tree_hash(src),'tree_hash_method':'SHA256 canonical sorted JSON path to {sha256,size}','inventory_sha256':sha(HERE/'evidence/source-inventory.json'),'production_files':production,'production_tree_hash':tree_hash(production)},
        models=models,ollama_version=version,docker_image=image,java_identity=jdk,gradle_identity=approved['jvm_profile'],verifier=approved,
        nfrt={'manifest':config['manifest'],'sha256':config['sha256'],'identity':att['identity'],'independent_source_policy':att['independent_source_policy'],'entries':att['entries'],'policy':'Pinned v2 source-class attestation from NFRT-ATTESTATION-002; no changes during study'},
        order=order,hardware=hardware,hardware_inventory=hardware_inventory,python={'version':sys.version,'executable':sys.executable,'platform':platform.platform()},
        qualification={'recorder_and_cell_harness_sha256':{p:sha(HERE/p) for p in qualified},'regression':counts,'nfrt_final_audit_sha256':sha(ROOT/'HIVE-NFRT-ATTESTATION-002/evidence/final-audit.json'),'all_task_scopes_compatible':True},
        known_limitations_before_trials=['Historical runs occurred before multiple intentional controller/infrastructure repairs; no single-repair attribution.','Runtime readiness is a short diagnostic only, not proof of full-workload capacity.','Resource-only targeted routing observation is deferred; all four authorized task scopes are Java.'],
        instrumentation_files={p.name:sha(p) for p in HERE.glob('*.py')},prior_inventory_sha256=sha(HERE/'evidence/prior-inventory.json'))
    freeze['provider']['environment']={k:os.environ.get(k) for k in ('OLLAMA_BASE_URL','OLLAMA_CONTEXT_LENGTH','OLLAMA_NUM_PARALLEL','OLLAMA_MAX_LOADED_MODELS','OLLAMA_KEEP_ALIVE')}
    freeze['safety']['inherited_cloud_credential_removed_from_study_process']=INHERITED_CLOUD_CREDENTIAL_REMOVED
    freeze['runtime_policy']['readiness']='Exactly one bounded non-task request per model in frozen order before cells; no further warmups.'
    save(HERE/'FREEZE.json',freeze);(HERE/'LOCK.sha256').write_text(sha(HERE/'FREEZE.json')+'\n')
    event('frozen',source_tree_hash=tree_hash(src),trials=16,model_digests_match=True,prior_files_sealed=len(prior))

if __name__=='__main__':main()
