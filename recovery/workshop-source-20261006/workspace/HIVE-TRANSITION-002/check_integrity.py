"""Read-only verification of both previous experiments; never writes their trees."""
import hashlib,json
from pathlib import Path
from diagnostic_capture import save
HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent/'HIVE-TRANSITION-001'
ORIGINAL=Path(r'C:\Users\billy\Documents\Codex\2026-09-13\referenced-chatgpt-conversation-this-is-an\work\HIVE-FACTORIAL-002')
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
before=json.loads((HERE/'evidence/prior-study-before.json').read_text())
changed=[rel for rel,h in before.items() if not (PRIOR/rel).is_file() or digest(PRIOR/rel)!=h]
added=[p.relative_to(PRIOR).as_posix() for p in PRIOR.rglob('*') if p.is_file()
       and not any(x in p.parts for x in ('__pycache__','.pytest_cache')) and p.relative_to(PRIOR).as_posix() not in before]
save(HERE/'evidence/prior-study-integrity-after.json',{'files_checked':len(before),'changed_or_missing':changed,'added':added,'unchanged':not changed and not added})
manifest=json.loads((PRIOR/'evidence/factorial-before-manifest.json').read_text())
changed=[]
for entry in manifest:
    p=ORIGINAL/entry['path']
    if not p.is_file() or p.stat().st_size!=entry['size'] or digest(p)!=entry['sha256']: changed.append(entry['path'])
old={e['path'] for e in manifest}
added=[p.relative_to(ORIGINAL).as_posix() for p in ORIGINAL.rglob('*') if p.is_file()
       and not any(x in p.parts for x in ('__pycache__','.pytest_cache')) and p.relative_to(ORIGINAL).as_posix() not in old]
result={'files_checked':len(manifest),'changed_or_missing':changed,'added':added,'unchanged':not changed and not added}
save(HERE/'evidence/factorial-integrity-after.json',result)
print(json.dumps(result))
