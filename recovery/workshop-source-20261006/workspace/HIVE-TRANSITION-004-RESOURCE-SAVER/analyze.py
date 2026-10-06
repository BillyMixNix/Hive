"""Read-only correlation of existing verifier timings and Docker lifecycle logs.

No engine/container start, setting changes, model calls, or gate executions.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent / 'HIVE-TRANSITION-004'
LOG = Path(os.environ['LOCALAPPDATA']) / 'Docker/log/host'
EVIDENCE = HERE / 'evidence'
EVIDENCE.mkdir(exist_ok=False)

def sha(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()

def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')

def timestamp(line):
    match = re.match(r'\[([^]]+)\]', line)
    return dt.datetime.fromisoformat(match[1].replace('Z', '+00:00')) if match else None

def sec(a, b):
    return round((timestamp(b['text']) - timestamp(a['text'])).total_seconds(), 6)

manifest = {str(p.relative_to(HERE.parent)): sha(p)
            for p in PRIOR.rglob('*') if p.is_file()}
manifest['HIVE-TRANSITION-004-REPORT.md'] = sha(HERE.parent / 'HIVE-TRANSITION-004-REPORT.md')
save(EVIDENCE / 'prior-before.json', manifest)
settings = Path(os.environ['APPDATA']) / 'Docker/settings-store.json'
settings_before = sha(settings)
save(EVIDENCE / 'settings-before.json', {
    'path': str(settings), 'sha256': settings_before,
    'relevant_explicit_values': {k: v for k, v in json.loads(settings.read_text()).items()
                               if re.search(r'saver|idle|pause|wsl|memory|cpu', k, re.I)}})

cases = []
names = ['hive-verify-4993c0baef72']
for case in ['measured-baseline', 'measured-preserved', 'measured-known-good',
             'post-regression-baseline', 'post-regression-preserved']:
    root = PRIOR / 'evidence/verifier-replays' / case
    invocation = json.loads((root / 'diagnostics/invocation.json').read_text())
    events = [json.loads(s) for s in (root / 'diagnostics/verification-events.jsonl').read_text().splitlines()]
    names.append(invocation['container'])
    cases.append((case, root, invocation, events))

# Extract only lifecycle transitions and exact study-container create/start/remove
# requests; omit unrelated API requests, configuration, environment and payloads.
source_manifest = []
all_lines = []
for path in sorted(LOG.glob('*.log*')):
    if not path.name.startswith(('monitor.log', 'com.docker.backend.exe.log')):
        continue
    raw = path.read_bytes()
    rows = []
    for number, line in enumerate(raw.decode('utf-8', errors='replace').splitlines(), 1):
        if line.startswith('[2026-10-05T'):
            rows.append({'source': str(path), 'line': number, 'text': line})
    if rows:
        source_manifest.append({'path': str(path), 'sha256_at_read': hashlib.sha256(raw).hexdigest(),
                                'bytes_at_read': len(raw), 'first_day_record': rows[0]['text'][:40],
                                'last_day_record': rows[-1]['text'][:40]})
        all_lines.extend(rows)

ids = {}
for row in all_lines:
    for name in names:
        if name in row['text']:
            match = re.search(r'exposer\.\w+\(([0-9a-f]{64}), /' + name, row['text'])
            if match:
                ids[name] = match[1]
assert len(ids) == len(names), ids

selected = []
for row in all_lines:
    t = timestamp(row['text'])
    line = row['text']
    lifecycle = re.search(r'\[(?:main|com\.docker\.backend\.exe)\.idle\s*\].*'
                          r'(idle -> busy|busy -> idle|starting VM|VM started|VM stopped|stopping VM|timer expired|efficiency mode)', line)
    study_name = any(name in line for name in names)
    study_id = any(value in line for value in ids.values())
    api_boundary = study_id and re.search(r'POST .*/start|DELETE .*/containers/|exposer\.(?:Approve|Add)', line)
    if t.hour >= 14 and (lifecycle or study_name or api_boundary):
        selected.append(row)
selected.sort(key=lambda r: timestamp(r['text']))
save(EVIDENCE / 'docker-log-sources.json', source_manifest)
save(EVIDENCE / 'container-identities.json', ids)
with (EVIDENCE / 'docker-lifecycle-excerpts.jsonl').open('w', encoding='utf-8') as stream:
    for row in selected:
        stream.write(json.dumps(row) + '\n')

def find(predicate):
    return next(r for r in selected if predicate(r['text']))

historical_id = ids[names[0]]
hstart = find(lambda s: '[2026-10-05T14:54:09.' in s and 'starting VM' in s)
hready = find(lambda s: '[2026-10-05T14:54:17.' in s and '.idle ' in s and 'VM started' in s)
hcontainer = find(lambda s: '<< POST ' in s and historical_id + '/start' in s)
hremove = find(lambda s: '>> DELETE ' in s and names[0] in s)
save(EVIDENCE / 'transition-003-startup.json', {
    'run_id': '45ad10e6dd49', 'container': names[0], 'container_id': historical_id,
    'wake_started': hstart, 'wake_ready': hready, 'container_start_returned': hcontainer,
    'removal_requested': hremove,
    'observed_vm_wake_seconds': sec(hstart, hready),
    'ready_to_container_start_response_seconds': sec(hready, hcontainer),
    'wake_to_container_start_response_seconds': sec(hstart, hcontainer),
    'container_start_response_to_removal_request_seconds': sec(hcontainer, hremove),
    'wake_to_removal_request_seconds': sec(hstart, hremove),
    'limitation': 'Host Docker CLI launch and first verifier instruction timestamp were not preserved. Start API response is not first verifier instruction. Original internal Gradle phase is still unknown.'})

timings = []
for case, root, invocation, events in cases:
    def e(phase):
        return next(r for r in events if r['phase'] == phase)
    def elapsed(a, b):
        x, y = e(a), e(b)
        if x.get('origin') == y.get('origin') == 'container':
            return round((y['source_event']['elapsed_ms'] - x['source_event']['elapsed_ms']) / 1000, 6)
        return round((y['elapsed_ms'] - x['elapsed_ms']) / 1000, 6)
    launch = dt.datetime.fromisoformat(e('verifier_launch_requested')['wall_timestamp'])
    started = dt.datetime.fromisoformat(e('container_verifier_started')['wall_timestamp'])
    wake = [r for r in selected if launch <= timestamp(r['text']) <= started and 'starting VM' in r['text']]
    ready = [r for r in selected if launch <= timestamp(r['text']) <= started and '.idle ' in r['text'] and 'VM started' in r['text']]
    row = {'case': case, 'container': invocation['container'], 'container_id': ids[invocation['container']],
           'launch_utc': launch.isoformat(), 'first_container_event_utc': started.isoformat(),
           'engine_state': 'RESOURCE_SAVER_WAKE_OBSERVED' if wake else 'ALREADY_RUNNING_ENGINE',
           'wake_seconds': sec(wake[0], ready[0]) if wake and ready else 0,
           'launch_to_first_event_seconds': elapsed('verifier_launch_requested', 'container_verifier_started'),
           'startup_percent_of_budget': round(elapsed('verifier_launch_requested', 'container_verifier_started') / 2.4, 3),
           'project_copy_seconds': elapsed('project_materialization_started', 'project_available'),
           'wrapper_copy_seconds': elapsed('wrapper_copy_started', 'wrapper_copy_complete'),
           'native_copy_seconds': elapsed('external_inputs_copy_started', 'external_inputs_copy_complete'),
           'before_gradle_seconds': elapsed('verifier_launch_requested', 'gradle_invoked'),
           'gradle_exposure_seconds': elapsed('gradle_invoked', 'timeout_fired'),
           'outer_seconds': elapsed('verifier_launch_requested', 'timeout_fired'),
           'timeout_seconds': invocation['timeout_seconds'],
           'candidate_sha256': json.loads((root / 'preflight.json').read_text())['candidate_sha256'],
           'last_task_marker': [r['source_event']['marker'] for r in events if r['phase'] == 'gradle_output_marker'][-1],
           'verification_passed': json.loads((root / 'result.json').read_text())['report']['passed']}
    # Copy exact timing-bearing artifacts; these are evidence copies, never a rerun.
    for file in ['diagnostics/invocation.json', 'diagnostics/verification-events.jsonl', 'preflight.json', 'result.json']:
        target = EVIDENCE / 'prior-measurements' / case / file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / file).read_bytes())
    timings.append(row)
assert timings[0]['engine_state'] == 'RESOURCE_SAVER_WAKE_OBSERVED'
assert all(t['engine_state'] == 'ALREADY_RUNNING_ENGINE' for t in timings[1:])
assert timings[0]['candidate_sha256'] == timings[3]['candidate_sha256']
assert timings[1]['candidate_sha256'] == timings[4]['candidate_sha256']
assert all(t['timeout_seconds'] == 240 and not t['verification_passed'] for t in timings)
save(EVIDENCE / 'timing-comparison.json', timings)

timer = time.monotonic()
state = subprocess.run(['docker', 'desktop', 'status', '--format', 'json'], capture_output=True, text=True, timeout=10)
save(EVIDENCE / 'current-status.json', {'observed_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    'command': ['docker', 'desktop', 'status', '--format', 'json'],
    'elapsed_seconds': time.monotonic() - timer, 'returncode': state.returncode,
    'stdout': state.stdout, 'stderr': state.stderr,
    'interpretation': 'Status=stopped alone does not distinguish Resource Saver from another stopped-engine cause. No start, stop, pause, or unpause command was sent.'})
after = {name: sha(HERE.parent / name) for name in manifest}
assert after == manifest
assert sha(settings) == settings_before
save(EVIDENCE / 'integrity.json', {'prior_files_checked': len(manifest), 'prior_unchanged': True,
    'docker_settings_unchanged': True, 'model_calls': 0, 'new_verifier_runs': 0,
    'new_container_launches': 0, 'production_edits': 0})
print(json.dumps({'historical_wake_seconds': sec(hstart, hready), 'historical_start_seconds': sec(hstart, hcontainer),
                  'timings': timings, 'prior_files_unchanged': len(manifest)}, indent=2))
