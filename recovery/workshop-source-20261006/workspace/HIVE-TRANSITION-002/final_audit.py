"""Final internal evidence consistency checks, no generation or old-tree writes."""
import hashlib,json,re
from pathlib import Path
from diagnostic_capture import save
HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent/'HIVE-TRANSITION-001'
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
freeze=json.loads((HERE/'FREEZE.json').read_text())
assert sha(HERE/'FREEZE.json')==(HERE/'LOCK.sha256').read_text().strip()
assert all(sha(HERE/p)==h for p,h in freeze['files_sha256'].items())
assert sha(HERE/'repaired-workshop/workshop/hive.py')==sha(PRIOR/'repaired-workshop/workshop/hive.py')
assert all(json.loads((HERE/'evidence'/p).read_text())['unchanged'] for p in
           ('prior-study-integrity-after.json','factorial-integrity-after.json'))
result=json.loads((HERE/'evidence/live-diagnostic/raw_results.json').read_text())
assert len(result)==1 and result[0]['run_id']=='6b87294fdc72'
assert result[0]['model_calls']==2 and result[0]['planner_corrections']==1
assert result[0]['changed_files']==[] and result[0]['full_verification'] is None
assert result[0]['candidate_sha256']==freeze['baseline']['sha256']
measurements=json.loads((HERE/'evidence/live-input-measurements.json').read_text())
assert len(measurements)==3
assert [r['http_status'] for r in measurements]==[500,200,200]
assert measurements[0]['wire_sha256']==measurements[1]['wire_sha256']
assert all(r['full_token_count_matches'] and r['remaining_after_full_output_cap']>0 for r in measurements[1:])
assert all(r['options']['num_ctx']==12288 and r['truncate'] is False for r in measurements)
assert sha(HERE/'wire-request.json')==measurements[0]['wire_sha256']
assert json.loads((HERE/'evidence/regression.json').read_text())['exit_code']==0
required=['intended-input.md','wire-request.json','context-budget.md','fidelity.md',
          'sentinel-results.json','j001-turn-reconstruction.md']
assert all((HERE/p).is_file() for p in required)
report=HERE.parent/'HIVE-TRANSITION-002-REPORT.md'
text=report.read_text()
assert len(re.findall(r'^## \d+\.',text,re.M))==14
for target in re.findall(r'\]\(([^)]+)\)',text):
    if not target.startswith('http'):assert (report.parent/target).exists(),target
save(HERE/'evidence/final-audit.json',{'passed':True,'classification':'INPUT_FIDELITY_DEFECT_IDENTIFIED_AND_REPAIRED',
     'one_live_J001_trial':True,'completed_model_calls':2,'http_attempts':3,
     'hive_validator_byte_identical_to_transition_001':True,'freeze_source_hashes_match':True,
     'accepted_input_counts_match_rendered_tokens':True,'candidate_remains_baseline':True,
     'report_sha256':sha(report),'required_artifacts':{p:sha(HERE/p) for p in required}})
print('Final audit passed: immutable source/gates, one trial, complete input counts, report links and artifacts.')
