"""No model generation: reconstruct historical serialization, render, tokenize."""
import asyncio, hashlib, json, re, subprocess, sys
from pathlib import Path
import httpx
from diagnostic_capture import save
HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'HIVE-TRANSITION-001'
sys.dont_write_bytecode = True
sys.path.insert(0, str(PRIOR / 'repaired-workshop'))
from workshop import providers

def runner_url():
    output = subprocess.check_output(['powershell','-NoProfile','-Command',
        "Get-CimInstance Win32_Process | Where-Object Name -eq 'llama-server.exe' | Select-Object -ExpandProperty CommandLine"], text=True)
    ports = re.findall(r'--port (\d+)', output)
    assert len(ports)==1, output
    return 'http://127.0.0.1:' + ports[0]

def main():
    runner = runner_url()
    client = httpx.Client(timeout=120, trust_env=False)
    def tokenize(s):
        r = client.post(runner+'/tokenize',json={'content':s,'add_special':True})
        r.raise_for_status(); return r.json()['tokens']
    def decode(tokens):
        r = client.post(runner+'/detokenize',json={'tokens':tokens}); r.raise_for_status(); return r.json()['content']
    records = []
    inputs = []
    for index in (1,2):
        boundary = json.loads((PRIOR / f'evidence/live-revision2/model-boundary/{index:02d}/request.json').read_text())
        captured = []
        async def fake(body, **kwargs):
            captured.append(body); return {'text':'','input_tokens':0,'output_tokens':0,'raw_id':None}
        providers._ollama_chat_once = fake
        asyncio.run(providers.ollama_chat(boundary['model'],boundary['messages'],boundary['instructions'],**boundary['options']))
        body = captured[0]
        inputs.append((f'historical-planner-{index}',body))
    for label in ('short-default','long-default'):
        p = HERE / f'evidence/sentinels/{label}/wire/01/wire-request.json'
        if p.exists(): inputs.append((label,json.loads(p.read_bytes())))
    # Historical worker size measurement; does not generate worker responses.
    rev1=json.loads((PRIOR/'evidence/live/01-J001-r1-qwen2.5-coder-14b-hive/run.json').read_text())
    for trace in rev1['prompt_trace']:
        if trace['role']=='backend':
            inputs.append(('historical-worker',{'model':'qwen2.5-coder:14b','messages':[
                {'role':'system','content':'You are the bounded backend agent inside Nix Workshop Hive Build Mode. Follow the role contract exactly.'},
                {'role':'user','content':trace['prompt_text']}], 'stream':True, 'options':{'temperature':0.1,'num_predict':6000}}))
            break
    for label,body in inputs:
        folder = HERE / 'evidence/measurements' / label
        folder.mkdir(parents=True, exist_ok=True)
        wire = httpx.Request('POST','http://127.0.0.1:11434/api/chat',json=body).content
        (folder/'reconstructed-wire.json').write_bytes(wire)
        r=client.post('http://127.0.0.1:11434/api/chat',json={**body,'_debug_render_only':True})
        r.raise_for_status(); response=r.json(); save(folder/'render-only-response.json',response)
        rendered=response['_debug_info']['rendered_template']
        (folder/'rendered.txt').write_bytes(rendered.encode())
        tokens=tokenize(rendered)
        keep=4; limit=4096-(4096-keep)//2
        retained=tokens if len(tokens)<=4095 else tokens[:keep]+tokens[keep+len(tokens)-limit:]
        text=decode(retained)
        save(folder/'rendered-token-ids.json',tokens)
        save(folder/'inferred-retained-token-ids.json',retained)
        (folder/'inferred-retained.txt').write_bytes(text.encode())
        user=body['messages'][-1]['content']; system=body['messages'][0]['content']
        row={'label':label,'provenance':'historical wire reconstructed; render-only and tokenize responses newly measured',
             'wire_bytes':len(wire),'user_chars':len(user),'user_tokens':len(tokenize(user)),
             'system_tokens':len(tokenize(system)),'rendered_tokens':len(tokens),
             'wire_json_tokens_not_model_input':len(tokenize(wire.decode())),
             'format_tokens_not_prompt':len(tokenize(json.dumps(body.get('format',{})))),
             'configured_context':4096,'num_predict':body['options']['num_predict'],
             'inferred_retained':len(retained),'remaining_without_shift':4096-len(tokens),
             'critical_facts':{marker:{'in_intended':marker in user,'in_rendered':marker in rendered,'in_inferred_retained':marker in text}
               for marker in ('USER CHANGE REQUEST:','preserve complete UTF-16 surrogate pairs',
                 "Each file must have exactly one worker owner", "use the exact goal 'no change needed'",
                 'TRUE ROLE / WRITE CONSTRAINTS', 'PREVIOUS PLAN REJECTED BEFORE WORKER EXECUTION:',
                 'assigned to both backend and tests','public static final int MAX_LINE_CHARS = 240;',
                 'public static String boundLine(String line)')}}
        if 'USER CHANGE REQUEST:' in user:
            markers=['REPOSITORY MAP (','REPOSITORY-DERIVED IMPLEMENTATION FACTS (','USER CHANGE REQUEST:',
                     'IMMUTABLE INTENT OBLIGATIONS','HOST-AUTHORIZED TASK WRITE FILES','TRUE ROLE / WRITE CONSTRAINTS',
                     'Return JSON only:', 'PREVIOUS PLAN REJECTED BEFORE WORKER EXECUTION:']
            offsets=sorted((user.index(m),m) for m in markers if m in user)
            row['sections']=[{'name':m,'start_char':start,'end_char':offsets[i+1][0] if i+1<len(offsets) else len(user),
                'standalone_tokens':len(tokenize(user[start:offsets[i+1][0] if i+1<len(offsets) else len(user)])),
                'start_token_approx':len(tokenize(user[:start]))} for i,(start,m) in enumerate(offsets)]
        save(folder/'measurement.json',row); records.append(row)
        print(label, len(tokens),'tokens;',len(retained),'retained by source algorithm',flush=True)
    save(HERE/'evidence/token-measurements.json',records)

if __name__=='__main__': main()
