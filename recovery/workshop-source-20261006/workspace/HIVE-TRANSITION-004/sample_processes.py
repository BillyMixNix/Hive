"""Small read-only /proc snapshot; explicitly records its own observation overhead."""
import datetime,json,subprocess,sys,time
from pathlib import Path
from setup_study import HERE,save
case=sys.argv[1]
root=HERE/'evidence/verifier-replays'/case/'diagnostics'
inv=json.loads((root/'invocation.json').read_text());container=inv['container']
code=r'''
import json,os,pathlib
root=pathlib.Path('/proc');rows=[]
def read(p):
 try:return p.read_text(errors='replace')[:24000]
 except Exception as e:return type(e).__name__+': '+str(e)
for proc in root.iterdir():
 if not proc.name.isdigit() or int(proc.name)==os.getpid():continue
 row={'pid':int(proc.name),'cmdline':read(proc/'cmdline').replace('\x00',' ')}
 for name in ('status','stat','wchan','io'):row[name]=read(proc/name)
 fds={}
 try:
  for fd in (proc/'fd').iterdir():
   try:fds[fd.name]=os.readlink(fd)
   except OSError:pass
 except OSError:pass
 row['open_files']=fds;rows.append(row)
print(json.dumps({'processes':rows,'locks':read(root/'locks'),'tcp':read(root/'net/tcp'),
 'tcp6':read(root/'net/tcp6'),'memory_events':read(pathlib.Path('/sys/fs/cgroup/memory.events')),
 'cpu_stat':read(pathlib.Path('/sys/fs/cgroup/cpu.stat')),'memory_current':read(pathlib.Path('/sys/fs/cgroup/memory.current')),
 'pids_current':read(pathlib.Path('/sys/fs/cgroup/pids.current'))}))
'''
start=time.monotonic()
cp=subprocess.run(['docker','exec',container,'python3','-c',code],capture_output=True,text=True,timeout=8)
name='proc-'+datetime.datetime.now(datetime.timezone.utc).strftime('%H%M%S')+'.json'
save(root/name,{'kind':'read-only diagnostic exec, not gate execution','container':container,
 'returncode':cp.returncode,'elapsed_seconds':time.monotonic()-start,
 'stdout':json.loads(cp.stdout) if cp.returncode==0 else cp.stdout,'stderr':cp.stderr})
print(name,cp.returncode)
