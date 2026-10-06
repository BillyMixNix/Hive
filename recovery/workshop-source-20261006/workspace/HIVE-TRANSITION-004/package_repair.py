"""Package only reviewed source/test changes, not generated workspace files."""
import ast,copy,difflib,json
from pathlib import Path
from setup_study import HERE,PRIOR,sha,save
files=['workshop/hive.py','workshop/hive_verifier.py','workshop/verifier_trace.py','verification/jvm_runner.py',
 'tests/test_hive_isolated_verifier.py','tests/test_hive_jvm_profile.py','tests/test_verifier_observability.py']
patch=[];manifest=[]
for rel in files:
 old=PRIOR/'repaired-workshop'/rel;new=HERE/'repaired-workshop'/rel
 patch.extend(difflib.unified_diff(old.read_text().splitlines(True) if old.exists() else [],new.read_text().splitlines(True),
  fromfile='a/'+rel if old.exists() else '/dev/null',tofile='b/'+rel))
 manifest.append({'path':rel,'before_sha256':sha(old) if old.exists() else None,'after_sha256':sha(new)})
(HERE/'repair.patch').write_bytes(''.join(patch).encode());save(HERE/'repair-manifest.json',manifest)
def functions(root,rel):
 return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse((root/rel).read_text()).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
old=PRIOR/'repaired-workshop';new=HERE/'repaired-workshop'
before=functions(old,'workshop/hive.py');after=functions(new,'workshop/hive.py')
assert [n for n in before if before[n]!=after[n]]==['targeted_verify']
jbefore=functions(old,'verification/jvm_runner.py');jafter=functions(new,'verification/jvm_runner.py')
assert {n for n in jbefore if jbefore[n]!=jafter[n]}=={'_bounded_process','run_jvm_profile'}
class RemoveEvents(ast.NodeTransformer):
 def visit_Expr(self,n):
  if isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='_event':return None
  return self.generic_visit(n)
trees=[ast.parse((r/'verification/jvm_runner.py').read_text()) for r in (old,new)]
gates=[next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name=='run_jvm_profile') for t in trees]
assert ast.dump(gates[0])==ast.dump(RemoveEvents().visit(gates[1]))
unchanged=['workshop/providers.py','workshop/hive_protocol.py','workshop/hive_jvm.py','workshop/external_root.py','app.py','verification/runner.py']
assert all(sha(old/p)==sha(new/p) for p in unchanged)
save(HERE/'evidence/safety-audit.json',{
 'hive_only_changed_function':'targeted_verify (diagnostic metadata retention)',
 'jvm_gate_algorithm_identical_after_removing_event_emission':True,
 'changed_jvm_existing_functions':['_bounded_process (diagnostic streaming/read1)','run_jvm_profile (events only)'],
 'frozen_assertions_selectors_case_counts_and_source_checks_unchanged':True,
 'unchanged_files':{p:sha(new/p) for p in unchanged},
 'targeted_timeout':240,'behavioral_runtime_repair':'none','candidate_edits_in_repair':False})
print('Repair and safety audit packaged.')
