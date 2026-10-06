"""Integrity and unchanged-gate audit; never modifies old evidence."""
import ast,difflib,json,shutil,subprocess,sys
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
new=HERE/'repaired-workshop';old=HERE.parent/'HIVE-TRANSITION-004C/repaired-workshop'
def definitions(path):
 tree=ast.parse(path.read_text(encoding='utf-8-sig'))
 return {n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
a=definitions(old/'verification/jvm_runner.py');b=definitions(new/'verification/jvm_runner.py')
protected=[name for name in a if name!='_reports']
assert all(a[x]==b[x] for x in protected)
c=definitions(old/'workshop/hive.py');d=definitions(new/'workshop/hive.py')
allowed={'_worker_prompt','_json_repair_prompt','_parse_agent_json','_structural_repair_prompt','_targeted_repair_prompt','_run_build_impl'}
assert all(c[name]==d[name] for name in c if name not in allowed)
for name in ['workshop/providers.py','workshop/hive_protocol.py','workshop/hive_verifier.py',
             'workshop/external_root.py','workshop/hive_jvm.py','verification/nfrt_seed.py','workshop/verifier_trace.py']:
 assert sha(old/name)==sha(new/name),name
assert sha(Path(config['manifest']))==config['manifest_sha256']
seal=json.loads((HERE/'evidence/pre-edit-seal.json').read_text())
assert sha(HERE/'semantic-loss-diagnosis.md')==seal['diagnosis_sha256']
reg=json.loads((HERE/'evidence/regression/complete-03/source-manifest.json').read_text())
assert all(sha(new/p)==h for p,h in reg.items() if not set(Path(p).parts)&environment.SOURCE_EXCLUDES)
modified=[p.relative_to(new).as_posix() for p in new.rglob('*') if p.is_file()
    and not set(p.relative_to(new).parts)&environment.SOURCE_EXCLUDES and p.suffix!='.pyc'
    and (not (old/p.relative_to(new)).exists() or sha(p)!=sha(old/p.relative_to(new)))]
expected=['tests/test_hive_scopes.py','tests/test_semantic_fidelity.py','verification/jvm_runner.py','workshop/hive.py']
assert sorted(modified)==expected,modified
patch=''
for name in expected:
 previous=(old/name).read_text(encoding='utf-8').splitlines(keepends=True) if (old/name).exists() else []
 current=(new/name).read_text(encoding='utf-8').splitlines(keepends=True)
 patch+=''.join(difflib.unified_diff(previous,current,fromfile='a/'+name,tofile='b/'+name))
(HERE/'production.patch').write_text(patch,encoding='utf-8')
checks=[]
for invpath in (HERE/'evidence').rglob('invocation.json'):
 if 'regression' in invpath.parts:continue
 inv=json.loads(invpath.read_text())
 if 'container' not in inv:continue
 assert inv['timeout_seconds'] in (240,660)
 assert all(inv['argv'][i+1].endswith(',readonly') for i,v in enumerate(inv['argv']) if v=='--mount')
 cp=subprocess.run([inv['argv'][0],'inspect',inv['container']],capture_output=True,text=True,timeout=10)
 assert cp.returncode!=0 and 'no such' in cp.stderr.lower()
 checks.append({'container':inv['container'],'absent':True,'timeout':inv['timeout_seconds'],'readonly_mounts':True})
for root in (HERE/'evidence/runs').glob('*'):
 result=json.loads((root/'result.json').read_text());info=json.loads((root/'input.json').read_text())
 assert result['candidate_unchanged'] and external_root.tree_sha256(root/'candidate')==info['candidate_sha256']
live=HERE/'evidence/live-diagnostic/raw_results.json'
results=json.loads(live.read_text()) if live.exists() else []
assert len(results)<=1 and all(not r.get('applied') for r in results)
save(HERE/'evidence/final-audit.json',{'prior_sealed_files_unchanged':len(prior),
 'baseline_cache_image_validated':True,'attestation_unchanged':True,'tested_source_unchanged':True,
 'verifier_functions_identical_except_runtime_diagnostic_collection':protected,
 'scope_ownership_edit_and_targeted_verification_functions_identical':True,
 'context_provider_verifier_isolation_code_identical':True,'containers':checks,
 'production_and_test_files_changed':expected,'live_trials':len(results),'model_calls':sum(r.get('model_calls',0) for r in results)})
print('Audit passed:',len(prior),'prior files unchanged;',len(results),'fresh live trials.')
