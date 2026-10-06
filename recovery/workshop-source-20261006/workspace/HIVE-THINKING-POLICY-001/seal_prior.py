"""Extend the immutable evidence inventory; no prior file is written."""
from common import *

def main():
    old=ROOT/'HIVE-FACTORIAL-003R1'
    prior=read(old/'evidence/prior-inventory.json')
    errors=[]
    for i,(p,row) in enumerate(prior.items(),1):
        if not Path(p).is_file() or sha(p)!=row['sha256']:errors.append(p)
        if i%10000==0:print('Checked',i,'prior files',flush=True)
    assert not errors,errors
    for root in (old,):prior.update({str(root/p):r for p,r in manifest(root).items()})
    for p in ROOT.glob('*REPORT.md'):prior[str(p)]={'sha256':sha(p),'size':p.stat().st_size}
    save(HERE/'evidence/prior-inventory.json',prior)
    save(HERE/'evidence/prior-audit-before.json',{'at':stamp(),'files':len(prior),'changes':errors,'passed':not errors})
    print('Sealed',len(prior),'immutable historical files',flush=True)

if __name__=='__main__':main()
