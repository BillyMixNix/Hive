"""Read-only source inventory and byte-preserving recovery copy; never imports Hive."""
import collections, hashlib, json, os, re, stat, subprocess, sys, time
from pathlib import Path

AREA=Path(__file__).resolve().parent
REPO=AREA/'Hive'
OUT=REPO/'recovery/workshop-source-20261006'
WORKSPACE=Path('C:/Users/billy/Documents/Codex/2026-10-05/hive-transition-001-diagnose-and-repair')
HIST=Path('C:/Users/billy/Documents/Codex/2026-09-13/referenced-chatgpt-conversation-this-is-an/work')
BASE=Path('C:/Users/billy/Documents/Codex/2026-09-22/atm10-ai-companion-autonomous-build-mega/local-model-trial/runs/20260924-181046/baseline')
ROOTS={'workspace':WORKSPACE,'external/m3.2-baseline':BASE}
ROOTS.update({'external/historical-work/'+p.name:p for p in sorted(HIST.glob('HIVE-*'))})
ROOTS['external/original-v0.11.1']=HIST/'Nix-Workshop-v0.11.1-persistent-agents'
BACKLOG=HIST.parent/'nix-workshop-feature-backlog'
CACHE={'.git','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','.gradle','.venv','venv','node_modules','.tox','.nox','intermediate_results','downloaded_artifacts','gradle-user-home','gradle_home'}
BUILD={'build','dist','target','htmlcov'}
ARCHIVES={'.zip','.tar','.gz','.7z','.whl','.tgz','.xz','.bz2'}
COMPILED={'.pyc','.pyo','.class','.dll','.exe','.so','.dylib','.pdb','.obj','.o','.lib','.a'}
WEIGHTS={'.gguf','.safetensors','.onnx','.pt','.pth'}
SECRET_EXT={'.pem','.key','.p12','.pfx','.keystore','.jks'}
PATTERNS={
 'github_token':re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{50,255})'),
 'provider_key':re.compile(rb'sk-(?:proj-|ant-api\d\d-)?[A-Za-z0-9_-]{35,255}'),
 'aws_access_id':re.compile(rb'(?:AKIA|ASIA)[A-Z0-9]{16}'),
 'private_key':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
 'credential_url':re.compile(rb'https?://[^\s/"\x27:@]{1,80}:[^\s/"\x27@]{8,160}@'),
 'bearer_token':re.compile(rb'(?i)bearer\s+[A-Za-z0-9_\-.]{28,255}'),
}

def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
def digest(p):
 with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(name,value):
 p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8')+b'\n')
def entries(root):
 if root.is_file():yield root,Path(root.name);return
 for current,dirs,files in os.walk(root,followlinks=False):
  parent=Path(current)
  for name in sorted(dirs[:]):
   p=parent/name
   if p.is_symlink() or p.is_junction():dirs.remove(name);yield p,p.relative_to(root)
  for name in sorted(files):yield parent/name,(parent/name).relative_to(root)

def exclude(p,rel):
 parts=set(x.lower() for x in rel.parts);name=p.name.lower();s=p.suffix.lower()
 if p.is_symlink() or p.is_junction():return 'symlink_or_junction_not_followed'
 if name.startswith('.env') or name in {'credentials','credentials.json','secrets.json','.netrc','.npmrc','.pypirc','id_rsa','id_ed25519'} or s in SECRET_EXT:return 'credential_or_secret_file'
 if parts&CACHE:return 'git_metadata_or_dependency_runtime_cache'
 if parts&BUILD:return 'generated_build_output'
 if any(re.match(r'(?:full-)?regression(?:-final)?-temp|harness(?:-tests-final)?-temp|pytest-',x) for x in rel.parts):return 'generated_regression_scratch'
 if s in WEIGHTS:return 'model_weights'
 if s in COMPILED or s=='.bin':return 'compiled_binary_or_runtime_cache'
 if s=='.jar' and rel.as_posix().endswith('/gradle/wrapper/gradle-wrapper.jar') is False:return 'compiled_or_dependency_jar'
 if s in ARCHIVES:return 'opaque_archive_not_committed'
 if s in {'.db','.sqlite','.sqlite3'} or name.endswith(('.db-wal','.db-shm')):return 'runtime_database_may_contain_private_state'
 if any(x.lower() in {'data','media','self_snapshots','snapshots','workspace'} and (p.parents[len(rel.parts)-i-2]/'app.py').is_file() for i,x in enumerate(rel.parts[:-1]) if len(rel.parts)-i-2>=0):
  return 'application_runtime_or_user_state'
 if p.stat().st_size>=95*1024**2:return 'oversized_blob_requires_separate_recovery'
 return None

def git_state(root):
 command=['git','--no-optional-locks','-c','safe.directory='+str(root),'-C',str(root)]
 def run(args):
  p=subprocess.run(command+args,capture_output=True,timeout=30)
  return {'exit_code':p.returncode,'stdout':p.stdout.decode('utf-8','replace'),'stderr':p.stderr.decode('utf-8','replace')}
 status=run(['status','--porcelain=v2','--branch','--untracked-files=all'])
 result={'root':str(root),'status':status}
 if status['exit_code']==0:
  result['commit']=run(['rev-parse','HEAD']);result['branch']=run(['symbolic-ref','--short','-q','HEAD'])
  for key,args in [('tracked',['ls-files','-z']),('untracked',['ls-files','--others','--exclude-standard','-z']),('ignored',['ls-files','--others','--ignored','--exclude-standard','-z'])]:
   r=run(args);result[key]=r['stdout'].split('\0')[:-1]
 return result

def snapshot():
 OUT.mkdir(parents=True,exist_ok=True)
 assert not (OUT/'WORKSPACE-MANIFEST.jsonl').exists(),'Do not replace original inventory'
 write('SOURCE-ROOTS.json',{k:str(v) for k,v in ROOTS.items()})
 states=[git_state(WORKSPACE),git_state(BACKLOG)];rows=[];findings=[];errors=[];count=0;t0=time.monotonic()
 for label,root in ROOTS.items():
  print('INVENTORY',label,flush=True)
  for p,rel in entries(root):
   if rel.name=='.git' or '.git' in rel.parts:
    gitroot=p.parent if rel.name=='.git' else None
    if gitroot and not any(s['root']==str(gitroot) for s in states):states.append(git_state(gitroot))
   r={'path':label+'/'+rel.as_posix(),'origin':str(p),'root':label,'relative_path':rel.as_posix(),'git_status':'unversioned_workspace'}
   try:
    before=p.lstat();reason=exclude(p,rel);r.update(bytes=before.st_size,type='file')
    if p.is_symlink() or p.is_junction():
     data=os.readlink(p).encode('utf-8');r.update(type='link',link_target=os.readlink(p),sha256=hashlib.sha256(data).hexdigest());reason='symlink_or_junction_not_followed'
    else:
     h=hashlib.sha256();hits=set();chunks=[]
     with p.open('rb') as f:
      while b:=f.read(1024*1024):
       h.update(b)
       if reason is None:
        chunks.append(b)
     r['sha256']=h.hexdigest()
     after=p.stat()
     if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise RuntimeError('file changed during inventory')
     if reason is None:
      data=b''.join(chunks)
      for rule,pattern in PATTERNS.items():
       if pattern.search(data):hits.add(rule)
      if hits:
       reason='secret_scan_requires_review';findings.append({'path':r['path'],'sha256':r['sha256'],'rules':sorted(hits)})
      else:
       dest=OUT/r['path'];dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
    r['excluded_reason']=reason;r['included']=reason is None
    rows.append(r);count+=1
    if count%5000==0:print('FILES',count,'seconds',round(time.monotonic()-t0),flush=True)
   except Exception as exc:
    errors.append({'path':r['path'],'error_type':type(exc).__name__,'message':str(exc)})
  print('ROOT_DONE',label,count,flush=True)
 rows.sort(key=lambda r:r['path'])
 manifest=OUT/'WORKSPACE-MANIFEST.jsonl'
 with manifest.open('wb') as f:
  for r in rows:f.write(canonical(r)+b'\n')
 for name,selection in [('INCLUDED-FILES.jsonl',[r for r in rows if r['included']]),('EXCLUDED-FILES.jsonl',[r for r in rows if not r['included']])]:
  with (OUT/name).open('wb') as f:
   for r in selection:f.write(canonical(r)+b'\n')
 write('GIT-STATE.json',states);write('SECRET-SCAN-REVIEW.json',findings);write('INVENTORY-ERRORS.json',errors)
 trees={}
 for label in ROOTS:
  items={r['relative_path']:{k:r[k] for k in ('sha256','bytes','type')} for r in rows if r['root']==label}
  trees[label]={'files':len(items),'bytes':sum(r['bytes'] for r in rows if r['root']==label),'sha256':hashlib.sha256(canonical(items)).hexdigest()}
 summary={'manifest_sha256':digest(manifest),'tree_hash_method':'SHA256 of compact UTF-8 sorted-key JSON mapping relative path to {sha256,bytes,type}; link hashes cover target text, never dereferenced','roots':trees,'all_files':len(rows),'included_files':sum(r['included'] for r in rows),'excluded_files':sum(not r['included'] for r in rows),'excluded_reasons':dict(collections.Counter(r['excluded_reason'] for r in rows if r['excluded_reason'])),'secret_review_files':len(findings),'errors':len(errors)}
 write('MANIFEST-SUMMARY.json',summary);print(json.dumps(summary,indent=2),flush=True)
 assert not errors,'Inventory errors require explicit resolution'

if __name__=='__main__':snapshot()
