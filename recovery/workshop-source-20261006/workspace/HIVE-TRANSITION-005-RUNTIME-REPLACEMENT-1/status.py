"""Read already-written evidence; does not query or influence the runtime."""
import json,time
from pathlib import Path
from datetime import datetime,timezone
P=Path(__file__).resolve().parent/'evidence'
def load(p):
 try:return json.loads(p.read_text())
 except (ValueError,OSError):return {}
out={'at':datetime.now(timezone.utc).isoformat(),'calls':[]}
for folder in sorted((P/'runtime/calls').glob('*')):
 c=load(folder/'call.json')
 row={k:c.get(k) for k in ('number','role','started_at','ended_at','status','elapsed_seconds','input_tokens','output_tokens','error')}
 if not c.get('ended_at'):row['currently_elapsed_seconds']=round(time.monotonic()-c.get('monotonic_start',time.monotonic()),1)
 row['attempts']=[]
 for attempt in sorted(folder.glob('attempt-*')):
  t=load(attempt/'transport.json');row['attempts'].append(t)
  stream=attempt/'response.ndjson'
  row['attempts'][-1]['captured_bytes']=stream.stat().st_size if stream.exists() else 0
 out['calls'].append(row)
samples=sorted((P/'runtime').glob('[0-9]*.json'))
if samples:
 s=load(samples[-1]);h=s.get('host_memory',{}).get('data',{}).get('host',{})
 out['latest_resource']={'file':str(samples[-1]),'at':s.get('started_at'),'free_host_gib':h.get('free_physical_kib',0)/1024**2,
   'free_virtual_gib':h.get('free_virtual_kib',0)/1024**2,'gpu':s.get('gpu_memory',{}).get('stdout'),
   'residency':s.get('/api/ps'),'processes':s.get('host_memory',{}).get('data',{}).get('related_processes')}
out['result']=load(P/'live-diagnostic/raw_results.json')
print(json.dumps(out,indent=2))
