"""Post-trial immutable evidence audit. No model or verifier execution."""
import json,sys
from pathlib import Path
sys.dont_write_bytecode=True
from bootstrap import HERE,PRIOR,sha,save,manifest
import diagnostic_environment as env
def main():
 assert (HERE/'evidence/live-diagnostic/raw_results.json').exists(),'Run must finish first'
 prior=json.loads((HERE/'evidence/prior-evidence-seal.json').read_text())
 changed=[]
 for rel,h in prior.items():
  p=HERE.parent/rel
  if not p.is_file() or sha(p)!=h:changed.append(rel)
 save(HERE/'evidence/prior-evidence-audit.json',{'sealed_files':len(prior),'changed':changed})
 assert not changed,changed
 before=json.loads((HERE/'evidence/source-before.json').read_text())
 after=manifest(HERE/'repaired-workshop');save(HERE/'evidence/source-after.json',after)
 altered=[p for p in before.keys()|after.keys() if before.get(p)!=after.get(p)]
 production_altered=[p for p in altered if not set(Path(p).parts)&env.SOURCE_EXCLUDES]
 assert not production_altered,production_altered
 config=json.loads((PRIOR/'evidence/configuration.json').read_text())
 baseline=env.external_root.tree_sha256(Path(config['freeze']['baseline']['root']))
 assert baseline==config['freeze']['baseline']['sha256']
 attestation=json.loads(Path(config['manifest']).read_text())
 assert sha(Path(config['manifest']))==config['manifest_sha256']
 native=Path(config['approved']['approved_cache_root'])/'caches/neoformruntime/intermediate_results'
 seed_changed=[x['path'] for x in attestation['entries'] if not (native/x['path']).is_file() or sha(native/x['path'])!=x['sha256']]
 assert not seed_changed,seed_changed
 task=config['freeze']['tasks'][0]
 import diagnostic_runner as r
 assert sha(r.SOURCE_STUDY/'hidden-tests'/task['test_filename'])==task['test_sha256']
 result={'prior_files_checked':len(prior),'prior_files_changed':changed,'original_T005_source_unchanged':manifest(PRIOR/'repaired-workshop')==before,
  'isolated_source_files_checked':len(before),'isolated_production_files_changed':production_altered,'isolated_runtime_files_changed':altered,
  'baseline_sha256':baseline,'frozen_test_sha256':task['test_sha256'],'attestation_sha256':config['manifest_sha256'],
  'seed_files_verified':len(attestation['entries']),'seed_files_changed':seed_changed,'production_changes':[]}
 save(HERE/'evidence/postflight.json',result);print(json.dumps(result,indent=2))
if __name__=='__main__':main()
