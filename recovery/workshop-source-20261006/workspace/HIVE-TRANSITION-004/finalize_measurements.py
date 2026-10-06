"""Finalize the fixed five-measurement campaign and live-entry decision."""
import json,re
from pathlib import Path
from setup_study import HERE,save,sha
rows=json.loads((HERE/'evidence/timing-comparison.json').read_text())
assert len(rows)==5 and all(r['complete'] for r in rows)
order=['measured-baseline','measured-preserved','measured-known-good','post-regression-baseline','post-regression-preserved']
rows=sorted(rows,key=lambda r:order.index(r['case']))
def value(v):return 'not reached' if v is None else f'{v:.3f}'
table=['| Replay | Host preflight | Launch to container | Project copy | Wrapper copy | Native inputs | Before Gradle (inside budget) | Gradle exposure to timeout | Outer time | Post-timeout work |',
 '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
columns=['host_preflight_s','launch_to_container_event_s','project_copy_s','wrapper_copy_s','native_inputs_copy_s','outer_budget_before_gradle_s','gradle_exposure_before_outer_timeout_s','docker_total_s','post_process_to_return_s']
for row in rows:table.append('| '+row['case']+' | '+' | '.join(value(row[k]) for k in columns)+' |')
out='''# Timing comparison — verifier-only, no model generation

All durations below are seconds. Five fresh isolated candidates/containers were measured sequentially: three initial controls and two post-regression repeats. There was no behavioral runtime/performance repair between batches; the tested observability code is the same. Neither cache contents nor candidate code were tuned. The source manifest and exact invocation are recorded for every run.

'''+ '\n'.join(table)+'''

Host preflight occurs before the 240-second Docker deadline; post-timeout removal/cache validation/cleanup occurs after it. “Before Gradle” overlaps the listed setup subphases and must not be added to them. Cross-boundary launch latency uses host receipt time; within-container copy durations use the container's own monotonic clock. Gradle exposure is a censored interval ending at the outer timeout, not Gradle completion time. No inner Gradle duration or frozen test result is invented.

Every run's last task marker is `createMinecraftArtifacts`; the baseline and preserved-candidate repeats expose the native artifact reconstruction substeps in child-stdout.log. None records `compileJava`, `compileTestJava` or a `test` task marker. The accepted control was historically verified under the same frozen gate, but this measurement is a new timeout and does not change that history.

The major measured preparatory cost is the manifest-verified private copy of 3,895 native input files / 914,224,273 bytes. The baseline /proc sample observes filesystem waiting on an asset during this phase. Later active JVM/tool trees and advancing output locate continued work, not a demonstrated deadlock. Variation in setup/host state prevents treating these five observations as a general latency distribution or causal estimate of a particular environmental fault.

Full raw phase/output/process evidence is beneath `evidence/verifier-replays/<replay>/diagnostics/`; each result includes source/baseline integrity, candidate hash, exact frozen manifest and a no-model/no-promotion disposition. Preserved edits are labeled POST_HOC_CANDIDATE_VERIFICATION. No acceptance pass was obtained.
'''
(HERE/'timing-comparison.md').write_bytes(out.encode())
assert all(not r['result']['report']['passed'] for r in rows)
assert all(r['gradle_wall_s'] is None and not any(re.match(r'> Task :(?:compileJava|compileTestJava|test)(?:\s|$)',m) for m in r['task_markers']) for r in rows)
assert all(all(r['result'][k] for k in ('candidate_unchanged','baseline_unchanged','historical_source_unchanged')) for r in rows)
decision={'study':'HIVE-TRANSITION-004','model_trials':0,'model_calls':0,'run_live_trial':False,
 'conditions':{'observability_functioning':True,'complete_regression_passed':json.loads((HERE/'evidence/regression.json').read_text())['exit_code']==0,
 'specific_timeout_root_cause_sufficiently_established':False,'normal_candidate_reaches_meaningful_result_within_240_seconds':False},
 'reason':'All five controls expire in shared pre-test prerequisites. Exact historical phase and a specific remediable runtime cause remain unestablished. Live-entry conditions are unmet.',
 'targeted_timeout_unchanged_seconds':240,'candidate_implementation_changed':False,'underlying_runtime_repair':'none'}
save(HERE/'evidence/live-decision.json',decision)
save(HERE/'evidence/campaign-summary.json',{'verifier_only_measurements':5,'initial_controls':3,'post_regression_repeats':2,
 'all_timed_out':True,'all_before_observed_candidate_compilation':True,'all_integrity_checks_passed':True,
 'frozen_acceptance_results':0,'full_gates':0,'autonomous_trials':0,'historical_classifications_unchanged':True})
print(json.dumps(decision,indent=2))
