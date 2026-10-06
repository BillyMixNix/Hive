"""Rehash original inputs and recovery copies; read-only and no application imports."""
from snapshot import *
from concurrent.futures import ThreadPoolExecutor

def check(r):
 problems=[]
 try:
  p=Path(r['origin'])
  actual=hashlib.sha256(os.readlink(p).encode('utf-8')).hexdigest() if r['type']=='link' else digest(p)
  if actual!=r['sha256']:problems.append({'path':r['path'],'issue':'original_hash_changed','actual':actual})
  if r['included']:
   actual=digest(OUT/r['path'])
   if actual!=r['sha256']:problems.append({'path':r['path'],'issue':'copy_hash_mismatch','actual':actual})
 except Exception as exc:problems.append({'path':r['path'],'issue':type(exc).__name__,'message':str(exc)})
 return problems

def main():
 rows=[json.loads(s) for s in (OUT/'WORKSPACE-MANIFEST.jsonl').read_text(encoding='utf-8').splitlines()]
 before={r['path'] for r in rows};now=set()
 for label,root in ROOTS.items():
  for p,rel in entries(root):now.add(label+'/'+rel.as_posix())
 changes=[];t0=time.monotonic()
 with ThreadPoolExecutor(max_workers=8) as pool:
  for start in range(0,len(rows),5000):
   for result in pool.map(check,rows[start:start+5000]):changes.extend(result)
   print('AUDITED',min(start+5000,len(rows)),'seconds',round(time.monotonic()-t0),flush=True)
 result={'files_rehashed':len(rows),'copies_rehashed':sum(r['included'] for r in rows),'new_original_paths':sorted(now-before),'missing_original_paths':sorted(before-now),'hash_or_read_errors':changes,'elapsed_seconds':round(time.monotonic()-t0,3),'application_tests_run':False,'model_calls':0,'production_changes':False}
 result['passed']=not any(result[k] for k in ('new_original_paths','missing_original_paths','hash_or_read_errors'))
 write('INTEGRITY-AUDIT.json',result);print(json.dumps(result,indent=2),flush=True)
 assert result['passed']

if __name__=='__main__':main()
