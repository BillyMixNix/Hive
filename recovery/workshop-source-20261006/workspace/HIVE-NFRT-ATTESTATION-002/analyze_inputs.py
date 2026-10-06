"""Classify measured task inputs without treating dry runs as acceptance."""
from common import *

def normalize(value,project):
    if isinstance(value,str):return value.replace(project,'$PROJECT')
    if isinstance(value,list):return [normalize(x,project) for x in value]
    if isinstance(value,dict):return {k:normalize(v,project) for k,v in value.items()}
    return value
def determinants(snapshot):
    normalized=normalize(snapshot,snapshot['project'])
    return {k:normalized[k] for k in ['taskClass','graph','inputProperties','inputFiles','outputFiles','enableNativeCache','optionalInputs']}
def identity(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def main():
    fixtures=read(OUT/'sensitivity-fixtures.json');results=read(OUT/'input-probes/results.json')
    assert len(results)==len(fixtures)
    base=next(r for r in results if r['case']=='baseline');assert base['snapshot'] and base['result']['returncode']==0
    fixed=determinants(base['snapshot']);keymap={n['node']:n['key_sha1'] for n in read(HERE/'reconstruction-dependency-model.json')['nodes']}
    rows=[]
    for f in fixtures:
        r=next(r for r in results if r['case']==f['case']);s=r['snapshot'];d=determinants(s) if s else None
        same=d==fixed if s else None
        safe=f['kind'] in ('unchanged','comment','java_add') and (f['case'].split('-')[0] in ('baseline','A','B','C','D','E','F','G'))
        rows.append({**f,'gradle_returncode':r['result']['returncode'],'timed_out':r['result']['timed_out'],
            'measured_input_identity':identity(d) if d else None,'same_reconstruction_inputs_as_baseline':same,
            'changed_input_sections':[k for k in fixed if d and fixed[k]!=d[k]],
            'ten_node_keys':keymap if same else None,
            'key_evidence':'Expected identical by unchanged measured determinants and pinned implementation; freshly observed hits are recorded separately in real controls.' if same else 'Not executed; changed/unknown inputs cannot be authorized from old keys.',
            'expected_reuse_safe':True if same else False if s else None,
            'proposed_reuse_allowed':bool(same and safe),
            'variation_class':'SAFE_INDEPENDENT_VARIATION' if same and safe else 'RECONSTRUCTION_RELEVANT' if s and not same else 'CONSERVATIVELY_UNKNOWN',
            'scope_note':'Only the reviewed main Java class is proposed for generalized authorization; unchanged data in other probe categories is not broad authorization.'})
    save(OUT/'sensitivity-analysis.json',{'baseline_input_identity':identity(fixed),'results':rows})
    save(OUT/'normalized-reconstruction-inputs.json',normalize(base['snapshot'],base['snapshot']['project']))
    header='| Probe | Current policy | NFRT input identity equal? | Proposed reuse | Input sections changed |\n|---|---|---|---|---|\n'
    table='\n'.join(f"| {r['case']} | {r['current_policy_compatible']} | {r['same_reconstruction_inputs_as_baseline']} | {r['proposed_reuse_allowed']} | {', '.join(r['changed_input_sections'])} |" for r in rows)
    (HERE/'source-sensitivity.md').write_text('# Source-sensitivity probes\n\n'+header+table+'\n\nAll runtime captures used offline Gradle `--dry-run createMinecraftArtifacts`. No compilation or tests ran. Each source was copied from the same frozen baseline. Three independent project copies shared one private diagnostic Gradle home per container; no candidate classes or task execution were cached. Null identities represent offline configuration/resolution failure, not proof of equal inputs.\n\nThe node-key map on equal-input rows is a supported inference from fixed inputs/action implementations, not a claim that NFRT ran during the dry run. Real verifier cache-hit evidence is separate.\n',encoding='utf-8')
    print(table,flush=True)
if __name__=='__main__':main()
