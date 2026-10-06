import ast,json,subprocess,sys
from pathlib import Path
sys.dont_write_bytecode=True
from bootstrap import HERE,save,sha
sys.path.insert(0,str(HERE/'repaired-workshop'))
import diagnostic_environment as environment
from workshop import external_root
config=json.loads((HERE/'evidence/configuration.json').read_text())
prior=json.loads((HERE/'evidence/prior-evidence-seal.json').read_text())
changed=[r['path'] for r in prior if not (HERE.parent/r['path']).is_file() or sha(HERE.parent/r['path'])!=r['sha256']]
assert not changed,changed
assert environment.approved_environment(environment.reference_freeze())==config['approved']
new=HERE/'repaired-workshop';old=HERE.parent/'HIVE-TRANSITION-004/repaired-workshop'
modified=[p.relative_to(new).as_posix() for p in new.rglob('*') if p.is_file() and '__pycache__' not in p.parts and '.pytest_cache' not in p.parts and (not (old/p.relative_to(new)).exists() or sha(p)!=sha(old/p.relative_to(new)))]
def definitions(path):
 tree=ast.parse(path.read_text(encoding='utf-8-sig'))
 return {n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
a=definitions(old/'verification/jvm_runner.py');b=definitions(new/'verification/jvm_runner.py')
protected=['_validate_frozen_tests','_reports','_result_check','_source_digest','_clear_build_outputs','_changed_preexisting_runtime_files','_network_attempt_failure']
assert all(a[x]==b[x] for x in protected)
def argv(path):
 tree=ast.parse(path.read_text(encoding='utf-8-sig'))
 return {t.id:ast.dump(n.value,include_attributes=False) for n in ast.walk(tree) if isinstance(n,ast.Assign) for t in n.targets if isinstance(t,ast.Name) and t.id in ['targeted_argv','full_argv']}
assert argv(old/'verification/jvm_runner.py')==argv(new/'verification/jvm_runner.py')
for f in ['workshop/hive.py','workshop/providers.py','workshop/hive_jvm.py']:
 assert sha(old/f)==sha(new/f),f
replays=[]
for root in sorted((HERE/'evidence/runs').glob('*')):
 result=json.loads((root/'result.json').read_text());info=json.loads((root/'input.json').read_text())
 assert result['candidate_unchanged'] and external_root.tree_sha256(root/'candidate')==info['candidate_sha256']
 inv=json.loads((root/'diagnostics/invocation.json').read_text())
 assert inv['timeout_seconds']==240
 assert all(inv['argv'][i+1].endswith(',readonly') for i,v in enumerate(inv['argv']) if v=='--mount')
 cp=subprocess.run([inv['argv'][0],'inspect',inv['container']],capture_output=True,text=True,timeout=10)
 assert cp.returncode!=0 and 'no such' in cp.stderr.lower(),cp.stdout
 replays.append({'run':root.name,'candidate_unchanged':True,'container_absent':True,'outer_budget':240,'readonly_mounts':True})
assert sha(Path(config['manifest']))==config['manifest_sha256']
seal=json.loads((HERE/'evidence/pre-additional-repair-seal.json').read_text())
assert sha(HERE/'compile-diagnosis.md')==seal['diagnosis_sha256']
reg=json.loads((HERE/'evidence/regression/complete-02/source-manifest.json').read_text())
assert all(sha(new/p)==h for p,h in reg.items() if not set(Path(p).parts)&environment.SOURCE_EXCLUDES)
save(HERE/'evidence/final-audit.json',{'prior_sealed_files_unchanged':len(prior),'baseline_cache_image_validated':True,
 'protected_verifier_functions_identical':protected,'targeted_and_full_argv_identical':True,
 'scope_context_ownership_code_identical':True,'attestation_unchanged':True,'tested_source_unchanged':True,
 'pre_repair_diagnosis_unchanged':True,'replays':replays,'files_changed':modified,'model_calls':0})
print('Audit passed:',len(prior),'prior files unchanged; gates, cache, baseline and candidates intact.')
