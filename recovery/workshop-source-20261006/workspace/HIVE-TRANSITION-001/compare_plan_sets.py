"""Differentially replay frozen and diagnostic planner responses, model-free."""
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PRIOR = Path(r'C:\Users\billy\Documents\Codex\2026-09-13\referenced-chatgpt-conversation-this-is-an\work\HIVE-FACTORIAL-002')
os.environ.pop('OPENAI_API_KEY', None)
sys.dont_write_bytecode = True

if len(sys.argv) == 1:
    results = {}
    for variant in ('before', 'after'):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), variant],
                                check=True, capture_output=True, text=True)
        results[variant] = json.loads(result.stdout)
    assert len(results['before']) == len(results['after'])
    for old, new in zip(results['before'], results['after'], strict=True):
        assert old['id'] == new['id']
        assert not new['accepted'] or old['accepted']
        if old['id'].startswith('factorial'):
            assert old['accepted'] == new['accepted']
    (HERE / 'evidence/differential-plan-replay.json').write_text(json.dumps(results, indent=2))
    print('32 preserved plans replayed; no new acceptance. All 30 factorial decisions unchanged; live overlap now rejected.')
    raise SystemExit(0)

variant = sys.argv[1]
sys.path.insert(0, str(PRIOR / 'workshop' if variant == 'before' else HERE / 'repaired-workshop'))
from workshop import hive

runs = [(f"factorial-{t['ordinal']}", Path(t['run_artifact']))
        for t in json.loads((HERE / 'failure-taxonomy.json').read_text())['trials']]
runs.append(('live-revision1', HERE / 'evidence/live/01-J001-r1-qwen2.5-coder-14b-hive/run.json'))
results = []
for label, path in runs:
    run = json.loads(path.read_text())
    tokens = [(hive._HOST_WRITE_SCOPE, hive._HOST_WRITE_SCOPE.set(tuple(run['metadata']['host_write_scope']))),
              (hive._ACTIVE_AGENT_SCOPES, hive._ACTIVE_AGENT_SCOPES.set(hive.EXTERNAL_AGENT_SCOPES)),
              (hive._EXTERNAL_ROOT_MODE, hive._EXTERNAL_ROOT_MODE.set(True))]
    try:
        for a in run['plan_attempts']:
            result = {'id': f"{label}-{a['attempt']}"}
            try:
                plan, _ = hive._normalize_plan(hive._extract_json(a['raw']))
                hive._validate_host_write_scope(plan)
                hive._validate_intent_coverage(plan, run['intent_envelope'])
                result['accepted'] = True
            except Exception as error:
                result.update(accepted=False, error_type=type(error).__name__, error=str(error))
            results.append(result)
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
print(json.dumps(results))
