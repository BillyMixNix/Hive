import ast,difflib,hashlib,json
from pathlib import Path
from setup_study import save,sha
HERE=Path(__file__).resolve().parent
OLD=HERE.parent/'HIVE-TRANSITION-002/repaired-workshop'
NEW=HERE/'repaired-workshop'
paths=['workshop/hive.py','tests/test_host_write_scope.py','tests/test_planner_transition.py',
       'tests/test_planning_input_fidelity.py','tests/test_ownership_representation.py']
patch=[];manifest=[]
for rel in paths:
    a=OLD/rel;b=NEW/rel
    patch.extend(difflib.unified_diff(a.read_text().splitlines(keepends=True) if a.exists() else [],
      b.read_text().splitlines(keepends=True),fromfile='a/'+rel if a.exists() else '/dev/null',tofile='b/'+rel))
    manifest.append({'path':rel,'before_sha256':sha(a) if a.exists() else None,'after_sha256':sha(b)})
(HERE/'repair.patch').write_bytes(''.join(patch).encode());save(HERE/'repair-manifest.json',manifest)
def functions(path):
    return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(path.read_text()).body
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
before=functions(OLD/'workshop/hive.py');after=functions(NEW/'workshop/hive.py')
changed=[n for n in before if before[n]!=after.get(n)]
assert changed==['_planner_response_schema','_plan_correction_prompt'],changed
save(HERE/'evidence/production-function-diff.json',{'changed_functions':changed,
    'validators_dispatch_edit_execution_unchanged':True,'provider_context_unchanged':sha(OLD/'workshop/providers.py')==sha(NEW/'workshop/providers.py')})
print('Minimal repair packaged; validators, dispatch and executors are unchanged.')
