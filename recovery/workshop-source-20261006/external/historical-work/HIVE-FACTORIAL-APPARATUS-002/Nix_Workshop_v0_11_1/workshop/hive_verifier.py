from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path


DEFAULT_IMAGE = "nix-workshop-verifier:0.11.1-jvm21-extroot-002d-tmpfscopy"
MAX_OUTPUT_CHARS = 12_000
JVM_CONTAINER_LIMITS = {
    # NeoForm launches short-lived Java tools alongside the Gradle process.
    # The 320 container reproduced EAGAIN during the fresh full-gate setup;
    # retain a finite increment for NeoForm's transient thread burst.
    "pids": 384,
    "memory": "4g",
    # Docker defines memory-swap equal to memory as zero additional swap.
    "memory_swap": "4g",
    "cpus": 2,
    "gradle_max_workers": 2,
    "gradle_heap": "-Xmx768m",
}
ALLOWED_TOP_LEVEL = {"app.py", "pytest.ini", "requirements.txt", "workshop", "tests", "static"}
SENSITIVE_NAMES = {".env", "credentials", "credentials.json", "secrets.json"}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".db", ".sqlite", ".sqlite3"}


def _bounded(value: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    value = str(value or "")
    return value if len(value) <= limit else value[-limit:] + "\n[OUTPUT TRUNCATED]"


def _safe_relative(value: str) -> str:
    value = str(value or "").replace("\\", "/")
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", value):
        raise ValueError(f"unsafe verification path: {value!r}")
    return path.as_posix()


def _copy_verification_input(tree: Path, destination: Path) -> None:
    root = tree.resolve()
    for name in sorted(ALLOWED_TOP_LEVEL):
        source = root / name
        if not source.exists():
            continue
        if source.is_symlink():
            raise ValueError(f"verification input contains symlink: {name}")
        if source.is_file():
            if source.name.casefold() in SENSITIVE_NAMES or source.suffix.casefold() in SENSITIVE_SUFFIXES:
                continue
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination / name)
            continue
        for item in source.rglob("*"):
            if item.is_symlink():
                raise ValueError(f"verification input contains symlink: {item.relative_to(root).as_posix()}")
            if not item.is_file():
                continue
            rel = item.relative_to(root)
            lowered = {part.casefold() for part in rel.parts}
            if lowered & {"__pycache__", ".pytest_cache", ".git", ".venv", "venv", "node_modules"}:
                continue
            if item.name.casefold() in SENSITIVE_NAMES or item.suffix.casefold() in SENSITIVE_SUFFIXES:
                continue
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _failed(detail: str, *, image: str | None = None) -> dict:
    return {
        "passed": False,
        "checks": [{"name": "isolated_verifier", "passed": False, "detail": _bounded(detail)}],
        "isolation": {"backend": "docker", "image_ref": image or DEFAULT_IMAGE, "available": False},
    }


def run_isolated(
    tree: Path,
    mode: str,
    selected_files: list[str] | None = None,
    timeout: int = 150,
    *,
    external_root: bool = False,
    frozen_junit_tests: list[dict] | None = None,
    expected_jvm_profile: dict | None = None,
    expected_external_baseline_sha256: str | None = None,
) -> dict:
    """Execute fixed verification commands in a disposable, networkless container.

    No untrusted command text or host environment is forwarded.  Failure to
    locate the prebuilt verifier image is a verification failure; there is no
    host-execution fallback.
    """
    if mode not in {"full", "targeted"}:
        return _failed(f"unsupported verifier mode: {mode}")
    jvm_profile = None
    modules_cache = wrapper_cache = None
    native_assets_cache = native_artifacts_cache = None
    native_manifest_path = None
    native_manifest_sha256 = None
    if external_root:
        try:
            from . import hive_jvm
            jvm_profile = hive_jvm.inspect_gradle_project(Path(tree))
            if jvm_profile is not None:
                if not isinstance(expected_jvm_profile, dict) or jvm_profile != expected_jvm_profile:
                    return _failed(
                        "External Gradle wrapper differs from the immutable pre-model profile; verification is refused."
                    )
                if not frozen_junit_tests:
                    return _failed("External Gradle verification requires an explicit frozen JUnit acceptance manifest.")
                modules_cache, wrapper_cache = hive_jvm.gradle_cache_locations(jvm_profile)
        except Exception as exc:
            return _failed(f"External JVM verifier preflight failed: {type(exc).__name__}: {exc}")
    try:
        selected = [_safe_relative(item) for item in (selected_files or [])]
    except ValueError as exc:
        return _failed(str(exc))
    if jvm_profile is None and mode == "targeted" and any(not rel.startswith("tests/") or not rel.endswith(".py") for rel in selected):
        return _failed("targeted verifier accepts only Python files beneath tests/")

    docker = shutil.which("docker")
    configured_image = os.environ.get("NIX_HIVE_VERIFIER_IMAGE", DEFAULT_IMAGE).strip() or DEFAULT_IMAGE
    if jvm_profile is not None and configured_image != DEFAULT_IMAGE:
        return _failed("External JVM verification requires the fixed JDK 21 verifier image; image override is disabled.",
                       image=DEFAULT_IMAGE)
    image = DEFAULT_IMAGE if jvm_profile is not None else configured_image
    if not docker:
        return _failed("Docker is unavailable; Hive verification fails closed. Install/start Docker and build the pinned verifier image.", image=image)
    try:
        inspected = subprocess.run(
            [docker, "image", "inspect", image, "--format", "{{.Id}}"],
            capture_output=True, text=True, timeout=8,
        )
    except Exception as exc:
        return _failed(f"Verifier image preflight failed: {type(exc).__name__}: {exc}", image=image)
    if inspected.returncode != 0:
        return _failed(f"Verifier image is unavailable: {_bounded(inspected.stderr or inspected.stdout, 2000)}", image=image)
    image_id = (inspected.stdout or "").strip()

    parent = Path(tempfile.mkdtemp(prefix="hive-verifier-input-"))
    sanitized = parent / "source"
    container_name = f"hive-verify-{uuid.uuid4().hex[:12]}"
    try:
        if jvm_profile is not None:
            from .hive_jvm import copy_external_verification_input
            copy_external_verification_input(Path(tree), sanitized, frozen_junit_tests or [])
        else:
            _copy_verification_input(Path(tree), sanitized)
        mount_source = str(sanitized.resolve())
        if "," in mount_source:
            return _failed("Verifier source path contains a comma and cannot be mounted safely.", image=image)
        payload = json.dumps(selected, separators=(",", ":"))
        if jvm_profile is not None:
            payload = json.dumps({
                **jvm_profile,
                "frozen_tests": [{key: test[key] for key in ("path", "class_name", "expected_cases", "sha256")}
                                 for test in frozen_junit_tests or []],
                "targeted_timeout": min(max(int(timeout), 1), 240),
                "full_timeout": 600,
                "external_build_inputs_manifest_sha256": native_manifest_sha256,
            }, separators=(",", ":"))
            modules_mount = str(modules_cache.resolve(strict=True)).replace("\\", "/")
            wrapper_mount = str(wrapper_cache.resolve(strict=True)).replace("\\", "/")
            native_assets_mount = native_artifacts_mount = None
            if jvm_profile.get("external_build_inputs") is not None:
                try:
                    native_assets_cache, native_artifacts_cache = hive_jvm.external_build_input_locations(
                        jvm_profile,
                        baseline_sha256=expected_external_baseline_sha256,
                        container_image_id=image_id,
                    )
                except Exception as exc:
                    return _failed(
                        f"External build-input cache preflight failed: {type(exc).__name__}: {exc}", image=image
                    )
                native_assets_mount = str(native_assets_cache.resolve(strict=True)).replace("\\", "/")
                native_artifacts_mount = str(native_artifacts_cache.resolve(strict=True)).replace("\\", "/")
                run_cache_root = native_assets_cache.parents[2]
                evidence = run_cache_root.parent.parent / run_cache_root.name
                native_manifest_path = evidence / "external-build-inputs.manifest.json"
                if native_manifest_path.is_symlink() or not native_manifest_path.is_file():
                    return _failed("External build-input manifest disappeared after preflight.", image=image)
                manifest_bytes = native_manifest_path.read_bytes()
                if len(manifest_bytes) > 32_000_000:
                    return _failed("External build-input manifest exceeds its verification bound.", image=image)
                native_manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
            if ("," in modules_mount or "," in wrapper_mount
                    or (native_assets_mount is not None and "," in native_assets_mount)
                    or (native_artifacts_mount is not None and "," in native_artifacts_mount)
                    or (native_manifest_path is not None and "," in str(native_manifest_path))):
                return _failed("Gradle cache path contains a comma and cannot be mounted safely.", image=image)
            payload_object = json.loads(payload)
            payload_object["external_build_inputs_manifest_sha256"] = native_manifest_sha256
            payload = json.dumps(payload_object, separators=(",", ":"))
            container_mode = "jvm-full" if mode == "full" else "jvm-targeted"
            container_limit = JVM_CONTAINER_LIMITS["memory"]
            workspace_tmpfs = "/work:rw,nosuid,nodev,size=4g,mode=1777"
            timeout = min(max(int(timeout), 1), 660 if mode == "full" else 300)
        else:
            modules_mount = wrapper_mount = ""
            container_mode = mode
            container_limit = "1g"
            workspace_tmpfs = "/work:rw,nosuid,nodev,size=768m,mode=1777"
        command = [
            docker, "run", "--name", container_name, "--rm",
            "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit",
            str(JVM_CONTAINER_LIMITS["pids"] if jvm_profile is not None else 128),
            "--memory", container_limit,
            "--memory-swap", JVM_CONTAINER_LIMITS["memory_swap"] if jvm_profile is not None else container_limit,
            "--cpus", str(JVM_CONTAINER_LIMITS["cpus"] if jvm_profile is not None else 2),
            "--tmpfs", workspace_tmpfs,
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m,mode=1777",
            "--mount", f"type=bind,source={mount_source},target=/source,readonly",
            "--env", "HOME=/tmp/home", "--env", "TMPDIR=/tmp",
            "--env", "PYTHONDONTWRITEBYTECODE=1",
        ]
        if jvm_profile is not None:
            command.extend([
                "--mount", f"type=bind,source={modules_mount},target=/approved-gradle-cache/modules-2,readonly",
                "--mount", f"type=bind,source={wrapper_mount},target=/approved-gradle-cache/wrapper/dists/{Path(jvm_profile['distribution']).stem},readonly",
                "--env", "JAVA_HOME=/opt/java/openjdk",
                "--env", "GRADLE_USER_HOME=/work/gradle-user-home",
                "--env", "GRADLE_RO_DEP_CACHE=/approved-gradle-cache",
                "--env", "PATH=/opt/java/openjdk/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "--env", "LANG=C.UTF-8", "--env", "CI=true",
            ])
            if native_assets_cache is not None and native_artifacts_cache is not None:
                command.extend([
                    "--mount", f"type=bind,source={native_assets_mount},target=/approved-gradle-cache/neoformruntime/assets,readonly",
                    "--mount", f"type=bind,source={native_artifacts_mount},target=/approved-gradle-cache/neoformruntime/artifacts,readonly",
                    "--mount", f"type=bind,source={str(native_manifest_path.resolve(strict=True)).replace(chr(92), '/')},target=/tmp/hive-external-build-inputs.manifest.json,readonly",
                ])
        command.extend([
            image, container_mode, payload,
        ]
        )
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run([docker, "rm", "-f", container_name], capture_output=True, text=True, timeout=10)
            if jvm_profile is not None and native_assets_cache is not None:
                try:
                    hive_jvm.external_build_input_locations(
                        jvm_profile, baseline_sha256=expected_external_baseline_sha256,
                        container_image_id=image_id,
                    )
                except Exception as exc:
                    return _failed(f"External build-input cache integrity failed after timeout: {exc}", image=image)
            return _failed(f"Isolated verification timed out after {timeout}s.", image=image)
        if jvm_profile is not None and native_assets_cache is not None:
            try:
                hive_jvm.external_build_input_locations(
                    jvm_profile, baseline_sha256=expected_external_baseline_sha256,
                    container_image_id=image_id,
                )
            except Exception as exc:
                return _failed(f"External build-input cache integrity failed after verification: {exc}", image=image)
        try:
            report = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError):
            return _failed(
                f"Verifier returned invalid output (exit {result.returncode}): {_bounded(result.stdout + result.stderr)}",
                image=image,
            )
        if not isinstance(report, dict) or not isinstance(report.get("checks"), list):
            return _failed("Verifier report did not satisfy the expected schema.", image=image)
        report["passed"] = bool(report.get("passed")) and result.returncode == 0
        report["isolation"] = {
            "backend": "docker", "image_ref": image, "image_id": image_id,
            "available": True, "network": "none", "rootfs": "readonly",
            "source": "sanitized-readonly", "workspace": "tmpfs",
            "limits": {
                "pids": JVM_CONTAINER_LIMITS["pids"] if jvm_profile is not None else 128,
                "memory": container_limit,
                "memory_swap": JVM_CONTAINER_LIMITS["memory_swap"] if jvm_profile is not None else container_limit,
                "swap_additional": "0 bytes" if jvm_profile is not None else "0 bytes",
                "cpus": JVM_CONTAINER_LIMITS["cpus"] if jvm_profile is not None else 2,
            },
        }
        if jvm_profile is not None:
            report["isolation"].update({
                "java_runtime": "pinned JDK 21 in verifier image",
                "gradle_wrapper_version": jvm_profile["version"],
                "host_controlled_build_concurrency": {
                    "gradle_max_workers": JVM_CONTAINER_LIMITS["gradle_max_workers"],
                    "gradle_heap": JVM_CONTAINER_LIMITS["gradle_heap"],
                    "active_processor_count": 2,
                },
                "gradle_cache_mounts": "read-only wrapper distribution and modules-2 dependency cache",
                "inherited_host_environment": [],
            })
            if native_assets_cache is not None:
                report["isolation"]["external_build_input_mounts"] = (
                    "read-only manifest-verified inputs copied into private tmpfs for execution"
                )
        if result.stderr:
            report["runtime_stderr"] = _bounded(result.stderr, 3000)
        return report
    except Exception as exc:
        return _failed(f"Isolated verifier failed: {type(exc).__name__}: {exc}", image=image)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def targeted_verify_isolated(tree: Path, test_files: list[str], *, external_root: bool = False,
                              frozen_junit_tests: list[dict] | None = None,
                              expected_jvm_profile: dict | None = None,
                              expected_external_baseline_sha256: str | None = None) -> dict:
    return run_isolated(tree, "targeted", test_files, timeout=240 if external_root else 75,
                        external_root=external_root, frozen_junit_tests=frozen_junit_tests,
                        expected_jvm_profile=expected_jvm_profile,
                        expected_external_baseline_sha256=expected_external_baseline_sha256)


def verify_tree_isolated(tree: Path, *, external_root: bool = False,
                         frozen_junit_tests: list[dict] | None = None,
                         expected_jvm_profile: dict | None = None,
                         expected_external_baseline_sha256: str | None = None) -> dict:
    return run_isolated(tree, "full", timeout=660 if external_root else 150,
                        external_root=external_root, frozen_junit_tests=frozen_junit_tests,
                        expected_jvm_profile=expected_jvm_profile,
                        expected_external_baseline_sha256=expected_external_baseline_sha256)
