"""Seal the implementation and verify immutable prior evidence; no runtime calls."""
import ast,difflib,hashlib,json,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
BASE=ROOT/'HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/repaired-workshop'
SOURCE=HERE/'repaired-workshop'
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(name,data):
    (HERE/'evidence'/name).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

# Tests use only the new copy's app database. Do not ship test-induced runtime
# changes as production changes; restore copied runtime files to the original bytes.
before=json.loads((HERE/'evidence/source-before.json').read_text())
restored=[]
for rel in before:
    if rel.split('/')[0] in ('data','.pytest_cache') and sha(SOURCE/rel)!=before[rel]:
        shutil.copyfile(BASE/rel,SOURCE/rel);restored.append(rel)

prior=json.loads((ROOT/'HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/prior-evidence-seal.json').read_text())
replacement=json.loads((ROOT/'HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/evidence/delivery-seal.json').read_text())
for path,digest in replacement['files_sha256'].items():
    prior['HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1/'+path]=digest
prior['HIVE-TRANSITION-005-RUNTIME-REPLACEMENT-1-REPORT.md']=replacement['report_sha256']
changed_prior=[]
for rel,digest in prior.items():
    if not (ROOT/rel).is_file() or sha(ROOT/rel)!=digest:changed_prior.append(rel)

history=json.loads((ROOT/'HIVE-REVIEWER-ANALYSIS-001/evidence/inventory.json').read_text())
historical={r['path']:r['sha256'] for g in history['groups'] for r in g['records']}
historical.update({r['path']:r['sha256'] for r in history['other_result_files']})
changed_historical=[p for p,digest in historical.items() if sha(p)!=digest]
source_before_changed=[rel for rel,digest in before.items() if sha(BASE/rel)!=digest]

after={p.relative_to(SOURCE).as_posix():sha(p) for p in SOURCE.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
runtime_dirs={'data','.pytest_cache','snapshots','self_snapshots','hive_runs','workspace','media','reports','logs'}
changed_all=[p for p in sorted(set(before)|set(after)) if before.get(p)!=after.get(p)]
changed=[p for p in changed_all if p.split('/')[0] not in runtime_dirs]
patch=[]
for rel in changed:
    old=(BASE/rel).read_text(encoding='utf-8').splitlines(keepends=True) if (BASE/rel).exists() else []
    new=(SOURCE/rel).read_text(encoding='utf-8').splitlines(keepends=True) if (SOURCE/rel).exists() else []
    patch.extend(difflib.unified_diff(old,new,fromfile='a/'+rel,tofile='b/'+rel))
(HERE/'production.patch').write_text(''.join(patch),encoding='utf-8')

unchanged_files=['workshop/providers.py','workshop/hive_protocol.py','workshop/hive_edits.py','workshop/hive_context.py',
                 'workshop/external_root.py','workshop/hive_jvm.py','workshop/hive_verifier.py','workshop/verifier_trace.py',
                 'verification/jvm_runner.py','verification/nfrt_seed.py']
assert all(sha(BASE/rel)==sha(SOURCE/rel) for rel in unchanged_files)
def functions(path):
    tree=ast.parse(path.read_text(encoding='utf-8'))
    return {n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
a,b=functions(BASE/'workshop/hive.py'),functions(SOURCE/'workshop/hive.py')
protected=['_normalize_plan','_validate_host_write_scope','_planner_response_schema','_planner_prompt','_plan_correction_prompt',
           '_worker_prompt','_targeted_repair_prompt','_targeted_diagnostic','validate_edit','_prepare_agent_edits',
           '_external_verification_guard','targeted_verify','verify_tree','_restore_pending_edits']
assert all(a[name]==b[name] for name in protected)
save('final-integrity.json',{
 'sealed_prior_files_checked':len(prior),'sealed_prior_files_changed':changed_prior,
 'historical_run_result_files_checked':len(historical),'historical_files_changed':changed_historical,
 'original_source_files_checked':len(before),'original_source_files_changed':source_before_changed,
 'protected_files_byte_identical':unchanged_files,'protected_functions_ast_identical':protected,
 'production_and_test_files_changed':changed,'restored_test_runtime_files':restored,
 'test_generated_runtime_files_excluded_from_patch':[p for p in changed_all if p.split('/')[0] in runtime_dirs],
 'model_calls':0,'historical_apply_calls':0,'history_rescored':False,
 'counterfactual_only':True,
})
save('final-source-manifest.json',after)
assert not changed_prior and not changed_historical and not source_before_changed
print(json.dumps({'prior_unchanged':len(prior),'history_unchanged':len(historical),'original_source_unchanged':len(before),'changed':changed},indent=2))
