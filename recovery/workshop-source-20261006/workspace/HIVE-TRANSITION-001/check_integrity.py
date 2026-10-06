"""Verify every inventoried original factorial file without writing that tree."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORIGINAL = Path(r'C:\Users\billy\Documents\Codex\2026-09-13\referenced-chatgpt-conversation-this-is-an\work\HIVE-FACTORIAL-002')
manifest = json.loads((HERE / 'evidence/factorial-before-manifest.json').read_text())
changed = []
for entry in manifest:
    p = ORIGINAL / entry['path']
    if not p.is_file() or p.stat().st_size != entry['size'] or hashlib.sha256(p.read_bytes()).hexdigest() != entry['sha256']:
        changed.append(entry['path'])
original_paths = {e['path'] for e in manifest}
added = [p.relative_to(ORIGINAL).as_posix() for p in ORIGINAL.rglob('*')
         if p.is_file() and not any(part in {'__pycache__', '.pytest_cache'} for part in p.relative_to(ORIGINAL).parts)
         and p.relative_to(ORIGINAL).as_posix() not in original_paths]
result = {'files_checked': len(manifest), 'changed_or_missing': changed, 'added': added,
          'unchanged': not changed and not added, 'excluded': ['__pycache__', '.pytest_cache']}
(HERE / 'evidence/factorial-integrity-after.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result))
