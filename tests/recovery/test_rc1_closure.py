"""Model-free RC1 closure guards."""

import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from hive_canonical import CandidateSpec, produce_candidate
from hive_canonical.controller import UnqualifiedBuildControlScopeError, _qualify_gradle_scope


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "recovery/rc1-closure/fixture_resolver.py"
SPEC = importlib.util.spec_from_file_location("fixture_resolver", MODULE)
resolver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resolver)


@pytest.mark.parametrize("path", [
    "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts",
    "gradle.properties", "gradlew", "gradlew.bat", "gradle/wrapper/gradle-wrapper.properties",
    "gradle/init.d/inject.gradle", "gradle/libs.versions.toml", "buildSrc/src/main/java/X.java",
    "build-logic/build.gradle.kts", "src/test/java/ForgedTest.java",
    "src/main/resources/anything", "src/main/java/X.txt", "VERIFICATION.md",
])
def test_gradle_control_scope_rejected(path):
    with pytest.raises(UnqualifiedBuildControlScopeError, match="UNQUALIFIED_BUILD_CONTROL_SCOPE"):
        _qualify_gradle_scope((path,), gradle_project=True)


@pytest.mark.parametrize("path", [
    "src/main/java/dev/atmcompanion/state/SnapshotFormatter.java",
    "src/main/java/dev/atmcompanion/IngredientAllocation.java",
    "src/main/java/dev/atmcompanion/Observation.java",
    "src/main/java/dev/atmcompanion/ExecutionContext.java",
    "src/main/java/newpackage/NewClass.java",
])
def test_source_only_gradle_scope_eligible(path):
    _qualify_gradle_scope((path,), gradle_project=True)


def test_gradle_scope_rejected_before_worker(monkeypatch, tmp_path):
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    (baseline / "gradlew").write_text("synthetic", encoding="utf-8")
    calls = []
    async def agent(role, prompt):
        calls.append(role)
        raise AssertionError("worker/model must not be called")
    # Known Gradle authority paths are rejected even without a recognized
    # pinned profile, before any supplied agent callback is reached.
    from hive_canonical.legacy.workshop import hive_jvm
    monkeypatch.setattr(hive_jvm, "inspect_gradle_project", lambda _: None)
    spec = CandidateSpec(baseline, tmp_path / "runs", "synthetic request", "scripted",
                         ("build.gradle",))
    with pytest.raises(UnqualifiedBuildControlScopeError):
        asyncio.run(produce_candidate(spec, agent))
    assert calls == []


def _map(tmp_path):
    path = tmp_path / "map.json"
    path.write_bytes((ROOT / "RECOVERY_FIXTURE_MAP.json").read_bytes())
    return path


def test_exact_fixture_bytes_and_repeat_materialization(tmp_path):
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    mapping = _map(tmp_path)
    name = "ordinal-03/planner-1.response.txt"
    first = resolver.materialize(ROOT, isolated, mapping, (name,))
    second = resolver.materialize(ROOT, isolated, mapping, (name,))
    assert first == second
    dest = Path(first[0]["destination"])
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == first[0]["sha256"]


def test_frozen_test_and_recovered_source_identity():
    mapping = json.loads((ROOT / "RECOVERY_FIXTURE_MAP.json").read_text(encoding="utf-8"))
    experiment = ROOT / "recovery/workshop-source-20261006/workspace/HIVE-FACTORIAL-003R1"
    for name, expected in mapping["requesting_test_sha256"].items():
        test = experiment / "repaired-workshop/tests" / name
        assert hashlib.sha256(test.read_bytes()).hexdigest() == expected
    # Original source fixtures remain committed bytes; resolver reads Git and
    # never writes this experiment's evidence directory.
    for row in mapping["fixtures"]:
        assert not (experiment / "evidence" / row["relative_path"]).exists()


@pytest.mark.parametrize("name", ["../escape", "unmapped.json"])
def test_unmapped_or_traversal_fixture_fails_closed(tmp_path, name):
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    with pytest.raises(resolver.FixtureResolutionError):
        resolver.materialize(ROOT, isolated, _map(tmp_path), (name,))


@pytest.mark.parametrize("mutation", ["ambiguous", "wrong_hash", "missing", "traversal", "unknown_state"])
def test_bad_fixture_mapping_fails_closed(tmp_path, mutation):
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    mapping = _map(tmp_path)
    data = json.loads(mapping.read_text(encoding="utf-8"))
    if mutation == "ambiguous":
        data["fixtures"].append(dict(data["fixtures"][0]))
    elif mutation == "wrong_hash":
        data["fixtures"][0]["sha256"] = "0" * 64
    elif mutation == "missing":
        data["source_prefix"] = "missing/evidence/"
    elif mutation == "traversal":
        data["fixtures"][0]["relative_path"] = "../escape"
    else:
        data["fixtures"][0]["disposition"] = "AMBIGUOUS"
    mapping.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(resolver.FixtureResolutionError):
        resolver.materialize(ROOT, isolated, mapping, (data["fixtures"][0]["relative_path"],))


def test_existing_mismatched_fixture_rejected(tmp_path):
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    data = json.loads(_map(tmp_path).read_text(encoding="utf-8"))
    name = data["fixtures"][0]["relative_path"]
    dest = isolated / data["destination_prefix"] / name
    dest.parent.mkdir(parents=True)
    dest.write_text("substitute", encoding="utf-8")
    with pytest.raises(resolver.FixtureResolutionError, match="existing destination mismatch"):
        resolver.materialize(ROOT, isolated, _map(tmp_path), (name,))


def test_link_escape_rejected(tmp_path):
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    data = json.loads(_map(tmp_path).read_text(encoding="utf-8"))
    prefix = isolated / data["destination_prefix"]
    prefix.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        prefix.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink privilege unavailable")
    with pytest.raises(resolver.FixtureResolutionError):
        resolver.materialize(ROOT, isolated, _map(tmp_path), (data["fixtures"][0]["relative_path"],))
