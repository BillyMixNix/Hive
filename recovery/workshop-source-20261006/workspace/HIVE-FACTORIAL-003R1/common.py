"""Study instrumentation only; never modifies the frozen controller."""
import hashlib,json,os,sys,time
from datetime import datetime,timezone
from pathlib import Path
sys.dont_write_bytecode=True
# Local study process only; never read, log, or modify the external credential.
INHERITED_CLOUD_CREDENTIAL_REMOVED=bool(os.environ.pop('OPENAI_API_KEY',None))
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
STUDY='HIVE-FACTORIAL-003R1'
HIST=Path('C:/Users/billy/Documents/Codex/2026-09-13/referenced-chatgpt-conversation-this-is-an/work/HIVE-FACTORIAL-002')
TASK_SOURCE=HIST.parent/'HIVE-FACTORIAL-001'
SOURCE=HERE/'repaired-workshop'
OUTPUT_LIMITS={'planner':2048,'ui':6000,'backend':6000,'tests':6000,'reviewer':1536}
def stamp():return datetime.now(timezone.utc).isoformat()
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8');temp.replace(path)
def manifest(root):
    root=Path(root)
    return {p.relative_to(root).as_posix():{'sha256':sha(p),'size':p.stat().st_size} for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink()}
def tree_hash(rows):return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def event(kind,**data):
    row={'at':stamp(),'monotonic':time.monotonic(),'event':kind,**data}
    with (HERE/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,default=str)+'\n')
    print(json.dumps(row,default=str),flush=True)

def read(path):return json.loads(Path(path).read_bytes())
