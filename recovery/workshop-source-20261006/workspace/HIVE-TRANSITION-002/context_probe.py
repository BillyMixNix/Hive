"""Synthetic transport intervention; never a J001 candidate attempt."""
import asyncio, json, sys
from pathlib import Path
import httpx
from diagnostic_capture import install, save
HERE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(HERE/'repaired-workshop'))
from workshop import providers
from sentinel_probe import FACTS

async def main(label, context):
    folder=HERE/'evidence/sentinels'/label
    folder.mkdir(parents=True,exist_ok=False)
    body=json.loads((HERE/'evidence/sentinels/long-default/wire/01/wire-request.json').read_bytes())
    body['truncate']=False
    if context: body['options']['num_ctx']=context
    restore=install(providers,folder/'wire')
    try:
        try:
            result=await providers._ollama_chat_once(body)
            try: parsed=json.loads(result['text'])
            except ValueError: parsed={}
            result.update(expected=FACTS,matches={k:parsed.get(k)==v for k,v in FACTS.items()})
        except Exception as exc:
            result={'exception':type(exc).__name__,'message':str(exc)}
    finally: restore()
    save(folder/'result.json',result)
    with httpx.Client(trust_env=False) as client: save(folder/'runtime-ps.json',client.get('http://127.0.0.1:11434/api/ps').json())
    print(json.dumps(result),flush=True)

if __name__=='__main__': asyncio.run(main(sys.argv[1],int(sys.argv[2])))
