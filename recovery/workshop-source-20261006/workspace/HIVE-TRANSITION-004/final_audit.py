"""Read-only evidence/repair audit; no model or verification invocation."""
import json,re,sys
from pathlib import Path
sys.dont_write_bytecode=True
from setup_study import HERE,PRIOR,save,sha
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
checks={}
def check(name,value):checks[name]=bool(value);assert value,name
report=HERE.parent/'HIVE-TRANSITION-004-REPORT.md'
seal=read(HERE/'evidence/reconstruction-seal.json')
check('pre_instrumentation_reconstruction_unchanged',sha(HERE/'reconstruction.md')==seal['reconstruction_sha256'] and sha(HERE/'verifier-path.md')==seal['verifier_path_sha256'])
seal=read(HERE/'evidence/pre-replay-diagnosis-seal.json')
check('pre_replay_diagnosis_unchanged',sha(HERE/'diagnosis.md')==seal['diagnosis_sha256'])
manifest=read(HERE/'repair-manifest.json')
check('delivered_source_matches_manifest',all(sha(HERE/'repaired-workshop'/r['path'])==r['after_sha256'] for r in manifest))
tested=read(HERE/'evidence/tested-source-manifest.json')
check('delivered_source_was_regression_tested',all(tested[r['path']]==r['after_sha256'] for r in manifest))
check('all_prior_inventoried_evidence_unchanged',all(r['unchanged'] for r in read(HERE/'evidence/prior-integrity-after.json').values()))
check('transition_003_report_unchanged',sha(HERE.parent/'HIVE-TRANSITION-003-REPORT.md')==read(PRIOR/'evidence/final-audit.json')['report_sha256'])
history=read(HERE/'evidence/accepted-control-history/manifest.json')
check('accepted_control_history_unchanged',all(sha(Path(r['source']))==r['sha256']==sha(HERE/r['copy']) for r in history))
eval_history=read(PRIOR/'evidence/eval009-source-manifest.json')
check('historical_eval009_unchanged',all(sha(Path(r['source']))==r['sha256'] for r in eval_history))
check('complete_suite_passed',read(HERE/'evidence/regression.json')['exit_code']==0 and '453 passed, 6 skipped' in (HERE/'evidence/regression.log').read_text())
rows=read(HERE/'evidence/timing-comparison.json')
check('exactly_five_verifier_only_replays',len(rows)==5 and all(r['complete'] for r in rows))
check('all_replays_fail_without_acceptance',all(not r['result']['report']['passed'] and r['result']['model_calls']==0 for r in rows))
check('all_candidates_and_baselines_unchanged',all(all(r['result'][k] for k in ('candidate_unchanged','baseline_unchanged','historical_source_unchanged')) for r in rows))
sys.path.insert(0,str(HERE/'repaired-workshop'))
from workshop.external_root import tree_sha256
baseline=read(PRIOR/'FREEZE.json')['baseline']
check('final_frozen_baseline_hash_unchanged',tree_sha256(Path(baseline['root']))==baseline['sha256'])
for row in rows:
 root=HERE/'evidence/verifier-replays'/row['case'];inv=read(root/'diagnostics/invocation.json');argv=inv['argv']
 events=[json.loads(s) for s in (root/'diagnostics/verification-events.jsonl').read_text().splitlines()]
 mounts=[argv[i+1] for i,x in enumerate(argv[:-1]) if x=='--mount']
 check(row['case']+'_240_seconds',inv['timeout_seconds']==240 and any(e['phase']=='timeout_fired' for e in events))
 check(row['case']+'_fixed_isolation',argv[argv.index('--network')+1]=='none' and '--read-only' in argv and
       argv[argv.index('--pids-limit')+1]=='448' and argv[argv.index('--memory')+1]=='4g' and argv[argv.index('--cpus')+1]=='2' and all(m.endswith(',readonly') for m in mounts))
 check(row['case']+'_partial_output_preserved',(root/'diagnostics/child-stdout.log').stat().st_size>0 and (root/'diagnostics/stderr.log').stat().st_size>0)
 check(row['case']+'_termination_cleanup_confirmed',any(e['phase']=='container_after_termination' and e['absence_confirmed'] for e in events) and any(e['phase']=='cleanup_complete' and e['removed'] for e in events))
 check(row['case']+'_event_order',all(a['monotonic']<=b['monotonic'] for a,b in zip(events,events[1:])))
 runtime=read(root/'preflight.json')['production_manifest']
 check(row['case']+'_same_production_instrumentation',all(runtime.get(r['path'].replace('/','\\'),runtime.get(r['path']))==r['after_sha256'] for r in manifest if not r['path'].startswith('tests/')))
decision=read(HERE/'evidence/live-decision.json')
check('live_trial_correctly_not_run',decision['model_trials']==0 and decision['model_calls']==0 and not decision['run_live_trial'])
check('all_18_sections_complete',len(re.findall(r'^## \d+\.',report.read_text(),re.M))==18 and 'Pending final replay' not in report.read_text())
docs=[report,*[HERE/p for p in ('reconstruction.md','reconstruction-sources.md','verifier-path.md','diagnosis.md','timing-comparison.md','observability.md')]]
missing=[]
for doc in docs:
 for target in re.findall(r'\]\(([^)]+)\)',doc.read_text()):
  if '://' in target or target.startswith('#'):continue
  if not (doc.parent/target.split('#')[0]).exists():missing.append((str(doc),target))
check('report_links_resolve',not missing)
save(HERE/'evidence/final-audit.json',{'passed':all(checks.values()),'checks':checks,
 'report_sha256':sha(report),'diagnosis_sha256':sha(HERE/'diagnosis.md'),'model_calls':0,
 'verification_calls_in_this_audit':0})
print(json.dumps({'passed':True,'checks':len(checks),'model_calls':0},indent=2))
