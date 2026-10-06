"""Measure preserved review input, never transmit it."""
import hashlib,json,sys
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
SOURCE=ROOT/'HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop'
sys.path.insert(0,str(SOURCE))
from workshop import hive
run_path=ROOT/'HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/live-diagnostic/runs/4574db69cea0/run.json'
wire_path=ROOT/'HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/runtime/calls/03-reviewer/attempt-01/wire-request.json'
run=json.loads(run_path.read_text())
wire=json.loads(wire_path.read_text())
expected=hive._reviewer_prompt(run['request'],run['diff'],run['verification'])
content=next(m['content'] for m in wire['messages'] if m['role']=='user')
v=json.dumps(run['verification'],indent=2)
prefix=v[:20000]
try:json.loads(prefix);parseable=True
except ValueError:parseable=False
repair=hive._json_repair_prompt('reviewer','not JSON',ValueError('SYNTHETIC'))
synthetic=hive._reviewer_prompt('REQUEST_MARKER','x'*70000+'DIFF_END_SENTINEL',{'passed':True,'detail':'y'*22000,'last':'VERIFY_END_SENTINEL'})
result={
 'sources':{'run':str(run_path),'wire':str(wire_path)},
 'wire_request_sha256':hashlib.sha256(wire_path.read_bytes()).hexdigest(),
 'reviewer_prompt_matches_current_constructor':content==expected,
 'original_task_chars':len(run['request']),'diff_chars':len(run['diff']),
 'diff_sent_chars':len(run['diff'][:70000]),'verification_full_chars':len(v),
 'verification_sent_chars':len(prefix),'verification_omitted_chars':max(0,len(v)-20000),
 'verification_prefix_is_valid_json':parseable,
 'verification_fields':[{'name':c.get('name'),'name_position_in_serialized_json':v.find(json.dumps(c.get('name'))),
                        'name_present_in_sent_prefix':json.dumps(c.get('name')) in prefix} for c in run['verification']['checks']],
 'last_sent_verification_chars':prefix[-300:],
 'wire_model':wire['model'],'wire_options':wire['options'],'truncate':wire.get('truncate'),
 'model_visible':'UNKNOWN: provider allocation failed; known sent request is not evidence of model consumption.',
 'synthetic_long_input':{'diff_tail_survives':'DIFF_END_SENTINEL' in synthetic,'verification_tail_survives':'VERIFY_END_SENTINEL' in synthetic,
                         'truncation_marker_present':'truncat' in synthetic.lower()},
 'json_repair_prompt':str(repair),
 'json_repair_reincludes_original_request':run['request'] in repair,
 'json_repair_reincludes_diff':run['diff'] in repair,
}
(HERE/'evidence/reviewer-input.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ['sources','json_repair_prompt','last_sent_verification_chars']},indent=2))
