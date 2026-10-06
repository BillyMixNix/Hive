"""One controlled new diagnostic, using the frozen runner's run_one unchanged.

diagnostic_runner changes only study labeling, import wiring and source path.
This entrypoint intentionally never invokes the factorial batch runner/main.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ.pop('OPENAI_API_KEY', None)
sys.dont_write_bytecode = True
import diagnostic_runner as r

HERE = Path(__file__).resolve().parent
ORIGINAL = Path(r'C:\Users\billy\Documents\Codex\2026-09-13\referenced-chatgpt-conversation-this-is-an\work\HIVE-FACTORIAL-002')

def main():
    out = HERE / 'evidence/live'
    out.mkdir(exist_ok=False)  # Never overwrite or silently run another diagnostic.
    r.EVIDENCE = out
    r.RUNS = out / 'runs'
    original = json.loads((ORIGINAL / 'FREEZE.json').read_text())
    assert r.sha(ORIGINAL / 'FREEZE.json') == (ORIGINAL / 'LOCK.sha256').read_text().strip()
    r.prior.no_cloud_key()
    assert r.providers.ollama_base() == 'http://127.0.0.1:11434'
    assert r.prior.disk_free_bytes() >= r.prior.MIN_FREE_BYTES
    reference = r.prior.reference_freeze()
    print('Checking sealed baseline, verifier and approved offline caches', flush=True)
    approved = r.prior.approved_environment(reference)
    assert approved['baseline_sha256'] == original['baseline']['sha256']
    assert approved['verifier_image_id'] == original['verifier_image_id']
    assert r.prior.hive_verifier.JVM_CONTAINER_LIMITS == original['verifier_limits']
    models = r.model_inventory()
    model = next(x for x in models if x['name'] == 'qwen2.5-coder:14b')
    assert model == next(x for x in original['models'] if x['name'] == model['name'])
    tasks = r.task_specs()
    assert [{k:v for k,v in t.items() if k != 'test_source'} for t in tasks] == original['tasks']
    task = next(t for t in tasks if t['id'] == 'J001')
    # Only hive.py may differ among preexisting source files; verification stays byte-identical.
    changes = []
    for item in r.prior.source_manifest():
        old = ORIGINAL / 'workshop' / item['path']
        if old.exists() and r.sha(old) != item['sha256']:
            changes.append(item['path'])
    assert changes == ['workshop/hive.py'], changes
    freeze = {**original, 'study': 'HIVE-TRANSITION-001', 'status': 'diagnostic-preregistered',
              'parent_study': 'HIVE-FACTORIAL-002', 'parent_freeze_sha256': r.sha(ORIGINAL / 'FREEZE.json'),
              'apparatus_change': 'Planner scope schema and complete scope correction feedback; canonical inactive goal guidance',
              'production_changes': changes,
              'diagnostic_policy': 'One new J001 trial; measure transition progress, do not estimate success rate',
              'order': [{'task_id': 'J001', 'replicate': 1, 'model': model['name'], 'controller': 'hive'}],
              'source_manifest_sha256': hashlib.sha256(json.dumps(r.prior.source_manifest(), sort_keys=True).encode()).hexdigest()}
    r.save_json(HERE / 'FREEZE.json', freeze)
    (HERE / 'LOCK.sha256').write_text(r.sha(HERE / 'FREEZE.json') + '\n')
    r.save_json(out / 'preflight.json', {'approved': approved, 'model': model,
                                       'scope': task['files'], 'parent_lock': r.sha(ORIGINAL / 'FREEZE.json'),
                                       'production_changes': changes, 'source_manifest': r.prior.source_manifest()})
    print('Preflight passed. Starting one local-only J001 diagnostic.', flush=True)
    result = asyncio.run(r.run_one(freeze['order'][0], freeze, task, 1))
    r.save_json(out / 'raw_results.json', [result])
    print(json.dumps(result, indent=2), flush=True)

if __name__ == '__main__':
    main()
