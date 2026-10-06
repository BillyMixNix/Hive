"""Collect only synthetic test evidence after the final successful verification run."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET

project = Path(__file__).resolve().parents[1]
destination = project / 'evidence-m2'
log = project.parent / 'm2-playtest-fix.log'
raw = log.read_text(encoding='utf-8-sig', errors='replace')
for required in ('BUILD SUCCESSFUL', 'All 14 required tests passed', 'All 2 required tests passed'):
    if required not in raw:
        raise SystemExit(f'Final run has not passed: {required}')

def sanitized(text):
    # Test logs may contain absolute Gradle/JDK/project paths, never needed for release evidence.
    text = text.replace(str(project), '<PROJECT>')
    text = text.replace(str(project).replace('\\', '/'), '<PROJECT>')
    text = re.sub(r'[A-Za-z]:[\\/]Users[\\/][^\\/\s<>"\']+', '<USER_HOME>', text)
    return text

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
if totals != dict(tests=93, failures=0, errors=0, skipped=0):
    raise SystemExit(f'Unexpected JUnit results: {totals}')

inputs = {
    'live-snapshot.json': 'run-gametest/evidence/live-snapshot.json',
    'real-server-player-snapshot.json': 'run-gametest/evidence/real-server-player-snapshot.json',
    'm2-index.json': 'run-gametest/evidence/m2-index.json',
    'm2-live-plan.json': 'run-gametest/evidence/m2-live-plan.json',
    'm2-reload.json': 'run-gametest/evidence/m2-reload.json',
    'm2-budget-regression.json': 'run-gametest/evidence/m2-budget-regression.json',
    'ftb-quests-fixture.json': 'run-questtest/evidence/ftb-quests-fixture.json',
}
for name, relative in inputs.items():
    path = project / relative
    (destination / name).write_text(sanitized(path.read_text(encoding='utf-8')), encoding='utf-8')
print(f'Collected final synthetic evidence: {totals}, 14 core and 2 FTB GameTests.')
