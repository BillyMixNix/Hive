"""Freeze minimal transport intervention and six prospective conditions."""
import ast,copy,platform,subprocess,xml.etree.ElementTree as ET
import httpx
from common import *
import environment as env
import runtime_observer as observer
from verification import nfrt_seed

def counts(path):
    suites=ET.parse(path).getroot().findall('testsuite')
    return {k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}

def main():
    assert not (HERE/'FREEZE.json').exists()
    old=ROOT/'HIVE-FACTORIAL-003R1';prior=read(old/'FREEZE.json')
    origin=manifest(old/'repaired-workshop');assert origin==read(HERE/'evidence/source-before.json')
    assert tree_hash(origin)==prior['source']['tree_hash']
    source=manifest(SOURCE);changed=sorted(p for p in set(origin)|set(source) if origin.get(p)!=source.get(p))
    allowed=['app.py','workshop/providers.py','workshop/thinking_policy.py','workshop/thinking_profiles.json','tests/test_thinking_policy.py','tests/test_semantic_fidelity.py']
    assert changed==sorted(allowed),changed
    save(HERE/'evidence/source-inventory.json',source)
    production={p:r for p,r in source.items() if not set(Path(p).parts)&env.SOURCE_EXCLUDES}
    save(HERE/'evidence/production-inventory.json',production)
    tests=counts(HERE/'evidence/full-regression-final/pytest.xml')
    assert tests['tests']>=621 and tests['failures']==tests['errors']==0 and tests['skipped']==6,tests
    harness=counts(HERE/'evidence/harness-tests.xml');assert harness==dict(tests=52,failures=0,errors=0,skipped=0),harness
    assert all(sha(HERE/p)==sha(ROOT/'HARNESS-QUALIFICATION-001'/p) for p in ('recorder.py','cell_harness.py'))
    proof=read(HERE/'evidence/capability/result.json');assert proof['supported'] and proof['source_unchanged']
    assert read(HERE/'evidence/prior-audit-before.json')['passed']
    env.no_cloud_key();approved=env.approved_environment(env.reference_freeze());assert approved==prior['verifier']
    baseline=Path(prior['baseline']['root']);assert env.external_root.tree_sha256(baseline)==prior['baseline']['sha256']
    config=read(ROOT/'HIVE-NFRT-ATTESTATION-002/evidence/attestation-configuration.json')
    assert sha(config['manifest'])==config['sha256']==prior['nfrt']['sha256']
    os.environ['GRADLE_USER_HOME']=approved['approved_cache_root']
    os.environ['HIVE_NFRT_SEED_MANIFEST']=config['manifest'];os.environ['HIVE_NFRT_SEED_SHA256']=config['sha256']
    assert nfrt_seed.configured_seed(baseline,Path(approved['approved_cache_root']),approved['jvm_profile'],approved['baseline_sha256'],approved['verifier_image_id'],prior['nfrt']['identity']['downloaded_manifest_sha256'])
    with httpx.Client(timeout=15,trust_env=False) as c:
        tags=c.get(env.OLLAMA+'/api/tags').json()['models'];version=c.get(env.OLLAMA+'/api/version').json()
        entry=next(m for m in tags if m['name']==proof['model']);show=c.post(env.OLLAMA+'/api/show',json={'model':proof['model']}).json()
    assert version==proof['version'] and entry['digest']==proof['digest']
    assert hashlib.sha256(show['template'].encode()).hexdigest()==proof['template_sha256']
    for t in prior['tasks']:
        assert sha(TASK_SOURCE/'hidden-tests'/t['test_filename'])==t['test_sha256']
        assert hashlib.sha256(t['request'].encode()).hexdigest()==t['request_sha256']
    selected=(3,6,8,9,12,15)
    order=[{**prior['order'][i-1],'historical_cell':i} for i in selected]
    assert all(c['model']==proof['model'] for c in order)
    assert env.hive.MAX_PLAN_CORRECTIONS==env.hive.MAX_EDIT_REPAIRS_PER_WORKER==env.hive.MAX_TARGETED_CORRECTIONS_PER_WORKER==1
    assert env.providers.OLLAMA_TOTAL_GENERATION_TIMEOUT==env.providers.OLLAMA_CHAT_TIMEOUT==900
    app=ast.parse((SOURCE/'app.py').read_text(encoding='utf-8'))
    limits=next(ast.literal_eval(n.value) for n in app.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='HIVE_LOCAL_OUTPUT_TOKEN_LIMITS' for t in n.targets))
    assert limits==OUTPUT_LIMITS
    freeze=copy.deepcopy(prior)
    freeze.update(study=STUDY,frozen_at=stamp(),status='preregistered',historical_control={'path':str(old/'FREEZE.json'),'sha256':sha(old/'FREEZE.json'),'selected_cells':list(selected)},
        source={'path':str(SOURCE),'origin':str(old/'repaired-workshop'),'origin_tree_hash':tree_hash(origin),'tree_hash':tree_hash(source),'files':len(source),
                'tree_hash_method':'SHA256 canonical sorted JSON path to {sha256,size}','production_files':production,'production_tree_hash':tree_hash(production),'changed_files':changed},
        models=[{'historical':next(m['historical'] for m in prior['models'] if m['historical']['name']==proof['model']),'current':entry,'show':show}],
        ollama_version=version,order=order,hardware=observer.snapshot('pre-freeze'),
        python={'version':sys.version,'executable':sys.executable,'platform':platform.platform()},
        thinking_policy={'worker_think':False,'eligible_roles':['ui','backend','tests'],'structured_bounded_only':True,'planner':'omitted/default','reviewer':'omitted/default',
            'capability_profile':read(SOURCE/'workshop/thinking_profiles.json'),'capability_proof_sha256':sha(HERE/'evidence/capability/result.json'),'per_request_identity_validation':True},
        regression=tests,harness_regression=harness,
        instrumentation_files={p.name:sha(p) for p in HERE.glob('*.py')},prior_inventory_sha256=sha(HERE/'evidence/prior-inventory.json'),
        protocol_sha256=sha(HERE/'PROTOCOL.md'))
    freeze['runtime_policy']['readiness']='Only the two pre-edit non-task capability probes; no further warmups or residency normalization. Preserve actual residency and resource state.'
    freeze['runtime_policy']['readiness_order']=[]
    freeze['safety']['inherited_cloud_credential_removed_from_study_process']=INHERITED_CLOUD_CREDENTIAL_REMOVED
    freeze['provider']['environment']={k:os.environ.get(k) for k in ('OLLAMA_BASE_URL','OLLAMA_CONTEXT_LENGTH','OLLAMA_NUM_PARALLEL','OLLAMA_MAX_LOADED_MODELS','OLLAMA_KEEP_ALIVE')}
    save(HERE/'FREEZE.json',freeze);(HERE/'LOCK.sha256').write_text(sha(HERE/'FREEZE.json')+'\n')
    event('frozen',source_tree_hash=tree_hash(source),prospective_cells=6,regression=tests,harness=harness)

if __name__=='__main__':main()
