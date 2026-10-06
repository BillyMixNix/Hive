from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from jvm_runner import run_jvm_profile


def run(command, *, timeout):
    try:
        cp = subprocess.run(command, cwd="/work", capture_output=True, text=True, timeout=timeout)
        return cp.returncode == 0, (cp.stdout + "\n" + cp.stderr)[-12000:]
    except subprocess.TimeoutExpired:
        return False, f"command timed out after {timeout}s"


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in {"full", "targeted", "jvm-full", "jvm-targeted"}:
        raise SystemExit(2)
    mode = sys.argv[1]
    selected = json.loads(sys.argv[2])
    if mode.startswith("jvm-"):
        if not isinstance(selected, dict):
            raise SystemExit(2)
        selected["mode"] = "full" if mode == "jvm-full" else "targeted"
        result = run_jvm_profile(Path("/source"), Path("/work"), selected)
        print(json.dumps(result, separators=(",", ":")))
        raise SystemExit(0 if result.get("passed") else 1)
    if not isinstance(selected, list):
        raise SystemExit(2)
    Path("/tmp/home").mkdir(parents=True, exist_ok=True)
    shutil.copytree("/source", "/work", dirs_exist_ok=True)
    checks = []

    py_files = sorted(Path("/work").rglob("*.py"))
    compile_errors = []
    for path in py_files:
        ok, detail = run([sys.executable, "-m", "py_compile", str(path)], timeout=20)
        if not ok:
            compile_errors.append([path.relative_to("/work").as_posix(), detail[-3000:]])
    checks.append({"name": "python_compile", "passed": not compile_errors,
                   "detail": "all Python files compile" if not compile_errors else json.dumps(compile_errors)[-10000:]})

    pytest_args = selected if mode == "targeted" else []
    ok, detail = run([sys.executable, "-m", "pytest", "-q", "--disable-warnings", "--maxfail=1",
                      "--basetemp", "/tmp/pytest", *pytest_args], timeout=60 if mode == "targeted" else 120)
    checks.append({"name": "targeted_pytest" if mode == "targeted" else "pytest", "passed": ok, "detail": detail})

    index = Path("/work/static/index.html")
    node = shutil.which("node")
    if index.exists():
        if not node:
            checks.append({"name": "javascript_parse", "passed": False, "detail": "Node is missing from verifier image"})
        else:
            match = re.search(r"<script>(.*?)</script>", index.read_text(encoding="utf-8"), re.S | re.I)
            if not match:
                checks.append({"name": "javascript_parse", "passed": False, "detail": "inline script block not found"})
            else:
                cp = subprocess.run([node, "--check"], input=match.group(1), text=True, capture_output=True, timeout=20)
                checks.append({"name": "javascript_parse", "passed": cp.returncode == 0,
                               "detail": (cp.stdout + cp.stderr)[-6000:] or "node --check passed"})

    report = {"passed": all(item["passed"] for item in checks), "checks": checks}
    print(json.dumps(report, separators=(",", ":")))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
