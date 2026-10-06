"""Create only the new recovery commit using byte-exact Git blob plumbing."""
from snapshot import *

PARENT='9a4c6436899e24f9bdee216d837c490ffc5d69ca'
BRANCH='refs/heads/recovery/workshop-source-20261006'

def git(*args,data=None):
 return subprocess.run(['git','-c','core.longpaths=true','-c','core.autocrlf=false','-C',str(REPO),*args],input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout

def main():
 assert json.loads((OUT/'INTEGRITY-AUDIT.json').read_bytes())['passed']
 assert git('rev-parse','HEAD').decode().strip()==PARENT
 assert git('symbolic-ref','HEAD').decode().strip()==BRANCH
 assert not git('diff','--name-only')
 assert not git('diff','--cached','--name-only')
 files=sorted(p for p in OUT.rglob('*') if p.is_file())
 assert not any(p.stat().st_size>=95*1024**2 for p in files)
 names=[p.relative_to(REPO).as_posix() for p in files]
 assert all('\n' not in x and '\r' not in x and not x.startswith('"') for x in names)
 # All ordinary copied sources must agree with final selection, not initial copy.
 rows=[json.loads(line) for line in __import__('gzip').decompress((OUT/'WORKSPACE-MANIFEST.jsonl.gz').read_bytes()).decode('utf-8').splitlines()]
 for r in rows:
  assert (OUT/r['path']).is_file()==r['included'],r['path']
 known={str(OUT/r['path']):r['sha256'] for r in rows if r['included']}
 expected=[known[str(p)] if str(p) in known else digest(p) for p in files]
 representatives={}
 for name,sha in zip(names,expected):representatives.setdefault(sha,name)
 unique_ids=git('hash-object','-w','--no-filters','--stdin-paths',data=('\n'.join(representatives.values())+'\n').encode('utf-8')).decode().splitlines()
 assert len(unique_ids)==len(representatives)
 sha_to_oid=dict(zip(representatives,unique_ids));blob_ids=[sha_to_oid[sha] for sha in expected]
 index=b''.join(f'100644 {oid}\t{name}\0'.encode('utf-8') for oid,name in zip(blob_ids,names))
 git('update-index','-z','--index-info',data=index)
 changes=git('diff','--cached','--name-status','-z').decode('utf-8').split('\0')[:-1]
 assert len(changes)==len(names)*2
 assert all(changes[i]=='A' and changes[i+1].startswith('recovery/workshop-source-20261006/') for i in range(0,len(changes),2))
 tree=git('write-tree').decode().strip()
 commit=git('commit-tree',tree,'-p',PARENT,data=b'Recover current Workshop source and immutable experiment evidence\n\nAdd byte-preserving source/evidence snapshot, manifests, exclusions and recovery audit. No production changes, tests, model calls or promotion.\n').decode().strip()
 git('update-ref',BRANCH,commit,PARENT)
 # Check the actual committed blobs against local bytes, without checkout filters.
 proc=subprocess.Popen(['git','-C',str(REPO),'cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 checked={}
 for p,oid,sha in zip(files,blob_ids,expected):
  if oid not in checked:
   proc.stdin.write((oid+'\n').encode());proc.stdin.flush()
   header=proc.stdout.readline().decode().strip().split()
   assert header[1]=='blob'
   size=int(header[2]);remaining=size;h=hashlib.sha256()
   while remaining:
    b=proc.stdout.read(min(1024*1024,remaining));assert b;h.update(b);remaining-=len(b)
   assert proc.stdout.read(1)==b'\n';checked[oid]=h.hexdigest()
  assert checked[oid]==sha,str(p)
 proc.stdin.close();assert proc.wait()==0
 result={'branch':BRANCH,'parent':PARENT,'commit':commit,'git_tree':tree,'added_files':len(names),'unique_blobs_verified':len(checked),'sha256_blob_verification':'passed','modified_or_deleted_parent_files':0,'push_performed':False}
 (AREA/'commit-summary.json').write_bytes(json.dumps(result,indent=2).encode()+b'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
