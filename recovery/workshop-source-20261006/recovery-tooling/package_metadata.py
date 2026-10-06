"""Compress newly created recovery inventories, never historical evidence."""
from snapshot import *
import gzip, shutil

def main():
 assert json.loads((OUT/'INTEGRITY-AUDIT.json').read_bytes())['passed']
 summary=json.loads((OUT/'MANIFEST-SUMMARY.json').read_bytes());storage={}
 for name in ('WORKSPACE-MANIFEST.jsonl','INCLUDED-FILES.jsonl','EXCLUDED-FILES.jsonl'):
  source=OUT/name;dest=OUT/(name+'.gz')
  with source.open('rb') as inp,dest.open('wb') as raw,gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0,compresslevel=9) as out:
   shutil.copyfileobj(inp,out,1024*1024)
  with gzip.open(dest,'rb') as inp:roundtrip=hashlib.file_digest(inp,'sha256').hexdigest()
  assert roundtrip==digest(source)
  storage[name]={'stored_as':dest.name,'uncompressed_sha256':roundtrip,'compressed_sha256':digest(dest),'uncompressed_bytes':source.stat().st_size,'compressed_bytes':dest.stat().st_size}
 summary['manifest_storage']=storage;write('MANIFEST-SUMMARY.json',summary)
 toolsdir=OUT/'recovery-tooling';toolsdir.mkdir(exist_ok=True)
 for name in ('snapshot.py','review_snapshot.py','finalize_selection.py','source_report.py','audit_originals.py','write_reports.py','package_metadata.py','quarantine_copies.ps1','commit_snapshot.py'):
  (toolsdir/name).write_bytes((AREA/name).read_bytes())
 (OUT/'REMOTE-HEADS-BEFORE.txt').write_bytes((AREA/'remote-heads-before.txt').read_bytes())
 print(json.dumps(storage,indent=2))

if __name__=='__main__':main()
