"""After the sole live trial: measure accepted requests without generation."""
import json, hashlib
from pathlib import Path
import httpx
from diagnostic_capture import save
from measure_inputs import runner_url
HERE=Path(__file__).resolve().parent

def main():
    root=HERE/'evidence/live-diagnostic'
    # Require a terminal candidate-trial outcome before measurement.
    outcomes=json.loads((root/'raw_results.json').read_text())
    assert len(outcomes)==1
    rows=[]
    with httpx.Client(timeout=120,trust_env=False) as client:
        for folder in sorted((root/'wire').iterdir()):
            body=json.loads((folder/'wire-request.json').read_bytes())
            response=client.post('http://127.0.0.1:11434/api/chat',json={**body,'_debug_render_only':True})
            response.raise_for_status(); rendered=response.json()['_debug_info']['rendered_template']
            url=runner_url()
            token_response=client.post(url+'/tokenize',json={'content':rendered,'add_special':True})
            token_response.raise_for_status(); tokens=token_response.json()['tokens']
            (folder/'rendered.txt').write_bytes(rendered.encode())
            save(folder/'render-only-response.json',response.json())
            save(folder/'rendered-token-ids.json',tokens)
            chunks=[json.loads(line) for line in (folder/'response.ndjson').read_text().splitlines() if line]
            raw=''.join(c.get('message',{}).get('content','') for c in chunks)
            (folder/'raw-response.txt').write_bytes(raw.encode())
            terminal=next((c for c in reversed(chunks) if c.get('done')),None)
            try: parsed=json.loads(raw)
            except ValueError: parsed=None
            user=body['messages'][-1]['content']
            rows.append({'http_attempt':folder.name,'http_status':json.loads((folder/'http-response.json').read_text())['status_code'],
                'wire_sha256':hashlib.sha256((folder/'wire-request.json').read_bytes()).hexdigest(),
                'prompt_sha256':hashlib.sha256(user.encode()).hexdigest(),
                'intended_user_tokens':len(client.post(url+'/tokenize',json={'content':user,'add_special':True}).json()['tokens']),
                'rendered_tokens':len(tokens),'reported_tokens':terminal.get('prompt_eval_count') if terminal else None,
                'full_token_count_matches':terminal.get('prompt_eval_count')==len(tokens) if terminal else None,
                'remaining_after_full_output_cap':body['options']['num_ctx']-len(tokens)-body['options']['num_predict'],
                'options':body['options'],'truncate':body.get('truncate'),'terminal':terminal,
                'error':next((c.get('error') for c in chunks if c.get('error')),None),
                'parser_result':'object' if isinstance(parsed,dict) else 'no JSON object',
                'facts':{m:{'in_sent_user':m in user,'in_rendered':m in rendered} for m in
                    ('Each file must have exactly one worker owner',"exact goal 'no change needed'",
                     'preserve complete UTF-16 surrogate pairs','assigned to both backend and tests',
                     'public static final int MAX_LINE_CHARS = 240;','public static String boundLine(String line)')}})
            print(folder.name,'rendered',len(tokens),'reported',rows[-1]['reported_tokens'],flush=True)
    save(HERE/'evidence/live-input-measurements.json',rows)

if __name__=='__main__': main()
