"""Container-side, network-enabled Gradle dependency-cache priming only.

This is deliberately not part of the verifier entrypoint or verification
mode. The host wrapper launches it only after explicit operator opt-in.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

try:  # Host tests import this as a package; the image runs it as a script.
    from verification.jvm_runner import _bounded_process, _source_digest
except ModuleNotFoundError:  # pragma: no cover - exercised in the verifier image
    from jvm_runner import _bounded_process, _source_digest


JAVA_HOME = "/opt/java/openjdk"
JAVA_VERSION_RE = re.compile(r'\bversion\s+"(21(?:\.[0-9]+){0,3}(?:\+[0-9A-Za-z._-]+)?)"')
GRADLE_TASK_RE = re.compile(r"^:?[A-Za-z][A-Za-z0-9_:-]*$")
FAILED_TASK_RE = re.compile(r"(?m)^> Task (:[A-Za-z0-9_:-]+) FAILED\s*$")
NETWORK_INPUT_FAILURE_RE = re.compile(
    r"UnknownHostException|UnresolvedAddressException|ConnectException|"
    r"NoRouteToHostException|SocketTimeoutException|Could not (?:GET|HEAD|resolve)|"
    r"Failed to (?:download|connect)|Could not resolve all files|"
    r"Could not find (?:any matches for )?.*required by",
    re.IGNORECASE,
)
TEST_FAILURE_RE = re.compile(
    r"There were failing tests|tests? failed|AssertionFailedError|Failures:\s*[1-9]|"
    r"failed to execute tests|GameTest.*(?:failed|failure)|Missing test structure:", re.IGNORECASE,
)
MAX_PROFILE_BYTES = 64_000
PRIME_TIMEOUT_SECONDS = 1800
MAX_PRIME_LOG_BYTES = 128_000
MAX_PRIME_EVENTS = 5000
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


class _PrimeOutputFacts:
    """Retain bounded task/network/source facts without storing unbounded logs."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = {"stdout": "", "stderr": ""}
        self._urls = set()
        self._failed_tasks = set()
        self._artifact_task_seen = False
        self._artifact_task_failed = False
        self._network_failure = False
        self._test_failure = False
        self._lines = []

    def __call__(self, stream: str, chunk: bytes) -> None:
        text = chunk.decode("utf-8", errors="replace")
        with self._lock:
            combined = self._pending[stream] + text
            lines = combined.splitlines(keepends=True)
            self._pending[stream] = ""
            if lines and not lines[-1].endswith(("\n", "\r")):
                self._pending[stream] = lines.pop()
            for raw in lines:
                self._observe_line(raw.rstrip("\r\n"))

    def _observe_line(self, line: str) -> None:
        short = line[:2048]
        task = re.match(r"^> Task (:[A-Za-z0-9_:-]+)(?:\s+(.*))?$", short)
        if task:
            name, status = task.group(1), (task.group(2) or "").strip()
            if name == ":createMinecraftArtifacts":
                self._artifact_task_seen = True
                if status.upper() == "FAILED":
                    self._artifact_task_failed = True
            if status.upper() == "FAILED":
                self._failed_tasks.add(name)
        if NETWORK_INPUT_FAILURE_RE.search(short):
            self._network_failure = True
        if TEST_FAILURE_RE.search(short):
            self._test_failure = True
        if URL_RE.search(short) and re.search(r"download|\bGET\b|\bHEAD\b|\bHTTP\b|\u2193", short, re.I):
            for url in URL_RE.findall(short):
                if len(self._urls) < MAX_PRIME_EVENTS:
                    self._urls.add(url.rstrip(".,);]}"))
        if (task or NETWORK_INPUT_FAILURE_RE.search(short) or TEST_FAILURE_RE.search(short)):
            if len(self._lines) < MAX_PRIME_EVENTS:
                self._lines.append(short)

    def snapshot(self) -> dict:
        with self._lock:
            for stream, pending in self._pending.items():
                if pending:
                    self._observe_line(pending)
                    self._pending[stream] = ""
            return {
                "observed_urls": sorted(self._urls),
                "failed_tasks": sorted(self._failed_tasks),
                "create_minecraft_artifacts_seen": self._artifact_task_seen,
                "create_minecraft_artifacts_failed": self._artifact_task_failed,
                "network_or_input_failure_seen": self._network_failure,
                "test_failure_seen": self._test_failure,
                "diagnostic_lines": self._lines[-200:],
            }


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_profile(source: Path, profile: dict) -> list[str]:
    if not isinstance(profile, dict):
        raise ValueError("priming profile must be an object")
    tasks = profile.get("full_tasks")
    if (not isinstance(tasks, list) or not tasks or len(tasks) > 64
            or any(not isinstance(task, str) or not GRADLE_TASK_RE.fullmatch(task) for task in tasks)):
        raise ValueError("priming requires statically validated Gradle task identifiers")
    version = str(profile.get("version", ""))
    if (not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", version)
            or profile.get("distribution") not in {f"gradle-{version}-bin.zip", f"gradle-{version}-all.zip"}):
        raise ValueError("priming requires a valid checked-in Gradle wrapper profile")
    native = profile.get("external_build_inputs")
    if native is not None and (not isinstance(native, dict)
            or native != {"kind": "neoformruntime", "cache_relative": "caches/neoformruntime",
                          "input_directories": ["artifacts", "assets"]}):
        raise ValueError("priming requires a statically detected, allowlisted native input-cache profile")
    wrapper = source / "gradle" / "wrapper"
    jar, properties = wrapper / "gradle-wrapper.jar", wrapper / "gradle-wrapper.properties"
    if (_digest(jar) != profile.get("wrapper_jar_sha256")
            or _digest(properties) != profile.get("wrapper_properties_sha256")):
        raise ValueError("checked-in Gradle Wrapper changed after host preflight")
    return tasks


def _prime_outcome(run: dict, facts: dict, tasks: list[str], gradle_home: Path,
                   profile: dict, source_unchanged: bool) -> dict:
    output = f"{run.get('stdout', '')}\n{run.get('stderr', '')}"
    failed_tasks = sorted(set(FAILED_TASK_RE.findall(output)) | set(facts.get("failed_tasks", [])))
    artifact_seen = bool(facts.get("create_minecraft_artifacts_seen")) or bool(re.search(
        r"(?m)^> Task :createMinecraftArtifacts(?:\s|$)", output
    ))
    artifact_failed = bool(facts.get("create_minecraft_artifacts_failed")) or ":createMinecraftArtifacts" in failed_tasks
    completed_artifact_task = artifact_seen and not artifact_failed
    network_failure = bool(facts.get("network_or_input_failure_seen")) or bool(NETWORK_INPUT_FAILURE_RE.search(output))
    test_failure = bool(facts.get("test_failure_seen")) or bool(TEST_FAILURE_RE.search(output))
    native_spec = profile.get("external_build_inputs")
    native_counts = {}
    if native_spec is not None:
        native_root = gradle_home.joinpath(*native_spec["cache_relative"].split("/"))
        for name in native_spec["input_directories"]:
            directory = native_root / name
            native_counts[name] = sum(1 for p in directory.rglob("*") if p.is_file() and not p.is_symlink()) if directory.is_dir() else 0
    native_cache_ready = native_spec is None or all(native_counts.get(name, 0) > 0
                                                    for name in native_spec["input_directories"])
    if network_failure or (native_spec is not None and artifact_failed):
        failure_classification = "external_input_acquisition_failure"
    elif run.get("returncode") == 0 and not run.get("timed_out"):
        failure_classification = None
    elif test_failure or any(task.endswith(("runGameTestServer", "runQuestTestServer")) for task in failed_tasks):
        failure_classification = "application_or_test_failure"
    else:
        failure_classification = "gradle_execution_failure"
    # Priming is successful when required external inputs were materialized,
    # even if a disposable application/GameTest task itself fails. Verification
    # remains the separate, authoritative offline pass/fail gate.
    input_ready = (source_unchanged and native_cache_ready and not network_failure and not artifact_failed
                   and not run.get("timed_out")
                   and (native_spec is None or completed_artifact_task))
    application_test_diagnostics = [
        line for line in facts.get("diagnostic_lines", [])
        if isinstance(line, str) and TEST_FAILURE_RE.search(line)
    ]
    game_test_task_failed = any(task.endswith(("runGameTestServer", "runQuestTestServer"))
                                for task in failed_tasks)
    return {
        "failed_tasks": failed_tasks,
        "failure_classification": failure_classification,
        "network_or_dependency_acquisition_failure": bool(network_failure or artifact_failed),
        "create_minecraft_artifacts_completed": completed_artifact_task,
        "native_cache_file_counts": native_counts,
        "native_cache_ready": native_cache_ready,
        "external_inputs_primed": input_ready,
        "full_gate_passed": run.get("returncode") == 0 and not run.get("timed_out"),
        "application_or_test_failure_observed": bool(test_failure or game_test_task_failed),
        "application_test_diagnostics": application_test_diagnostics[-50:],
        "statically_requested_tasks": tasks,
    }


def run_priming(profile: dict) -> dict:
    """Resolve the candidate's complete documented task graph into the cache."""
    source = Path("/source").resolve(strict=True)
    work = Path("/work")
    project = work / "candidate"
    gradle_home = Path("/approved-gradle-cache").resolve(strict=True)
    tasks = _validate_profile(source, profile)
    source_before = _source_digest(source)
    work.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, project, symlinks=False)
    if not gradle_home.is_dir() or not os.access(gradle_home, os.W_OK):
        raise ValueError("dedicated approved Gradle cache mount is not writable")
    (Path("/tmp/home")).mkdir(parents=True, exist_ok=True)
    (Path("/tmp/tmp")).mkdir(parents=True, exist_ok=True)

    env = {
        "JAVA_HOME": JAVA_HOME,
        "GRADLE_USER_HOME": str(gradle_home),
        "HOME": "/tmp/home",
        "TMPDIR": "/tmp/tmp",
        "PATH": f"{JAVA_HOME}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "CI": "true",
    }
    # GRADLE_RO_DEP_CACHE is intentionally absent: priming uses the dedicated
    # writable Gradle user home; verification separately mounts modules-2 RO.
    java_argv = [f"{JAVA_HOME}/bin/java", "-version"]
    java = _bounded_process(java_argv, cwd=project, env=env, timeout=15)
    java_text = java.get("stderr", "") + java.get("stdout", "")
    match = JAVA_VERSION_RE.search(java_text)
    if java.get("returncode") != 0 or java.get("timed_out") or not match:
        raise ValueError("pinned Java 21 runtime is missing or unsupported")

    gradle_argv = [
        f"{JAVA_HOME}/bin/java", "-Djava.io.tmpdir=/tmp/tmp", "-classpath",
        "gradle/wrapper/gradle-wrapper.jar", "org.gradle.wrapper.GradleWrapperMain",
        "--no-daemon", "--console=plain", "--info", "--continue", "--max-workers=2",
        "--rerun-tasks", "--no-build-cache", "-Dorg.gradle.jvmargs=-Xmx768m",
        *tasks,
    ]
    started = time.monotonic()
    facts_collector = _PrimeOutputFacts()
    run = _bounded_process(
        gradle_argv, cwd=project, env=env, timeout=PRIME_TIMEOUT_SECONDS,
        max_log_bytes=MAX_PRIME_LOG_BYTES, output_observer=facts_collector,
    )
    elapsed = round(time.monotonic() - started, 3)
    source_unchanged = source_before == _source_digest(source)
    facts = facts_collector.snapshot()
    outcome = _prime_outcome(run, facts, tasks, gradle_home, profile, source_unchanged)
    report = {
        "mode": "dependency_cache_priming",
        "cache_priming_succeeded": outcome["external_inputs_primed"],
        "java_version": match.group(1),
        "gradle_wrapper_version": profile["version"],
        "full_gate_tasks": tasks,
        "task_outcome": outcome,
        "output_facts": facts,
        "commands": [
            {"phase": "java_version", "argv": java_argv, "returncode": java.get("returncode")},
            {
                "phase": "resolve_documented_gradle_graph",
                "argv": gradle_argv,
                "returncode": run.get("returncode"),
                "timed_out": bool(run.get("timed_out")),
                "wall_seconds": elapsed,
            },
        ],
        "source_unchanged": source_unchanged,
        "stdout_tail": run.get("stdout", "")[-12000:],
        "stderr_tail": run.get("stderr", "")[-12000:],
    }
    return report


def main() -> int:
    if len(sys.argv) != 2 or len(sys.argv[1]) > MAX_PROFILE_BYTES:
        raise SystemExit("prime_runner expects exactly one bounded profile JSON argument")
    try:
        profile = json.loads(sys.argv[1])
        report = run_priming(profile)
    except Exception as exc:
        report = {
            "mode": "dependency_cache_priming",
            "cache_priming_succeeded": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    print(json.dumps(report, separators=(",", ":")), flush=True)
    return 0 if report.get("cache_priming_succeeded") else 1


if __name__ == "__main__":
    raise SystemExit(main())
