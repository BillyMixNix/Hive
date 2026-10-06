"""Read-only prior audit, isolated production copy and pinned-source extraction."""
import hashlib,json,shutil,sys,zipfile
from pathlib import Path
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8')
def inventory(root):return {p.relative_to(root).as_posix():{'sha256':sha(p),'size':p.stat().st_size} for p in sorted(root.rglob('*')) if p.is_file()}
if __name__=='__main__':
    out=HERE/'evidence';out.mkdir(exist_ok=False)
    prior=json.loads((ROOT/'HARNESS-QUALIFICATION-001/evidence/prior-before.json').read_bytes())
    for folder in [ROOT/'HARNESS-QUALIFICATION-001']:
        prior.update({str(folder/p):r for p,r in inventory(folder).items()})
    for p in ROOT.glob('*REPORT.md'):prior[str(p)]={'sha256':sha(p),'size':p.stat().st_size}
    changed=[p for p,r in prior.items() if not Path(p).is_file() or sha(p)!=r['sha256']]
    assert not changed,changed
    save(out/'prior-before.json',prior)
    original=ROOT/'HIVE-FACTORIAL-003/repaired-workshop';source=inventory(original)
    assert source==json.loads((ROOT/'HARNESS-QUALIFICATION-001/evidence/production-before.json').read_bytes())
    save(out/'original-source.json',source)
    shutil.copytree(original,HERE/'repaired-workshop')
    upstream=ROOT/'HIVE-TRANSITION-004B/evidence/upstream'
    for name in ['moddev-gradle-2.0.147-sources.jar','neoform-runtime-2.0.31-sources.jar']:
        with zipfile.ZipFile(upstream/name) as z:
            for path in z.namelist():
                if not path.endswith('.java'):continue
                target=out/'pinned-source'/name.removesuffix('-sources.jar')/path
                target.resolve().relative_to(out.resolve());target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(path))
    save(out/'bootstrap.json',{'prior_files':len(prior),'original_source_files':len(source),'original_source_unchanged':True,
          'pinned_source_archives':{p:sha(upstream/p) for p in ['moddev-gradle-2.0.147-sources.jar','neoform-runtime-2.0.31-sources.jar']},'model_calls':0})
    print('Prior evidence sealed and production copied without changes.',flush=True)
