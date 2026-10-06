"""Assemble probe results and minimal patch; no model calls."""
import difflib, hashlib, json
from pathlib import Path
from diagnostic_capture import save
HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent/'HIVE-TRANSITION-001'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
rows=[]
for label in ('short-default','long-default','long-no-truncate','long-sized'):
    folder=HERE/'evidence/sentinels'/label
    result=json.loads((folder/'result.json').read_text())
    wire=folder/'wire/01/wire-request.json'
    body=json.loads(wire.read_bytes())
    terminal=[]
    if (folder/'wire/01/response.ndjson').exists():
        terminal=[json.loads(line) for line in (folder/'wire/01/response.ndjson').read_text().splitlines()]
    rows.append({'label':label,'synthetic_not_J001':True,'wire_file':str(wire.relative_to(HERE)),
       'wire_sha256':sha(wire),'options':body.get('options'),'truncate':body.get('truncate','omitted'),
       'result':result,'terminal_metadata':terminal[-1] if terminal else None,
       'runtime':json.loads((folder/'runtime-ps.json').read_text()),
       'interpretation':'positional retrieval evidence only; not semantic reasoning or reliability measurement'})
save(HERE/'sentinel-results.json',{'study':'HIVE-TRANSITION-002','probe_count':4,'results':rows})
production=['app.py','workshop/hive_protocol.py','workshop/providers.py']
tests=['tests/test_hive_prompt_contract.py','tests/test_planning_input_fidelity.py']
patch=[]; manifest=[]
for rel in production+tests:
    old=PRIOR/'repaired-workshop'/rel; new=HERE/'repaired-workshop'/rel
    patch.extend(difflib.unified_diff(old.read_text().splitlines(keepends=True) if old.exists() else [],
        new.read_text().splitlines(keepends=True),fromfile='a/'+rel if old.exists() else '/dev/null',tofile='b/'+rel))
    manifest.append({'path':rel,'kind':'production' if rel in production else 'regression',
                     'before_sha256':sha(old) if old.exists() else None,'after_sha256':sha(new)})
(HERE/'repair.patch').write_bytes(''.join(patch).encode())
save(HERE/'repair-manifest.json',manifest)
sources={p.relative_to(HERE/'evidence/upstream').as_posix():sha(p)
         for p in (HERE/'evidence/upstream').rglob('*') if p.is_file()}
save(HERE/'evidence/upstream-sha256.json',sources)
print('Sentinel results, repair patch and manifests written.')
