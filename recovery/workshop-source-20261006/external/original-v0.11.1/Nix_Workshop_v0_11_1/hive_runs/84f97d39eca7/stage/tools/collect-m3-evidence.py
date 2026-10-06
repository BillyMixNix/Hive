"""Collect bounded, sanitized disposable-harness evidence; no launcher/user-world files."""
from pathlib import Path
import json
import hashlib
import re
import xml.etree.ElementTree as ET

project = Path(__file__).resolve().parents[1]
destination = project / 'evidence-m3'
raw = (project.parent / 'm3-verification-final.log').read_text(encoding='utf-8-sig', errors='replace')
for required in ('BUILD SUCCESSFUL', 'All 23 required tests passed', 'All 2 required tests passed'):
    if required not in raw:
        raise SystemExit(f'Final verification missing: {required}')

def sanitized(text):
    text = text.replace(str(project.parent).replace('\\', '\\\\'), '<WORKSPACE>')
    text = text.replace(str(project.parent), '<WORKSPACE>').replace(str(project.parent).replace('\\', '/'), '<WORKSPACE>')
    return re.sub(r'[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s<>"\']+', '<USER_HOME>', text)

destination.mkdir(exist_ok=True)
(destination / 'junit').mkdir(exist_ok=True)
(destination / 'verification-final.log').write_text(sanitized(raw), encoding='utf-8')
totals = dict(tests=0, failures=0, errors=0, skipped=0)
for path in sorted((project / 'build/test-results/test').glob('TEST-*.xml')):
    xml = path.read_text(encoding='utf-8')
    suite = ET.fromstring(xml)
    for key in totals:
        totals[key] += int(suite.attrib.get(key, 0))
    (destination / 'junit' / path.name).write_text(sanitized(xml), encoding='utf-8')
if totals != dict(tests=119, failures=0, errors=0, skipped=0):
    raise SystemExit(f'Unexpected unit results: {totals}')
inputs = {
    'live-snapshot.json': 'run-gametest/evidence/live-snapshot.json',
    'real-server-player-snapshot.json': 'run-gametest/evidence/real-server-player-snapshot.json',
    'runtime-index.json': 'run-gametest/evidence/m2-index.json',
    'crafting-plan.json': 'run-gametest/evidence/m2-live-plan.json',
    'reload.json': 'run-gametest/evidence/m2-reload.json',
    'index-budget-regression.json': 'run-gametest/evidence/m2-budget-regression.json',
    'cooking-plan.json': 'run-gametest/evidence/m3-cooking-plan.json',
    'ftb-quests-fixture.json': 'run-questtest/evidence/ftb-quests-fixture.json',
}
for name, relative in inputs.items():
    text = (project / relative).read_text(encoding='utf-8')
    json.loads(text)
    (destination / name).write_text(sanitized(text), encoding='utf-8')
# Retain the diagnosed failed experiment too, without credentials or personal paths.
failure = project.parent / 'm3-feature-fixture-failure.log'
if failure.is_file():
    (destination / 'feature-fixture-failure.log').write_text(sanitized(failure.read_text(encoding='utf-8-sig', errors='replace')), encoding='utf-8')
(destination / 'suite-summary.json').write_text(json.dumps({'junit': totals, 'coreGameTests': 23, 'ftbGameTests': 2}, indent=2), encoding='utf-8')
pack = project.parent / 'runtime-m3-atm10'
probe = pack / 'evidence/m3-atm10-production-smoke.json'
if probe.is_file():
    data = json.loads(probe.read_text(encoding='utf-8'))
    if data.get('terminalStatus') != 'passed': raise SystemExit('Production pack probe did not pass')
    original = project / 'build/libs/ATM-Companion-0.3.0.jar'
    deployed = pack / 'mods/ATM-Companion-M3.jar'
    if original.read_bytes() != deployed.read_bytes(): raise SystemExit('Probe JAR differs from release build')
    (destination / 'atm10-production-smoke.json').write_text(sanitized(probe.read_text(encoding='utf-8')), encoding='utf-8')
    (destination / 'tested-jar-sha256.txt').write_text(hashlib.sha256(original.read_bytes()).hexdigest() + '\n', encoding='utf-8')
    for name in ('SOURCE-PROVENANCE.json', 'RUNTIME-PREPARATION.json'):
        if (pack / name).is_file():
            (destination / name.lower()).write_text(sanitized((pack / name).read_text(encoding='utf-8-sig')), encoding='utf-8')
    for name in ('m3-atm10-production.log', 'm3-atm10-smoke.log', 'm3-atm10-installer.log'):
        source = project.parent / name
        if source.is_file():
            (destination / name).write_text(sanitized(source.read_text(encoding='utf-8-sig', errors='replace')), encoding='utf-8')
print(f'Collected {totals}; 23 core and 2 FTB runtime tests.')
