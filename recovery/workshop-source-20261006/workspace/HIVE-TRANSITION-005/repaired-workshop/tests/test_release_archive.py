from pathlib import Path
import zipfile

from package_release import build


def test_produced_archive_excludes_runtime_artifacts_and_includes_offline_parser(tmp_path):
    source = tmp_path / 'source'
    good = ['app.py', 'workshop/vendor/acorn.cjs', 'workshop/vendor/LICENSE-acorn.txt']
    bad = ['data/workshop.db', '.pytest_cache/state', '__pycache__/app.pyc', 'loose.pyc',
           'loose.db', 'server.log', 'old.zip', 'hive_runs/old/run.json', 'workspace/secret.py',
           'snapshots/old.py', 'build/generated.py', 'node_modules/package/index.js', '.env',
           '.env.local', '.coverage', 'coverage.xml', 'secret.pem', '.idea/project.xml']
    for rel in good + bad:
        path = source / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('fixture', encoding='utf-8')
    archive = tmp_path / 'Nix-Workshop-v0.11.1.zip'
    sha = build(source, archive)
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        assert sorted(names) == sorted('Nix_Workshop_v0_11_1/' + rel for rel in good)
        assert z.testzip() is None
    assert len(sha) == 64
