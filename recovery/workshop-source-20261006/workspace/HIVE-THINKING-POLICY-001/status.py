"""Read-only monitoring; never touches active execution or its configuration."""
from common import *

def main():
    results=read(HERE/'evidence/raw-results.json') if (HERE/'evidence/raw-results.json').exists() else []
    print('COMPLETED',len(results),'/6',[(r['historical_cell'],r['primary_outcome']) for r in results])
    folders=sorted((HERE/'evidence/trials').glob('*'))
    if not folders:return
    folder=folders[-1];calls=sorted((folder/'runtime/calls').glob('*'))
    if calls:
        call=calls[-1];row=read(call/'call.json')
        print('LATEST',folder.name,call.name,'status',row.get('status','running'),'elapsed',round((datetime.now(timezone.utc)-datetime.fromisoformat(row['started_at'])).total_seconds(),1))
        attempts=sorted(call.glob('attempt-*'))
        if attempts:
            attempt=attempts[-1];tr=read(attempt/'transport.json');wire=read(attempt/'wire-request.json')
            print('ATTEMPT',attempt.name,'HTTP',tr.get('http_status'),'think',wire.get('think','OMITTED'))
            stream=attempt/'response.ndjson';channels={'thinking':0,'content':0};done=False;last=None
            if stream.exists():
                for line in stream.read_text(encoding='utf-8',errors='replace').splitlines():
                    try:c=json.loads(line)
                    except ValueError:continue
                    for k in channels:channels[k]+=len(c.get('message',{}).get(k,''))
                    done|=bool(c.get('done'));last=c.get('created_at',last)
            print('CHANNEL_CHARACTERS',channels,'done',done,'last',last)
    snaps=[]
    for p in (folder/'runtime').glob('*.json'):
        try:r=read(p)
        except ValueError:continue
        if isinstance(r,dict) and 'host_memory' in r:snaps.append(r)
    if snaps:
        r=max(snaps,key=lambda x:x['started_at']);h=r['host_memory'].get('data',{}).get('host',{})
        print('RESOURCE',r['started_at'],'host_free_GiB',round(h.get('free_physical_kib',0)/1024**2,3),
              'virtual_free_GiB',round(h.get('free_virtual_kib',0)/1024**2,3),'GPU',r.get('gpu_memory',{}).get('stdout','').strip())
    if (HERE/'evidence/STOPPED.json').exists():print('STOPPED',read(HERE/'evidence/STOPPED.json'))
    if (HERE/'evidence/COMPLETED.json').exists():print('STUDY COMPLETE')

if __name__=='__main__':main()
