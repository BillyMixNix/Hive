import hashlib,json,shutil,sys
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n')
if __name__=='__main__':
 previous=['HIVE-TRANSITION-001','HIVE-TRANSITION-002','hive-transition-003','HIVE-TRANSITION-004','HIVE-TRANSITION-004B','HIVE-TRANSITION-004-RESOURCE-SAVER']
 rows=[]
 for name in previous:
  for p in (HERE.parent/name).rglob('*'):
   if p.is_file() and not p.is_symlink():rows.append({'path':p.relative_to(HERE.parent).as_posix(),'sha256':sha(p),'size':p.stat().st_size})
 save(HERE/'evidence/prior-evidence-seal.json',rows)
 shutil.copytree(HERE.parent/'HIVE-TRANSITION-004/repaired-workshop',HERE/'repaired-workshop',ignore=shutil.ignore_patterns('__pycache__','.pytest_cache','.git','*.pyc'))
 for name in ['ordinal-03','planner-input-fixtures','live']:
  src=HERE.parent/'HIVE-TRANSITION-004/evidence'/name
  if src.exists():shutil.copytree(src,HERE/'evidence'/name)
 shutil.copyfile(HERE.parent/'HIVE-TRANSITION-004/diagnostic_environment.py',HERE/'diagnostic_environment.py')
 shutil.copyfile(HERE.parent/'HIVE-TRANSITION-004/evidence/historical-replay.json',HERE/'evidence/historical-replay.json')
 save(HERE/'evidence/bootstrap.json',{'prior_files':len(rows),'policy_sha256':sha(HERE/'cache-policy.md')})
 print('Isolated source copied; prior evidence sealed:',len(rows))
