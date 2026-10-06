import json,sys
sys.dont_write_bytecode=True
from bootstrap import HERE,save,sha
rows=[]
for label,failures in [('readiness-baseline',1),('readiness-preserved',2)]:
 root=HERE/'evidence/runs'/label
 result=json.loads((root/'result.json').read_text())
 events=[json.loads(line) for line in (root/'diagnostics/verification-events.jsonl').read_text().splitlines()]
 launch=next(x for x in events if x['phase']=='verifier_launch_requested')
 exits=[x for x in events if x['phase'] in ('verifier_process_exit','timeout_fired') and 'source_event' not in x]
 terminal=exits[-1]
 elapsed=terminal['monotonic']-launch['monotonic']
 check=next((x for x in result['report']['checks'] if x['name']=='frozen_junit_acceptance'),None)
 tests=check['detail'].get('tests',[]) if check else []
 expected_names=['truncationNeverSplitsAPair()'] + (['fullPairAtExactBoundRemainsIntact()'] if failures==2 else [])
 observed_names=[d['test_name'] for t in tests for d in t.get('failure_diagnostics',[])]
 ready=(check is not None and check['passed'] is False and elapsed<240 and len(tests)==1
        and all(tests[0].get(k)==v for k,v in {'tests':3,'failures':failures,'errors':0,'skipped':0}.items())
        and sorted(observed_names)==sorted(expected_names)
        and result['candidate_unchanged'] and not check['detail']['timed_out']
        and any(x['phase']=='nfrt_seed_copy_complete' for x in events)
        and any(x['phase']=='fresh_full_compilation_policy_installed' for x in events))
 rows.append({'label':label,'ready':ready,'bounded_seconds':round(elapsed,3),
              'host_seconds':result['total_host_elapsed_seconds'],'tests':tests,
              'report_sha256':sha(root/'result.json'),'seed_validated':any(x['phase']=='nfrt_seed_copy_complete' for x in events)})
save(HERE/'evidence/readiness.json',{'ready':all(r['ready'] for r in rows),'controls':rows,
     'policy':'No model call if either control fails readiness. No retries or timeout changes.'})
print(json.dumps(rows,indent=2))
if not all(r['ready'] for r in rows):raise SystemExit(2)
