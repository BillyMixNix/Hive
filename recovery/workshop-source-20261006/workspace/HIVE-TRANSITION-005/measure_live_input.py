"""Post-trial render/token accounting only; no generated completions."""
import json,re,subprocess,sys
from pathlib import Path
import httpx
sys.dont_write_bytecode=True
from bootstrap import HERE,save
root=HERE/'evidence/live-diagnostic';rows=[]
# This endpoint's render-only behavior was established in TRANSITION-002/003.
# Do not invoke this script unless the preserved local runtime still supports it.
with httpx.Client(timeout=60,trust_env=False) as client:
 for folder in sorted((root/'wire').iterdir()):
  body=json.loads((folder/'wire-request.json').read_text())
  chunks=[json.loads(x) for x in (folder/'response.ndjson').read_text().splitlines()]
  terminal=next((x for x in reversed(chunks) if x.get('done')),None)
  if terminal is None:
   rows.append({'call':folder.name,'known_sent':True,'model_visible':'UNKNOWN; no completed model response',
       'provider_errors':[x['error'] for x in chunks if x.get('error')]})
   continue
  response=client.post('http://127.0.0.1:11434/api/chat',json={**body,'_debug_render_only':True})
  response.raise_for_status();reply=response.json()
  assert '_debug_info' in reply
  rendered=reply['_debug_info']['rendered_template']
  cmd="Get-CimInstance Win32_Process | Where-Object Name -eq 'llama-server.exe' | Select-Object -ExpandProperty CommandLine"
  processes=subprocess.check_output(['powershell','-NoProfile','-Command',cmd],text=True)
  ports=re.findall(r'--port (\d+)',processes);assert len(ports)==1
  tokenized=client.post('http://127.0.0.1:'+ports[0]+'/tokenize',json={'content':rendered,'add_special':True})
  tokenized.raise_for_status();tokens=tokenized.json()['tokens']
  (folder/'rendered.txt').write_text(rendered,encoding='utf-8');save(folder/'render-only-response.json',reply)
  save(folder/'rendered-token-ids.json',tokens)
  rows.append({'call':folder.name,'rendered_tokens':len(tokens),'provider_input_tokens':terminal['prompt_eval_count'],
   'full_input_count_matches':len(tokens)==terminal['prompt_eval_count'],'context':body['options']['num_ctx'],
   'truncate':body.get('truncate'),'output_cap':body['options']['num_predict'],
   'full_output_cap_slack':body['options']['num_ctx']-len(tokens)-body['options']['num_predict']})
save(HERE/'evidence/live-input-measurements.json',rows)
print(json.dumps(rows,indent=2))
