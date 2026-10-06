import shutil
from pathlib import Path
from setup_study import HERE,save,sha
root=Path(r'C:\Users\billy\Documents\Codex\2026-09-13\referenced-chatgpt-conversation-this-is-an\work\HIVE-ASTRA-J001-INDEPENDENT-VERIFY/sealed-evidence')
dest=HERE/'evidence/accepted-control-history';dest.mkdir(exist_ok=False)
rows=[]
for name in ('summary.json','preflight.json','targeted.json','full.json'):
 source=root/name;shutil.copy2(source,dest/name)
 rows.append({'source':str(source),'copy':str((dest/name).relative_to(HERE)),'sha256':sha(source)})
save(dest/'manifest.json',rows)
