"""Read-only final audit; requires all frozen task cells completed."""
import json,subprocess,shutil
from common import *
import environment as env
from verification import nfrt_seed
def read(p):return json.loads(Path(p).read_bytes())
def main():
    lock=read(HERE/'FREEZE.json');results=read(HERE/'evidence/raw-results.json')
    assert len(results)==16 and (HERE/'evidence/COMPLETED.json').exists()
    expected=read(HERE/'evidence/source-inventory.json');now=manifest(SOURCE)
    source_changes=[p for p in sorted(set(expected)|set(now)) if expected.get(p)!=now.get(p)]
    original=manifest(ROOT/'HIVE-NFRT-ATTESTATION-002/repaired-workshop')
    prior=read(HERE/'evidence/prior-inventory.json');prior_changes=[]
    for p,row in prior.items():
        if not Path(p).is_file() or sha(p)!=row['sha256']:prior_changes.append(p)
    baseline=env.external_root.tree_sha256(Path(lock['baseline']['root']))
    tests={t['id']:sha(TASK_SOURCE/'hidden-tests'/t['test_filename']) for t in lock['tasks']}
    os.environ['GRADLE_USER_HOME']=lock['verifier']['approved_cache_root']
    os.environ['HIVE_NFRT_SEED_MANIFEST']=lock['nfrt']['manifest'];os.environ['HIVE_NFRT_SEED_SHA256']=lock['nfrt']['sha256']
    approved=env.approved_environment(env.reference_freeze())
    seed=nfrt_seed.configured_seed(Path(lock['baseline']['root']),Path(approved['approved_cache_root']),approved['jvm_profile'],approved['baseline_sha256'],approved['verifier_image_id'],lock['nfrt']['identity']['downloaded_manifest_sha256'])
    assert seed
    rows=[]
    for r in results:
        folder=Path(r['evidence']);run=read(folder/'run.json');ident=read(folder/'integrity.json');task=next(t for t in lock['tasks'] if t['id']==r['task_id'])
        stage=Path(ident['stage_root']);candidate=Path(ident['candidate_root'])
        requests=[]
        for p in (folder/'runtime/calls').glob('*/*/wire-request.json'):
            body=read(p);role=p.parent.parent.name.split('-',1)[1]
            text='\n'.join(m['content'] for m in body['messages'])
            requests.append({'path':str(p),'sha256':sha(p),'model_matches':body['model']==r['model'],
                'configuration_matches':body['options']=={'temperature':.1,'num_predict':OUTPUT_LIMITS[role],'num_ctx':12288} and body['truncate'] is False,
                'hidden_test_source_absent':all((TASK_SOURCE/'hidden-tests'/t['test_filename']).read_text(encoding='utf-8').strip() not in text for t in lock['tasks'])})
        frozen=run['metadata']['external_root']['frozen_junit_tests']
        frozen_ok=env.hive_jvm.verify_frozen_artifacts(frozen,HERE/'evidence/runs'/r['run_id']) and frozen[0]['sha256']==task['test_sha256']
        row={'ordinal':r['ordinal'],'run_id':r['run_id'],'task':r['task_id'],
            'candidate_still_exact_baseline':env.external_root.tree_sha256(candidate)==baseline,
            'stage_matches_end_of_trial':env.external_root.tree_sha256(stage)==ident['stage_tree_sha256'],
            'frozen_test_identity':frozen_ok,'allowed_write_files':task['files'],'actual_changed_files':ident['actual_changed_files'],
            'scoped':set(ident['actual_changed_files'])<=set(task['files']),'applied':run.get('applied'),'promotion_allowed':run['metadata']['external_root']['promotion_allowed'],
            'study_authorization':r['promotion_authorization'],'requests':requests}
        rows.append(row)
    ordered=[{k:r[k] for k in ('task_id','replicate','model','controller','historical_ordinal')} for r in results]
    ok=(not source_changes and original==expected and not prior_changes and baseline==lock['baseline']['sha256'] and approved==lock['verifier']
        and all(tests[t['id']]==t['test_sha256'] for t in lock['tasks']) and ordered==lock['order']
        and all(r['candidate_still_exact_baseline'] and r['stage_matches_end_of_trial'] and r['frozen_test_identity'] and r['scoped'] and r['applied'] is False and r['promotion_allowed'] is False and r['study_authorization']=='not_authorized'
            and all(q['model_matches'] and q['configuration_matches'] and q['hidden_test_source_absent'] for q in r['requests']) for r in rows)
        and len({r['run_id'] for r in rows})==16)
    report={'at':stamp(),'passed':ok,'source_tree_hash_before':lock['source']['tree_hash'],'source_tree_hash_after':tree_hash(now),
        'source_changes':source_changes,'original_source_matches':original==expected,'prior_files_checked':len(prior),'prior_changed':prior_changes,
        'baseline_sha256':baseline,'frozen_tests':tests,'approved_verifier_environment_matches':approved==lock['verifier'],'nfrt_attestation_sha256':sha(lock['nfrt']['manifest']),
        'exact_frozen_order':ordered==lock['order'],'trials':rows,'promotion_calls':0,
        'isolation_basis':'Every initial candidate and its unchanged candidate-origin tree matches the frozen baseline; only each run-owned private stage contains edits. Models receive only controller-mediated context inside that root. No previous stage is used as an input.'}
    save(HERE/'evidence/final-integrity.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='trials'},indent=2));assert ok
if __name__=='__main__':main()
