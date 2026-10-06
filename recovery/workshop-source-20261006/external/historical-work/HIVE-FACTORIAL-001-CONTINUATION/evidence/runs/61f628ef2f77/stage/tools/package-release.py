"""Create a small release ZIP from an explicit source allowlist; run after verification."""
from pathlib import Path
import hashlib
import shutil
import zipfile

project = Path(__file__).resolve().parents[1]
output = project.parent
jar = project / 'build/libs/ATM-Companion-0.2.1.jar'
required = [jar, project / 'README.md', project / 'VERIFICATION.md',
            project / 'M2-ARCHITECTURE.md', project / 'M2-ADVERSARIAL-REVIEW.md',
            project / 'evidence-m2/verification-final.log']
for path in required:
    if not path.is_file():
        raise SystemExit(f'Missing release input: {path.name}')

allowed_files = ['build.gradle', 'settings.gradle', 'gradle.properties', 'gradlew', 'gradlew.bat',
                 '.gitignore', 'README.md', 'VERIFICATION.md', 'M2-RESEARCH.md', 'M2-ADVERSARIAL-REVIEW.md',
                 'LICENSE', 'THIRD-PARTY-NOTICES.md', 'ARCHITECTURE.md', 'M2-ARCHITECTURE.md', 'PLAYTEST-M2.md']
allowed_dirs = ['src', 'gradle', 'tools', 'evidence-m2']
paths = [project / name for name in allowed_files if (project / name).is_file()]
for directory in allowed_dirs:
    paths.extend(p for p in (project / directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts)

with zipfile.ZipFile(jar) as archive:
    assert archive.testzip() is None
    jar_names = archive.namelist()
    assert 'version="0.2.1"' in archive.read('META-INF/neoforge.mods.toml').decode()
    assert not any(n.startswith(('dev/ftb/', 'dev/architectury/', 'net/minecraft/',
                                 'dev/atmcompanion/gametest/', 'dev/atmcompanion/tests/', 'dev/atmcompanion/questtests/',
                                 'data/atm_companion_tests/', 'data/atm_companion_questtests/'))
                   or 'GameTests' in n or n.endswith('.jar') for n in jar_names)
release_jar = output / 'ATM-Companion-M2.jar'
shutil.copyfile(jar, release_jar)
bundle = output / 'ATM-Companion-M2.zip'
with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(paths):
        archive.write(path, 'source/' + path.relative_to(project).as_posix())
    archive.write(jar, 'ATM-Companion-M2.jar')
    archive.write(project / 'README.md', 'README.md')
    archive.write(project / 'VERIFICATION.md', 'VERIFICATION.md')
    archive.write(project / 'M2-ARCHITECTURE.md', 'M2-ARCHITECTURE.md')
    archive.write(project / 'PLAYTEST-M2.md', 'PLAYTEST-M2.md')
with zipfile.ZipFile(bundle) as archive:
    assert archive.testzip() is None
    names = archive.namelist()
    assert not any('/.gradle/' in n or '/build/' in n or '/run/' in n or '/run-gametest/' in n or '/run-questtest/' in n for n in names)
    assert len(names) == len(set(names))
    assert archive.read('ATM-Companion-M2.jar') == jar.read_bytes()
checksum_file = output / 'SHA256SUMS-M2.txt'
checksum_file.write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in [release_jar, bundle]), encoding='utf-8')
print(f'Created {release_jar.name}: {release_jar.stat().st_size:,} bytes')
print(f'Created {bundle.name}: {bundle.stat().st_size:,} bytes; {len(names)} entries')
print(checksum_file.read_text())
