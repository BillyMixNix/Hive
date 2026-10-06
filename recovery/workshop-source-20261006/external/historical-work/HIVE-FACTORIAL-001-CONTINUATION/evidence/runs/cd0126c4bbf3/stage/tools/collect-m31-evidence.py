"""Collect bounded, sanitized disposable-harness evidence; no launcher/user-world files."""
from pathlib import Path
import json
import hashlib
import re
import xml.etree.ElementTree as ET

project = Path(__file__).resolve().parents[1]
destination = project / 'evidence-m31'
raw = (project.parent / 'm31-verification-final.log').read_text(encoding='utf-8-sig', errors='replace')
for required in ('BUILD SUCCESSFUL', 'All 26 required tests passed', 'All 2 required tests passed', 'ATM Companion 0.3.1 (atm_companion)'):
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
# Preserve this hotfix's actually executed unit run (the later clean run may reuse cache).
unit_run = project.parent / 'm31-targeted-build.log'
unit_text = unit_run.read_text(encoding='utf-8-sig', errors='replace')
if 'BUILD SUCCESSFUL' not in unit_text: raise SystemExit('Missing executed hotfix unit validation')
(destination / 'targeted-build.log').write_text(sanitized(unit_text), encoding='utf-8')
(destination / 'suite-summary.json').write_text(json.dumps({'junit': totals, 'coreGameTests': 26, 'ftbGameTests': 2}, indent=2), encoding='utf-8')
print(f'Collected {totals}; 26 core and 2 FTB runtime tests.')
