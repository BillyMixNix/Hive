"""Preserve and audit an invalid measurement attempt; no inference or replay."""
import json,sys
from common import *
import environment as env
from verification import nfrt_seed
def read(p):return json.loads(Path(p).read_bytes())
def main():
    lock=read(HERE/'FREEZE.json');expected=read(HERE/'evidence/source-inventory.json');current=manifest(SOURCE)
    prior=read(HERE/'evidence/prior-inventory.json');changed=[]
    for p,row in prior.items():
        if not Path(p).is_file() or sha(p)!=row['sha256']:changed.append(p)
    os.environ['GRADLE_USER_HOME']=lock['verifier']['approved_cache_root']
    os.environ['HIVE_NFRT_SEED_MANIFEST']=lock['nfrt']['manifest'];os.environ['HIVE_NFRT_SEED_SHA256']=lock['nfrt']['sha256']
    approved=env.approved_environment(env.reference_freeze())
    seed=nfrt_seed.configured_seed(Path(lock['baseline']['root']),Path(approved['approved_cache_root']),approved['jvm_profile'],approved['baseline_sha256'],approved['verifier_image_id'],lock['nfrt']['identity']['downloaded_manifest_sha256'])
    assert seed
    folder=HERE/'evidence/trials/01-J001-r2-qwen2.5-coder_14b';run=read(folder/'run.json');identity=read(folder/'integrity.json')
    calls=read(folder/'runtime/calls.json');attempts=[]
    for p in (folder/'runtime/calls').glob('*/*/transport.json'):
        row=read(p);body=read(p.parent/'wire-request.json');role=row['role']
        assert body['model']=='qwen2.5-coder:14b' and body['options']=={'temperature':.1,'num_predict':OUTPUT_LIMITS[role],'num_ctx':12288} and body['truncate'] is False
        text='\n'.join(m['content'] for m in body['messages'])
        assert all((TASK_SOURCE/'hidden-tests'/t['test_filename']).read_text(encoding='utf-8').strip() not in text for t in lock['tasks'])
        row['wire_sha256']=sha(p.parent/'wire-request.json');attempts.append(row)
    rows=read(folder/'verification-records.json')
    assert len(rows)==1 and 'report' not in rows[0] and 'host_elapsed_seconds' not in rows[0]
    assert not list((HERE/'evidence/runs').glob('*/verification/*/invocation.json'))
    before=read(folder/'verifications/01-targeted/candidate.json')
    scope=lock['tasks'][0]['files'];copied=folder/'verifications/01-targeted/applied-source'
    assert set(before['files'])==set(scope) and all(sha(copied/p)==h for p,h in before['files'].items())
    tests={t['id']:sha(TASK_SOURCE/'hidden-tests'/t['test_filename']) for t in lock['tasks']}
    source_changes=[p for p in sorted(set(expected)|set(current)) if expected.get(p)!=current.get(p)]
    original_match=manifest(ROOT/'HIVE-REVIEWER-POLICY-001/repaired-workshop')==expected
    candidate_hash=env.external_root.tree_sha256(Path(identity['candidate_root']));stage_hash=env.external_root.tree_sha256(Path(identity['stage_root']))
    invariant=(not source_changes and original_match and not changed and approved==lock['verifier']
        and all(tests[t['id']]==t['test_sha256'] for t in lock['tasks'])
        and candidate_hash==stage_hash==lock['baseline']['sha256'] and run['applied'] is False)
    audit={'at':stamp(),'artifact_integrity_passed':invariant,'experimental_measurement_valid':False,
        'classification':'EXPERIMENT_INVALID','reason':'New measurement harness raised before actual verifier invocation, changing the live controller trajectory.',
        'source_tree_hash_before':lock['source']['tree_hash'],'source_tree_hash_after':tree_hash(current),'source_changes':source_changes,'original_source_matches':original_match,
        'prior_files_checked':len(prior),'prior_files_changed':changed,'baseline_sha256':approved['baseline_sha256'],'frozen_test_hashes':tests,
        'verifier_image_id':approved['verifier_image_id'],'approved_environment_matches':approved==lock['verifier'],
        'nfrt_attestation_sha256':sha(lock['nfrt']['manifest']),'nfrt_seed_verified':True,'candidate_origin_sha256':candidate_hash,'rolled_back_stage_sha256':stage_hash,
        'transient_candidate':before,'transient_candidate_preserved':True,'applied':False,'promotion_allowed':False,'promotion_authorization':'not_authorized',
        'actual_verifier_invocations':0,'frozen_acceptance':'not_run','full_gate':'not_run','planned_trials':16,'valid_completed_trials':0,'compromised_cells':1,'unstarted_cells':15,
        'task_model_calls':len(calls),'task_provider_attempts':sum(len(c['attempts']) for c in calls),'known_input_tokens':sum(c.get('input_tokens',0) for c in calls),
        'known_output_tokens':sum(c.get('output_tokens',0) for c in calls),'model_seconds':sum(c['elapsed_seconds'] for c in calls),
        'token_accounting_limitation':'First failed allocation attempt has no terminal token usage; totals are completed logical-call counts only.',
        'provider_attempts':attempts,'task_trials_replaced':0,'readiness_repeated':False,'study_executor_exit':'Exited by KeyError before the next cell; no process was killed by the subsequent stop check.'}
    save(HERE/'evidence/final-integrity.json',audit)
    save(HERE/'evidence/invalid-cell.json',{'ordinal':1,'run_id':run['id'],'task':'J001','replicate':2,'model':'qwen2.5-coder:14b','controller':'hive',
        'primary_software_outcome':'NOT_ESTIMABLE_HARNESS_COMPROMISED','study_classification':'EXPERIMENT_INVALID','native_status':run['status'],
        'semantic_review':run['semantic_review']['disposition'],'review_interpretation':'Review of an empty diff after harness-caused rollback; not an independent finding on the generated candidate.',
        'promotion_authorization':'not_authorized','native_promotion_authorization':run.get('promotion_authorization'),'applied':False,
        'furthest_unscored_observed_transition':'Scoped executable edit, then instrumented-verifier exception before actual verification',
        'plan':run['plan'],'errors':run.get('errors'),'calls':calls,'verification_records':rows,'transient_candidate':before})
    print(json.dumps({k:v for k,v in audit.items() if k not in ('provider_attempts','transient_candidate')},indent=2));assert invariant
if __name__=='__main__':main()
