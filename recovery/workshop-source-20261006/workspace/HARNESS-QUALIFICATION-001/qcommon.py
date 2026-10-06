"""Qualification artifacts only. No task-provider calls or production edits."""
import hashlib,json,os,sys
from datetime import datetime,timezone
from pathlib import Path
sys.dont_write_bytecode=True
os.environ.pop('OPENAI_API_KEY',None)
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
PRIOR=ROOT/'HIVE-FACTORIAL-003'
SOURCE=PRIOR/'repaired-workshop'
FREEZE=json.loads((PRIOR/'FREEZE.json').read_bytes())
TASK_SOURCE=Path('C:/Users/billy/Documents/Codex/2026-09-13/referenced-chatgpt-conversation-this-is-an/work/HIVE-FACTORIAL-001')
sys.path.insert(0,str(SOURCE))
from workshop import hive,hive_jvm,hive_verifier,external_root,providers
from verification import nfrt_seed
def stamp():return datetime.now(timezone.utc).isoformat()
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,data):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    temp=p.with_suffix(p.suffix+'.tmp');temp.write_text(json.dumps(data,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8');temp.replace(p)
def read(p):return json.loads(Path(p).read_bytes())
def manifest(root):return {p.relative_to(root).as_posix():{'sha256':sha(p),'size':p.stat().st_size} for p in sorted(Path(root).rglob('*')) if p.is_file() and not p.is_symlink()}
def configure():
    os.environ['GRADLE_USER_HOME']=FREEZE['verifier']['approved_cache_root']
    os.environ['HIVE_NFRT_SEED_MANIFEST']=FREEZE['nfrt']['manifest']
    os.environ['HIVE_NFRT_SEED_SHA256']=FREEZE['nfrt']['sha256']
def forbid_models():
    async def forbidden(*args,**kwargs):raise AssertionError('Model inference is forbidden during harness qualification')
    providers.ollama_chat=forbidden;providers.openai_chat=forbidden
def attest(tree):
    configure()
    return nfrt_seed.configured_seed(tree,Path(FREEZE['verifier']['approved_cache_root']),FREEZE['verifier']['jvm_profile'],
        FREEZE['baseline']['sha256'],FREEZE['verifier']['verifier_image_id'],FREEZE['nfrt']['identity']['downloaded_manifest_sha256'])
