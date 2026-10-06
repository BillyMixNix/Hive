"""Verify prior studies and read historical artifacts without writing them."""
import json
from pathlib import Path
from setup_study import save,sha
HERE=Path(__file__).resolve().parent
results={}
for name in ('HIVE-TRANSITION-001','HIVE-TRANSITION-002'):
    root=HERE.parent/name
    before=json.loads((HERE/f'evidence/{name}-before.json').read_text())
    changed=[p for p,h in before.items() if not (root/p).is_file() or sha(root/p)!=h]
    added=[p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
      and not any(x in p.parts for x in ('__pycache__','.pytest_cache')) and p.relative_to(root).as_posix() not in before]
    results[name]={'files_checked':len(before),'changed_or_missing':changed,'added':added,'unchanged':not changed and not added}
root=Path(r'C:\Users\billy\Documents\Codex\2026-09-13\referenced-chatgpt-conversation-this-is-an\work\HIVE-FACTORIAL-002')
before=json.loads((HERE.parent/'HIVE-TRANSITION-001/evidence/factorial-before-manifest.json').read_text())
changed=[e['path'] for e in before if not (root/e['path']).is_file() or sha(root/e['path'])!=e['sha256']]
paths={e['path'] for e in before}
added=[p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
  and not any(x in p.parts for x in ('__pycache__','.pytest_cache')) and p.relative_to(root).as_posix() not in paths]
results['HIVE-FACTORIAL-002']={'files_checked':len(before),'changed_or_missing':changed,'added':added,'unchanged':not changed and not added}
evals=json.loads((HERE/'evidence/eval009-source-manifest.json').read_text())
changed=[e['source'] for e in evals if sha(Path(e['source']))!=e['sha256']]
results['HIVE-EVAL-009-inspected-artifacts']={'files_checked':len(evals),'changed':changed,'unchanged':not changed}
save(HERE/'evidence/prior-integrity-after.json',results)
print(json.dumps(results,indent=2))
assert all(x['unchanged'] for x in results.values())
