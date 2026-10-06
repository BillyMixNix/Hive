"""After controls, verify identities, cache hits/fresh compilation and history immutability."""
import ast,difflib,importlib.util,re,xml.etree.ElementTree as ET
from common import *

def junit_totals(path):
    root=ET.parse(path).getroot();suites=[root] if root.tag=='testsuite' else root.findall('testsuite')
    return {k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
def main():
    assert read(OUT/'final-validation-steps.json')[-1]['exit_code']==0
    original=read(OUT/'original-source.json');original_now=inventory(ORIGINAL)
    prior=read(OUT/'prior-before.json');changes=[p for p,r in prior.items() if not Path(p).is_file() or sha(p)!=r['sha256']]
    # Includes all sealed priming files, downloaded assets/artifacts, modules,
    # manifests, image and baseline. Read-only and after timed controls finish.
    spec=importlib.util.spec_from_file_location('nfrt_read_only_environment',ROOT/'HIVE-FACTORIAL-003/environment.py')
    env=importlib.util.module_from_spec(spec);spec.loader.exec_module(env)
    approved=env.approved_environment(env.reference_freeze());assert approved==FREEZE['verifier']
    doc=read(OUT/'approved-nfrt-seed-v2.json');old=read(FREEZE['nfrt']['manifest'])
    assert attest(BASE,OUT/'approved-nfrt-seed-v2.json')
    current=inventory(SOURCE)
    changed=[p for p in sorted(set(current)|set(original)) if current.get(p)!=original.get(p)]
    allowed={'verification/nfrt_seed.py','verification/NFRT-SEED-POLICY.md','tests/test_nfrt_source_policy.py','tests/test_semantic_fidelity.py'}
    source_bound=set(changed)==allowed
    save(OUT/'final-source-inventory.json',current)
    tree_hash=hashlib.sha256(json.dumps(current,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    patches=[]
    for p in changed:
        before=(ORIGINAL/p).read_text(encoding='utf-8').splitlines(True) if (ORIGINAL/p).is_file() else []
        patches.extend(difflib.unified_diff(before,(SOURCE/p).read_text(encoding='utf-8').splitlines(True),fromfile='original/'+p,tofile='repaired/'+p))
    (HERE/'production-and-tests.patch').write_text(''.join(patches),encoding='utf-8')
    no_benchmark_logic=not any(s in (SOURCE/'verification/nfrt_seed.py').read_text() for s in ('J001','J002','J003','J004','SnapshotFormatter','IngredientAllocation','Observation.java','ExecutionContext','ExecutionAssessment'))
    nodes={n['node'] for n in read(HERE/'reconstruction-dependency-model.json')['nodes']};controls=[]
    for row in read(OUT/'real-controls/qualified-results.json'):
        inv=row['native_invocation_evidence'];negative=row['label'].startswith('negative')
        output='';raw=None;events=[]
        if inv:
            path=Path(inv[0]['invocation_file']).parent
            raw=read(path/'stdout.log')
            for c in raw['checks']:
                detail=c.get('detail',{})
                if isinstance(detail,dict):output+=detail.get('stdout_tail','')+'\n'
            events=[json.loads(line) for line in (path/'verification-events.jsonl').read_text().splitlines()]
        clean=re.sub(r'\x1b\[[0-9;]*m','',output)
        hits=set(re.findall(r'Used cache of (\w+)',clean))
        compile_events=row['compile_events'];entered={e['task']:e for e in compile_events if e['event']=='java_compile_actions_entered'}
        completed={e['task'] for e in compile_events if e['event']=='java_compile_actions_complete'}
        frozen=next((c['detail'] for c in (raw or {}).get('checks',[]) if c['name']=='frozen_junit_acceptance'),{})
        counts={k:sum(t.get(k,0) for t in frozen.get('tests',[])) for k in ('tests','failures','errors','skipped')}
        native_checks=(raw or {}).get('checks',[])
        source_explicit=any(c['name']=='source_immutability' and c['passed'] is True for c in native_checks)
        # Unchanged jvm_runner.py:683-692 checks source/runtime digests BEFORE
        # returning a behavioral failure, but emits an explicit positive row
        # only on the passing targeted branch (:694-700). Infer only from a
        # normally returned, complete frozen FAIL with that exact control flow.
        # Never insert a synthetic check into the verifier's preserved report.
        source_inferred=bool(raw and raw.get('passed') is False
            and len(native_checks)==1
            and native_checks[0].get('name')=='frozen_junit_acceptance'
            and native_checks[0].get('passed') is False
            and frozen.get('timed_out') is False and not frozen.get('report_error')
            and frozen.get('tests') and raw.get('executed_commands')
            and current['verification/jvm_runner.py']==original['verification/jvm_runner.py'])
        source_check=source_explicit or source_inferred
        source_status=('EXPLICIT_PASS' if source_explicit else
            'INFERRED_PASS_FROM_COMPLETED_FAILURE_PATH' if source_inferred else
            'NOT_INVOKED' if negative else 'NOT_ESTABLISHED')
        seed_events=[e for e in events if e['phase']=='nfrt_seed_copy_complete']
        seed_details=seed_events[0].get('source_event',{}).get('details',{}) if seed_events else {}
        fresh=all(t in entered and entered[t].get('incremental') is False and t in completed for t in (':compileJava',':compileTestJava'))
        command_flags=all('--rerun-tasks' in c['argv'] and '--no-build-cache' in c['argv'] and '--offline' in c['argv'] for c in (raw or {}).get('executed_commands',[]))
        tests_expected=counts=={'tests':3,'failures':0 if row['label']=='known-good-J001' else 1,'errors':0,'skipped':0}
        result={'label':row['label'],'seconds':row['seconds'],'passed':row['report']['passed'],'counts':counts,'native_invocations':len(inv),
            'recorder_invocations':len(row['records']),'measurement_status':row['recorder']['measurement_status'],
            'cache_hit_nodes':sorted(hits),'all_ten_cache_hits':hits==nodes,'fresh_compilation':fresh,
            'source_counts':{k:len(v.get('sources',[])) for k,v in entered.items()},
            'new_source_compiled':any(p.endswith('/qualification/independence/FreshCompilationProbe.java') for p in entered.get(':compileJava',{}).get('sources',[])),
            'seed_copy':seed_details,'unchanged_gate_flags':command_flags,'timed_out':frozen.get('timed_out'),
            'source_integrity_passed':source_check,'native_source_integrity_evidence':source_status,
            'native_source_integrity_reference':'verification/jvm_runner.py:683-700',
            'candidate_unchanged':row['candidate_unchanged'],'origin_unchanged':row['origin_unchanged'],
            'frozen_tests_unchanged':row['frozen_tests_unchanged'],'historical_fixture_result_reproduced':tests_expected if not negative else None,
            'diagnostic_only':True,'candidate_sha256':row['candidate_sha256']}
        if negative:
            result['fail_closed_before_launch']=not inv and row['report']['passed'] is False and 'NFRT source inventory changed' in json.dumps(row['report']) and any(e['phase']=='nfrt_seed_validation_started' for e in row.get('preflight_events',[]))
            result['qualification_passed']=result['fail_closed_before_launch']
        else:
            result['qualification_passed']=all([hits==nodes,fresh,command_flags,tests_expected,source_check,frozen.get('timed_out') is False,
                len(inv)==1,seed_details.get('private_copy') is True,seed_details.get('files')==22,seed_details.get('bytes')==163178447,
                inv[0]['invocation']['timeout_seconds']==240,inv[0]['phase_counts']['junit_reports_collected']==1,
                result['new_source_compiled'] if row['label']=='outside-and-added-main' else True])
        controls.append(result)
    save(OUT/'real-controls/summary.json',controls)
    tests=junit_totals(OUT/'full-regression-final/pytest.xml')
    frozen={t['id']:sha(TASK_SOURCE/'hidden-tests'/t['test_filename'])==t['test_sha256'] for t in FREEZE['tasks']}
    baseline_hash=external_root.tree_sha256(BASE)
    seal=read(OUT/'diagnosis-seal.json')
    assertions={
        'original_source_unchanged':original==original_now,'historical_evidence_unchanged':not changes,
        'baseline_unchanged':baseline_hash==FREEZE['baseline']['sha256'],'frozen_tests_unchanged':all(frozen.values()),
        'approved_environment_unchanged':approved==FREEZE['verifier'],'prior_attestation_unchanged':sha(FREEZE['nfrt']['manifest'])==FREEZE['nfrt']['sha256'],
        'seed_bytes_inventory_provenance_unchanged':all(doc[k]==old[k] for k in ('entries','identity','source_inventory','forbidden_packages')),
        'bounded_production_changes_only':source_bound,'no_benchmark_policy_logic':no_benchmark_logic,
        'pre_edit_diagnosis_seal_valid':sha(HERE/'diagnosis.md')==seal['diagnosis_sha256'] and sha(HERE/'reconstruction-dependency-model.json')==seal['dependency_model_sha256'],
        'all_four_scopes_compatible':all(r['compatible'] and r['candidate_unchanged'] for r in read(OUT/'scope-preflight/matrix.json')['tasks']),
        'complete_regression_passed':tests['failures']==tests['errors']==0,
        'real_controls_qualified':len(controls)==4 and all(r['qualification_passed'] for r in controls),
        'qualified_harness_exactly_once':all(r['recorder_invocations']==1 and r['measurement_status']=='MEASURED' for r in controls),
        'isolated_candidate_integrity':all(r['candidate_unchanged'] and r['origin_unchanged'] and r['frozen_tests_unchanged'] for r in controls)}
    report={'at':stamp(),'classification':'FACTORIAL_READY' if all(assertions.values()) else 'FACTORIAL_NOT_READY',
        'criteria':assertions,'original_source_files':len(original),'prior_files_checked':len(prior),'prior_changes':changes,
        'production_files_changed':changed,'final_source_tree_hash':tree_hash,'final_source_tree_hash_method':'SHA256 of canonical sorted JSON path -> {sha256,size}',
        'baseline_sha256':baseline_hash,'frozen_tests':frozen,'attestation_sha256':sha(OUT/'approved-nfrt-seed-v2.json'),
        'regression':tests,'controls':controls,'model_calls':0,'factorial_trials':0,'promotions':0}
    save(OUT/'final-audit.json',report);print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':main()
