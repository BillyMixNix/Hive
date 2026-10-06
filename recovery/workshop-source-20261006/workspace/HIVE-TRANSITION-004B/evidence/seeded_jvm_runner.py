"""Fixed-command Gradle/JUnit profile executed only inside the verifier container."""

from __future__ import annotations

import hashlib
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections import deque
from pathlib import Path


MAX_LOG_BYTES = 12_000
MAX_SOURCE_FILES = 100_000
MAX_SOURCE_BYTES = 1_000_000_000
MAX_JUNIT_REPORTS = 5_000
MAX_JUNIT_REPORT_BYTES = 2_000_000
MAX_JUNIT_TOTAL_BYTES = 32_000_000
MAX_EXTERNAL_INPUT_COPY_BYTES = 1_500_000_000
MAX_EXTERNAL_INPUT_FILES = 100_000
EXTERNAL_INPUT_MANIFEST = Path("/tmp/hive-external-build-inputs.manifest.json")
JAVA_HOME = "/opt/java/openjdk"
GRADLE_VERSION_RE = re.compile(r'\bversion\s+"(21(?:\.[0-9]+){0,3}(?:\+[0-9A-Za-z._-]+)?)"')
TEST_CLASS_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*$")
GRADLE_TASK_RE = re.compile(r"^:?[A-Za-z][A-Za-z0-9_:-]*$")
NETWORK_ATTEMPT_RE = re.compile(
    r"UnknownHostException|UnresolvedAddressException|ConnectException|"
    r"NoRouteToHostException|SocketTimeoutException|Could not (?:GET|HEAD|resolve)|"
    r"Failed to (?:download|connect)|Connection timed out",
    re.IGNORECASE,
)
RUNTIME_DIRS = {".git", ".gradle", "build", "target", "__pycache__", ".pytest_cache", "node_modules"}
APPROVED_RUNTIME_OUTPUT_DIRS = {"run-gametest", "run-questtest"}

_TRACE_START = time.monotonic()
_TRACE_LOCK = threading.Lock()
_TRACE_OUTPUT_BYTES = 0
_TRACE_OUTPUT_LIMIT = 2_000_000


def _event(phase, **fields):
    """Diagnostic-only stderr stream; stdout remains the final gate report."""
    if not os.environ.get("HIVE_VERIFICATION_RUN_ID"):
        return
    try:
        with _TRACE_LOCK:
            now = time.monotonic()
            row = {"monotonic": now, "wall_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   "run_id": os.environ["HIVE_VERIFICATION_RUN_ID"], "phase": phase,
                   "pid": os.getpid(), "elapsed_ms": round((now-_TRACE_START)*1000,3),
                   "clock_domain": "container", **fields}
            print("HIVE_VERIFIER_EVENT "+json.dumps(row,ensure_ascii=False), file=sys.stderr, flush=True)
    except Exception:
        # Observability may not change a gate's decision or block pipe drains.
        pass


def _observe_output(label, chunk, pid):
    global _TRACE_OUTPUT_BYTES
    if not os.environ.get("HIVE_VERIFICATION_RUN_ID"): return
    old = _TRACE_OUTPUT_BYTES
    _TRACE_OUTPUT_BYTES += len(chunk)
    if old < _TRACE_OUTPUT_LIMIT:
        text = chunk[:_TRACE_OUTPUT_LIMIT-old].decode("utf-8",errors="replace")
        _event("process_output", stream=label, child_pid=pid, text=text)
        for line in text.splitlines():
            if line.startswith("> Task ") or line.startswith("> Configure ") or "Daemon" in line:
                _event("gradle_output_marker", child_pid=pid, marker=line[:1000])
    if old < _TRACE_OUTPUT_LIMIT <= _TRACE_OUTPUT_BYTES:
        _event("output_diagnostic_limit", retained_bytes=_TRACE_OUTPUT_LIMIT)


def _bounded_process(argv, *, cwd: Path, env: dict, timeout: int, process_factory=None,
                     max_log_bytes: int = MAX_LOG_BYTES, output_observer=None):
    """Run an argv-only command while retaining a bounded tail of each stream."""
    process_factory = process_factory or subprocess.Popen
    started = time.monotonic()
    _event("process_launch_requested", argv=list(argv), cwd=str(cwd), timeout_seconds=timeout)
    process = process_factory(
        argv, cwd=str(cwd), env=env, shell=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    _event("process_launched", child_pid=getattr(process,"pid",None))
    streams = {"stdout": deque(), "stderr": deque()}
    sizes = {"stdout": 0, "stderr": 0}

    def drain(label, stream):
        while True:
            chunk = getattr(stream, "read1", stream.read)(4096)
            if not chunk:
                return
            _observe_output(label, chunk, getattr(process,"pid",None))
            if output_observer is not None:
                try:
                    output_observer(label, chunk)
                except Exception:
                    # Diagnostics must never prevent a pipe from being drained.
                    pass
            buf = streams[label]
            buf.append(chunk)
            sizes[label] += len(chunk)
            while sizes[label] > max_log_bytes and buf:
                overflow = sizes[label] - max_log_bytes
                first = buf[0]
                if len(first) <= overflow:
                    sizes[label] -= len(buf.popleft())
                else:
                    buf[0] = first[overflow:]
                    sizes[label] -= overflow

    readers = [threading.Thread(target=drain, args=(label, getattr(process, label)), daemon=True)
               for label in ("stdout", "stderr")]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _event("inner_timeout_fired", child_pid=getattr(process,"pid",None), timeout_seconds=timeout)
        process.kill()
        return_code = process.wait()
    for reader in readers:
        reader.join(timeout=5)
    _event("process_exit", child_pid=getattr(process,"pid",None), returncode=return_code, timed_out=timed_out,
           readers_finished=all(not r.is_alive() for r in readers))
    def tail(label):
        return b"".join(streams[label]).decode("utf-8", errors="replace")
    return {
        "returncode": return_code,
        "stdout": tail("stdout"),
        "stderr": tail("stderr"),
        "timed_out": timed_out,
        "wall_seconds": round(time.monotonic() - started, 3),
    }


def _validated_runtime_output_dirs(values) -> tuple[str, ...]:
    if (not isinstance(values, list)
            or any(not isinstance(value, str) for value in values)
            or len(values) != len(set(values))):
        raise ValueError("pinned Gradle runtime-output directories must be a unique list")
    if any(value not in APPROVED_RUNTIME_OUTPUT_DIRS for value in values):
        raise ValueError("Gradle runtime-output directory is not in the host-approved policy")
    return tuple(values)


def _validate_runtime_output_roots(root: Path, runtime_output_dirs: tuple[str, ...]) -> None:
    for name in runtime_output_dirs:
        path = root / name
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if path.is_symlink() or not path.is_dir():
            raise ValueError(f"approved Gradle runtime-output root is not a real directory: {name}")


def _runtime_output_manifest(root: Path, runtime_output_dirs: tuple[str, ...]) -> dict[str, str]:
    """Hash only files present before Gradle; newly generated runtime files are disposable."""
    _validate_runtime_output_roots(root, runtime_output_dirs)
    manifest: dict[str, str] = {}
    count = total = 0
    for name in runtime_output_dirs:
        start = root / name
        if not start.exists():
            continue
        for current, dirs, files in os.walk(start, topdown=True, followlinks=False):
            base = Path(current)
            dirs.sort(key=lambda value: (value.casefold(), value))
            for dirname in dirs:
                child = base / dirname
                if child.is_symlink() or not child.is_dir():
                    raise ValueError(f"Gradle runtime-output tree contains a linked/special directory: {child.relative_to(root)}")
            for filename in sorted(files, key=lambda value: (value.casefold(), value)):
                path = base / filename
                if path.is_symlink() or not path.is_file():
                    raise ValueError(f"Gradle runtime-output tree contains a linked/special file: {path.relative_to(root)}")
                rel = path.relative_to(root).as_posix()
                size = path.stat().st_size
                count += 1
                total += size
                if count > MAX_SOURCE_FILES or total > MAX_SOURCE_BYTES:
                    raise ValueError("pre-existing Gradle runtime output exceeds JVM profile input bounds")
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                manifest[rel] = digest.hexdigest()
    return manifest


def _changed_preexisting_runtime_files(root: Path, runtime_output_dirs: tuple[str, ...],
                                       before: dict[str, str]) -> list[str]:
    try:
        _validate_runtime_output_roots(root, runtime_output_dirs)
    except ValueError as exc:
        return [str(exc)]
    changed = []
    for rel, expected in before.items():
        path = root.joinpath(*rel.split("/"))
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root.resolve(strict=True))
            for parent in path.parents:
                if parent == root:
                    break
                if parent.is_symlink():
                    raise ValueError("runtime path contains a symlink")
            if path.is_symlink() or not path.is_file():
                raise ValueError("runtime file disappeared or changed type")
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                changed.append(rel)
        except (OSError, RuntimeError, ValueError):
            changed.append(rel)
    return changed


def _source_digest(root: Path, runtime_output_dirs=()) -> str:
    root = Path(root).resolve(strict=True)
    approved_runtime_dirs = _validated_runtime_output_dirs(list(runtime_output_dirs))
    _validate_runtime_output_roots(root, approved_runtime_dirs)
    digest = hashlib.sha256()
    count = total = 0
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        relative_base = base.relative_to(root)
        retained = []
        for name in dirs:
            child = base / name
            if relative_base == Path(".") and name in approved_runtime_dirs:
                if child.is_symlink() or not child.is_dir():
                    raise ValueError(f"approved Gradle runtime-output root is not a real directory: {name}")
                continue
            if name.casefold() not in RUNTIME_DIRS:
                retained.append(name)
        dirs[:] = sorted(retained, key=lambda value: (value.casefold(), value))
        for name in sorted(files, key=lambda value: (value.casefold(), value)):
            path = base / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"verification candidate contains a link or special file: {path.relative_to(root)}")
            rel = path.relative_to(root).as_posix()
            size = path.stat().st_size
            total += size
            count += 1
            if count > MAX_SOURCE_FILES or total > MAX_SOURCE_BYTES:
                raise ValueError("verification candidate exceeds JVM profile input bounds")
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
            digest.update(b"\0")
    return digest.hexdigest()


def _copy_wrapper_distribution(source: Path, gradle_home: Path, version: str) -> None:
    destination = gradle_home / "wrapper" / "dists" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError("Gradle wrapper cache destination already exists")
    copied = False
    for entry in sorted(source.iterdir(), key=lambda item: item.name):
        if entry.is_symlink() or not entry.is_dir():
            continue
        distribution = entry / f"gradle-{version}"
        executable = distribution / "bin" / "gradle"
        if not executable.is_file() or executable.is_symlink():
            continue
        target = destination / entry.name
        shutil.copytree(entry, target, symlinks=False)
        executable_copy = target / f"gradle-{version}" / "bin" / "gradle"
        executable_copy.chmod(executable_copy.stat().st_mode | 0o111)
        copied = True
    if not copied:
        raise ValueError(f"exact Gradle {version} distribution is missing from the approved read-only cache")


def _copy_external_build_inputs(gradle_home: Path, approved_cache: Path, spec: dict,
                                manifest_path: Path, expected_manifest_sha256: str) -> dict:
    """Verify read-only inputs and copy them into the bounded private tmpfs cache.

    NeoForm updates timestamps on some downloaded metadata even when the bytes
    are already cached. The approved bind mounts therefore stay read-only while
    the hash-verified inputs are copied into this run's disposable Gradle home.
    """
    if (not isinstance(spec, dict) or spec.get("kind") != "neoformruntime"
            or spec.get("cache_relative") != "caches/neoformruntime"
            or set(spec.get("input_directories", [])) != {"artifacts", "assets"}):
        raise ValueError("unsupported external build-input cache layout")
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_manifest_sha256 or "")):
        raise ValueError("external build-input manifest hash is missing or invalid")
    manifest_path = Path(manifest_path)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("read-only external build-input manifest is missing or linked")
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_manifest_sha256:
        raise ValueError("external build-input manifest hash mismatch")
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("external build-input manifest is invalid JSON") from exc
    entries = manifest.get("files") if isinstance(manifest, dict) else None
    if (manifest.get("schema_version") != 1
            or manifest.get("cache_relative") != "caches/neoformruntime"
            or not isinstance(entries, list) or not entries or len(entries) > MAX_EXTERNAL_INPUT_FILES):
        raise ValueError("external build-input manifest has an unsupported schema or inventory")
    expected = {}
    total_bytes = 0
    for item in entries:
        rel = item.get("path") if isinstance(item, dict) else None
        parts = rel.split("/") if isinstance(rel, str) else []
        if (not parts or parts[0] not in {"artifacts", "assets"}
                or any(part in {"", ".", ".."} for part in parts)
                or "\\" in rel or rel.startswith("/")
                or not isinstance(item.get("size"), int) or item["size"] < 0
                or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))
                or rel in expected):
            raise ValueError("external build-input manifest contains an unsafe or duplicate file")
        expected[rel] = (item["size"], item["sha256"])
        total_bytes += item["size"]
        if total_bytes > MAX_EXTERNAL_INPUT_COPY_BYTES:
            raise ValueError("external build-input cache exceeds the bounded tmpfs copy budget")

    approved_root = approved_cache.resolve(strict=True)
    native_cache = gradle_home / "caches" / "neoformruntime"
    native_cache.mkdir(parents=True, exist_ok=True)
    native_source = approved_root / "neoformruntime"
    actual = set()
    for name in ("artifacts", "assets"):
        source = approved_root / "neoformruntime" / name
        if source.is_symlink() or not source.is_dir():
            raise ValueError(f"manifested NeoForm input mount is missing or unsafe: {name}")
        resolved = source.resolve(strict=True)
        try:
            resolved.relative_to(approved_root)
        except ValueError as exc:
            raise ValueError(f"NeoForm input mount escapes approved cache: {name}") from exc
        for current, dirs, files in os.walk(source, topdown=True, followlinks=False):
            base = Path(current)
            for directory in dirs:
                if (base / directory).is_symlink():
                    raise ValueError("read-only NeoForm input mount contains a linked directory")
            for filename in files:
                item_path = base / filename
                if item_path.is_symlink() or not item_path.is_file():
                    raise ValueError("read-only NeoForm input mount contains a link or special file")
                actual.add(item_path.relative_to(native_source).as_posix())
    if actual != set(expected):
        raise ValueError("read-only NeoForm input inventory differs from the frozen manifest")

    copied = 0
    for rel in sorted(expected):
        size_expected, hash_expected = expected[rel]
        source = native_source.joinpath(*rel.split("/"))
        target = native_cache.joinpath(*rel.split("/"))
        if source.stat().st_size != size_expected:
            raise ValueError(f"manifested external build-input size mismatch: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        copied_size = 0
        with source.open("rb") as src, target.open("xb") as dst:
            while chunk := src.read(1024 * 1024):
                copied_size += len(chunk)
                digest.update(chunk)
                dst.write(chunk)
        if copied_size != size_expected or digest.hexdigest() != hash_expected:
            raise ValueError(f"manifested external build-input hash mismatch while copying: {rel}")
        copied += copied_size
    return {"files": len(expected), "bytes": copied,
            "manifest_sha256": expected_manifest_sha256,
            "approved_cache_mount": "read-only", "verification_copy": "private tmpfs"}


def _clear_build_outputs(project: Path) -> None:
    outputs = []
    for path in project.rglob("build"):
        if path.is_dir() and not path.is_symlink():
            outputs.append(path)
    for path in sorted(outputs, key=lambda value: len(value.parts), reverse=True):
        shutil.rmtree(path)


def _validate_frozen_tests(project: Path, frozen_tests: list[dict]) -> list[str]:
    classes = []
    for item in frozen_tests:
        rel = str(item.get("path", ""))
        class_name = str(item.get("class_name", ""))
        expected_path_class = ".".join(rel.removeprefix("src/test/java/")[:-5].split("/"))
        if (not rel.startswith("src/test/java/") or not rel.endswith(".java")
                or ".." in rel.split("/") or class_name != expected_path_class
                or not TEST_CLASS_RE.fullmatch(class_name)
                or not isinstance(item.get("expected_cases"), int)
                or isinstance(item.get("expected_cases"), bool) or item["expected_cases"] < 1):
            raise ValueError("frozen JUnit manifest contains an invalid path, class, or expected-case count")
        path = project.joinpath(*rel.split("/"))
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"frozen JUnit acceptance source is missing: {rel}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != item.get("sha256"):
            raise ValueError(f"frozen JUnit acceptance source was modified: {rel}")
        classes.append(class_name)
    if not classes:
        raise ValueError("Gradle profile requires at least one frozen JUnit acceptance test")
    return classes


def _reports(project: Path) -> tuple[list[dict], str | None]:
    files = []
    for current, dirs, names in os.walk(project, topdown=True, followlinks=False):
        base = Path(current)
        if any((base / name).is_symlink() for name in dirs):
            return [], "Gradle output contains a symlinked directory; report collection failed closed"
        dirs[:] = sorted(name for name in dirs if not (base / name).is_symlink())
        relative = base.relative_to(project).parts
        if len(relative) >= 3 and relative[-3:] == ("build", "test-results", "test"):
            files.extend(base / name for name in names if name.startswith("TEST-") and name.endswith(".xml"))
    files.sort(key=lambda p: p.as_posix())
    if not files:
        return [], "Gradle exited without fresh JUnit XML reports"
    if len(files) > MAX_JUNIT_REPORTS:
        return [], "Gradle produced more JUnit XML reports than the bounded verifier can inspect"
    total_bytes = 0
    for path in files:
        if path.is_symlink() or not path.is_file():
            return [], "Gradle output contains a linked or special JUnit report"
        size = path.stat().st_size
        total_bytes += size
        if size > MAX_JUNIT_REPORT_BYTES or total_bytes > MAX_JUNIT_TOTAL_BYTES:
            return [], "Gradle JUnit XML reports exceed the bounded report-size limit"
    totals: dict[str, dict] = {}
    all_cases = 0
    for path in files:
        try:
            suite = ET.parse(path).getroot()
        except (OSError, ET.ParseError) as exc:
            return [], f"invalid JUnit XML report {path.relative_to(project).as_posix()}: {exc}"
        for case in suite.findall(".//testcase"):
            class_name = case.attrib.get("classname") or suite.attrib.get("name", "")
            row = totals.setdefault(class_name, {"tests": 0, "failures": 0, "errors": 0, "skipped": 0})
            row["tests"] += 1
            all_cases += 1
            row["failures"] += len(case.findall("failure"))
            row["errors"] += len(case.findall("error"))
            row["skipped"] += len(case.findall("skipped"))
    if all_cases == 0:
        return [], "JUnit XML reports contained no executed test cases"
    return [{"class_name": key, **value} for key, value in sorted(totals.items())], None


def _result_check(name: str, command_result: dict, reports: list[dict] | None = None) -> dict:
    detail = {
        "returncode": command_result.get("returncode"),
        "timed_out": bool(command_result.get("timed_out")),
        "wall_seconds": command_result.get("wall_seconds"),
        "stdout_tail": command_result.get("stdout", "")[-MAX_LOG_BYTES:],
        "stderr_tail": command_result.get("stderr", "")[-MAX_LOG_BYTES:],
    }
    if reports is not None:
        detail["tests"] = reports
    passed = command_result.get("returncode") == 0 and not command_result.get("timed_out")
    return {"name": name, "passed": passed, "detail": detail}


def _network_attempt_failure(name: str, command_result: dict) -> dict | None:
    combined = f"{command_result.get('stdout', '')}\n{command_result.get('stderr', '')}"
    match = NETWORK_ATTEMPT_RE.search(combined)
    if not match:
        return None
    excerpt = combined[max(0, match.start() - 300):min(len(combined), match.end() + 500)]
    return {
        "name": f"network_access_attempt:{name}",
        "passed": False,
        "detail": "External verification attempted network access inside the network-disabled verifier: " + excerpt,
    }


def run_jvm_profile(source: Path, work_root: Path, config: dict, *, process_runner=None,
                    approved_cache_root: Path = Path("/approved-gradle-cache")) -> dict:
    """Run frozen acceptance tests, then fixed full `check`, in a tmpfs tree."""
    process_runner = process_runner or _bounded_process
    checks = []
    work_root = Path(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    project = work_root / "candidate"
    gradle_home = Path(work_root) / "gradle-user-home"
    approved_cache = Path(approved_cache_root)
    try:
        _event("container_verifier_started", mode=config.get("mode"))
        _event("project_materialization_started")
        shutil.copytree(source, project, symlinks=False)
        _event("project_available", project=str(project))
        frozen_classes = _validate_frozen_tests(project, config.get("frozen_tests", []))
        _event("frozen_tests_validated", classes=frozen_classes)
        full_tasks = config.get("full_tasks", ["check"])
        if (not isinstance(full_tasks, list) or not 1 <= len(full_tasks) <= 64
                or any(not isinstance(task, str) or not GRADLE_TASK_RE.fullmatch(task)
                       for task in full_tasks)):
            raise ValueError("pinned Gradle regression gate contains an invalid task identifier")
        runtime_output_dirs = _validated_runtime_output_dirs(config.get("runtime_output_dirs", []))
        distribution_name = config["distribution"].removesuffix(".zip")
        _event("wrapper_copy_started")
        _copy_wrapper_distribution(approved_cache / "wrapper" / "dists" / distribution_name,
                                   gradle_home, config["version"])
        _event("wrapper_copy_complete", gradle_version=config["version"])
        (gradle_home / "caches").mkdir(parents=True, exist_ok=True)
        external_copy = None
        external_spec = config.get("external_build_inputs")
        if external_spec is not None:
            _event("external_inputs_copy_started")
            external_copy = _copy_external_build_inputs(
                gradle_home, approved_cache, external_spec, EXTERNAL_INPUT_MANIFEST,
                config.get("external_build_inputs_manifest_sha256"),
            )
            _event("external_inputs_copy_complete", details=external_copy)
        (Path(work_root) / "home").mkdir(parents=True, exist_ok=True)
        (Path(work_root) / "tmp").mkdir(parents=True, exist_ok=True)
        env = {
            "JAVA_HOME": JAVA_HOME,
            "GRADLE_USER_HOME": str(gradle_home),
            # Gradle appends `modules-2` to this root when resolving its
            # shared read-only dependency cache.
            "GRADLE_RO_DEP_CACHE": str(approved_cache),
            "HOME": str(Path(work_root) / "home"),
            "TMPDIR": str(Path(work_root) / "tmp"),
            "PATH": f"{JAVA_HOME}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8",
            "CI": "true",
        }
        _event("java_detection_started", environment=env)
        java = process_runner([f"{JAVA_HOME}/bin/java", "-version"], cwd=project, env=env, timeout=15)
        version_output = java.get("stderr", "") + java.get("stdout", "")
        match = GRADLE_VERSION_RE.search(version_output)
        if java.get("returncode") != 0 or java.get("timed_out") or not match:
            raise ValueError("pinned Java 21 runtime is missing or unsupported")
        java_version = match.group(1)
        _event("java_detected", version=java_version)
        report = {"passed": False, "checks": checks, "java_version": java_version,
                  "gradle_wrapper_version": config["version"], "full_gate_tasks": full_tasks,
                  "executed_commands": []}
        if external_copy is not None:
            report["external_build_inputs_copy"] = external_copy

        _event("source_hashing_started")
        runtime_before = _runtime_output_manifest(project, runtime_output_dirs)
        source_before = _source_digest(project, runtime_output_dirs)
        _clear_build_outputs(project)
        _event("source_hashing_complete")
        targeted_argv = [
            f"{JAVA_HOME}/bin/java", "-Djava.io.tmpdir=/work/tmp", "-classpath",
            "gradle/wrapper/gradle-wrapper.jar", "org.gradle.wrapper.GradleWrapperMain",
            "--no-daemon", "--offline", "--console=plain", "--max-workers=2",
            "--rerun-tasks", "--no-build-cache", "-Dorg.gradle.jvmargs=-Xmx768m",
            "test",
        ]
        for class_name in frozen_classes:
            targeted_argv.extend(["--tests", class_name])
        report["executed_commands"].append({"phase": "targeted_junit", "argv": targeted_argv})
        _event("gradle_invoked", gate="targeted_junit", argv=targeted_argv)
        targeted = process_runner(targeted_argv, cwd=project, env=env, timeout=int(config.get("targeted_timeout", 240)))
        _event("gradle_returned", gate="targeted_junit", returncode=targeted.get("returncode"), timed_out=targeted.get("timed_out"))
        targeted_reports, report_error = _reports(project)
        _event("junit_reports_collected", reports=targeted_reports, error=report_error)
        targeted_check = _result_check("frozen_junit_acceptance", targeted, targeted_reports)
        for item in config.get("frozen_tests", []):
            matches = [row for row in targeted_reports if row["class_name"] == item["class_name"]]
            observed = sum(row["tests"] for row in matches)
            failures = sum(row["failures"] + row["errors"] + row["skipped"] for row in matches)
            if observed != item["expected_cases"] or failures:
                targeted_check["passed"] = False
                targeted_check["detail"].setdefault("acceptance_mismatches", []).append({
                    "class_name": item["class_name"], "expected_cases": item["expected_cases"],
                    "observed_cases": observed, "failures_errors_skipped": failures,
                })
        if report_error:
            targeted_check["passed"] = False
            targeted_check["detail"]["report_error"] = report_error
        checks.append(targeted_check)
        network_failure = _network_attempt_failure("targeted_junit", targeted)
        if network_failure:
            checks.append(network_failure)
        runtime_changes = _changed_preexisting_runtime_files(project, runtime_output_dirs, runtime_before)
        if source_before != _source_digest(project, runtime_output_dirs) or runtime_changes:
            checks.append({"name": "source_immutability", "passed": False,
                           "detail": "Gradle acceptance execution mutated protected source" +
                           (f" or pre-existing runtime files: {runtime_changes[:20]}" if runtime_changes else "" )})
            report["checks"] = checks
            return report
        if not targeted_check["passed"]:
            report["checks"] = checks
            return report

        if config.get("mode") == "targeted":
            checks.append({"name": "source_immutability", "passed": True,
                           "detail": "non-generated candidate source remained unchanged"})
            report["checks"] = checks
            report["passed"] = all(item["passed"] for item in checks)
            report["runtime_output_dirs"] = list(runtime_output_dirs)
            return report

        _clear_build_outputs(project)
        full_argv = [
            f"{JAVA_HOME}/bin/java", "-Djava.io.tmpdir=/work/tmp", "-classpath",
            "gradle/wrapper/gradle-wrapper.jar", "org.gradle.wrapper.GradleWrapperMain",
            "--no-daemon", "--offline", "--console=plain", "--max-workers=2",
            "--rerun-tasks", "--no-build-cache", "-Dorg.gradle.jvmargs=-Xmx768m", *full_tasks,
        ]
        report["executed_commands"].append({"phase": "full_gradle_check", "argv": full_argv})
        _event("gradle_invoked", gate="full_gradle_check", argv=full_argv)
        full = process_runner(full_argv, cwd=project, env=env, timeout=int(config.get("full_timeout", 600)))
        _event("gradle_returned", gate="full_gradle_check", returncode=full.get("returncode"), timed_out=full.get("timed_out"))
        full_reports, full_error = _reports(project)
        full_check = _result_check("full_gradle_check", full, full_reports)
        if any(row["failures"] or row["errors"] for row in full_reports):
            full_check["passed"] = False
            full_check["detail"]["reported_test_failures"] = True
        if full_error:
            full_check["passed"] = False
            full_check["detail"]["report_error"] = full_error
        checks.append(full_check)
        network_failure = _network_attempt_failure("full_gradle_check", full)
        if network_failure:
            checks.append(network_failure)
        runtime_changes = _changed_preexisting_runtime_files(project, runtime_output_dirs, runtime_before)
        if source_before != _source_digest(project, runtime_output_dirs) or runtime_changes:
            checks.append({"name": "source_immutability", "passed": False,
                           "detail": "Gradle full verification mutated protected source" +
                           (f" or pre-existing runtime files: {runtime_changes[:20]}" if runtime_changes else "" )})
        else:
            checks.append({"name": "source_immutability", "passed": True,
                           "detail": "non-generated candidate source remained unchanged"})
        report["checks"] = checks
        report["passed"] = all(item["passed"] for item in checks)
        report["runtime_output_dirs"] = list(runtime_output_dirs)
        return report
    except subprocess.TimeoutExpired as exc:
        checks.append({"name": "gradle_timeout", "passed": False,
                       "detail": f"Gradle verification timed out after {exc.timeout}s"})
    except Exception as exc:
        checks.append({"name": "jvm_profile", "passed": False,
                       "detail": f"{type(exc).__name__}: {exc}"})
    return {"passed": False, "checks": checks, "gradle_wrapper_version": config.get("version"),
            "executed_commands": []}


# Appended only to a diagnostic copy of the unchanged runner. Never installed.
_diagnostic_original_copy = _copy_external_build_inputs
def _copy_external_build_inputs(*args, **kwargs):
    result = _diagnostic_original_copy(*args, **kwargs)
    _event('diagnostic_intermediate_seed_started')
    manifest_file = Path('/probe/evidence/seed-manifest.json')
    raw = manifest_file.read_bytes()
    expected = os.environ['HIVE_DIAGNOSTIC_SEED_MANIFEST_SHA256']
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('diagnostic seed manifest hash mismatch')
    manifest = json.loads(raw)
    entries = manifest['entries']
    source = Path('/diagnostic-intermediates')
    destination = Path(args[0]) / 'caches/neoformruntime/intermediate_results'
    if destination.exists():
        raise ValueError('diagnostic generated-cache destination is not fresh')
    if {p.name for p in source.iterdir()} != {r['path'] for r in entries}:
        raise ValueError('diagnostic seed inventory mismatch')
    if len(entries) != 22 or sum(r['size'] for r in entries) != 163178447:
        raise ValueError('diagnostic frozen seed differs from measured bounded inventory')
    destination.mkdir()
    for row in entries:
        name = row['path']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            raise ValueError('unsafe diagnostic seed filename')
        original = source/name
        if original.is_symlink() or not original.is_file():
            raise ValueError('linked or nonfile diagnostic seed')
        target = destination/name
        shutil.copyfile(original, target)
        if target.stat().st_size != row['size'] or hashlib.sha256(target.read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('diagnostic seed content mismatch')
    _event('diagnostic_intermediate_seed_complete', count=len(entries),bytes=sum(r['size'] for r in entries),
           manifest_sha256=expected)
    return result
