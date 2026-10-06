"""Create an isolated study; never import or write previous production trees."""
import hashlib,json,shutil,sys
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent/'HIVE-TRANSITION-003'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,obj):
 p.parent.mkdir(parents=True,exist_ok=True)
 p.write_bytes((json.dumps(obj,indent=2,ensure_ascii=False)+'\n').encode())
if __name__=='__main__':
 for name in ('HIVE-TRANSITION-001','HIVE-TRANSITION-002','HIVE-TRANSITION-003'):
  root=HERE.parent/name
  save(HERE/f'evidence/{name}-before.json',{p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file()})
 shutil.copytree(PRIOR/'repaired-workshop',HERE/'repaired-workshop',ignore=shutil.ignore_patterns('__pycache__','.pytest_cache'))
 for rel in ('evidence/ordinal-03','evidence/planner-input-fixtures'):
  shutil.copytree(PRIOR/rel,HERE/rel)
 shutil.copy2(PRIOR/'evidence/historical-replay.json',HERE/'evidence/historical-replay.json')
 shutil.copytree(PRIOR/'evidence/live-stage-observation',HERE/'evidence/transition-003/applied-stage')
 for name in ('run.json','calls.json','result.json','candidate_metadata.json'):
  src=PRIOR/'evidence/live-diagnostic/01-J001-r1-qwen2.5-coder-14b-hive'/name
  shutil.copy2(src,HERE/'evidence/transition-003'/name)
 for name in ('diagnostic_environment.py','diagnostic_runner.py','diagnostic_capture.py'):
  (HERE/name).write_bytes((PRIOR/name).read_bytes().replace(b'HIVE-TRANSITION-003',b'HIVE-TRANSITION-004'))
 save(HERE/'evidence/source-before.json',{p.relative_to(HERE/'repaired-workshop').as_posix():sha(p) for p in (HERE/'repaired-workshop').rglob('*') if p.is_file()})
 print('Isolated source and historical evidence prepared.')
