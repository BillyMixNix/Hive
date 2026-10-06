import hashlib,json,re
from pathlib import Path
HERE=Path(__file__).resolve().parent;E=HERE/'evidence';P=HERE.parent/'HIVE-TRANSITION-004'
def read(p):return json.loads(p.read_text())
checks={}
audit=read(E/'integrity-audit.json');timings=read(E/'timings.json')
checks['prior_evidence_baseline_and_cache_intact']=all(audit[k] for k in ['existing_evidence_files_unchanged','approved_cache_unchanged','baseline_unchanged'])
checks['no_model_calls_or_production_edits']=audit['model_calls']==0 and audit['production_edits']==0
checks['bounded_preregistered_run_count']=audit['new_targeted_runs']==2 and audit['task_input_probe_containers']==1
checks['identical_reconstruction_inputs']=read(E/'input-comparison.json')['identical']
checks['all_ten_native_keys_recomputed']=read(E/'cache-key-audit.json')['all_keys_recomputed']
checks['all_ten_nodes_hit_in_both_replays']=all(len(r['cached_nodes'])==10 for r in timings)
checks['compilation_still_required']=all('> Task :compileJava' in r['tasks'] for r in timings)
checks['timeout_never_passes']=all(r['result']['timed_out'] and not r['result']['gate_passed'] and r['result']['timeout_seconds']==240 for r in timings)
checks['all_diagnostic_containers_absent']=all(r['result']['cleanup']['container_absent'] for r in timings) and read(E/'runs/inputs/cleanup-followup.json')['absent']
original_events=[json.loads(s) for s in (P/'evidence/verifier-replays/post-regression-baseline/diagnostics/verification-events.jsonl').read_text().splitlines()]
original_gradle=next(r['source_event']['argv'] for r in original_events if r['phase']=='gradle_invoked')
for case in ['baseline','preserved']:
 events=[json.loads(s) for s in (E/'runs'/case/'diagnostics/verification-events.jsonl').read_text().splitlines()]
 invocation=read(E/'runs'/case/'diagnostics/invocation.json');cmd=invocation['argv']
 checks[case+'_gate_command_unchanged']=next(r['source_event']['argv'] for r in events if r['phase']=='gradle_invoked')==original_gradle
 checks[case+'_same_deadline_isolation']=invocation['timeout_seconds']==240 and cmd[cmd.index('--network')+1]=='none' and '--read-only' in cmd and all(cmd[i+1].endswith(',readonly') for i,s in enumerate(cmd) if s=='--mount')
 checks[case+'_seed_manifest_verified']=any(r['phase']=='diagnostic_intermediate_seed_complete' and r['source_event']['count']==22 for r in events)
 checks[case+'_no_prior_test_report_used']=not any(r['phase']=='junit_reports_collected' for r in events)
checks['all_gate_functions_identical']=audit['frozen_verifier_gate_functions_identical']
report=HERE.parent/'HIVE-TRANSITION-004B-REPORT.md'
links=re.findall(r'\]\(([^)]+)\)',report.read_text())
checks['report_links_resolve']=all((report.parent/link).exists() for link in links if not link.startswith('https:'))
checks['report_complete']='PENDING' not in report.read_text()
out={'passed':all(checks.values()),'checks':checks,
     'report_sha256':hashlib.sha256(report.read_bytes()).hexdigest(),
     'conclusion':'AVOIDABLE_PER_CANDIDATE_DEPENDENCY_RECONSTRUCTION_DEMONSTRATED',
     'scope':'Frozen M3.2/J001 source-only edit; not arbitrary build-input changes.',
     'furthest_observed_transition':'Artifact creation completed; compileJava observed; outer timeout; no frozen-test verdict.',
     'production_repair':'None; diagnostic-only attested native cache seed.'}
(E/'final-audit.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2));assert out['passed']
