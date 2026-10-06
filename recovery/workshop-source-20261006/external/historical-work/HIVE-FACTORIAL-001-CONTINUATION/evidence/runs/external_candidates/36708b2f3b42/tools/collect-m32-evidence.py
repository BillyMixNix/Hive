"""Collect bounded, sanitized disposable-harness evidence; no launcher/user-world files."""
from pathlib import Path
import json
import hashlib
import re
import xml.etree.ElementTree as ET

project = Path(__file__).resolve().parents[1]
destination = project / 'evidence-m32'
raw = (project.parent / 'm32-verification-final.log').read_text(encoding='utf-8-sig', errors='replace')
for required in ('BUILD SUCCESSFUL', 'All 26 required tests passed', 'All 3 required tests passed', 'ATM Companion 0.3.2 (atm_companion)'):
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
if totals != dict(tests=130, failures=0, errors=0, skipped=0):
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
    'ftb-large-book.json': 'run-questtest/evidence/ftb-large-book.json',
}
for name, relative in inputs.items():
    text = (project / relative).read_text(encoding='utf-8')
    json.loads(text)
    (destination / name).write_text(sanitized(text), encoding='utf-8')
# Aggregate production quest evidence contains no user world or quest content.
for stem in ('baseline', 'optimized'):
    source = project.parent / f'm32-quest-{stem}-production.log'
    content = source.read_text(encoding='utf-8-sig', errors='replace')
    # Keep only Companion probe/observation lines; omit unrelated pack output.
    lines = [line for line in content.splitlines() if 'ATM Companion FTB observation' in line or 'ATM Companion disposable full-pack quest' in line]
    (destination / f'quest-production-{stem}.log').write_text(sanitized('\n'.join(lines)) + '\n', encoding='utf-8')
experiments = []
for name in ('m32-clean-gates.log', 'm32-first-gates-failed.log', 'm32-quest-targeted.log', 'm32-quest-profile.log', 'm32-summary-first-gates-failed.log'):
    content = (project.parent / name).read_text(encoding='utf-8-sig', errors='replace')
    experiments.append(name + '\n' + '\n'.join(line for line in content.splitlines()
            if 'Task ' in line and 'not found' in line or 'LogTestReporter' in line or 'ATM Companion FTB observation' in line or 'BUILD FAILED' in line))
(destination / 'failed-experiments.log').write_text(sanitized('\n\n'.join(experiments)), encoding='utf-8')
(destination / 'suite-summary.json').write_text(json.dumps({'junit': totals, 'coreGameTests': 26, 'ftbGameTests': 3}, indent=2), encoding='utf-8')
print(f'Collected {totals}; 26 core and 3 FTB runtime tests.')
