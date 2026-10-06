"""Final read-only byte audit and qualification criteria, never a study restart."""
import importlib.util,json,xml.etree.ElementTree as ET
from qcommon import *
from run_controls import canonical
def main():
    before=read(HERE/'evidence/production-before.json');current=manifest(SOURCE)
    differences=[p for p in sorted(set(before)|set(current)) if before.get(p)!=current.get(p)]
    prior=read(HERE/'evidence/prior-before.json')
    changed=[p for p,r in prior.items() if not Path(p).is_file() or sha(p)!=r['sha256']]
    spec=importlib.util.spec_from_file_location('read_only_historical_environment',PRIOR/'environment.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    approved=mod.approved_environment(mod.reference_freeze());assert approved==FREEZE['verifier']
    assert attest(Path(FREEZE['baseline']['root']))
    sources_ok=not differences and not changed and external_root.tree_sha256(Path(FREEZE['baseline']['root']))==FREEZE['baseline']['sha256']
    tests={t['id']:sha(TASK_SOURCE/'hidden-tests'/t['test_filename'])==t['test_sha256'] for t in FREEZE['tasks']}
    controls=read(HERE/'evidence/controls/results.json');comparisons=read(HERE/'evidence/controls/comparison.json')
    expected=[]
    for r in controls:
        frozen=next((c for c in r['report']['checks'] if c['name']=='frozen_junit_acceptance'),None)
        testrows=(frozen or {}).get('detail',{}).get('tests',[])
        totals={k:sum(t.get(k,0) for t in testrows) for k in ('tests','failures','errors','skipped')}
        native=r['native_invocation_evidence']
        proof=(len(native)==1 and native[0]['phase_counts']['gradle_invoked']==1 and native[0]['phase_counts']['junit_reports_collected']==1 and native[0]['phase_counts']['verifier_process_exit']==1)
        baseline=r['label'].startswith('A');expected_counts={'tests':3,'failures':1 if baseline else 0,'errors':0,'skipped':0}
        expected.append({'label':r['label'],'counts':totals,'historical_result_reproduced':totals==expected_counts and r['report']['passed'] is (not baseline),
            'native_invocation_proven':proof,'timed_out':(frozen or {}).get('detail',{}).get('timed_out'),
            'failure_identities':[d['test_name'] for t in testrows for d in t.get('failure_diagnostics',[])],
            'seconds':r['wall_seconds'],'measurement_status':(r.get('recorder') or {}).get('measurement_status','UNINSTRUMENTED')})
    dry=read(HERE/'evidence/scripted-cell/qualification.json');matrix=read(HERE/'evidence/nfrt-preflight/matrix.json')
    unit=ET.parse(HERE/'evidence/final-unit-tests.xml').getroot()
    suites=[unit] if unit.tag=='testsuite' else unit.findall('testsuite')
    totals={k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
    criteria={
        'production_unchanged':not differences,'prior_evidence_unchanged':not changed,
        'real_verifier_once_per_control':all(r['native_invocation_proven'] for r in expected),
        'instrumented_decisions_match':all(c['acceptance_fields_equal'] and c['candidate_identity_equal'] and c['frozen_test_identity_equal'] and c['integrity_passed'] and c['measurement_status']=='MEASURED' for c in comparisons),
        'controls_reach_expected_meaningful_results':all(r['historical_result_reproduced'] and r['timed_out'] is False for r in expected),
        'deterministic_exception_timeout_and_measurement_tests':totals['failures']==totals['errors']==0 and totals['tests']>=51,
        'sentinel_proof':all(r['wrapper_underlying_call_delta']==1 and r['argument_identity_preserved'] and (r['return_identity_preserved'] or r['exception_identity_preserved']) for r in read(HERE/'evidence/sentinel-proof.json')),
        'scripted_full_cell_and_rollback':dry['passed'],'all_task_scopes_preflighted':len(matrix['tasks'])==4,
        'final_baseline_tests_cache_integrity':sources_ok and all(tests.values()) and approved==FREEZE['verifier'] and sha(FREEZE['nfrt']['manifest'])==FREEZE['nfrt']['sha256']}
    qualified=all(criteria.values());ready=all(r['compatible'] for r in matrix['tasks'])
    report={'at':stamp(),'harness_qualified':qualified,'factorial_ready':ready,
        'classification':'FACTORIAL_NOT_READY' if qualified and not ready else 'HARNESS_QUALIFIED' if qualified else 'HARNESS_REPAIRED_NOT_QUALIFIED',
        'criteria':criteria,'production_files_checked':len(before),'production_changes':differences,'prior_files_checked':len(prior),'prior_changes':changed,
        'baseline_sha256':external_root.tree_sha256(Path(FREEZE['baseline']['root'])),'frozen_tests':tests,'nfrt_attestation_sha256':sha(FREEZE['nfrt']['manifest']),
        'verifier_image_id':approved['verifier_image_id'],'unit_tests':totals,'real_controls':expected,'model_calls':0,'factorial_trials':0,'promotion_calls':0}
    save(HERE/'evidence/final-audit.json',report);print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':main()
