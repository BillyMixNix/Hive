import collections,json,sys,zipfile
from pathlib import Path
sys.dont_write_bytecode=True
from bootstrap import HERE,save,sha
config=json.loads((HERE/'evidence/configuration.json').read_text());base=Path(config['freeze']['baseline']['root'])
source={}
for directory in (base/'src').iterdir():
 if directory.is_dir():
  files=list(directory.rglob('*.java'));source[directory.name]={'count':len(files),'bytes':sum(p.stat().st_size for p in files),'paths':[p.relative_to(base).as_posix() for p in files]}
cache=Path(config['approved']['approved_cache_root'])
manifest=json.loads((cache.parent.parent/cache.name/'external-build-inputs.manifest.json').read_text())
rows=manifest.get('artifacts') or manifest.get('files')
summary={}
for row in rows:
 key='assets' if '/assets/' in row['path'] or row['path'].startswith('assets/') else 'artifacts'
 group=summary.setdefault(key,{'files':0,'bytes':0});group['files']+=1;group['bytes']+=row['size']
save(HERE/'evidence/build-inventory.json',{'source_sets':source,'downloaded_inputs':summary,'source_filesystem':'Windows NTFS host path; Docker Desktop bind crossing to Linux','destination':'container /work tmpfs','hash_during_copy':True})
archive=HERE.parent/'HIVE-TRANSITION-004B/evidence/upstream/neoform-runtime-2.0.31-sources.jar'
with zipfile.ZipFile(archive) as z:
 for name in z.namelist():
  if name.endswith('.java') and any(k in name for k in ['ArtifactManager','AssetDownloader','DownloadManager','ParallelDownloader']):
   target=HERE/'evidence/upstream'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(name))
print(json.dumps({'source_counts':{k:v['count'] for k,v in source.items()},'downloaded_inputs':summary}))
