"""One non-task readiness request through the unchanged T005 provider."""
import asyncio,hashlib,importlib.util,json,os,shutil,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
import httpx
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
PRIOR=HERE.parent/'HIVE-TRANSITION-005'
SOURCE=PRIOR/'repaired-workshop'
EVIDENCE=HERE/'evidence'
MODEL='qwen2.5-coder:14b'

def stamp():return datetime.now(timezone.utc).isoformat()
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(p,v):
 p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(v,indent=2,ensure_ascii=False,default=str)+'\n',encoding='utf-8')
def source_manifest():
 return {p.relative_to(SOURCE).as_posix():sha(p) for p in SOURCE.rglob('*') if p.is_file() and not p.is_symlink()}
def shell_json(script):
 cp=subprocess.run(['powershell','-NoProfile','-Command',script],capture_output=True,text=True,timeout=25)
 try:return {'exit_code':cp.returncode,'data':json.loads(cp.stdout),'stderr':cp.stderr.strip()}
 except ValueError:return {'exit_code':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr.strip()}
def memory_sample():
 return shell_json("""$os=Get-CimInstance Win32_OperatingSystem; $mem=Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory; [ordered]@{time_utc=[DateTime]::UtcNow.ToString('o');host=[ordered]@{total_physical_kib=$os.TotalVisibleMemorySize;free_physical_kib=$os.FreePhysicalMemory;total_virtual_kib=$os.TotalVirtualMemorySize;free_virtual_kib=$os.FreeVirtualMemory;available_bytes=$mem.AvailableBytes;committed_bytes=$mem.CommittedBytes;commit_limit_bytes=$mem.CommitLimit};related_processes=@(Get-Process ollama*,llama-server*,vmmem*,com.docker.backend -ErrorAction SilentlyContinue | Select-Object ProcessName,Id,WorkingSet64,PrivateMemorySize64,CPU)} | ConvertTo-Json -Depth 5""")
def snapshot(label):
 result={'started_at':stamp(),'host_memory':memory_sample()}
 executable=shutil.which('nvidia-smi')
 if executable:
  cmd=[executable,'--query-gpu=index,name,driver_version,memory.total,memory.used,memory.free','--format=csv,noheader,nounits']
  cp=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
  result['gpu_memory']={'command':cmd,'units':'MiB as reported by nvidia-smi; dedicated GPU memory, not shared host RAM','exit_code':cp.returncode,'stdout':cp.stdout,'stderr':cp.stderr}
 else:result['gpu_memory']={'unavailable':'nvidia-smi not installed; no estimate substituted'}
 with httpx.Client(timeout=10,trust_env=False) as client:
  for endpoint in ('/api/ps','/api/version'):
   try:
    response=client.get('http://127.0.0.1:11434'+endpoint);response.raise_for_status()
    result[endpoint]=response.json()
   except Exception as exc:result[endpoint]={'error':type(exc).__name__+': '+str(exc)}
 result['finished_at']=stamp();save(EVIDENCE/(label+'.json'),result)
 return result

class Tee(httpx.AsyncByteStream):
 def __init__(self,inner,path):self.inner,self.path=inner,path
 async def __aiter__(self):
  with self.path.open('xb') as output:
   async for chunk in self.inner:
    output.write(chunk);output.flush();yield chunk
 async def aclose(self):await self.inner.aclose()

async def main():
 EVIDENCE.mkdir(exist_ok=False)
 before_source=source_manifest();save(EVIDENCE/'hive-files-before.json',before_source)
 # Only provider configuration/system role is extracted. No historical task,
 # candidate, frozen tests or historical planner schema is reused.
 previous=json.loads((PRIOR/'evidence/live-diagnostic/wire/01/wire-request.json').read_text())
 options=previous['options'];system=previous['messages'][0]['content']
 assert previous['model']==MODEL and previous['stream'] is True and previous['truncate'] is False
 assert options=={'temperature':0.1,'num_predict':2048,'num_ctx':12288}
 spec=importlib.util.spec_from_file_location('readiness_provider',SOURCE/'workshop/providers.py')
 provider=importlib.util.module_from_spec(spec);spec.loader.exec_module(provider)
 assert provider.ollama_base()=='http://127.0.0.1:11434'
 assert provider.OLLAMA_TOTAL_GENERATION_TIMEOUT==900 and provider.OLLAMA_CHAT_TIMEOUT==900
 expected=json.loads((PRIOR/'evidence/live-diagnostic/preflight.json').read_text())['model']
 with httpx.Client(timeout=15,trust_env=False) as client:
  response=client.get('http://127.0.0.1:11434/api/tags');response.raise_for_status()
  inventory=next(x for x in response.json()['models'] if x['name']==MODEL)
  assert inventory['digest']==expected['digest'] and inventory['size']==expected['bytes']
  response=client.post('http://127.0.0.1:11434/api/show',json={'model':MODEL});response.raise_for_status()
  info=response.json()
  save(EVIDENCE/'model-identity.json',{'inventory':inventory,'parameters':info.get('parameters'),
       'details':info.get('details'),'native_context':{k:v for k,v in info.get('model_info',{}).items() if k.endswith('.context_length')}})
 prompt='This is a non-task model-runtime readiness check. Return exactly one complete JSON object with status equal to ready and marker equal to runtime-check. No software task, code, file operation, or tool use is requested.'
 schema={'type':'object','properties':{'status':{'type':'string','enum':['ready']},
       'marker':{'type':'string','enum':['runtime-check']}},'required':['status','marker'],'additionalProperties':False}
 config={'study':'HIVE-MODEL-RUNTIME-READINESS-001','model':MODEL,'endpoint':provider.ollama_base()+'/api/chat',
  'options':options,'stream':True,'truncate':False,'system':system,'prompt':prompt,'format':schema,
  'provider_file_sha256':sha(SOURCE/'workshop/providers.py'),
  'output_role_selection':'T005 failed planner call: existing 2048 output cap; not the 6000 worker cap',
  'normal_total_timeout_seconds':900,'normal_read_timeout_seconds':900,'existing_max_http_attempts':2,
  'stop_sequences':'not supplied in request, unchanged; model parameters captured separately',
  'unspecified_options':'keep_alive, seed, num_gpu, num_batch, top_p etc remain unspecified as in T005',
  'intentional_non_task_changes':['user prompt','diagnostic JSON response schema'],
  'environment_observed':{k:os.environ.get(k) for k in ('OLLAMA_BASE_URL','OLLAMA_CONTEXT_LENGTH','OLLAMA_NUM_PARALLEL','OLLAMA_MAX_LOADED_MODELS','OLLAMA_KEEP_ALIVE','OLLAMA_GPU_OVERHEAD','CUDA_VISIBLE_DEVICES')},
  'environment_limit':'Client-process variables only; inherited environment of the already-running server is not exposed by the API. No environment settings changed.'}
 save(EVIDENCE/'configuration.json',config)
 attempts=[];real_client=httpx.AsyncClient
 class Recorder(httpx.AsyncHTTPTransport):
  async def handle_async_request(self,request):
   if request.url.path!='/api/chat':return await super().handle_async_request(request)
   assert str(request.url)==config['endpoint']
   body=json.loads(request.content)
   assert body['options']==options and body['truncate'] is False and body['format']==schema
   assert body['messages']==[{'role':'system','content':system},{'role':'user','content':prompt}]
   number=len(attempts)+1;folder=EVIDENCE/'wire'/f'{number:02d}';folder.mkdir(parents=True,exist_ok=False)
   (folder/'wire-request.json').write_bytes(request.content)
   row={'attempt':number,'started_at':stamp(),'monotonic_start':time.monotonic(),
       'endpoint':str(request.url),'request_bytes':len(request.content),'request_sha256':sha(folder/'wire-request.json')}
   attempts.append(row);save(folder/'transport.json',row)
   try:
    response=await super().handle_async_request(request)
    row.update(http_status=response.status_code,headers_at=stamp(),headers_elapsed_seconds=time.monotonic()-row['monotonic_start'])
    save(folder/'transport.json',row);response.stream=Tee(response.stream,folder/'response.ndjson')
    return response
   except BaseException as exc:
    row.update(transport_error=type(exc).__name__+': '+str(exc),ended_at=stamp(),elapsed_seconds=time.monotonic()-row['monotonic_start'])
    save(folder/'transport.json',row);raise
 def client(*args,**kwargs):return real_client(*args,transport=Recorder(),**kwargs)
 before=snapshot('before')
 provider.httpx.AsyncClient=client
 start=time.monotonic();started_at=stamp();output=None;error=None
 print('Starting one non-task provider request; parameters unchanged, 900-second limit.',flush=True)
 try:
  output=await provider.ollama_chat(MODEL,[{'role':'user','content':prompt}],system,
    response_format=schema,temperature=options['temperature'],max_output_tokens=options['num_predict'],
    context_window=options['num_ctx'],total_timeout=900.0)
 except Exception as exc:error={'type':type(exc).__name__,'message':str(exc)}
 finally:
  elapsed=time.monotonic()-start;provider.httpx.AsyncClient=real_client
  after=snapshot('after')
 terminals=[];provider_errors=[]
 for folder in sorted((EVIDENCE/'wire').glob('*')):
  stream=folder/'response.ndjson'
  chunks=[json.loads(line) for line in stream.read_text().splitlines() if line] if stream.exists() else []
  terminals.extend(x for x in chunks if x.get('done'))
  provider_errors.extend({'attempt':folder.name,'error':x['error']} for x in chunks if x.get('error'))
 parsed=None
 if output:
  (EVIDENCE/'response.txt').write_text(output['text'],encoding='utf-8')
  try:parsed=json.loads(output['text'])
  except ValueError:pass
 complete=bool(output and terminals and terminals[-1].get('done_reason')=='stop'
               and parsed=={'status':'ready','marker':'runtime-check'}
               and output.get('input_tokens',0)>0 and output.get('output_tokens',0)>0)
 after_source=source_manifest();save(EVIDENCE/'hive-files-after.json',after_source)
 unchanged=before_source==after_source
 result={'study':config['study'],'started_at':started_at,'finished_at':stamp(),'elapsed_provider_seconds':elapsed,
   'complete_response':complete,'within_normal_900_second_limit':elapsed<=900,
   'ready':complete and elapsed<=900 and unchanged,'output':output,'parsed_response':parsed,
   'provider_error':error,'provider_http_errors':provider_errors,'logical_requests':1,'http_attempts':len(attempts),
   'terminal_metadata':terminals,'hive_unchanged':unchanged,'hive_files_checked':len(before_source),
   'no_task_information_supplied':True,'model_parameters_changed':False}
 save(EVIDENCE/'result.json',result)
 print(json.dumps(result,indent=2),flush=True)
 if not unchanged:raise RuntimeError('Hive files changed during diagnostic; inspect manifests')

if __name__=='__main__':asyncio.run(main())
