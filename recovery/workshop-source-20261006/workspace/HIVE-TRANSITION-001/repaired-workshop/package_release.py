"""Build a clean source release without runtime state or caches."""
from pathlib import Path
import hashlib, shutil, tempfile, zipfile
EXCLUDED={"data","media","reports","snapshots","self_snapshots","workspace","hive_runs","logs",".pytest_cache","pytest-of-billy","__pycache__",".mypy_cache",".ruff_cache","build","dist",".git",".venv","venv","node_modules","outputs","releases","artifacts","htmlcov",".tox",".nox",".idea",".vscode"}
def build(source: Path, output: Path):
    with tempfile.TemporaryDirectory(dir=source.parent) as td:
        stage=Path(td)/"Nix_Workshop_v0_11_1"
        shutil.copytree(source,stage,ignore=shutil.ignore_patterns(*EXCLUDED,"tmp*","pytest-*","*.pyc","*.log","*.zip","*.db",".env",".env.*",".coverage","coverage.xml","*.pem","*.key","*.p12","*.pfx"))
        with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as z:
            for p in sorted(stage.rglob("*")):
                if p.is_file(): z.write(p,p.relative_to(stage.parent))
    return hashlib.sha256(output.read_bytes()).hexdigest()
if __name__=="__main__":
    import sys
    print(build(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve()))
