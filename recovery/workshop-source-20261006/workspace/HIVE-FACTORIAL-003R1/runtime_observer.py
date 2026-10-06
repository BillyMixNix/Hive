"""Evidence-only request/stream/resource capture. No runtime tuning."""
import asyncio,contextvars,json,queue,shutil,subprocess,threading,time
from datetime import datetime,timezone
from pathlib import Path
import httpx
from common import HERE,save,sha,OUTPUT_LIMITS
OUT=HERE/'evidence/runtime'
CURRENT=contextvars.ContextVar('observed_call',default=None)
def stamp():return datetime.now(timezone.utc).isoformat()
def snapshot(label):
 row={'label':label,'started_at':stamp(),'monotonic_start':time.monotonic()}
 script="""$os=Get-CimInstance Win32_OperatingSystem; $mem=Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory; [ordered]@{time_utc=[DateTime]::UtcNow.ToString('o');host=[ordered]@{total_physical_kib=$os.TotalVisibleMemorySize;free_physical_kib=$os.FreePhysicalMemory;total_virtual_kib=$os.TotalVirtualMemorySize;free_virtual_kib=$os.FreeVirtualMemory;available_bytes=$mem.AvailableBytes;committed_bytes=$mem.CommittedBytes;commit_limit_bytes=$mem.CommitLimit};related_processes=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(ollama|llama-server|vmmem|com.docker.backend)' } | Select-Object Name,ProcessId,ParentProcessId,WorkingSetSize,PrivatePageCount,UserModeTime,KernelModeTime,CommandLine)} | ConvertTo-Json -Depth 5"""
 try:
  cp=subprocess.run(['powershell','-NoProfile','-Command',script],capture_output=True,text=True,timeout=25)
  row['host_memory']={'exit_code':cp.returncode,'data':json.loads(cp.stdout),'stderr':cp.stderr}
 except Exception as exc:row['host_memory']={'error':str(exc)}
 try:
  cmd=[shutil.which('nvidia-smi') or 'nvidia-smi','--query-gpu=index,name,driver_version,memory.total,memory.used,memory.free','--format=csv,noheader,nounits']
  cp=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
  row['gpu_memory']={'command':cmd,'units':'MiB','exit_code':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr}
 except Exception as exc:row['gpu_memory']={'error':str(exc)}
 with httpx.Client(timeout=5,trust_env=False) as client:
  for endpoint in ('/api/ps','/api/version'):
   try:
    response=client.get('http://127.0.0.1:11434'+endpoint);response.raise_for_status();row[endpoint]=response.json()
   except Exception as exc:row[endpoint]={'error':str(exc)}
 try:
  cp=subprocess.run([shutil.which('docker') or 'docker','ps','--no-trunc','--format','{{json .}}'],capture_output=True,text=True,timeout=10)
  row['docker']={'exit_code':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr}
 except Exception as exc:row['docker']={'error':str(exc)}
 row['finished_at']=stamp();save(OUT/(label+'.json'),row);return row

class Monitor:
 def __init__(self):self.queue=queue.Queue();self.thread=threading.Thread(target=self.run,daemon=True);self.n=0
 def start(self):self.thread.start()
 def mark(self,label):self.queue.put(label)
 def run(self):
  while True:
   try:label=self.queue.get(timeout=30)
   except queue.Empty:label='periodic'
   if label is None:return
   self.n+=1;snapshot(f'{self.n:04d}-{label}')
 def stop(self):self.queue.put(None);self.thread.join(timeout=55)

def install(provider,monitor):
 real_client=httpx.AsyncClient;original=provider.ollama_chat;calls=[]
 class Tee(httpx.AsyncByteStream):
  def __init__(self,inner,folder,row):self.inner,self.folder,self.row=inner,folder,row
  async def __aiter__(self):
   try:
    with (self.folder/'response.ndjson').open('xb') as out:
     async for chunk in self.inner:
      if 'first_stream_bytes_at' not in self.row:self.row['first_stream_bytes_at']=stamp()
      out.write(chunk);out.flush();yield chunk
    self.row['stream_complete']=True
   except BaseException as exc:
    self.row['stream_error']={'type':type(exc).__name__,'message':str(exc)};raise
   finally:
    self.row.update(ended_at=stamp(),elapsed_seconds=time.monotonic()-self.row['monotonic_start'])
    save(self.folder/'transport.json',self.row);monitor.mark(self.row['resource_label']+'-end')
  async def aclose(self):await self.inner.aclose()
 class Recorder(httpx.AsyncHTTPTransport):
  async def handle_async_request(self,request):
   if request.url.path!='/api/chat':return await super().handle_async_request(request)
   call=CURRENT.get();assert call is not None
   body=json.loads(request.content)
   assert str(request.url)=='http://127.0.0.1:11434/api/chat'
   assert body['model']==call['model'] and body['stream'] is True and body['truncate'] is False
   assert body['options']=={'temperature':0.1,'num_predict':OUTPUT_LIMITS[call['role']],'num_ctx':12288}
   attempt=len(call['attempts'])+1
   folder=OUT/'calls'/f"{call['number']:02d}-{call['role']}"/f'attempt-{attempt:02d}';folder.mkdir(parents=True,exist_ok=False)
   (folder/'wire-request.json').write_bytes(request.content)
   label=f"call-{call['number']:02d}-attempt-{attempt:02d}"
   row={'attempt':attempt,'call':call['number'],'role':call['role'],'started_at':stamp(),
        'monotonic_start':time.monotonic(),'endpoint':str(request.url),'request_sha256':sha(folder/'wire-request.json'),
        'request_bytes':len(request.content),'resource_label':label}
   call['attempts'].append(row);save(folder/'transport.json',row);monitor.mark(label+'-start')
   try:
    response=await super().handle_async_request(request)
    row.update(http_status=response.status_code,headers_at=stamp(),headers_elapsed_seconds=time.monotonic()-row['monotonic_start'])
    save(folder/'transport.json',row);response.stream=Tee(response.stream,folder,row);return response
   except BaseException as exc:
    row.update(transport_error={'type':type(exc).__name__,'message':str(exc)},ended_at=stamp(),elapsed_seconds=time.monotonic()-row['monotonic_start'])
    save(folder/'transport.json',row);monitor.mark(label+'-end');raise
 def client(*args,**kwargs):return real_client(*args,transport=Recorder(),**kwargs)
 async def observed(model,messages,instructions,*args,**kwargs):
  assert model in ('qwen2.5-coder:14b','qwen3:8b')
  role=instructions.split('bounded ',1)[1].split(' agent',1)[0]
  assert kwargs['temperature']==0.1 and kwargs['max_output_tokens']==OUTPUT_LIMITS[role] and kwargs['context_window']==12288
  call={'number':len(calls)+1,'role':role,'model':model,'started_at':stamp(),'monotonic_start':time.monotonic(),
        'provider_settings':{k:kwargs[k] for k in ('temperature','max_output_tokens','context_window','total_timeout')},'attempts':[]}
  calls.append(call);folder=OUT/'calls'/f"{call['number']:02d}-{role}";save(folder/'call.json',call)
  token=CURRENT.set(call)
  print(f"Model call {call['number']}: {role}; unchanged provider/context settings.",flush=True)
  try:
   result=await original(model,messages,instructions,*args,**kwargs)
   call.update(status='completed',input_tokens=result.get('input_tokens'),output_tokens=result.get('output_tokens'))
   save(folder/'provider-result.json',result);(folder/'response.txt').write_text(result['text'],encoding='utf-8')
   return result
  except Exception as exc:
   call.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)})
   raise
  finally:
   call.update(ended_at=stamp(),elapsed_seconds=time.monotonic()-call['monotonic_start'])
   save(folder/'call.json',call);save(OUT/'calls.json',calls);CURRENT.reset(token)
   monitor.mark(f"call-{call['number']:02d}-finished")
   print(f"Model call {call['number']}: {call['status']} after {call['elapsed_seconds']:.3f}s; HTTP attempts {len(call['attempts'])}.",flush=True)
 provider.httpx.AsyncClient=client;provider.ollama_chat=observed
 def restore():provider.httpx.AsyncClient=real_client;provider.ollama_chat=original
 return restore
