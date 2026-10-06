from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from verification import prime_gradle_cache, prime_runner


def test_priming_requires_explicit_network_opt_in():
    with pytest.raises(SystemExit):
        prime_gradle_cache.parse_args([
            "--baseline-root", "C:/baseline",
            "--candidate-root", "C:/runs/external_candidates/0123456789ab",
            "--cache-root", "C:/runs/approved-gradle-caches/0123456789ab",
        ])


def test_prime_container_has_only_one_persistent_writable_mount(tmp_path):
    candidate = tmp_path / "candidate"
    cache_root = tmp_path / "cache"
    candidate.mkdir()
    cache_root.mkdir()
    profile = {
        "version": "9.2.1",
        "distribution": "gradle-9.2.1-bin.zip",
        "full_tasks": ["clean", "build", "runGameTestServer"],
    }

    command = prime_gradle_cache.build_prime_command(
        "docker", candidate, cache_root, profile, "hive-prime-0123456789ab"
    )

    assert command[command.index("--network") + 1] == "bridge"
    assert "--read-only" in command
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--pids-limit") + 1] == "512"
    mounts = [command[index + 1] for index, item in enumerate(command[:-1]) if item == "--mount"]
    assert len(mounts) == 2
    source_mount = next(item for item in mounts if "target=/source" in item)
    cache_mount = next(item for item in mounts if "target=/approved-gradle-cache" in item)
    assert source_mount.endswith("target=/source,readonly")
    assert not cache_mount.endswith(",readonly")
    assert "GRADLE_USER_HOME=/approved-gradle-cache" in command
    assert not any(item.startswith("GRADLE_RO_DEP_CACHE=") for item in command)
    assert command[command.index("--entrypoint") + 1] == "python3"
    assert command[-2] == "/opt/verifier/prime_runner.py"
    assert "--privileged" not in command


def test_priming_runner_rejects_freeform_or_injected_gradle_tasks(tmp_path):
    root = tmp_path / "source"
    wrapper = root / "gradle" / "wrapper"
    wrapper.mkdir(parents=True)
    jar = wrapper / "gradle-wrapper.jar"
    properties = wrapper / "gradle-wrapper.properties"
    jar.write_bytes(b"wrapper")
    properties.write_text("distributionUrl=gradle-9.2.1-bin.zip\n", encoding="utf-8")
    profile = {
        "version": "9.2.1",
        "distribution": "gradle-9.2.1-bin.zip",
        "wrapper_jar_sha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
        "wrapper_properties_sha256": hashlib.sha256(properties.read_bytes()).hexdigest(),
        "full_tasks": ["build;curl-attacker"],
    }

    with pytest.raises(ValueError, match="statically validated Gradle task identifiers"):
        prime_runner._validate_profile(root, profile)


def test_priming_runner_rejects_unrecognized_external_input_cache_profiles(tmp_path):
    root = tmp_path / "source"
    wrapper = root / "gradle" / "wrapper"
    wrapper.mkdir(parents=True)
    jar = wrapper / "gradle-wrapper.jar"
    properties = wrapper / "gradle-wrapper.properties"
    jar.write_bytes(b"wrapper")
    properties.write_text("distributionUrl=gradle-9.2.1-bin.zip\n", encoding="utf-8")
    profile = {
        "version": "9.2.1", "distribution": "gradle-9.2.1-bin.zip",
        "wrapper_jar_sha256": hashlib.sha256(jar.read_bytes()).hexdigest(),
        "wrapper_properties_sha256": hashlib.sha256(properties.read_bytes()).hexdigest(),
        "full_tasks": ["build"],
        "external_build_inputs": {"kind": "arbitrary", "cache_relative": "../../outside",
                                  "input_directories": ["anything"]},
    }
    with pytest.raises(ValueError, match="allowlisted native input-cache profile"):
        prime_runner._validate_profile(root, profile)


def test_priming_cache_manifest_is_sorted_and_hashes_each_new_file(tmp_path):
    cache = tmp_path / "cache"
    (cache / "wrapper" / "dists").mkdir(parents=True)
    (cache / "caches" / "modules-2").mkdir(parents=True)
    (cache / "wrapper" / "dists" / "gradle.zip").write_bytes(b"wrapper bytes")
    (cache / "caches" / "modules-2" / "artifact.jar").write_bytes(b"artifact bytes")

    manifest = prime_gradle_cache._inventory_cache(cache)

    assert [item["path"] for item in manifest] == [
        "caches/modules-2/artifact.jar",
        "wrapper/dists/gradle.zip",
    ]
    assert manifest[0]["sha256"] == hashlib.sha256(b"artifact bytes").hexdigest()
    assert manifest[1]["sha256"] == hashlib.sha256(b"wrapper bytes").hexdigest()


def test_priming_manifest_rejects_symlinks(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("not in cache", encoding="utf-8")
    try:
        (cache / "linked-artifact").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    with pytest.raises(prime_gradle_cache.PrimingError, match="link or special file"):
        prime_gradle_cache._inventory_cache(cache)


def test_repository_provenance_records_requests_not_documentation_links():
    logs = """See https://help.gradle.org for help.
Downloading https://maven.neoforged.net/releases/plugin.jar
Resource missing. [HTTP GET: https://repo.maven.apache.org/maven2/example.pom]
"""

    assert prime_gradle_cache._repository_origins(logs) == [
        "https://maven.neoforged.net",
        "https://repo.maven.apache.org",
    ]


def test_prime_runner_continues_after_game_test_failure_and_classifies_it(tmp_path):
    gradle_home = tmp_path / "gradle-home"
    native = gradle_home / "caches" / "neoformruntime"
    for name in ("assets", "artifacts"):
        directory = native / name
        directory.mkdir(parents=True)
        (directory / "cached-input").write_bytes(b"input")
    facts = {
        "failed_tasks": [":runGameTestServer"],
        "create_minecraft_artifacts_seen": True,
        "create_minecraft_artifacts_failed": False,
        "network_or_input_failure_seen": False,
        "test_failure_seen": True,
    }
    profile = {"external_build_inputs": {
        "kind": "neoformruntime", "cache_relative": "caches/neoformruntime",
        "input_directories": ["artifacts", "assets"],
    }}
    result = prime_runner._prime_outcome(
        {"returncode": 1, "timed_out": False, "stdout": "", "stderr": ""},
        facts, ["clean", "build", "runGameTestServer"], gradle_home, profile, True,
    )
    assert result["failure_classification"] == "application_or_test_failure"
    assert result["external_inputs_primed"] is True
    assert result["full_gate_passed"] is False


def test_network_input_failure_prevents_prime_success_even_when_files_exist(tmp_path):
    gradle_home = tmp_path / "gradle-home"
    native = gradle_home / "caches" / "neoformruntime"
    for name in ("assets", "artifacts"):
        directory = native / name
        directory.mkdir(parents=True)
        (directory / "partial-input").write_bytes(b"partial")
    facts = {
        "failed_tasks": [":createMinecraftArtifacts"],
        "create_minecraft_artifacts_seen": True,
        "create_minecraft_artifacts_failed": True,
        "network_or_input_failure_seen": True,
        "test_failure_seen": False,
    }
    profile = {"external_build_inputs": {
        "kind": "neoformruntime", "cache_relative": "caches/neoformruntime",
        "input_directories": ["artifacts", "assets"],
    }}
    result = prime_runner._prime_outcome(
        {"returncode": 1, "timed_out": False, "stdout": "", "stderr": ""},
        facts, ["clean", "build"], gradle_home, profile, True,
    )
    assert result["failure_classification"] == "external_input_acquisition_failure"
    assert result["external_inputs_primed"] is False


def test_prime_output_facts_capture_task_status_network_failure_and_download_url():
    facts = prime_runner._PrimeOutputFacts()
    facts("stdout", b"> Task :createMinecraftArtifacts\n  \xe2\x86\x93 https://meta.example/version_manifest.json\n")
    facts("stderr", b"Could not GET https://repo.example/input.json\n> Task :runGameTestServer FAILED\n")
    result = facts.snapshot()
    assert result["create_minecraft_artifacts_seen"] is True
    assert result["create_minecraft_artifacts_failed"] is False
    assert result["failed_tasks"] == [":runGameTestServer"]
    assert result["network_or_input_failure_seen"] is True
    assert "https://meta.example/version_manifest.json" in result["observed_urls"]


def test_game_test_failure_does_not_masquerade_as_external_input_acquisition_failure(tmp_path):
    facts = prime_runner._PrimeOutputFacts()
    facts("stdout", b"> Task :createMinecraftArtifacts\n> Task :runGameTestServer FAILED\n")
    facts("stderr", b"Resource missing. [HTTP GET: https://repo.example/maven/fallback.pom]\n"
                      b"java.lang.IllegalStateException: Missing test structure: atm_companion_tests:empty\n")
    snapshot = facts.snapshot()
    gradle_home = tmp_path / "gradle-home"
    native = gradle_home / "caches" / "neoformruntime"
    for name in ("assets", "artifacts"):
        directory = native / name
        directory.mkdir(parents=True)
        (directory / "input").write_bytes(b"cached")
    profile = {"external_build_inputs": {
        "kind": "neoformruntime", "cache_relative": "caches/neoformruntime",
        "input_directories": ["artifacts", "assets"],
    }}
    result = prime_runner._prime_outcome(
        {"returncode": 1, "timed_out": False, "stdout": "", "stderr": ""}, snapshot,
        ["clean", "build", "runGameTestServer"], gradle_home, profile, True,
    )
    assert result["failure_classification"] == "application_or_test_failure"
    assert result["application_or_test_failure_observed"] is True
    assert any("Missing test structure: atm_companion_tests:empty" in line
               for line in result["application_test_diagnostics"])
    assert result["network_or_dependency_acquisition_failure"] is False
    assert result["external_inputs_primed"] is True
    assert "https://repo.example/maven/fallback.pom" in snapshot["observed_urls"]


def test_external_input_manifest_covers_native_artifacts_and_asset_objects(tmp_path):
    cache = tmp_path / "cache"
    native = cache / "caches" / "neoformruntime"
    artifacts = native / "artifacts"
    indexes = native / "assets" / "indexes"
    artifacts.mkdir(parents=True)
    indexes.mkdir(parents=True)
    asset = b"minecraft asset bytes"
    asset_hash = hashlib.sha1(asset).hexdigest()
    asset_path = native / "assets" / "objects" / asset_hash[:2] / asset_hash
    asset_path.parent.mkdir(parents=True)
    asset_path.write_bytes(asset)
    launcher_url = "https://meta.example/game/version_manifest_v2.json?private=omit"
    version_url = "https://meta.example/packages/1.21.1.json"
    index_url = "https://meta.example/packages/17.json"
    client_url = "https://data.example/objects/client.jar"
    (artifacts / "minecraft_launcher_manifest.json").write_text(json.dumps({
        "versions": [{"id": "1.21.1", "url": version_url}],
    }), encoding="utf-8")
    (artifacts / "minecraft_1.21.1_version_manifest.json").write_text(json.dumps({
        "assetIndex": {"id": "17", "url": index_url},
        "downloads": {"client": {"url": client_url}},
    }), encoding="utf-8")
    (artifacts / "minecraft_1.21.1_client.jar").write_bytes(b"client")
    (indexes / "17.json").write_text(json.dumps({"objects": {
        "textures/example": {"hash": asset_hash, "size": len(asset)},
    }}), encoding="utf-8")
    profile = {
        "version": "9.2.1", "distribution_sha256": "1" * 64,
        "wrapper_jar_sha256": "2" * 64, "wrapper_properties_sha256": "3" * 64,
        "verification_policy_sha256": "4" * 64,
        "external_build_inputs": {"kind": "neoformruntime",
                                   "cache_relative": "caches/neoformruntime",
                                   "input_directories": ["artifacts", "assets"]},
    }
    manifest, provenance = prime_gradle_cache.build_external_build_input_records(
        cache, profile, baseline_sha256="a" * 64, container_image_id="sha256:" + "b" * 64,
        observed_urls=[launcher_url], acquisition_started_utc="2026-09-30T00:00:00Z",
        acquisition_ended_utc="2026-09-30T00:01:00Z", priming_command=["gradle-wrapper", "build"],
    )
    entries = {item["path"]: item for item in manifest["files"]}
    assert list(entries) == sorted(entries, key=lambda path: (path.casefold(), path))
    assert entries["artifacts/minecraft_launcher_manifest.json"]["source_url"] == "https://meta.example/game/version_manifest_v2.json"
    assert entries["artifacts/minecraft_1.21.1_version_manifest.json"]["source_url"] == version_url
    assert entries["artifacts/minecraft_1.21.1_client.jar"]["source_url"] == client_url
    assert entries[f"assets/objects/{asset_hash[:2]}/{asset_hash}"]["source_url"] == (
        f"https://resources.download.minecraft.net/{asset_hash[:2]}/{asset_hash}"
    )
    provenance_by_path = {item["path"]: item for item in provenance["files"]}
    asset_record = provenance_by_path[f"assets/objects/{asset_hash[:2]}/{asset_hash}"]
    assert asset_record["size"] == len(asset)
    assert asset_record["sha256"] == hashlib.sha256(asset).hexdigest()
    assert asset_record["local_cache_path"].replace("\\", "/").endswith(
        asset_path.as_posix().split("neoformruntime/")[-1]
    )
    assert asset_record["acquired_at_utc"]
    assert asset_record["baseline_sha256"] == "a" * 64
    assert asset_record["container_image_id"] == "sha256:" + "b" * 64
    assert asset_record["priming_command_sha256"] == provenance["priming_command_sha256"]


def test_prime_cache_persists_external_input_evidence_in_matching_run_directory(tmp_path, monkeypatch):
    workshop = tmp_path / "workshop"
    runs = workshop / "hive_runs"
    run_id = "123456abcdef"
    evidence = runs / run_id
    candidate = runs / "external_candidates" / run_id
    cache = runs / "approved-gradle-caches" / run_id
    baseline = tmp_path / "baseline"
    wrapper = baseline / "gradle" / "wrapper"
    wrapper.mkdir(parents=True)
    (baseline / "build.gradle").write_text("plugins { id 'net.neoforged.moddev' version '2.0.147' }\n", encoding="utf-8")
    (baseline / "settings.gradle").write_text("rootProject.name = 'fixture'\n", encoding="utf-8")
    (baseline / "gradlew").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (wrapper / "gradle-wrapper.jar").write_bytes(b"wrapper bytes")
    (wrapper / "gradle-wrapper.properties").write_text(
        "distributionUrl=https\\://services.gradle.org/distributions/gradle-9.2.1-bin.zip\n"
        "distributionSha256Sum=" + "a" * 64 + "\n", encoding="utf-8",
    )
    runs.mkdir(parents=True)
    evidence.mkdir(parents=True)
    metadata = prime_gradle_cache.external_root.prepare_candidate(str(baseline), candidate, workshop, runs)
    assert metadata["baseline_sha256"] == prime_gradle_cache.external_root.tree_sha256(baseline)
    monkeypatch.setattr(prime_gradle_cache, "REPO_ROOT", workshop)
    monkeypatch.setattr(prime_gradle_cache, "HIVE_RUNS", runs)
    monkeypatch.setattr(prime_gradle_cache, "APPROVED_CACHE_ROOT", runs / "approved-gradle-caches")
    monkeypatch.setattr(prime_gradle_cache, "_inspect_image", lambda docker: "sha256:" + "b" * 64)
    monkeypatch.setattr(prime_gradle_cache.shutil, "which", lambda name: "docker")

    def fake_container(command, **kwargs):
        cache_mount = next(command[index + 1] for index, value in enumerate(command[:-1])
                           if value == "--mount" and "target=/approved-gradle-cache" in command[index + 1])
        mount_value = cache_mount
        cache_path = Path(mount_value.split("source=", 1)[1].split(",target=", 1)[0])
        native = cache_path / "caches" / "neoformruntime"
        (native / "artifacts").mkdir(parents=True)
        (native / "assets" / "indexes").mkdir(parents=True)
        (native / "artifacts" / "minecraft_launcher_manifest.json").write_text('{"versions":[]}', encoding="utf-8")
        (native / "assets" / "indexes" / "17.json").write_text('{"objects":{}}', encoding="utf-8")
        report = {
            "mode": "dependency_cache_priming", "cache_priming_succeeded": True,
            "java_version": "21.0.12.1", "gradle_wrapper_version": "9.2.1",
            "full_gate_tasks": ["check"], "source_unchanged": True,
            "task_outcome": {"external_inputs_primed": True, "full_gate_passed": True},
            "output_facts": {"observed_urls": ["https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"],
                             "diagnostic_lines": []},
            "commands": [{"phase": "resolve_documented_gradle_graph",
                           "argv": ["java", "GradleWrapperMain", "--offline", "check"],
                           "returncode": 0}],
        }
        class Completed:
            returncode = 0
            stdout = json.dumps(report)
            stderr = ""
        return Completed()

    monkeypatch.setattr(prime_gradle_cache.subprocess, "run", fake_container)
    code, result = prime_gradle_cache.prime_cache(
        str(baseline), str(candidate), str(cache), allow_network=True,
    )
    assert code == 0
    assert result["success"] is True
    prime_record = json.loads(Path(result["provenance_path"]).read_text(encoding="utf-8"))
    assert Path(prime_record["external_build_inputs_manifest"]).is_file()
    assert Path(prime_record["external_build_inputs_provenance"]).is_file()
    saved_provenance = json.loads(Path(prime_record["external_build_inputs_provenance"]).read_text(encoding="utf-8"))
    assert saved_provenance["baseline_sha256"] == metadata["baseline_sha256"]
    assert saved_provenance["cache_priming_succeeded"] is True
    assert prime_record["external_build_input_count"] == 2
