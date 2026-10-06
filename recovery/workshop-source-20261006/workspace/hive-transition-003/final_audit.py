"""Audit sealed inputs, delivered changes, trace and report; no generation or gate calls."""
import hashlib,json,re,sys
from pathlib import Path
sys.dont_write_bytecode=True
from setup_study import save
HERE=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
checks={}
def check(name,condition):
    checks[name]=bool(condition)
    assert condition,name

seal=read(HERE/'evidence/pre-edit-seal.json')
check('pre_edit_diagnosis_seal_intact',sha(HERE/'diagnosis.md')==seal['diagnosis_sha256'])
freeze=read(HERE/'FREEZE.json')
check('freeze_hash_intact',sha(HERE/'FREEZE.json')==(HERE/'LOCK.sha256').read_text().strip())
check('registered_harness_and_production_hashes_intact',all(sha(HERE/p)==h for p,h in freeze['files_sha256'].items()))
manifest=read(HERE/'repair-manifest.json')
check('delivered_patch_source_matches_tested_manifest',all(sha(HERE/'repaired-workshop'/r['path'])==r['after_sha256'] for r in manifest))
check('only_one_production_file_changed', [r['path'] for r in manifest if not r['path'].startswith('tests/')]==['workshop/hive.py'])
prior=HERE.parent/'HIVE-TRANSITION-002/repaired-workshop'
check('context_and_gates_unchanged',all(sha(HERE/'repaired-workshop'/p)==sha(prior/p) for p in
 ('workshop/providers.py','workshop/hive_protocol.py','app.py','workshop/hive_verifier.py','workshop/external_root.py')))
check('prior_evidence_inventory_verified_unchanged',all(r['unchanged'] for r in read(HERE/'evidence/prior-integrity-after.json').values()))
regression=read(HERE/'evidence/regression.json')
check('complete_regression_passed',regression['exit_code']==0 and '447 passed, 6 skipped' in (HERE/'evidence/regression.log').read_text())
replay=read(HERE/'evidence/historical-replay.json')
check('36_historical_decisions_unchanged',len(replay['before'])==len(replay['after'])==36 and all(
 all(a.get(k)==b.get(k) for k in ('id','accepted','dispatch_eligible','error','correction_text_sha256'))
 for a,b in zip(replay['before'],replay['after'])))
check('34_invalid_plans_still_rejected',sum(not r['accepted'] for r in replay['after'])==34)
summary=read(HERE/'evidence/live-summary.json')
results=read(HERE/'evidence/live-diagnostic/raw_results.json')
check('exactly_one_new_trial_recorded',len(results)==1 and read(HERE/'evidence/J001-LIVE-STARTED.json')['allowed_trials']==1)
check('first_request_differs_only_in_schema',summary['first_request_equal_to_transition_002_except_format'])
check('all_live_inputs_complete_at_provider_accounting_boundary',all(m['full_input_count_matches'] and m['context']==12288 and m['truncate'] is False for m in read(HERE/'evidence/live-input-measurements.json')))
check('normal_budget_and_containment',results[0]['planner_corrections']==0 and results[0]['targeted_corrections']==1 and
 summary['identical_correction_rejected'] and summary['final_stage_file_restored_to_baseline'] and not summary['applied'])
check('no_task_success_or_full_gate_claim',summary['classification']=='MODEL_TASK_FAILURE' and not summary['full_gate_executed'])
# Independent final tree hash check, using the unchanged production snapshot rules.
sys.path.insert(0,str(HERE/'repaired-workshop'))
from workshop.external_root import tree_sha256
check('frozen_baseline_hash_still_intact',tree_sha256(Path(freeze['baseline']['root']))==freeze['baseline']['sha256'])
report=HERE.parent/'HIVE-TRANSITION-003-REPORT.md'
required=['reconstruction.md','expressibility.md','ownership-semantics.md','eval009-contrast.md','diagnosis.md',
 'repair.md','historical-replay.md','live-diagnostic.md']
check('required_reports_exist',all((HERE/p).is_file() for p in required) and report.is_file())
check('all_17_report_sections_complete',len(re.findall(r'^## \d+\.',report.read_text(),re.M))==17 and 'Pending final trace' not in report.read_text() and 'Pending completion' not in report.read_text())
bad_links=[]
for doc in [report,*[HERE/p for p in required]]:
    for target in re.findall(r'\]\(([^)]+)\)',doc.read_text()):
        if '://' in target or target.startswith('#'):continue
        if not (doc.parent/target.split('#')[0]).exists():bad_links.append({'document':str(doc),'target':target})
check('report_evidence_links_resolve',not bad_links)
save(HERE/'evidence/final-audit.json',{'checks':checks,'passed':all(checks.values()),
 'report_sha256':sha(report),'diagnosis_sha256':sha(HERE/'diagnosis.md'),
 'live_run_id':summary['run_id'],'note':'No additional model generation or verifier invocation.'})
print(json.dumps(checks,indent=2))
