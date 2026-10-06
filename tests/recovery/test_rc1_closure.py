"""Model-free RC1 closure guards."""

import asyncio
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from hive_canonical import CandidateSpec, produce_candidate
from hive_canonical.controller import (UnqualifiedBuildControlScopeError,
                                       ProtectedDiagnosticTransportError,
                                       _qualify_gradle_scope, _protected_agent_call)


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "recovery/rc1-closure/fixture_resolver.py"
SPEC = importlib.util.spec_from_file_location("fixture_resolver", MODULE)
resolver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resolver)
ENV_SPEC = importlib.util.spec_from_file_location(
    "verify_environment", ROOT / "recovery/rc1-closure/environment/verify_environment.py")
environment = importlib.util.module_from_spec(ENV_SPEC)
ENV_SPEC.loader.exec_module(environment)


@pytest.fixture
def isolated_worktree(tmp_path, request):
    root = tmp_path / "isolated"
    subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", "--no-checkout",
                    str(root), "HEAD"], check=True, capture_output=True)
    def cleanup():
        assert root.resolve().is_relative_to(tmp_path.resolve())
        subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(root)],
                       check=True, capture_output=True)
    request.addfinalizer(cleanup)
    return root


@pytest.mark.parametrize("path", [
    "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts",
    "gradle.properties", "gradlew", "gradlew.bat", "gradle/wrapper/gradle-wrapper.properties",
    "gradle/init.d/inject.gradle", "gradle/libs.versions.toml", "buildSrc/src/main/java/X.java",
    "build-logic/build.gradle.kts", "src/test/java/ForgedTest.java",
    "src/main/resources/anything", "src/main/java/X.txt", "VERIFICATION.md",
    "subproject/gradle.properties", "subproject/settings.gradle.kts",
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


def test_protected_verifier_feedback_cannot_reach_model():
    calls = []
    async def model(role, prompt):
        calls.append((role, prompt))
        return "{}"
    guarded = _protected_agent_call(model, frozen_tests=True)
    with pytest.raises(ProtectedDiagnosticTransportError):
        asyncio.run(guarded("backend", "TARGETED VERIFICATION CORRECTION\nsecret emitted by candidate"))
    with pytest.raises(ProtectedDiagnosticTransportError):
        asyncio.run(guarded("reviewer", "review context with possible emitted secret"))
    assert calls == []
    assert asyncio.run(guarded("planner", "ordinary plan")) == "{}"
    assert len(calls) == 1


def test_no_frozen_test_does_not_disable_normal_correction():
    calls = []
    async def model(role, prompt):
        calls.append(role)
        return "{}"
    guarded = _protected_agent_call(model, frozen_tests=False)
    assert asyncio.run(guarded("backend", "TARGETED VERIFICATION CORRECTION\nsynthetic")) == "{}"
    assert asyncio.run(guarded("reviewer", "synthetic review")) == "{}"
    assert calls == ["backend", "reviewer"]


def test_verifier_invoked_tag_must_match_frozen_image(monkeypatch):
    class Completed:
        def __init__(self, value):
            self.stdout = value
    outputs = iter([Completed("sha256:expected\n"), Completed("sha256:other\n")])
    monkeypatch.setattr(environment.subprocess, "run", lambda *a, **k: next(outputs))
    with pytest.raises(ValueError, match="image tag"):
        environment.verify_image_binding("sha256:expected")


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


def test_exact_fixture_bytes_and_repeat_materialization(tmp_path, isolated_worktree):
    isolated = isolated_worktree
    mapping = _map(tmp_path)
    name = "ordinal-03/planner-1.response.txt"
    first = resolver.materialize(ROOT, isolated, mapping, (name,))
    second = resolver.materialize(ROOT, isolated, mapping, (name,))
    assert first == second
    dest = Path(first[0]["destination"])
    assert hashlib.sha256(dest.read_bytes()).hexdigest() == first[0]["sha256"]


def test_unregistered_directory_cannot_receive_fixtures(tmp_path):
    destination = tmp_path / "arbitrary-directory"
    destination.mkdir()
    with pytest.raises(resolver.FixtureResolutionError, match="detached linked test worktree"):
        resolver.materialize(ROOT, destination, _map(tmp_path))


def test_frozen_test_and_recovered_source_identity():
    mapping = json.loads((ROOT / "RECOVERY_FIXTURE_MAP.json").read_text(encoding="utf-8"))
    experiment = ROOT / "recovery/workshop-source-20261006/workspace/HIVE-FACTORIAL-003R1"
    for name, expected in mapping["requesting_test_sha256"].items():
        test = experiment / "repaired-workshop/tests" / name
        assert hashlib.sha256(test.read_bytes()).hexdigest() == expected
    # The committed frozen tree remains unchanged even if this particular
    # isolated worktree has recovery-only materialized evidence paths.
    for row in mapping["fixtures"]:
        git_path = (Path(mapping["destination_prefix"]) / row["relative_path"]).as_posix()
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "HEAD", "--", git_path],
                                 capture_output=True, text=True, check=True)
        assert tracked.stdout == ""


@pytest.mark.parametrize("name", ["../escape", "unmapped.json"])
def test_unmapped_or_traversal_fixture_fails_closed(tmp_path, isolated_worktree, name):
    isolated = isolated_worktree
    with pytest.raises(resolver.FixtureResolutionError):
        resolver.materialize(ROOT, isolated, _map(tmp_path), (name,))


@pytest.mark.parametrize("mutation", ["ambiguous", "wrong_hash", "missing", "traversal", "unknown_state"])
def test_bad_fixture_mapping_fails_closed(tmp_path, isolated_worktree, mutation):
    isolated = isolated_worktree
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


def test_existing_mismatched_fixture_rejected(tmp_path, isolated_worktree):
    isolated = isolated_worktree
    data = json.loads(_map(tmp_path).read_text(encoding="utf-8"))
    name = data["fixtures"][0]["relative_path"]
    dest = isolated / data["destination_prefix"] / name
    dest.parent.mkdir(parents=True)
    dest.write_text("substitute", encoding="utf-8")
    with pytest.raises(resolver.FixtureResolutionError, match="existing destination mismatch"):
        resolver.materialize(ROOT, isolated, _map(tmp_path), (name,))


def test_link_escape_rejected(tmp_path, isolated_worktree):
    isolated = isolated_worktree
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
