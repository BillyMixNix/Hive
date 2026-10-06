"""Exactly two non-task requests, before production changes. No task/model solutions."""
import asyncio,httpx
from common import *
import runtime_observer as observer

MODEL='qwen3:8b'
DIGEST='500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41'
BASE='http://127.0.0.1:11434'

async def probe(think):
    out=HERE/'evidence/capability'/str(think).lower();out.mkdir(parents=True,exist_ok=False)
    observer.OUT=out/'resources';observer.snapshot('before')
    body={'model':MODEL,'messages':[{'role':'system','content':'This is a non-task transport diagnostic. Return the requested JSON object.'},
        {'role':'user','content':'Compute 17 times 23. Return a JSON object with result as the integer product and diagnostic as the string ready.'}],
        'format':{'type':'object','properties':{'result':{'type':'integer'},'diagnostic':{'type':'string'}},'required':['result','diagnostic'],'additionalProperties':False},
        'stream':True,'think':think,'options':{'temperature':0.1,'num_predict':6000,'num_ctx':12288},'truncate':False}
    payload=json.dumps(body,separators=(',',':')).encode();(out/'wire-request.json').write_bytes(payload)
    row={'model':MODEL,'digest':DIGEST,'think':think,'endpoint':BASE+'/api/chat','deadline_seconds':900,'started_at':stamp(),
        'request_sha256':sha(out/'wire-request.json'),'attempts':1,'thinking_characters':0,'answer_characters':0}
    monitor=observer.Monitor();monitor.start();start=time.monotonic();answer=[]
    async def exchange():
        async with httpx.AsyncClient(timeout=900,trust_env=False) as client:
            async with client.stream('POST',BASE+'/api/chat',content=payload,headers={'Content-Type':'application/json'}) as r:
                row.update(http_status=r.status_code,headers_seconds=time.monotonic()-start)
                r.raise_for_status()
                with (out/'response.ndjson').open('xb') as stream:
                    async for line in r.aiter_lines():
                        if not line:continue
                        stream.write(line.encode()+b'\n');stream.flush();c=json.loads(line)
                        row.setdefault('first_stream_seconds',time.monotonic()-start)
                        for key,label in [('thinking','thinking'),('content','answer')]:
                            text=(c.get('message') or {}).get(key,'')
                            if text:
                                row.setdefault('first_'+label+'_seconds',time.monotonic()-start)
                                row[label+'_characters']+=len(text)
                                if key=='content':answer.append(text)
                        if c.get('done'):row['terminal_metadata']={k:v for k,v in c.items() if k!='message'}
                        if c.get('error'):raise RuntimeError(c['error'])
    try:
        await asyncio.wait_for(exchange(),timeout=900)
        row['answer']=''.join(answer);row['complete']=row.get('terminal_metadata',{}).get('done') is True
        row['structured_response_valid']=json.loads(row['answer'])=={'result':391,'diagnostic':'ready'}
    except Exception as exc:row['error']={'type':type(exc).__name__,'message':str(exc)}
    finally:
        row.update(ended_at=stamp(),elapsed_seconds=time.monotonic()-start)
        save(out/'result.json',row);monitor.stop();observer.snapshot('after')
    event('capability_probe_completed',think=think,result=row)
    return row

async def main():
    assert not (HERE/'evidence/capability/STARTED.json').exists()
    assert manifest(SOURCE)==read(HERE/'evidence/source-before.json'),'Probe must precede production edits'
    with httpx.Client(timeout=15,trust_env=False) as c:
        tags=c.get(BASE+'/api/tags').json();version=c.get(BASE+'/api/version').json()
        show=c.post(BASE+'/api/show',json={'model':MODEL}).json()
    assert next(m['digest'] for m in tags['models'] if m['name']==MODEL)==DIGEST
    save(HERE/'evidence/capability/STARTED.json',{'at':stamp(),'order':[True,False],'policy':'Two non-task probes only; unchanged worker context/output/sampling/deadline; no unload, restart or runtime tuning.'})
    save(HERE/'evidence/capability/model-show.json',show);save(HERE/'evidence/capability/tags.json',tags);save(HERE/'evidence/capability/version.json',version)
    rows=[await probe(True),await probe(False)]
    supported=all(r.get('complete') and r.get('structured_response_valid') and r.get('http_status')==200 and not r.get('error') for r in rows) and rows[0]['thinking_characters']>0 and rows[1]['thinking_characters']==0
    save(HERE/'evidence/capability/result.json',{'supported':supported,'rows':rows,'model':MODEL,'digest':DIGEST,'version':version,
        'template_sha256':hashlib.sha256(show['template'].encode()).hexdigest(),'capabilities':show.get('capabilities'),
        'thinking_metadata':show.get('thinking'),'source_unchanged':manifest(SOURCE)==read(HERE/'evidence/source-before.json')})
    print('CAPABILITY_SUPPORTED='+str(supported),flush=True)

if __name__=='__main__':asyncio.run(main())
