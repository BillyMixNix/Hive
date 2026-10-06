from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app
from verification import jvm_runner
from workshop import external_root, hive, hive_jvm, hive_verifier, runtime


_REAL_VERIFY_TREE_ISOLATED = hive_verifier.verify_tree_isolated


TEST_PATH = "src/test/java/example/WidgetAcceptanceTest.java"
TEST_CLASS = "example.WidgetAcceptanceTest"
TEST_SOURCE = "package example; class WidgetAcceptanceTest { @org.junit.jupiter.api.Test void accepted() {} }\n"


def _frozen_spec(source=TEST_SOURCE):
    return {"path": TEST_PATH, "class_name": TEST_CLASS, "expected_cases": 1, "source": source}


def _project(tmp_path: Path):
    root = tmp_path / "project"
    wrapper = root / "gradle" / "wrapper"
    main = root / "src" / "main" / "java" / "example"
    main.mkdir(parents=True)
    wrapper.mkdir(parents=True)
    (main / "Widget.java").write_text(
        "package example; class Widget { int value() { return 1; } }\n", encoding="utf-8"
    )
    (root / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")
    (root / "settings.gradle").write_text("rootProject.name = 'fixture'\n", encoding="utf-8")
    (root / "gradlew").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (wrapper / "gradle-wrapper.jar").write_bytes(b"trusted checked-in wrapper jar fixture")
    (wrapper / "gradle-wrapper.properties").write_text(
        "distributionUrl=https\\://services.gradle.org/distributions/gradle-9.2.1-bin.zip\n"
        "distributionSha256Sum=" + "a" * 64 + "\n", encoding="utf-8"
    )
    profile = hive_jvm.inspect_gradle_project(root)
    frozen = hive_jvm.freeze_junit_tests(root, [_frozen_spec()])
    frozen_file = root / TEST_PATH
    frozen_file.parent.mkdir(parents=True)
    frozen_file.write_text(TEST_SOURCE, encoding="utf-8", newline="\n")
    return root, profile, frozen


def test_runtime_output_dirs_require_literal_host_approved_neoforge_run_configuration(tmp_path):
    root, _, _ = _project(tmp_path)
    (root / "build.gradle").write_text(
        """neoForge {
  runs {
    gameTestServer {
      gameDirectory = project.file('run-gametest')
    }
    questTestServer {
      gameDirectory = project.file(\"run-questtest\")
    }
  }
}
""",
        encoding="utf-8",
    )
    profile = hive_jvm.inspect_gradle_project(root)
    assert profile["runtime_output_dirs"] == ["run-gametest", "run-questtest"]

    (root / "build.gradle").write_text(
        """// gameTestServer { gameDirectory = project.file('run-gametest') }
def note = \"questTestServer { gameDirectory = project.file('run-questtest') }\"
neoForge { runs { gameTestServer { gameDirectory = project.file(outputDir) } } }
""",
        encoding="utf-8",
    )
    assert hive_jvm.inspect_gradle_project(root)["runtime_output_dirs"] == []
    (root / "build.gradle").write_text(
        "def pattern = /neoForge { runs { gameTestServer { gameDirectory = project.file('run-gametest') } } }/\n",
        encoding="utf-8",
    )
    assert hive_jvm.inspect_gradle_project(root)["runtime_output_dirs"] == []


def test_source_digest_excludes_only_declared_runtime_outputs_and_protects_preexisting_files(tmp_path):
    root, profile, frozen = _project(tmp_path)
    (root / "build.gradle").write_text(
        "neoForge { runs { gameTestServer { gameDirectory = project.file('run-gametest') } } }\n",
        encoding="utf-8",
    )
    profile = hive_jvm.inspect_gradle_project(root)
    runtime_dir = root / "run-gametest"
    runtime_dir.mkdir()
    preexisting = runtime_dir / "operator-config.toml"
    preexisting.write_text("keep immutable", encoding="utf-8")
    original_digest = jvm_runner._source_digest(root, profile["runtime_output_dirs"])
    (runtime_dir / "logs").mkdir()
    (runtime_dir / "logs" / "latest.log").write_text("generated output", encoding="utf-8")
    assert jvm_runner._source_digest(root, profile["runtime_output_dirs"]) == original_digest

    baseline = jvm_runner._runtime_output_manifest(root, tuple(profile["runtime_output_dirs"]))
    preexisting.write_text("changed", encoding="utf-8")
    assert jvm_runner._changed_preexisting_runtime_files(
        root, tuple(profile["runtime_output_dirs"]), baseline
    ) == ["run-gametest/operator-config.toml"]


def test_runtime_output_exclusion_rejects_unapproved_or_linked_roots(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    with pytest.raises(ValueError, match="host-approved"):
        jvm_runner._source_digest(root, ["arbitrary-output"])
    try:
        (root / "run-gametest").symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlinks are unavailable on this platform: {exc}")
    else:
        with pytest.raises(ValueError, match="real directory"):
            jvm_runner._source_digest(root, ["run-gametest"])


def _cached_gradle(tmp_path: Path):
    root = tmp_path / "gradle-home"
    modules = root / "caches" / "modules-2"
    distribution = root / "wrapper" / "dists" / "gradle-9.2.1-bin" / "hash" / "gradle-9.2.1" / "bin"
    modules.mkdir(parents=True)
    distribution.mkdir(parents=True)
    (distribution / "gradle").write_text("cached distribution marker\n", encoding="utf-8")
    return root


def _neoform_approved_cache(tmp_path: Path, profile: dict, *, run_id="a1b2c3d4e5f6",
                            baseline="a" * 64, image="sha256:" + "b" * 64):
    runs = tmp_path / "hive_runs"
    evidence = runs / run_id
    cache = runs / "approved-gradle-caches" / run_id
    modules = cache / "caches" / "modules-2"
    distribution = cache / "wrapper" / "dists" / "gradle-9.2.1-bin" / "hash" / "gradle-9.2.1" / "bin"
    modules.mkdir(parents=True)
    distribution.mkdir(parents=True)
    (distribution / "gradle").write_text("cached distribution", encoding="utf-8")
    native = cache / "caches" / "neoformruntime"
    assets = native / "assets" / "indexes"
    artifacts = native / "artifacts"
    assets.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    (assets / "17.json").write_text('{"objects":{}}', encoding="utf-8")
    (artifacts / "version.json").write_text('{"version":"1.21.1"}', encoding="utf-8")
    profile_fields = {key: profile.get(key) for key in (
        "version", "distribution_sha256", "wrapper_jar_sha256", "wrapper_properties_sha256",
        "verification_policy_sha256",
    )}
    rows = []
    for path in (assets / "17.json", artifacts / "version.json"):
        rows.append({
            "path": path.relative_to(native).as_posix(), "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source_url": None, "source_repository": None,
        })
    manifest = {
        "schema_version": 1, "cache_relative": "caches/neoformruntime",
        "baseline_sha256": baseline, "container_image_id": image,
        "gradle_wrapper": profile_fields, "files": rows,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    evidence.mkdir(parents=True)
    (evidence / "external-build-inputs.manifest.json").write_bytes(manifest_bytes)
    (evidence / "external-build-inputs.provenance.json").write_text(json.dumps({
        "external_build_inputs_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "baseline_sha256": baseline, "container_image_id": image,
        "cache_priming_succeeded": True,
    }), encoding="utf-8")
    return cache, assets.parent, artifacts, baseline, image


def _neoform_profile(root: Path):
    (root / "build.gradle").write_text(
        "plugins { id 'java'; id 'net.neoforged.moddev' version '2.0.147' }\n", encoding="utf-8"
    )
    return hive_jvm.inspect_gradle_project(root)


def _write_report(project: Path, *, classname=TEST_CLASS, count=1, skipped=0, failed=0):
    reports = project / "build" / "test-results" / "test"
    reports.mkdir(parents=True, exist_ok=True)
    cases = "".join(
        f'<testcase classname="{classname}" name="case{i}">'
        f'{"<skipped/>" if i < skipped else ""}{"<failure/>" if i < failed else ""}</testcase>'
        for i in range(count)
    )
    (reports / "TEST-example.xml").write_text(
        f'<testsuite name="{classname}" tests="{count}">{cases}</testsuite>', encoding="utf-8"
    )


def _config(profile, frozen, mode="full"):
    return {
        **profile,
        "mode": mode,
        "targeted_timeout": 240,
        "full_timeout": 600,
        "frozen_tests": [{key: item[key] for key in ("path", "class_name", "expected_cases", "sha256")}
                         for item in frozen],
    }


def _successful_runner(calls):
    def runner(argv, *, cwd, env, timeout):
        calls.append((list(argv), Path(cwd), dict(env), timeout))
        if argv[-1] == "-version":
            return {"returncode": 0, "stdout": "", "stderr": 'openjdk version "21.0.12" 2026-01-20\n',
                    "timed_out": False, "wall_seconds": 0.01}
        _write_report(Path(cwd))
        return {"returncode": 0, "stdout": "BUILD SUCCESSFUL", "stderr": "",
                "timed_out": False, "wall_seconds": 1.25}
    return runner


def test_valid_wrapper_runs_frozen_acceptance_then_full_check_in_candidate(tmp_path):
    root, profile, frozen = _project(tmp_path)
    profile["full_tasks"] = ["clean", "build", "integrationTest"]
    cache = tmp_path / "approved-gradle-cache"
    dists = cache / "wrapper" / "dists" / "gradle-9.2.1-bin" / "hash" / "gradle-9.2.1" / "bin"
    dists.mkdir(parents=True)
    (dists / "gradle").write_text("cached distribution", encoding="utf-8")
    (cache / "modules-2").mkdir(parents=True)
    calls = []

    hostile_profile = _config(profile, frozen)
    hostile_profile.update({
        "pids_limit": 1,
        "memory_limit": "64m",
        "max_workers": 99,
        "jvm_args": "-XX:ActiveProcessorCount=64",
    })
    result = jvm_runner.run_jvm_profile(
        root, tmp_path / "container-work", hostile_profile,
        process_runner=_successful_runner(calls), approved_cache_root=cache,
    )

    assert result["passed"] is True
    assert [item["phase"] for item in result["executed_commands"]] == ["targeted_junit", "full_gradle_check"]
    targeted_argv = result["executed_commands"][0]["argv"]
    full_argv = result["executed_commands"][1]["argv"]
    assert "org.gradle.wrapper.GradleWrapperMain" in targeted_argv
    assert "gradlew" not in targeted_argv[0]
    assert targeted_argv[-2:] == ["--tests", TEST_CLASS]
    assert targeted_argv[-3] == "test"
    assert "--max-workers=2" in targeted_argv and "--max-workers=2" in full_argv
    assert "-Dorg.gradle.jvmargs=-Xmx768m" in targeted_argv
    assert not any("ActiveProcessorCount=64" in str(item) for item in targeted_argv + full_argv)
    assert full_argv[-3:] == ["clean", "build", "integrationTest"]
    assert all(call[1] == tmp_path / "container-work" / "candidate" for call in calls)
    assert all(call[2]["GRADLE_USER_HOME"].endswith("gradle-user-home") for call in calls)
    assert all(call[2]["GRADLE_RO_DEP_CACHE"] == str(cache) for call in calls)
    assert all((Path(call[2]["GRADLE_RO_DEP_CACHE"]) / "modules-2").is_dir() for call in calls)
    assert all(not (Path(call[2]["GRADLE_RO_DEP_CACHE"]) / "modules-2" / "modules-2").exists()
               for call in calls)
    assert all("OPENAI_API_KEY" not in call[2] and "USERPROFILE" not in call[2] for call in calls)
    assert result["java_version"] == "21.0.12"
    assert result["gradle_wrapper_version"] == "9.2.1"
    assert result["full_gate_tasks"] == ["clean", "build", "integrationTest"]


def test_neoform_native_inputs_are_verified_and_copied_to_private_gradle_tmpfs(tmp_path):
    approved = tmp_path / "approved-gradle-cache"
    native = approved / "neoformruntime"
    payloads = {"assets/indexes/17.json": b'{"objects":{}}',
                "artifacts/version.json": b'{"id":"1.21.1"}'}
    rows = []
    for rel, payload in payloads.items():
        path = native / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        rows.append({"path": rel, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
    manifest = {"schema_version": 1, "cache_relative": "caches/neoformruntime", "files": rows}
    manifest_path = tmp_path / "manifest.json"
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest_path.write_bytes(manifest_bytes)
    gradle_home = tmp_path / "work" / "gradle-user-home"
    result = jvm_runner._copy_external_build_inputs(gradle_home, approved, {
        "kind": "neoformruntime", "cache_relative": "caches/neoformruntime",
        "input_directories": ["artifacts", "assets"],
    }, manifest_path, hashlib.sha256(manifest_bytes).hexdigest())
    copied = gradle_home / "caches" / "neoformruntime"
    assert result["files"] == 2
    assert result["bytes"] == sum(map(len, payloads.values()))
    assert result["approved_cache_mount"] == "read-only"
    assert result["verification_copy"] == "private tmpfs"
    for rel, payload in payloads.items():
        assert (copied / rel).read_bytes() == payload
        assert not (copied / rel).is_symlink()
    assert not (gradle_home / "wrapper").exists()


def test_neoform_native_input_copy_rejects_manifest_hash_mismatch(tmp_path):
    approved = tmp_path / "approved-gradle-cache"
    native = approved / "neoformruntime"
    for name in ("assets", "artifacts"):
        (native / name).mkdir(parents=True)
    manifest = {"schema_version": 1, "cache_relative": "caches/neoformruntime", "files": [
        {"path": f"{name}/empty", "size": 0, "sha256": hashlib.sha256(b"").hexdigest()}
        for name in ("assets", "artifacts")
    ]}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest hash mismatch"):
        jvm_runner._copy_external_build_inputs(tmp_path / "work", approved, {
            "kind": "neoformruntime", "cache_relative": "caches/neoformruntime",
            "input_directories": ["artifacts", "assets"],
        }, manifest_path, "0" * 64)


def test_targeted_junit_requires_exact_fresh_report_and_count(tmp_path):
    root, profile, frozen = _project(tmp_path)
    cache = tmp_path / "cache"
    dists = cache / "wrapper" / "dists" / "gradle-9.2.1-bin" / "hash" / "gradle-9.2.1" / "bin"
    dists.mkdir(parents=True)
    (dists / "gradle").write_text("distribution", encoding="utf-8")
    (cache / "modules-2").mkdir(parents=True)
    calls = []

    result = jvm_runner.run_jvm_profile(root, tmp_path / "work", _config(profile, frozen, "targeted"),
                                        process_runner=_successful_runner(calls), approved_cache_root=cache)

    assert result["passed"] is True
    assert len(calls) == 2  # Java version, then exact JUnit class; no full-suite command.
    assert [check["name"] for check in result["checks"]] == ["frozen_junit_acceptance", "source_immutability"]


def test_missing_wrapper_and_missing_exact_distribution_fail_closed(tmp_path, monkeypatch):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "build.gradle").write_text("plugins { id 'java' }\n", encoding="utf-8")
    with pytest.raises(hive_jvm.JVMProfileError, match="missing its checked-in"):
        hive_jvm.inspect_gradle_project(plain)

    root, profile, _ = _project(tmp_path)
    home = tmp_path / "empty-gradle-home"
    (home / "caches" / "modules-2").mkdir(parents=True)
    (home / "wrapper" / "dists" / "gradle-9.2.1-bin").mkdir(parents=True)
    monkeypatch.setenv("GRADLE_USER_HOME", str(home))
    with pytest.raises(hive_jvm.JVMProfileError, match="network fallback is disabled"):
        hive_jvm.gradle_cache_locations(profile)


def test_checked_in_full_gate_is_static_task_only_and_rejects_freeform_arguments(tmp_path):
    root, _, _ = _project(tmp_path)
    policy = root / "VERIFICATION.md"
    policy.write_text(
        "# Verification\n\n## Exact commands\n\n"
        "```powershell\n.\\gradlew.bat clean build integrationTest --console=plain\n"
        "python tools/collect-results.py\n```\n",
        encoding="utf-8",
    )
    profile = hive_jvm.inspect_gradle_project(root)
    assert profile["full_tasks"] == ["clean", "build", "integrationTest"]
    assert profile["verification_policy_sha256"]

    policy.write_text(
        "## Exact commands\n```powershell\n.\\gradlew.bat build --init-script=C:\\temp\\inject.gradle\n```\n",
        encoding="utf-8",
    )
    with pytest.raises(hive_jvm.JVMProfileError, match="unsupported option"):
        hive_jvm.inspect_gradle_project(root)


def test_nonzero_exit_and_timeout_are_failures(tmp_path):
    root, profile, frozen = _project(tmp_path)
    cache = tmp_path / "cache"
    dists = cache / "wrapper" / "dists" / "gradle-9.2.1-bin" / "hash" / "gradle-9.2.1" / "bin"
    dists.mkdir(parents=True)
    (dists / "gradle").write_text("distribution", encoding="utf-8")
    (cache / "modules-2").mkdir(parents=True)

    def fail(argv, **kwargs):
        if argv[-1] == "-version":
            return {"returncode": 0, "stdout": "", "stderr": 'openjdk version "21.0.12"', "timed_out": False}
        _write_report(kwargs["cwd"])
        return {"returncode": 1, "stdout": "failure", "stderr": "test failed", "timed_out": False}

    failed = jvm_runner.run_jvm_profile(root, tmp_path / "nonzero-work", _config(profile, frozen),
                                        process_runner=fail, approved_cache_root=cache)
    assert failed["passed"] is False
    assert failed["checks"][0]["passed"] is False

    def timed_out(argv, **kwargs):
        if argv[-1] == "-version":
            return {"returncode": 0, "stdout": "", "stderr": 'openjdk version "21.0.12"', "timed_out": False}
        return {"returncode": -9, "stdout": "", "stderr": "", "timed_out": True}

    timeout = jvm_runner.run_jvm_profile(root, tmp_path / "timeout-work", _config(profile, frozen),
                                         process_runner=timed_out, approved_cache_root=cache)
    assert timeout["passed"] is False
    assert timeout["checks"][0]["detail"]["timed_out"] is True


def test_verifier_fails_closed_when_gradle_output_reports_network_attempt(tmp_path):
    root, profile, frozen = _project(tmp_path)
    cache = tmp_path / "cache"
    dists = cache / "wrapper" / "dists" / "gradle-9.2.1-bin" / "hash" / "gradle-9.2.1" / "bin"
    dists.mkdir(parents=True)
    (dists / "gradle").write_text("distribution", encoding="utf-8")
    (cache / "modules-2").mkdir(parents=True)

    def network_attempt(argv, **kwargs):
        if argv[-1] == "-version":
            return {"returncode": 0, "stdout": "", "stderr": 'openjdk version "21.0.12"', "timed_out": False}
        _write_report(Path(kwargs["cwd"]))
        return {"returncode": 0, "stdout": "UnresolvedAddressException while fetching an input", "stderr": "",
                "timed_out": False}

    result = jvm_runner.run_jvm_profile(
        root, tmp_path / "network-attempt-work", _config(profile, frozen, "targeted"),
        process_runner=network_attempt, approved_cache_root=cache,
    )
    assert result["passed"] is False
    assert any(check["name"] == "network_access_attempt:targeted_junit" and not check["passed"]
               for check in result["checks"])


def test_stale_or_missing_report_cannot_pass_on_zero_exit(tmp_path):
    root, profile, frozen = _project(tmp_path)
    stale = root / "build" / "test-results" / "test"
    stale.mkdir(parents=True)
    _write_report(root)
    cache = tmp_path / "cache"
    dists = cache / "wrapper" / "dists" / "gradle-9.2.1-bin" / "hash" / "gradle-9.2.1" / "bin"
    dists.mkdir(parents=True)
    (dists / "gradle").write_text("distribution", encoding="utf-8")
    (cache / "modules-2").mkdir(parents=True)

    def no_reports(argv, **kwargs):
        if argv[-1] == "-version":
            return {"returncode": 0, "stdout": "", "stderr": 'openjdk version "21.0.12"', "timed_out": False}
        return {"returncode": 0, "stdout": "BUILD SUCCESSFUL", "stderr": "", "timed_out": False}

    result = jvm_runner.run_jvm_profile(root, tmp_path / "work", _config(profile, frozen),
                                        process_runner=no_reports, approved_cache_root=cache)
    assert result["passed"] is False
    assert "fresh JUnit XML reports" in result["checks"][0]["detail"]["report_error"]


@pytest.mark.parametrize("mutation", ["frozen_test", "unowned_source"])
def test_verification_source_mutation_is_rejected(tmp_path, mutation):
    root, profile, frozen = _project(tmp_path)
    cache = tmp_path / "cache"
    dists = cache / "wrapper" / "dists" / "gradle-9.2.1-bin" / "hash" / "gradle-9.2.1" / "bin"
    dists.mkdir(parents=True)
    (dists / "gradle").write_text("distribution", encoding="utf-8")
    (cache / "modules-2").mkdir(parents=True)

    def mutate(argv, **kwargs):
        cwd = Path(kwargs["cwd"])
        if argv[-1] == "-version":
            return {"returncode": 0, "stdout": "", "stderr": 'openjdk version "21.0.12"', "timed_out": False}
        destination = cwd / (TEST_PATH if mutation == "frozen_test" else "src/main/java/example/Widget.java")
        destination.write_text("tampered by Gradle", encoding="utf-8")
        _write_report(cwd)
        return {"returncode": 0, "stdout": "BUILD SUCCESSFUL", "stderr": "", "timed_out": False}

    result = jvm_runner.run_jvm_profile(root, tmp_path / "work", _config(profile, frozen),
                                        process_runner=mutate, approved_cache_root=cache)
    assert result["passed"] is False
    assert result["checks"][-1]["name"] == "source_immutability"
    assert result["checks"][-1]["passed"] is False


def test_declared_game_test_runtime_files_are_disposable_but_not_copied_back(tmp_path):
    root, profile, frozen = _project(tmp_path)
    (root / "build.gradle").write_text(
        "neoForge { runs { gameTestServer { gameDirectory = project.file('run-gametest') } } }\n",
        encoding="utf-8",
    )
    profile = hive_jvm.inspect_gradle_project(root)
    config = _config(profile, frozen)
    cache = tmp_path / "cache"
    dists = cache / "wrapper" / "dists" / "gradle-9.2.1-bin" / "hash" / "gradle-9.2.1" / "bin"
    dists.mkdir(parents=True)
    (dists / "gradle").write_text("distribution", encoding="utf-8")
    (cache / "modules-2").mkdir(parents=True)

    def writes_runtime_output(argv, **kwargs):
        cwd = Path(kwargs["cwd"])
        if argv[-1] == "-version":
            return {"returncode": 0, "stdout": "", "stderr": 'openjdk version "21.0.12"', "timed_out": False}
        (cwd / "run-gametest" / "logs").mkdir(parents=True, exist_ok=True)
        (cwd / "run-gametest" / "logs" / "latest.log").write_text("server output", encoding="utf-8")
        _write_report(cwd)
        return {"returncode": 0, "stdout": "BUILD SUCCESSFUL", "stderr": "", "timed_out": False}

    work = tmp_path / "verifier-work"
    result = jvm_runner.run_jvm_profile(root, work, config, process_runner=writes_runtime_output,
                                        approved_cache_root=cache)
    assert result["passed"] is True
    assert result["runtime_output_dirs"] == ["run-gametest"]
    assert (work / "candidate" / "run-gametest" / "logs" / "latest.log").is_file()
    assert not (root / "run-gametest").exists()


def test_unsupported_java_runtime_and_command_injection_fail_before_gradle(tmp_path):
    root, profile, frozen = _project(tmp_path)
    cache = tmp_path / "cache"
    dists = cache / "wrapper" / "dists" / "gradle-9.2.1-bin" / "hash" / "gradle-9.2.1" / "bin"
    dists.mkdir(parents=True)
    (dists / "gradle").write_text("distribution", encoding="utf-8")
    (cache / "modules-2").mkdir(parents=True)
    calls = []

    def java17(argv, **kwargs):
        calls.append(argv)
        return {"returncode": 0, "stdout": "", "stderr": 'openjdk version "17.0.1"', "timed_out": False}

    result = jvm_runner.run_jvm_profile(root, tmp_path / "java17", _config(profile, frozen),
                                        process_runner=java17, approved_cache_root=cache)
    assert result["passed"] is False
    assert len(calls) == 1

    injected = _config(profile, frozen)
    injected["frozen_tests"][0]["class_name"] = "example.X;touch /tmp/escaped"
    calls.clear()
    result = jvm_runner.run_jvm_profile(root, tmp_path / "injection", injected,
                                        process_runner=java17, approved_cache_root=cache)
    assert result["passed"] is False
    assert calls == []


def test_frozen_junit_source_is_immutable_to_hive_worker_edits(tmp_path):
    root, _, frozen = _project(tmp_path)
    runs = tmp_path / "runs"
    run_dir = runs / ("e" * 12)
    metadata = hive_jvm.store_frozen_junit_tests(frozen, run_dir)
    tokens = [hive._ACTIVE_AGENT_SCOPES.set(hive.EXTERNAL_AGENT_SCOPES),
              hive._FROZEN_JVM_TESTS.set(tuple(metadata))]
    try:
        ok, reason = hive.validate_edit("backend", {
            "path": "src//test/java/example/WidgetAcceptanceTest.java",
            "operation": "replace", "find": "accepted", "replace": "changed",
        }, ["src//test/java/example/WidgetAcceptanceTest.java"])
    finally:
        hive._FROZEN_JVM_TESTS.reset(tokens[1])
        hive._ACTIVE_AGENT_SCOPES.reset(tokens[0])
    assert not ok
    assert "frozen JUnit" in reason
    assert hive_jvm.verify_frozen_artifacts(metadata, run_dir)


def test_verifier_docker_command_mounts_only_approved_readonly_caches(tmp_path, monkeypatch):
    root, profile, specs = _project(tmp_path)
    run_dir = tmp_path / "runs" / ("f" * 12)
    frozen = hive_jvm.store_frozen_junit_tests(specs, run_dir)
    root_cache = _cached_gradle(tmp_path)
    monkeypatch.setenv("GRADLE_USER_HOME", str(root_cache))
    monkeypatch.setenv("NIX_HIVE_VERIFIER_PIDS", "999999")
    commands = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[1:3] == ["image", "inspect"]:
            return Result(stdout="sha256:image-id\n")
        return Result(stdout=json.dumps({"passed": True, "checks": [{"name": "jvm", "passed": True}]}))

    monkeypatch.setattr(hive_verifier.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(hive_verifier.subprocess, "run", fake_run)
    result = _REAL_VERIFY_TREE_ISOLATED(root, external_root=True, frozen_junit_tests=frozen,
                                        expected_jvm_profile=profile)

    command = commands[1]
    assert result["passed"] is True
    assert ["--network", "none"] == command[command.index("--network"):command.index("--network") + 2]
    assert "bridge" not in command
    assert "--read-only" in command and "--cap-drop" in command
    assert command[command.index("--pids-limit") + 1] == "448"
    assert command[command.index("--memory") + 1] == "4g"
    assert command[command.index("--memory-swap") + 1] == "4g"
    assert command[command.index("--cpus") + 1] == "2"
    assert result["isolation"]["limits"] == {
        "pids": 448, "memory": "4g", "memory_swap": "4g",
        "swap_additional": "0 bytes", "cpus": 2,
    }
    assert result["isolation"]["host_controlled_build_concurrency"] == {
        "gradle_max_workers": 2, "gradle_heap": "-Xmx768m", "active_processor_count": 2,
    }
    mounts = [command[index + 1] for index, value in enumerate(command[:-1]) if value == "--mount"]
    assert len(mounts) == 4
    assert sum('target=/opt/verifier/jvm_runner.py,readonly' in m for m in mounts)==1
    assert all(item.endswith(",readonly") for item in mounts)
    modules_mount = next(item for item in mounts if "target=/approved-gradle-cache/modules-2" in item)
    assert modules_mount.endswith("target=/approved-gradle-cache/modules-2,readonly")
    assert "modules-2/modules-2" not in " ".join(command)
    assert all("modules-2" in item or "wrapper/dists/gradle-9.2.1-bin" in item or "target=/source" in item
               or "target=/opt/verifier/jvm_runner.py,readonly" in item
               for item in mounts)
    env_args = [command[index + 1] for index, value in enumerate(command[:-1]) if value == "--env"]
    assert "GRADLE_RO_DEP_CACHE=/approved-gradle-cache" in env_args
    assert "GRADLE_USER_HOME=/work/gradle-user-home" in env_args
    assert all("JAVA_HOME=" not in item or item == "JAVA_HOME=/opt/java/openjdk" for item in env_args)
    assert not any("OPENAI_API_KEY" in item or "USERPROFILE" in item or "GRADLE_USER_HOME=" in item and "C:" in item
                   for item in env_args)
    assert command[-2] == "jvm-full"
    assert result["isolation"]["inherited_host_environment"] == []


def test_neoform_profile_mounts_manifested_native_inputs_readonly_with_network_disabled(tmp_path, monkeypatch):
    root, _, specs = _project(tmp_path)
    profile = _neoform_profile(root)
    cache, assets_parent, artifacts, baseline, image_id = _neoform_approved_cache(tmp_path, profile)
    frozen = hive_jvm.store_frozen_junit_tests(specs, tmp_path / "hive_runs" / "a1b2c3d4e5f6")
    monkeypatch.setenv("GRADLE_USER_HOME", str(cache))
    commands = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[1:3] == ["image", "inspect"]:
            return Result(stdout=image_id + "\n")
        return Result(stdout=json.dumps({"passed": True, "checks": [{"name": "frozen_junit_acceptance", "passed": True}]}))

    monkeypatch.setattr(hive_verifier.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(hive_verifier.subprocess, "run", fake_run)
    result = _REAL_VERIFY_TREE_ISOLATED(
        root, external_root=True, frozen_junit_tests=frozen, expected_jvm_profile=profile,
        expected_external_baseline_sha256=baseline,
    )

    assert result["passed"] is True, result
    command = commands[1]
    assert result["passed"] is True
    assert command[command.index("--network") + 1] == "none"
    mounts = [command[index + 1] for index, value in enumerate(command[:-1]) if value == "--mount"]
    assert len(mounts) == 7
    assert sum('target=/opt/verifier/jvm_runner.py,readonly' in m for m in mounts)==1
    assert all(item.endswith(",readonly") for item in mounts)
    assert any(f"source={str(assets_parent).replace(chr(92), '/')},target=/approved-gradle-cache/neoformruntime/assets,readonly" in item
               for item in mounts)
    assert any(f"source={str(artifacts).replace(chr(92), '/')},target=/approved-gradle-cache/neoformruntime/artifacts,readonly" in item
               for item in mounts)
    assert any("target=/tmp/hive-external-build-inputs.manifest.json,readonly" in item for item in mounts)
    manifest = json.loads((cache.parent.parent / cache.name / "external-build-inputs.manifest.json").read_text())
    payload = json.loads(command[-1])
    assert payload["external_build_inputs_manifest_sha256"] == hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert result["isolation"]["external_build_input_mounts"].startswith("read-only")


@pytest.mark.parametrize("tamper", ["modified", "extra", "missing", "wrong_baseline", "wrong_image"])
def test_external_build_input_manifest_fails_closed_on_tampering_or_wrong_binding(tmp_path, monkeypatch, tamper):
    root, _, specs = _project(tmp_path)
    profile = _neoform_profile(root)
    cache, assets_parent, artifacts, baseline, image_id = _neoform_approved_cache(tmp_path, profile)
    if tamper == "modified":
        (artifacts / "version.json").write_text('{"version":"tampered"}', encoding="utf-8")
    elif tamper == "extra":
        (artifacts / "unmanifested.bin").write_bytes(b"unexpected")
    elif tamper == "missing":
        (assets_parent / "indexes" / "17.json").unlink()
    frozen = hive_jvm.store_frozen_junit_tests(specs, tmp_path / "hive_runs" / "a1b2c3d4e5f6")
    monkeypatch.setenv("GRADLE_USER_HOME", str(cache))
    docker_calls = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    inspected_image_id = "sha256:" + "d" * 64 if tamper == "wrong_image" else image_id

    def fake_run(command, **kwargs):
        docker_calls.append(command)
        if command[1:3] == ["image", "inspect"]:
            return Result(stdout=inspected_image_id + "\n")
        pytest.fail("verification container must not launch after input integrity failure")

    monkeypatch.setattr(hive_verifier.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(hive_verifier.subprocess, "run", fake_run)
    supplied_baseline = "c" * 64 if tamper == "wrong_baseline" else baseline
    result = _REAL_VERIFY_TREE_ISOLATED(
        root, external_root=True, frozen_junit_tests=frozen, expected_jvm_profile=profile,
        expected_external_baseline_sha256=supplied_baseline,
    )
    assert result["passed"] is False
    assert "External build-input cache preflight failed" in result["checks"][0]["detail"]
    assert all(command[1:3] == ["image", "inspect"] for command in docker_calls)


def test_external_build_input_manifest_itself_must_be_run_bound(tmp_path, monkeypatch):
    root, _, specs = _project(tmp_path)
    profile = _neoform_profile(root)
    cache, _, _, baseline, image_id = _neoform_approved_cache(tmp_path, profile)
    evidence = tmp_path / "hive_runs" / "a1b2c3d4e5f6"
    manifest_path = evidence / "external-build-inputs.manifest.json"
    manifest_path.write_text(manifest_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    frozen = hive_jvm.store_frozen_junit_tests(specs, evidence)
    monkeypatch.setenv("GRADLE_USER_HOME", str(cache))
    monkeypatch.setattr(hive_verifier.shutil, "which", lambda name: "docker")
    calls = []
    class Result:
        returncode = 0
        stdout = image_id + "\n"
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append(command)
        return Result()

    monkeypatch.setattr(hive_verifier.subprocess, "run", fake_run)
    result = _REAL_VERIFY_TREE_ISOLATED(
        root, external_root=True, frozen_junit_tests=frozen, expected_jvm_profile=profile,
        expected_external_baseline_sha256=baseline,
    )
    assert result["passed"] is False
    assert "External build-input cache preflight failed" in result["checks"][0]["detail"]
    assert len(calls) == 1 and calls[0][1:3] == ["image", "inspect"]


def test_changed_wrapper_is_rejected_against_pre_model_profile_before_docker(tmp_path, monkeypatch):
    root, profile, specs = _project(tmp_path)
    frozen = hive_jvm.store_frozen_junit_tests(specs, tmp_path / "runs" / ("a" * 12))
    properties = root / "gradle" / "wrapper" / "gradle-wrapper.properties"
    properties.write_text(properties.read_text(encoding="utf-8").replace("9.2.1", "9.3.0"), encoding="utf-8")
    docker_calls = []
    monkeypatch.setattr(hive_verifier.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(hive_verifier.subprocess, "run", lambda *args, **kwargs: docker_calls.append(args))

    result = _REAL_VERIFY_TREE_ISOLATED(root, external_root=True, frozen_junit_tests=frozen,
                                        expected_jvm_profile=profile)

    assert result["passed"] is False
    assert "immutable pre-model profile" in result["checks"][0]["detail"]
    assert docker_calls == []


def test_changed_full_gate_policy_is_rejected_against_pre_model_profile(tmp_path, monkeypatch):
    root, _, specs = _project(tmp_path)
    policy = root / "VERIFICATION.md"
    policy.write_text("## Exact commands\n```text\n./gradlew clean build\n```\n", encoding="utf-8")
    profile = hive_jvm.inspect_gradle_project(root)
    frozen = hive_jvm.store_frozen_junit_tests(specs, tmp_path / "runs" / ("b" * 12))
    policy.write_text("## Exact commands\n```text\n./gradlew clean test\n```\n", encoding="utf-8")
    docker_calls = []
    monkeypatch.setattr(hive_verifier.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(hive_verifier.subprocess, "run", lambda *args, **kwargs: docker_calls.append(args))

    result = _REAL_VERIFY_TREE_ISOLATED(root, external_root=True, frozen_junit_tests=frozen,
                                        expected_jvm_profile=profile)

    assert result["passed"] is False
    assert "immutable pre-model profile" in result["checks"][0]["detail"]
    assert docker_calls == []


def test_external_jvm_profile_rejects_verifier_image_override(tmp_path, monkeypatch):
    root, profile, specs = _project(tmp_path)
    frozen = hive_jvm.store_frozen_junit_tests(specs, tmp_path / "runs" / ("c" * 12))
    monkeypatch.setenv("NIX_HIVE_VERIFIER_IMAGE", "untrusted/other:latest")
    monkeypatch.setattr(hive_verifier.shutil, "which", lambda name: "docker")
    docker_calls = []
    monkeypatch.setattr(hive_verifier.subprocess, "run", lambda *args, **kwargs: docker_calls.append(args))

    result = _REAL_VERIFY_TREE_ISOLATED(root, external_root=True, frozen_junit_tests=frozen,
                                        expected_jvm_profile=profile)

    assert result["passed"] is False
    assert "image override is disabled" in result["checks"][0]["detail"]
    assert docker_calls == []


@pytest.mark.parametrize("mutation_target", ["baseline", "candidate", "stage"])
def test_external_verification_detects_baseline_candidate_and_stage_mutation(tmp_path, mutation_target):
    workshop = tmp_path / "workshop"
    workshop.mkdir()
    runs = workshop / "hive_runs"
    runs.mkdir()
    repo = tmp_path / "baseline"
    repo.mkdir()
    (repo / "source.txt").write_text("baseline", encoding="utf-8")
    run_id = "1" * 12
    descriptor = external_root.prepare_candidate(str(repo), runs / "external_candidates" / run_id,
                                                workshop, runs)
    run_dir = runs / run_id
    run_dir.mkdir()
    stage = run_dir / "stage"
    external_root.copy_candidate_tree(Path(descriptor["candidate_root"]), stage, runs)
    context = dict(descriptor, run_dir=str(run_dir))
    metadata_token = hive._EXTERNAL_RUN_METADATA.set(context)
    frozen_token = hive._FROZEN_JVM_TESTS.set(())
    def mutate_boundary():
        target = {
            "baseline": repo / "source.txt",
            "candidate": Path(descriptor["candidate_root"]) / "source.txt",
            "stage": stage / "source.txt",
        }[mutation_target]
        target.write_text("mutated", encoding="utf-8")
        return {"passed": True, "checks": []}
    try:
        baseline_result = hive._external_verification_guard(stage, mutate_boundary)
    finally:
        hive._FROZEN_JVM_TESTS.reset(frozen_token)
        hive._EXTERNAL_RUN_METADATA.reset(metadata_token)
    assert baseline_result["passed"] is False
    assert baseline_result["checks"][-1]["name"] == "external_integrity"


def test_persistent_agent_java_candidate_uses_the_same_frozen_verifier_boundary(monkeypatch, tmp_path):
    workshop = tmp_path / "workshop"
    workshop.mkdir()
    runs = workshop / "hive_runs"
    runs.mkdir()
    (workshop / "static").mkdir()
    monkeypatch.setattr(app, "ROOT", workshop)
    monkeypatch.setattr(app, "HIVE_RUNS", runs)
    monkeypatch.setattr(app, "SELF_SNAPSHOTS", workshop / "self_snapshots")
    monkeypatch.setattr(app, "JOBS", runtime.JobManager(max_jobs=10))
    monkeypatch.setattr(app, "require_mode_for_code", lambda: None)
    monkeypatch.setattr(app.db, "add_ledger", lambda *args, **kwargs: None)

    repo, _, _ = _project(tmp_path)
    (repo / TEST_PATH).unlink()
    frozen = _frozen_spec(TEST_SOURCE + "\n// HIVE002_FROZEN_ASSERTION_SENTINEL\n")
    plan = {
        "summary": "Change Widget.value",
        "ui_goal": "no change needed",
        "backend_goal": "Change Widget.value to return 2",
        "tests_goal": "no change needed",
        "worker_files": {"ui": [], "backend": ["src/main/java/example/Widget.java"], "tests": []},
        "acceptance": ["Widget.value returns 2"],
        "worker_acceptance": {"ui": [], "backend": ["Widget.value returns 2"], "tests": []},
        "interface_contracts": [], "provider_changes": [],
    }
    prompts = []

    class FakePersistent:
        metrics = []

        def __init__(self, model):
            assert model == "gpt-6-astra"

        async def __call__(self, role, prompt):
            prompts.append((role, prompt))
            if role == "planner":
                return json.dumps(plan)
            if role == "backend":
                return json.dumps({"status": "implemented", "summary": "change value", "risks": [],
                                   "edits": [{"path": "src/main/java/example/Widget.java",
                                              "operation": "replace", "find": "return 1;", "replace": "return 2;"}]})
            if role == "reviewer":
                return json.dumps({"approve": True, "summary": "ok", "issues": [], "confidence": 1})
            raise AssertionError(role)

    captured = []
    def targeted(tree, files, *, external_root=False, frozen_junit_tests=None,
                 expected_jvm_profile=None, expected_external_baseline_sha256=None):
        captured.append(("targeted", Path(tree).resolve(), external_root, list(frozen_junit_tests or []),
                         expected_jvm_profile))
        return {"passed": True, "checks": [{"name": "frozen_junit_acceptance", "passed": True}]}

    def full(tree, *, external_root=False, frozen_junit_tests=None, expected_jvm_profile=None,
             expected_external_baseline_sha256=None):
        captured.append(("full", Path(tree).resolve(), external_root, list(frozen_junit_tests or []),
                         expected_jvm_profile))
        return {"passed": True, "checks": [{"name": "full_gradle_check", "passed": True}]}

    monkeypatch.setattr(app.persistent_agent, "PersistentAgentBackend", FakePersistent)
    monkeypatch.setattr(hive_verifier, "targeted_verify_isolated", targeted)
    monkeypatch.setattr(hive_verifier, "verify_tree_isolated", full)

    with TestClient(app.app) as client:
        response = client.post("/api/hive/build", json={
            "request": "Change Widget.value to return 2.",
            "allow_cloud": True,
            "agent_backend": "persistent",
            "external_source_root": str(repo),
            "allow_external_root": True,
            "frozen_junit_tests": [frozen],
        })
        assert response.status_code == 200, response.text
        job_id = response.json()["job_id"]
        for _ in range(200):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["state"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.01)
        else:
            pytest.fail("persistent fake external run did not finish")

    run = job["result"]
    manifest = run["metadata"]["external_root"]["frozen_junit_tests"]
    profile = run["metadata"]["external_root"]["jvm_profile"]
    assert run["candidate_disposition"] == "verified_review_approved" and run["applied"] is False
    assert not run["human_review_eligible"] and "external_candidate_only" in run["promotion_blockers"]
    assert [item[0] for item in captured] == ["targeted", "full"]
    assert all(item[2] is True for item in captured)
    assert all(item[3] == manifest for item in captured)
    assert all(item[4] == profile for item in captured)
    assert all(item[1] == runs / run["id"] / "stage" for item in captured)
    assert Path(manifest[0]["artifact_path"]).is_relative_to(runs / run["id"] / "frozen-junit")
    assert Path(manifest[0]["artifact_path"]).is_file()
    assert (repo / "src/main/java/example/Widget.java").read_text(encoding="utf-8").find("return 1;") >= 0
    assert (Path(run["metadata"]["external_root"]["candidate_root"]) / "src/main/java/example/Widget.java").read_text(encoding="utf-8").find("return 1;") >= 0
    assert all("HIVE002_FROZEN_ASSERTION_SENTINEL" not in prompt for role, prompt in prompts)
