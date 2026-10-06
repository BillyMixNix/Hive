import ast,json
from qcommon import *
assert not (HERE/'evidence/BEFORE.json').exists()
source=manifest(SOURCE)
assert source==read(PRIOR/'evidence/source-inventory.json')
save(HERE/'evidence/production-before.json',source)
prior=read(PRIOR/'evidence/prior-inventory.json')
prior.update({str(PRIOR/p):row for p,row in manifest(PRIOR).items()})
prior[str(ROOT/'HIVE-FACTORIAL-003-REPORT.md')]={'sha256':sha(ROOT/'HIVE-FACTORIAL-003-REPORT.md'),'size':(ROOT/'HIVE-FACTORIAL-003-REPORT.md').stat().st_size}
changes=[p for p,r in prior.items() if not Path(p).is_file() or sha(p)!=r['sha256']]
assert not changes,changes
save(HERE/'evidence/prior-before.json',prior)
inventory=[]
for p in sorted(PRIOR.glob('*.py')):
    tree=ast.parse(p.read_text(encoding='utf-8'))
    inventory.append({'path':p.name,'sha256':sha(p),'functions':[{'name':n.name,'line':n.lineno,'async':isinstance(n,ast.AsyncFunctionDef)} for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))],
        'classes':[{'name':n.name,'line':n.lineno} for n in ast.walk(tree) if isinstance(n,ast.ClassDef)]})
save(HERE/'evidence/harness-inventory.json',inventory)
save(HERE/'evidence/BEFORE.json',{'at':stamp(),'source_files':len(source),'source_tree_hash':FREEZE['source']['tree_hash'],'prior_files':len(prior),'source_unchanged':True,'prior_unchanged':True,
    'baseline_sha256':external_root.tree_sha256(Path(FREEZE['baseline']['root'])),'test_hashes':{t['id']:sha(TASK_SOURCE/'hidden-tests'/t['test_filename']) for t in FREEZE['tasks']},'nfrt_attestation_sha256':sha(FREEZE['nfrt']['manifest'])})
print('Production and prior evidence sealed; no inference.',flush=True)
