"""Seal prior evidence and create an isolated successor. No model calls."""
import hashlib,json,shutil,sys
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8')
if __name__=='__main__':
 rows=[]
 for directory in HERE.parent.iterdir():
  if directory==HERE:continue
  paths=directory.rglob('*') if directory.is_dir() else [directory]
  for p in paths:
   if p.is_file() and not p.is_symlink():rows.append({'path':p.relative_to(HERE.parent).as_posix(),'sha256':sha(p),'size':p.stat().st_size})
 save(HERE/'evidence/prior-evidence-seal.json',rows)
 prior=HERE.parent/'HIVE-TRANSITION-004C'
 shutil.copytree(prior/'repaired-workshop',HERE/'repaired-workshop',ignore=shutil.ignore_patterns('__pycache__','.pytest_cache','.git','*.pyc'))
 for name in ['ordinal-03','planner-input-fixtures','live']:
  shutil.copytree(prior/'evidence'/name,HERE/'evidence'/name)
 for name in ['historical-replay.json','approved-nfrt-seed.json']:
  shutil.copyfile(prior/'evidence'/name,HERE/'evidence'/name)
 for name in ['diagnostic_environment.py','run_regression.py','run_experiment.py']:
  text=(prior/name).read_text().replace('hive-transition-004c-','hive-transition-005-')
  (HERE/name).write_text(text)
 config=json.loads((prior/'evidence/configuration.json').read_text())
 config.update(study='HIVE-TRANSITION-005',manifest=str(HERE/'evidence/approved-nfrt-seed.json'))
 save(HERE/'evidence/configuration.json',config)
 for name in ['diagnostic_runner.py','diagnostic_capture.py']:
  shutil.copyfile(HERE.parent/'hive-transition-003'/name,HERE/name)
 save(HERE/'evidence/bootstrap.json',{'prior_files':len(rows),'source':'HIVE-TRANSITION-004C/repaired-workshop'})
 print('Sealed prior files:',len(rows))
