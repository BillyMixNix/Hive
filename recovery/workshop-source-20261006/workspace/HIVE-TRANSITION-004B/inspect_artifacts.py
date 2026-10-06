"""Read-only frozen-artifact investigation; outputs only to TRANSITION-004B."""
import hashlib,json,os,sys,urllib.request,zipfile,io
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
OUT=HERE/'evidence';OUT.mkdir(exist_ok=False)
PRIOR=HERE.parent/'HIVE-TRANSITION-004'
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,x):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2)+'\n')
freeze=json.loads((HERE.parent/'HIVE-TRANSITION-003/FREEZE.json').read_text())
preflight=json.loads((PRIOR/'evidence/verifier-replays/post-regression-baseline/preflight.json').read_text())
cache=Path(preflight['approved']['approved_cache_root'])
save(OUT/'inputs.json',{'freeze':freeze,'approved':preflight['approved']})
prior_files={str(p.relative_to(HERE.parent)):sha(p) for r in (PRIOR,HERE.parent/'HIVE-TRANSITION-004-RESOURCE-SAVER') for p in r.rglob('*') if p.is_file()}
for name in ['HIVE-TRANSITION-004-REPORT.md','HIVE-TRANSITION-003-REPORT.md']:
 prior_files[name]=sha(HERE.parent/name)
save(OUT/'prior-before.json',prior_files)
native=cache/'caches/neoformruntime/intermediate_results'
inventory=[]
for p in sorted(native.iterdir()):
 if p.is_file():
  row={'path':p.name,'size':p.stat().st_size,'sha256':sha(p)}
  if p.suffix=='.txt':
   target=OUT/'native-cache-keys'/p.name;target.parent.mkdir(exist_ok=True);target.write_bytes(p.read_bytes())
  if p.suffix=='.jar':
   with zipfile.ZipFile(p) as z:
    row['zip_entries']=len(z.namelist());row['candidate_package_entries']=[n for n in z.namelist() if n.startswith('dev/atmcompanion/')]
  inventory.append(row)
save(OUT/'native-generated-inventory.json',inventory)
records=[]
for artifact,version in [('moddev-gradle','2.0.147'),('neoform-runtime','2.0.31')]:
 jars=list((cache/f'caches/modules-2/files-2.1/net.neoforged/{artifact}/{version}').rglob('*.jar'))
 for p in jars:
  with zipfile.ZipFile(p) as z:
   manifest=z.read('META-INF/MANIFEST.MF').decode(errors='replace')
  records.append({'path':str(p),'sha256':sha(p),'manifest':manifest})
 url=f'https://maven.neoforged.net/releases/net/neoforged/{artifact}/{version}/{artifact}-{version}-sources.jar'
 try:
  with urllib.request.urlopen(url,timeout=30) as response:data=response.read()
  target=OUT/'upstream'/f'{artifact}-{version}-sources.jar';target.parent.mkdir(exist_ok=True);target.write_bytes(data)
  with zipfile.ZipFile(io.BytesIO(data)) as z:
   for name in z.namelist():
    if name.endswith('.java') and any(s in name for s in ('CreateMinecraftArtifacts','NeoFormRuntimeTask','NeoFormRuntimeExtension','ModDevArtifactsWorkflow','CacheManager','CacheKey','ExecutionNode','NeoFormEngine','NeoFormRuntimePlugin')):
     dest=target.parent/artifact/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(name))
  records.append({'url':url,'sha256':hashlib.sha256(data).hexdigest(),'saved':str(target)})
 except Exception as exc:records.append({'url':url,'error':repr(exc)})
save(OUT/'upstream-provenance.json',records)
print(json.dumps({'upstream':records,'generated_cache_files':len(inventory),'generated_cache_bytes':sum(x['size'] for x in inventory)},indent=2))
