"""Measure completed live requests with render-only/tokenization; no generation."""
import hashlib,json,re,subprocess,sys
from pathlib import Path
import httpx
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'tooling/python'))
from jsonschema import Draft202012Validator
from setup_study import save

def runner_url():
    output=subprocess.check_output(['powershell','-NoProfile','-Command',
      "Get-CimInstance Win32_Process | Where-Object Name -eq 'llama-server.exe' | Select-Object -ExpandProperty CommandLine"],text=True)
    ports=re.findall(r'--port (\d+)',output);assert len(ports)==1
    return 'http://127.0.0.1:'+ports[0]

def main():
    root=HERE/'evidence/live-diagnostic'
    result=json.loads((root/'raw_results.json').read_text());assert len(result)==1
    rows=[]
    with httpx.Client(timeout=180,trust_env=False) as c:
        for folder in sorted((root/'wire').iterdir()):
            body=json.loads((folder/'wire-request.json').read_bytes())
            resp=c.post('http://127.0.0.1:11434/api/chat',json={**body,'_debug_render_only':True});resp.raise_for_status()
            rendered=resp.json()['_debug_info']['rendered_template'];url=runner_url()
            token=c.post(url+'/tokenize',json={'content':rendered,'add_special':True});token.raise_for_status()
            ids=token.json()['tokens']
            (folder/'rendered.txt').write_bytes(rendered.encode());save(folder/'render-only-response.json',resp.json())
            save(folder/'rendered-token-ids.json',ids)
            chunks=[json.loads(l) for l in (folder/'response.ndjson').read_text().splitlines() if l]
            raw=''.join(x.get('message',{}).get('content','') for x in chunks)
            (folder/'raw-response.txt').write_bytes(raw.encode())
            terminal=next((x for x in reversed(chunks) if x.get('done')),None)
            try:parsed=json.loads(raw)
            except ValueError:parsed=None
            schema_errors=[e.message for e in Draft202012Validator(body['format']).iter_errors(parsed)] if parsed is not None else ['no JSON object']
            rows.append({'http_attempt':folder.name,'status':json.loads((folder/'http-response.json').read_text())['status_code'],
              'rendered_tokens':len(ids),'provider_input_tokens':terminal.get('prompt_eval_count') if terminal else None,
              'full_input_count_matches':terminal.get('prompt_eval_count')==len(ids) if terminal else None,
              'schema_valid':not schema_errors,'schema_errors':schema_errors,'terminal':terminal,
              'context':body['options'].get('num_ctx'),'truncate':body.get('truncate'),
              'full_output_cap_slack':body['options']['num_ctx']-len(ids)-body['options']['num_predict'],
              'prompt_sha256':hashlib.sha256(body['messages'][-1]['content'].encode()).hexdigest(),
              'worker_source_markers':{m:m in rendered for m in ['public static final int MAX_LINE_CHARS = 240;',
                 'public static String boundLine(String line)','CURRENT WORKER CONTRACT']}})
            print(folder.name,'rendered',len(ids),'reported',rows[-1]['provider_input_tokens'],'schema_valid',not schema_errors,flush=True)
    save(HERE/'evidence/live-input-measurements.json',rows)

if __name__=='__main__':main()
