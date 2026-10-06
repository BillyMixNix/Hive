"""Model-free investigation helpers; only this experiment's isolated source is writable."""
import hashlib,json,os,sys
from datetime import datetime,timezone
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent;OUT=HERE/'evidence'
ORIGINAL=ROOT/'HIVE-FACTORIAL-003/repaired-workshop';SOURCE=HERE/'repaired-workshop'
FREEZE=json.loads((ROOT/'HIVE-FACTORIAL-003/FREEZE.json').read_bytes())
BASE=Path(FREEZE['baseline']['root']);CACHE=Path(FREEZE['verifier']['approved_cache_root'])
TASK_SOURCE=Path('C:/Users/billy/Documents/Codex/2026-09-13/referenced-chatgpt-conversation-this-is-an/work/HIVE-FACTORIAL-001')
sys.path.insert(0,str(SOURCE))
from workshop import external_root,hive,hive_jvm,hive_verifier,providers
from verification import nfrt_seed
async def forbidden(*a,**k):raise AssertionError('No model calls authorized in NFRT attestation work')
providers.ollama_chat=forbidden;providers.openai_chat=forbidden
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
def save(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8')
def stamp():return datetime.now(timezone.utc).isoformat()
def inventory(root):return {p.relative_to(root).as_posix():{'sha256':sha(p),'size':p.stat().st_size} for p in sorted(Path(root).rglob('*')) if p.is_file()}
def configure(manifest=None):
    manifest=Path(manifest or FREEZE['nfrt']['manifest'])
    os.environ['GRADLE_USER_HOME']=str(CACHE)
    os.environ['HIVE_NFRT_SEED_MANIFEST']=str(manifest)
    os.environ['HIVE_NFRT_SEED_SHA256']=sha(manifest)
def attest(tree,manifest=None):
    configure(manifest)
    return nfrt_seed.configured_seed(tree,CACHE,FREEZE['verifier']['jvm_profile'],FREEZE['baseline']['sha256'],
             FREEZE['verifier']['verifier_image_id'],FREEZE['nfrt']['identity']['downloaded_manifest_sha256'])
