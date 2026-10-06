"""Archive only test-generated isolated runtime state, restore copied fixtures."""
import shutil
from bootstrap import HERE,sha,save
new=(HERE/'repaired-workshop').resolve();old=(HERE.parent/'HIVE-TRANSITION-004C/repaired-workshop').resolve()
out=(HERE/'evidence/regression/runtime-state').resolve();out.mkdir(parents=True,exist_ok=False)
rows=[]
for folder in (new/'snapshots').iterdir():
 if not (old/'snapshots'/folder.name).exists():
  source=folder.resolve();target=(out/'snapshots'/folder.name).resolve()
  assert source.is_relative_to(new/'snapshots') and target.is_relative_to(out)
  target.parent.mkdir(exist_ok=True)
  shutil.move(str(source),str(target));rows.append({'moved':source.relative_to(new).as_posix(),'to':target.relative_to(HERE).as_posix()})
db=new/'data/workshop.db';baseline=old/'data/workshop.db'
if sha(db)!=sha(baseline):
 shutil.copyfile(db,out/'workshop.db')
 shutil.copyfile(baseline,db);rows.append({'restored':'data/workshop.db','test_state':'evidence/regression/runtime-state/workshop.db'})
save(out/'actions.json',rows)
print('Preserved test-only state and restored original runtime fixtures:',len(rows))
