"""Package only source, documentation, sanitized evidence and the production M3 JAR."""
from pathlib import Path
import hashlib
import shutil
import zipfile

project = Path(__file__).resolve().parents[1]
output = project.parent
jar = project / 'build/libs/ATM-Companion-0.3.0.jar'
required = [jar, project / 'README.md', project / 'VERIFICATION.md', project / 'M3-ARCHITECTURE.md',
            project / 'M3-ADVERSARIAL-REVIEW.md', project / 'evidence-m3/verification-final.log']
for path in required:
    if not path.is_file(): raise SystemExit(f'Missing release input: {path.name}')

files = ['build.gradle', 'settings.gradle', 'gradle.properties', 'gradlew', 'gradlew.bat', '.gitignore',
         'README.md', 'VERIFICATION.md', 'M3-ARCHITECTURE.md', 'M3-ADVERSARIAL-REVIEW.md', 'ARCHITECTURE.md',
         'LICENSE', 'THIRD-PARTY-NOTICES.md', 'RESEARCH.md', 'M2-RESEARCH.md', 'M2-ARCHITECTURE.md',
         'evidence-m2/ftb-quests-fixture.json', 'evidence-m2/verification-final.log']
paths = [project / name for name in files]
for directory in ('src', 'gradle', 'tools', 'docs', 'evidence-m3'):
    paths.extend(p for p in (project / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
with zipfile.ZipFile(jar) as archive:
    assert archive.testzip() is None
    names = archive.namelist()
    assert 'version="0.3.0"' in archive.read('META-INF/neoforge.mods.toml').decode()
    forbidden = ('dev/ftb/', 'dev/architectury/', 'net/minecraft/', 'dev/atmcompanion/tests/',
                 'dev/atmcompanion/questtests/', 'dev/atmcompanion/packtests/', 'data/atm_companion_tests/',
                 'data/atm_companion_questtests/', 'data/atm_companion_packtests/')
    assert not any(n.startswith(forbidden) or 'GameTests' in n or n.endswith('.jar') for n in names)

release_jar = output / 'ATM-Companion-M3.jar'
shutil.copyfile(jar, release_jar)
bundle = output / 'ATM-Companion-M3.zip'
with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(paths): archive.write(path, 'source/' + path.relative_to(project).as_posix())
    archive.write(jar, 'ATM-Companion-M3.jar')
    for name in ('README.md', 'VERIFICATION.md', 'M3-ARCHITECTURE.md', 'M3-ADVERSARIAL-REVIEW.md'):
        archive.write(project / name, name)
with zipfile.ZipFile(bundle) as archive:
    assert archive.testzip() is None
    names = archive.namelist()
    assert len(names) == len(set(names))
    assert not any(any(part in n.split('/') for part in ('.gradle', 'build', 'run-gametest', 'run-questtest', 'runtime-m3-atm10', 'world', 'saves')) for n in names)
    assert archive.read('ATM-Companion-M3.jar') == jar.read_bytes()
checksum = output / 'SHA256SUMS-M3.txt'
checksum.write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in (release_jar, bundle)), encoding='utf-8')
print(f'{release_jar.name}: {release_jar.stat().st_size:,} bytes')
print(f'{bundle.name}: {bundle.stat().st_size:,} bytes; {len(names)} entries')
print(checksum.read_text())
