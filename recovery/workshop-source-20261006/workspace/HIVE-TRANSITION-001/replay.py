"""Replay exact historical responses; no model, no synthetic PASS responses."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

HERE = Path(__file__).resolve().parent
PRIOR = Path(r'C:\Users\billy\Documents\Codex\2026-09-13\referenced-chatgpt-conversation-this-is-an\work\HIVE-FACTORIAL-002')
variant = sys.argv[1]
assert variant in {'before', 'after'}
os.environ.pop('OPENAI_API_KEY', None)
sys.dont_write_bytecode = True
sys.path.insert(0, str(PRIOR / 'workshop' if variant == 'before' else HERE / 'repaired-workshop'))
from workshop import hive, external_root

original = json.loads((HERE / 'evidence/ordinal-03/run.json').read_text())
runs = HERE / 'evidence' / f'replay-{variant}' / 'runs'
run_id = uuid.uuid4().hex[:12]
runs.mkdir(parents=True, exist_ok=True)
metadata = external_root.prepare_candidate(
    original['metadata']['external_root']['baseline_root'],
    runs / 'external_candidates' / run_id, HERE / 'repaired-workshop', runs,
)
responses = iter(a['raw'] for a in original['plan_attempts'])
calls = []

async def call(role, prompt):
    assert role == 'planner', 'Historical invalid plans must never dispatch a worker'
    i = len(calls)
    if variant == 'before':
        assert str(prompt) == original['prompt_trace'][i]['prompt_text']
    calls.append({'role': role, 'prompt': str(prompt),
                  'schema': hive.response_schema_for_prompt(role, prompt)})
    return next(responses)

run = asyncio.run(hive.run_build(
    Path(metadata['candidate_root']), runs, original['request'], original['local_model'], call,
    metadata={'external_root': metadata, 'experiment': {'study_id': 'HIVE-TRANSITION-001',
                                                       'mode': f'historical-replay-{variant}'}},
    run_id=run_id, external_root_mode=True,
    allowed_write_files=original['metadata']['host_write_scope'],
))
summary = {'variant': variant, 'run_id': run_id, 'status': run['status'],
           'roles_called': [c['role'] for c in calls], 'changed_files': run['changed_files'],
           'verification': run['verification'], 'applied': run['applied'],
           'failures': [a.get('failure') for a in run['plan_attempts']],
           'response_hashes_match': [hashlib.sha256(a['raw'].encode()).hexdigest() == t['response_sha256']
                                    for a, t in zip(run['plan_attempts'], original['prompt_trace'], strict=True)],
           'candidate_sha256': external_root.tree_sha256(Path(metadata['candidate_root'])),
           'stage_sha256': external_root.tree_sha256(runs / run_id / 'stage')}
out = HERE / 'evidence' / f'replay-{variant}'
(out / 'calls.json').write_text(json.dumps(calls, indent=2), encoding='utf-8')
(out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k!='failures'}, indent=2))
