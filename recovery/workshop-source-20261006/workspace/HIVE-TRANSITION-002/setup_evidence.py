"""Create an isolated diagnostic source copy and preserve provenance (no generation)."""
import hashlib, json, shutil
from pathlib import Path
import httpx

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'HIVE-TRANSITION-001'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes((json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode())

if __name__ == '__main__':
    target = HERE / 'repaired-workshop'
    assert not target.exists()
    # Preserve every prior evidence/source file. Ignore only disposable Python caches.
    manifest = {p.relative_to(PRIOR).as_posix(): sha(p) for p in PRIOR.rglob('*')
                if p.is_file() and not any(x in p.parts for x in ('__pycache__', '.pytest_cache'))}
    save(HERE / 'evidence/prior-study-before.json', manifest)
    shutil.copytree(PRIOR / 'repaired-workshop', target,
                    ignore=shutil.ignore_patterns('__pycache__', '.pytest_cache'))
    for name in ('diagnostic_runner.py', 'diagnostic_environment.py'):
        (HERE / name).write_bytes((PRIOR / name).read_bytes().replace(b'HIVE-TRANSITION-001', b'HIVE-TRANSITION-002'))
    # Existing transition tests use these preserved fixtures relative to their source copy.
    shutil.copytree(PRIOR / 'evidence/ordinal-03', HERE / 'evidence/ordinal-03')
    fixture = 'evidence/live/01-J001-r1-qwen2.5-coder-14b-hive/run.json'
    (HERE / fixture).parent.mkdir(parents=True)
    shutil.copy2(PRIOR / fixture, HERE / fixture)
    with httpx.Client(timeout=60, trust_env=False) as client:
        save(HERE / 'evidence/runtime-version.json', client.get('http://127.0.0.1:11434/api/version').json())
        save(HERE / 'evidence/model-show.json', client.post('http://127.0.0.1:11434/api/show', json={'model':'qwen2.5-coder:14b'}).json())
        for name in ('server/prompt.go', 'server/routes.go', 'llm/server.go', 'api/types.go', 'envconfig/config.go'):
            url = 'https://raw.githubusercontent.com/ollama/ollama/v0.34.0/' + name
            response = client.get(url); response.raise_for_status()
            out = HERE / 'evidence/upstream' / name
            out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(response.content)
    print('Isolated source copied; prior evidence inventoried; runtime metadata and pinned upstream source saved.')
