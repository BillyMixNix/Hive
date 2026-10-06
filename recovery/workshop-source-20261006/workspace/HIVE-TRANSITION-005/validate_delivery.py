import copy,json,re,sys
from pathlib import Path
sys.dont_write_bytecode=True
from bootstrap import HERE,sha,save
sys.path.insert(0,str(HERE/'repaired-workshop'))
sys.path.insert(0,str(HERE.parent/'hive-transition-003/tooling/python'))
from workshop import hive
from jsonschema import Draft202012Validator
probes=json.loads((HERE/'evidence/semantic-probes-before.json').read_text())
path=probes[0]['plan']['worker_files']['backend'][0]
tokens=[(hive._ACTIVE_AGENT_SCOPES,hive._ACTIVE_AGENT_SCOPES.set(hive.EXTERNAL_AGENT_SCOPES)),
        (hive._HOST_WRITE_SCOPE,hive._HOST_WRITE_SCOPE.set((path,))),
        (hive._EXTERNAL_ROOT_MODE,hive._EXTERNAL_ROOT_MODE.set(True))]
rows=[]
try:
 schema=hive._planner_response_schema()
 for probe in probes:
  p=copy.deepcopy(probe['plan']);p.pop('_intent_envelope',None)
  errors=[e.message for e in Draft202012Validator(schema).iter_errors(p)]
  assert not errors,(probe['name'],errors)
  normalized,_=hive._normalize_plan(p);hive._validate_host_write_scope(normalized)
  rows.append({'name':probe['name'],'generation_schema_valid':True,'normalization_and_scope_valid':True})
finally:
 for var,token in reversed(tokens):var.reset(token)
save(HERE/'evidence/semantic-generation-schema-check.json',{'note':'Separate strict generation-schema check removes the copied host-only _intent_envelope field. Planner schema/normalization are unchanged production functions, verified by AST audit. No generation performed.','probes':rows})
report=HERE.parent/'HIVE-TRANSITION-005-REPORT.md';text=report.read_text(encoding='utf-8')
assert len(re.findall(r'^## \d+\.',text,re.M))==23
missing=[]
for target in re.findall(r'\]\(([^)]+)\)',text):
 if '://' in target:continue
 if not (report.parent/target.split('#')[0]).exists():missing.append(target)
assert not missing,missing
seal_files=['requirement-ledger.md','semantic-trace.json','semantic-trace.md','semantic-loss-diagnosis.md',
 'correction-reconstruction.md','architecture.md','production.patch','evidence/pre-edit-seal.json',
 'evidence/readiness.json','evidence/live-summary.json','evidence/final-audit.json',
 'evidence/regression/complete-03/result.json','evidence/regression/complete-03/pytest.log',
 'evidence/semantic-generation-schema-check.json']
save(HERE/'evidence/delivery-seal.json',{'report_sha256':sha(report),'files_sha256':{p:sha(HERE/p) for p in seal_files},
    'required_report_sections':23,'report_links_verified':True,'new_live_trials':1,'additional_model_calls':0})
print('Delivery validated: 23 sections, all links exist, all ten probes satisfy unchanged generation schema.')
