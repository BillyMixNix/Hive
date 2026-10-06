"""Audit the retrospective comparison without contacting Docker or changing prior evidence."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
E = HERE / 'evidence'
def read(p): return json.loads(p.read_text())
def sha(p):
    with p.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
rows = read(E / 'timing-comparison.json')
def normalized_argv(case):
    inv = read(E / 'prior-measurements' / case / 'diagnostics/invocation.json')
    result = []
    for item in inv['argv']:
        if item == inv['container']:
            item = '<unique-container>'
        elif item.startswith('type=bind,source=') and ',target=/source,readonly' in item:
            item = 'type=bind,source=<fresh-sanitized-source>,target=/source,readonly'
        elif item.startswith('HIVE_VERIFICATION_RUN_ID='):
            item = 'HIVE_VERIFICATION_RUN_ID=<unique-run>'
        result.append(item)
    return result

checks = {}
reference = normalized_argv(rows[0]['case'])
checks['same_verifier_command_except_isolated_identity_paths'] = all(normalized_argv(r['case']) == reference for r in rows)
preflights = [read(E / 'prior-measurements' / r['case'] / 'preflight.json') for r in rows]
def runtime_manifest(p):
    return {k: v for k, v in p['production_manifest'].items()
            if k.replace('\\', '/').startswith(('workshop/', 'verification/')) or k == 'app.py'}
checks['same_runtime_source_manifest'] = all(runtime_manifest(p) == runtime_manifest(preflights[0]) for p in preflights)
manifest_differences = []
for row, p in zip(rows, preflights):
    a, b = preflights[0]['production_manifest'], p['production_manifest']
    manifest_differences.append({'case': row['case'], 'all_nonidentical_python_paths':
                                [k for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k)]})
checks['same_approved_environment'] = all(p['approved'] == preflights[0]['approved'] for p in preflights)
checks['same_baseline_bytes_in_cold_warm_pair'] = rows[0]['candidate_sha256'] == rows[3]['candidate_sha256']
checks['all_timeouts_remain_failed'] = all(r['timeout_seconds'] == 240 and not r['verification_passed'] for r in rows)
before = read(E / 'prior-before.json')
checks['all_prior_files_unchanged'] = all(sha(HERE.parent / name) == value for name, value in before.items())
checks['original_resource_saver_wake_mapped_to_correct_container'] = read(E / 'transition-003-startup.json')['container'] == 'hive-verify-4993c0baef72'
checks['no_new_calls_or_edits'] = all(read(E / 'integrity.json')[key] == 0 for key in ('model_calls', 'new_verifier_runs', 'new_container_launches', 'production_edits'))
result = {'passed': all(checks.values()), 'checks': checks, 'manifest_differences': manifest_differences,
          'cold_minus_warm_baseline_startup_seconds': round(rows[0]['launch_to_first_event_seconds'] - rows[3]['launch_to_first_event_seconds'], 6),
          'cold_minus_warm_baseline_pre_gradle_seconds': round(rows[0]['before_gradle_seconds'] - rows[3]['before_gradle_seconds'], 6),
          'warning': 'Retrospective same-baseline pair, not randomized. Only observed VM wake interval is directly localized to wake; later copy differences are confounded by host/cache state.'}
(E / 'comparison-audit.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
assert result['passed']
