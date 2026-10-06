"""Synthetic positional retrieval control, separate from the one J001 trial."""
import asyncio, json, sys
from pathlib import Path
import httpx
from diagnostic_capture import install, save
HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE / 'repaired-workshop'))
from workshop import providers

POSITIONS = ['beginning','early_middle','middle','late_middle','end']
FACTS = dict(zip(POSITIONS, ['SABLE-731','CEDAR-428','MICA-962','ORBIT-315','LILAC-684']))
SCHEMA = {'type':'object','properties':{p:{'type':'string'} for p in POSITIONS},
          'required':POSITIONS,'additionalProperties':False}
SYSTEM = 'You are the bounded planner agent inside Nix Workshop Hive Build Mode. Follow the role contract exactly.'

def prompt(lines):
    chunks = ['Diagnostic retrieval only. Copy the identifier for each labeled sentinel into the matching JSON field. If unavailable, use UNKNOWN. Ordinary ledger entries are irrelevant.\n']
    for i, position in enumerate(POSITIONS):
        chunks.append(f'\nSENTINEL FACT [{position}]: identifier = {FACTS[position]}\n')
        if i < 4:
            chunks.extend(f'Ledger record {i*lines+j:04d}: shelf amber holds neutral sample; inspection remains pending.\n' for j in range(lines))
    chunks.append('\nReturn JSON only with fields beginning, early_middle, middle, late_middle, end; copy the sentinel identifiers exactly.\n')
    return ''.join(chunks)

async def main(label, lines):
    folder = HERE / 'evidence/sentinels' / label
    folder.mkdir(parents=True, exist_ok=False)
    text = prompt(lines)
    (folder / 'prompt.txt').write_bytes(text.encode())
    restore = install(providers, folder / 'wire')
    try:
        result = await providers.ollama_chat('qwen2.5-coder:14b', [{'role':'user','content':text}], SYSTEM,
                     response_format=SCHEMA, temperature=0.1, max_output_tokens=2048)
    finally: restore()
    try: parsed = json.loads(result['text'])
    except ValueError: parsed = {}
    save(folder / 'result.json', {**result,'expected':FACTS,'matches':{p:parsed.get(p)==FACTS[p] for p in POSITIONS}})
    with httpx.Client(trust_env=False) as client: save(folder / 'runtime-ps.json', client.get('http://127.0.0.1:11434/api/ps').json())
    print(json.dumps(result), flush=True)

if __name__=='__main__': asyncio.run(main(sys.argv[1],int(sys.argv[2])))
