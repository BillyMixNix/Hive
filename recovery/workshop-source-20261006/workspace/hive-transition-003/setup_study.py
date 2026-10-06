"""Separate source and immutable input inventories; no production edits or generation."""
import hashlib,json,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes((json.dumps(x,indent=2,ensure_ascii=False)+'\n').encode())
if __name__=='__main__':
    for name in ('HIVE-TRANSITION-001','HIVE-TRANSITION-002'):
        root=PARENT/name
        manifest={p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file()
                  and not any(s in p.parts for s in ('__pycache__','.pytest_cache'))}
        save(HERE/f'evidence/{name}-before.json',manifest)
    prior=PARENT/'HIVE-TRANSITION-002'
    shutil.copytree(prior/'repaired-workshop',HERE/'repaired-workshop',
      ignore=shutil.ignore_patterns('__pycache__','.pytest_cache'))
    for rel in ('evidence/ordinal-03','evidence/live/01-J001-r1-qwen2.5-coder-14b-hive','evidence/planner-input-fixtures'):
        shutil.copytree(prior/rel,HERE/rel)
    for name in ('diagnostic_runner.py','diagnostic_environment.py','diagnostic_capture.py'):
        (HERE/name).write_bytes((prior/name).read_bytes().replace(b'HIVE-TRANSITION-002',b'HIVE-TRANSITION-003'))
    source=prior/'evidence/live-diagnostic'
    dest=HERE/'evidence/transition-002'
    shutil.copytree(source/'wire',dest/'wire')
    for name in ('run.json','calls.json','result.json'):
        shutil.copy2(source/'01-J001-r1-qwen2.5-coder-14b-hive'/name,dest/name)
    shutil.copy2(prior/'evidence/live-input-measurements.json',dest/'input-measurements.json')
    save(HERE/'evidence/source-before.json',{p.relative_to(HERE/'repaired-workshop').as_posix():sha(p)
      for p in (HERE/'repaired-workshop').rglob('*.py') if '__pycache__' not in p.parts})
    print('Previous studies inventoried; unchanged source and exact T002 evidence copied.')
