#!/usr/bin/env python3
"""Frozen tree fingerprint implementation of the user-supplied specification."""
import hashlib,json,os,stat,sys
from pathlib import Path
EXCLUDED=set('.git .hg .svn .venv venv env envs virtualenv .tox .pytest_cache __pycache__ .mypy_cache .ruff_cache .cache cache caches node_modules .gradle .idea data media reports snapshots workspace hive_runs self_snapshots logs build dist target releases outputs artifacts'.split())
def tree_hash(root):
    root=Path(root).absolute()
    if root.is_symlink() or (hasattr(root,'is_junction') and root.is_junction()): raise ValueError('linked root')
    resolved=root.resolve(strict=True)
    records=[]
    def scan(directory):
        for entry in os.scandir(directory):
            p=Path(entry.path); rel=p.relative_to(root)
            st=p.lstat()
            if p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()): raise ValueError('linked path: '+str(rel))
            if not p.resolve(strict=True).is_relative_to(resolved): raise ValueError('escaping path: '+str(rel))
            if stat.S_ISDIR(st.st_mode):
                parts=rel.parts
                resource_data=(p.name=='data' and len(parts)>=3 and parts[0]=='src' and parts[-2]=='resources')
                if p.name in EXCLUDED and not resource_data:continue
                scan(p)
            elif stat.S_ISREG(st.st_mode):
                if p.name not in {'.git','.hg','.svn'}:
                    records.append((rel.as_posix(),hashlib.sha256(p.read_bytes()).hexdigest()))
            else:raise ValueError('special file: '+str(rel))
    scan(root)
    records.sort(key=lambda x:(x[0].casefold(),x[0]))
    digest=hashlib.sha256()
    for path,content_hash in records:
        raw=path.encode('utf-8');digest.update(len(raw).to_bytes(8,'big'));digest.update(raw);digest.update(content_hash.encode('ascii'))
    return {'tree_sha256':digest.hexdigest(),'file_count':len(records),'files':dict(records)}
if __name__=='__main__':print(json.dumps(tree_hash(sys.argv[1]),indent=2))
