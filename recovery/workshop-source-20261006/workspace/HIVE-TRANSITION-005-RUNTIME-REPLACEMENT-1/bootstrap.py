"""Read-only sealing and byte-identical isolated source copy. No inference."""
import hashlib,json,shutil,sys
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent/'HIVE-TRANSITION-005'
STUDY=HERE.name
def sha(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(v,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8')
def manifest(root):
 return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()}
if __name__=='__main__':
 assert not (HERE/'evidence').exists(),'Refusing to overwrite evidence'
 rows={}
 for directory in HERE.parent.iterdir():
  if directory==HERE:continue
  for p in (directory.rglob('*') if directory.is_dir() else [directory]):
   if p.is_file() and not p.is_symlink():rows[p.relative_to(HERE.parent).as_posix()]=sha(p)
 save(HERE/'evidence/prior-evidence-seal.json',rows)
 original=manifest(PRIOR/'repaired-workshop')
 shutil.copytree(PRIOR/'repaired-workshop',HERE/'repaired-workshop')
 assert manifest(HERE/'repaired-workshop')==original
 save(HERE/'evidence/source-before.json',original)
 shutil.copyfile(PRIOR/'diagnostic_environment.py',HERE/'diagnostic_environment.py')
 runner=(PRIOR/'diagnostic_runner.py').read_text()
 runner=runner.replace('"study_id": "HIVE-TRANSITION-005"','"study_id": "'+STUDY+'"')
 runner=runner.replace('OUTPUT_LIMITS = {"planner": 2048, "ui": 6000, "backend": 6000, "tests": 6000, "reviewer": 1536}',
  'OUTPUT_LIMITS = {role: 2048 for role in ("planner", "ui", "backend", "tests", "reviewer")}')
 needle='            if providers.openai_key() or providers.ollama_base() != "http://127.0.0.1:11434":'
 assert runner.count(needle)==1
 runner=runner.replace(needle,'            if getattr(providers, "RUNTIME_ABORTED", False):\n                append_event("inference_blocked_after_runtime_failure", role=role)\n                raise StudyStop("Authorized experiment stops inference after runtime failure")\n'+needle)
 (HERE/'diagnostic_runner.py').write_text(runner,encoding='utf-8')
 save(HERE/'evidence/bootstrap.json',{'prior_files':len(rows),'source_files':len(original),'source_byte_identical':True,
  'harness_changes':['new study/evidence paths','explicit user output cap 2048 for every role','prevent further logical inference after exhausted provider runtime failure'],
  'production_changes':[]})
 print(json.dumps({'prior_files':len(rows),'source_files':len(original),'byte_identical':True}))
