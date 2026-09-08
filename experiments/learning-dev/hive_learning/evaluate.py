"""Independent tests run on a copied candidate, outside the recipient workspace.

This is a trusted local development bench, not an OS sandbox for hostile code.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def validate_files(files):
    if not isinstance(files, dict) or not files or len(files) > 30:
        raise ValueError("files must be a nonempty mapping of at most 30 files")
    for name, content in files.items():
        path = PurePosixPath(name)
        if (not isinstance(name, str) or path.is_absolute() or ".." in path.parts
                or "\\" in name or ":" in name or any(part.startswith(".") for part in path.parts)
                or name != path.as_posix() or not name.endswith(".py")
                or path.name in {"conftest.py", "sitecustomize.py", "usercustomize.py"}):
            raise ValueError("invalid development fixture path")
        if not isinstance(content, str) or len(content.encode()) > 100_000:
            raise ValueError("fixture file too large or not text")


def read_suite(path, expected_sha256):
    raw = Path(path).read_bytes()
    if len(raw) > 2_000_000 or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("suite bytes do not match commitment")
    suite = strict_json(raw)
    if set(suite) != {"schema", "suite_id", "cases"} or suite["schema"] != "hive.learning.suite.v1":
        raise ValueError("invalid suite schema")
    cases = suite["cases"]
    if not isinstance(cases, list) or not 3 <= len(cases) <= 12:
        raise ValueError("suite needs 3–12 cases")
    ids, fixture_hashes, splits = set(), set(), set()
    for case in cases:
        if set(case) != {"id", "split", "goal", "files", "protected_tests"}:
            raise ValueError("invalid case fields")
        if not isinstance(case["id"], str) or not case["id"] or case["id"] in ids:
            raise ValueError("case IDs must be unique")
        ids.add(case["id"])
        if case["split"] not in {"trigger", "transfer", "retention"}:
            raise ValueError("invalid split")
        splits.add(case["split"])
        if not isinstance(case["goal"], str) or not 1 <= len(case["goal"]) <= 8000:
            raise ValueError("invalid goal")
        validate_files(case["files"])
        validate_files(case["protected_tests"])
        if any(not PurePosixPath(p).name.startswith("test_") for p in case["protected_tests"]):
            raise ValueError("protected tests must use test_ filenames")
        if set(case["files"]) & set(case["protected_tests"]):
            raise ValueError("protected tests overlap public files")
        key = json.dumps(case["files"], sort_keys=True)
        if key in fixture_hashes:
            raise ValueError("duplicate fixture bytes across cases")
        fixture_hashes.add(key)
    if splits != {"trigger", "transfer", "retention"}:
        raise ValueError("trigger, transfer, and retention cases are all required")
    return suite


def write_files(root, files):
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def candidate_snapshot(root, baseline):
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("recipient produced a symlink")
        relative = path.relative_to(root).as_posix()
        # Hive's logs and interpreter/test caches are not candidate source.
        if any(part in {".agent_runs", "__pycache__", ".pytest_cache"} for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            if relative not in baseline or path.stat().st_size > 100_000:
                raise ValueError("recipient created an unapproved file")
            result[relative] = path.read_text(encoding="utf-8")
    if set(result) != set(baseline):
        raise ValueError("recipient removed a fixture file")
    for name, original in baseline.items():
        if PurePosixPath(name).name.startswith("test_") and result[name] != original:
            raise ValueError("recipient changed a protected public test")
    return result


def grade(candidate, protected_tests, timeout=30):
    with tempfile.TemporaryDirectory(prefix="hive-independent-eval-") as temp:
        root = Path(temp)
        write_files(root, {**candidate, **protected_tests})
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("PYTHON", "PYTEST"))}
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            process = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                cwd=root, env=env, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return {"passed": False, "valid": False, "reason": "evaluator timeout"}
        return {"passed": process.returncode == 0,
                "valid": process.returncode in (0, 1), "exit_code": process.returncode,
                "output_sha256": hashlib.sha256((process.stdout + process.stderr).encode()).hexdigest()}
