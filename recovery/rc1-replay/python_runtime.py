"""Hash-bound host Python identity for one recovered replay; no network use."""

from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import os
import site
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "recovery/rc1-replay/PYTHON_RUNTIME_MANIFEST.json"
PACKAGES = ("pytest", "jsonschema", "fastapi", "httpx", "pydantic", "setuptools",
            "httpcore", "anyio", "certifi", "idna", "h11", "sniffio", "typing_extensions")
ENV_KEYS = ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONSAFEPATH",
            "PYTHONNOUSERSITE", "SETUPTOOLS_USE_DISTUTILS")


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_identity(root: Path, *, omit_site_packages: bool = False) -> dict:
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Python runtime tree is absent or linked")
    rows = []
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__" and
                         (not omit_site_packages or d != "site-packages"))
        for name in sorted(files):
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("Python runtime contains an unqualified link or special file")
            size = path.stat().st_size
            total += size
            rows.append((path.relative_to(root).as_posix(), size, file_sha(path)))
    return {"files": len(rows), "bytes": total,
            "tree_sha256": hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()}


def distribution_identity(name: str) -> dict:
    dist = metadata.distribution(name)
    if dist.files is None:
        raise ValueError(f"installed package has no file inventory: {name}")
    rows = []
    for item in sorted(dist.files, key=str):
        path = Path(dist.locate_file(item)).resolve(strict=True)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"package file is linked or nonregular: {name}")
        rows.append((str(item).replace("\\", "/"), path.stat().st_size, file_sha(path)))
    return {"version": dist.version, "files": len(rows),
            "tree_sha256": hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()}


def build() -> dict:
    home = Path(sys.prefix).resolve(strict=True)
    executable = Path(sys.executable).resolve(strict=True)
    dll = home / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    if executable.parent != home or not dll.is_file():
        raise ValueError("Python runtime is not the attested host installation")
    # The first entry is invocation-specific. It must be empty with cwd at the
    # checkout, or a directory inside this checkout. Every later import path
    # is exact and sealed in the manifest; injected search roots fail closed.
    if not sys.path:
        raise ValueError("Python import path is empty")
    entry = sys.path[0]
    entry_path = Path.cwd().resolve() if entry == "" else Path(entry).resolve(strict=True)
    if entry_path != ROOT and ROOT not in entry_path.parents:
        raise ValueError("Python entry import path is outside the replay checkout")
    user_site = Path(site.getusersitepackages())
    if user_site.exists() or any(Path(p).resolve() == user_site.resolve() for p in sys.path[1:] if p):
        raise ValueError("user-site Python packages are not qualified")
    if any(os.environ.get(key) is not None for key in ENV_KEYS if key != "SETUPTOOLS_USE_DISTUTILS"):
        raise ValueError("Python startup environment override is not qualified")
    import_tail = [{"path": str(Path(p).resolve(strict=False)), "exists": Path(p).exists()}
                   for p in sys.path[1:]]
    site_packages = home / "Lib/site-packages"
    hooks = {}
    for hook in sorted(site_packages.glob("*.pth")):
        if hook.is_symlink() or not hook.is_file():
            raise ValueError("Python startup hook is linked or nonregular")
        hooks[hook.name] = file_sha(hook)
    for directory in (home, home / "Lib", site_packages):
        for name in ("sitecustomize.py", "usercustomize.py", "python313._pth", "python._pth"):
            path = directory / name
            if path.exists():
                if path.is_symlink() or not path.is_file():
                    raise ValueError("Python startup override is linked or nonregular")
                hooks[str(path.relative_to(home)).replace("\\", "/")] = file_sha(path)
    return {"schema_version": 1, "python_version": sys.version,
            "python_home": str(home), "executable": str(executable),
            "executable_sha256": file_sha(executable),
            "python_dll_sha256": file_sha(dll),
            "import_path_tail": import_tail,
            "startup_hooks": hooks,
            "startup_environment": {key: os.environ.get(key) for key in ENV_KEYS},
            "stdlib": tree_identity(home / "Lib", omit_site_packages=True),
            "extension_dlls": tree_identity(home / "DLLs"),
            "packages": {name: distribution_identity(name) for name in PACKAGES}}


def verify() -> dict:
    approved = json.loads(MANIFEST.read_bytes())
    current = build()
    if current != approved:
        raise ValueError("host Python runtime differs from sealed 001C identity")
    return {"status": "PASS", "python_version": current["python_version"],
            "packages": {name: item["version"] for name, item in current["packages"].items()},
            "manifest_sha256": file_sha(MANIFEST)}


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("write", "verify"):
        raise SystemExit("usage: python_runtime.py write|verify")
    if sys.argv[1] == "write":
        MANIFEST.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(json.dumps(verify(), indent=2))
