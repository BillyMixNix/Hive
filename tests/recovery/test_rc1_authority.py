"""Deterministic authority-path probes; no model provider is contacted."""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from hive_canonical import CandidateSpec, produce_candidate
from hive_canonical.controller import CandidatePolicyError
from hive_canonical.legacy.workshop import hive, hive_review
from hive_canonical.promotion import PromotionUnavailableError
from hive_canonical.provenance import CandidateIntegrityError, assert_scoped_change, source_index


def fixture(tmp_path):
    baseline = tmp_path / "baseline"
    (baseline / "src").mkdir(parents=True)
    (baseline / "src" / "Widget.txt").write_text("value=1\n", encoding="utf-8")
    runs = tmp_path / "runs"
    runs.mkdir()
    return baseline, runs


def plan(files=None):
    return {
        "summary": "Update Widget behavior", "ui_goal": "no change needed",
        "backend_goal": "Change the value returned by Widget.value",
        "tests_goal": "no change needed",
        "worker_files": {"ui": [], "backend": files or ["src/Widget.txt"], "tests": []},
        "acceptance": ["Widget.value returns the requested value."],
        "worker_acceptance": {"ui": [], "backend": ["Widget value is 2."], "tests": []},
        "interface_contracts": [], "provider_changes": [],
    }


def scripted_call(*, edit_path="src/Widget.txt", model_error=False, planner=None):
    calls = []

    async def call(role, prompt):
        calls.append((role, prompt))
        if model_error:
            raise RuntimeError("synthetic provider unavailable")
        if role == "planner":
            return json.dumps(planner or plan())
        if role == "backend":
            return json.dumps({"status": "implemented", "summary": "update Widget.value",
                               "edits": [{"path": edit_path, "operation": "replace",
                                          "find": "value=1", "replace": "value=2"}], "risks": []})
        if role == "reviewer":
            return json.dumps({"approve": True, "summary": "synthetic review",
                               "issues": [], "confidence": 1.0})
        raise AssertionError(role)

    return call, calls


def spec(baseline, runs, scope=("src/Widget.txt",), **kwargs):
    return CandidateSpec(baseline_root=baseline, runs_root=runs,
                         request="Change src/Widget.txt to value=2.",
                         local_model="scripted-fixture", allowed_write_files=scope, **kwargs)


def test_candidate_authority_path_and_hash_binding(monkeypatch, tmp_path):
    baseline, runs = fixture(tmp_path)
    before = source_index(baseline)
    targeted = []
    full = []
    monkeypatch.setattr(hive, "targeted_verify", lambda tree, role, files:
                        targeted.append((Path(tree), role, tuple(files))) or {"passed": True, "checks": []})
    monkeypatch.setattr(hive, "verify_tree", lambda tree:
                        full.append(Path(tree)) or {"passed": True, "checks": []})
    call, calls = scripted_call()
    result = asyncio.run(produce_candidate(spec(baseline, runs), call))
    assert result.software_verified is True
    assert result.changed_files == ("src/Widget.txt",)
    assert result.verification_status == "passed"
    assert result.semantic_review == "approved"
    assert result.promotion_authorization == "unavailable" and not result.applied
    assert source_index(baseline) == before
    assert (result.candidate_stage / "src/Widget.txt").read_text() == "value=2\n"
    assert targeted and full == [result.candidate_stage]
    assert {role for role, _ in calls} == {"planner", "backend", "reviewer"}
    assert hashlib.sha256((result.candidate_stage / "src/Widget.txt").read_bytes()).hexdigest() != before["src/Widget.txt"]["sha256"]
    run = json.loads(result.run_record.read_text(encoding="utf-8"))
    assert run["verified_stage_sha256"] == hive._source_manifest(result.candidate_stage)[1]
    assert run["applied"] is False


@pytest.mark.parametrize("verification,expected", [
    ({"passed": True, "checks": []}, True),
    ({"passed": False, "checks": [{"name": "synthetic", "passed": False}]}, False),
])
def test_verifier_decision_not_overridden_by_reviewer(monkeypatch, tmp_path, verification, expected):
    baseline, runs = fixture(tmp_path)
    monkeypatch.setattr(hive, "targeted_verify", lambda *_: verification)
    monkeypatch.setattr(hive, "verify_tree", lambda *_: verification)
    call, _ = scripted_call()
    result = asyncio.run(produce_candidate(spec(baseline, runs), call))
    assert result.software_verified is expected
    assert result.promotion_authorization == "unavailable"


@pytest.mark.parametrize("scope", [
    (), ("../escape",), ("src/../Widget.txt",),
    ("src/Widget.txt", "src/widget.TXT"), ("build/output.txt",),
])
def test_host_scope_rejected_before_model_or_verifier(tmp_path, scope):
    baseline, runs = fixture(tmp_path)
    call, calls = scripted_call()
    with pytest.raises((CandidatePolicyError, ValueError)):
        asyncio.run(produce_candidate(spec(baseline, runs, scope), call))
    assert not calls


def test_frozen_test_scope_rejected_before_agent(tmp_path):
    baseline, runs = fixture(tmp_path)
    frozen = ({"path": "src/test/java/hidden/FrozenTest.java", "class_name": "hidden.FrozenTest",
               "expected_cases": 1, "source": "class FrozenTest {}"},)
    call, calls = scripted_call()
    with pytest.raises(CandidatePolicyError, match="frozen acceptance"):
        asyncio.run(produce_candidate(spec(baseline, runs,
                                           ("src/test/java/hidden/FrozenTest.java",),
                                           frozen_junit_tests=frozen), call))
    assert not calls


def test_unauthorized_worker_edit_cannot_change_baseline(monkeypatch, tmp_path):
    baseline, runs = fixture(tmp_path)
    before = source_index(baseline)
    monkeypatch.setattr(hive, "targeted_verify", lambda *_: pytest.fail("unauthorized edit reached verifier"))
    call, _ = scripted_call(edit_path="src/Other.txt")
    result = asyncio.run(produce_candidate(spec(baseline, runs), call))
    assert not result.software_verified
    assert source_index(baseline) == before


def test_provider_failure_is_not_software_failure(monkeypatch, tmp_path):
    baseline, runs = fixture(tmp_path)
    call, _ = scripted_call(model_error=True)
    result = asyncio.run(produce_candidate(spec(baseline, runs), call))
    assert not result.software_verified
    assert result.failure_class == "LOCAL_RUNTIME_FAILURE"
    assert result.verification_status != "passed"


def test_targeted_failure_correction_budget_and_rollback(monkeypatch, tmp_path):
    baseline, runs = fixture(tmp_path)
    before = source_index(baseline)
    attempts = []
    monkeypatch.setattr(hive, "targeted_verify", lambda tree, role, files:
                        attempts.append((str(tree), role)) or
                        {"passed": False, "checks": [{"name": "synthetic-check", "passed": False,
                                                      "detail": "value differs"}]})
    monkeypatch.setattr(hive, "verify_tree", lambda *_: pytest.fail("full gate reached after targeted failure"))
    call, calls = scripted_call()
    result = asyncio.run(produce_candidate(spec(baseline, runs), call))
    run = json.loads(result.run_record.read_text(encoding="utf-8"))
    assert not result.software_verified
    assert source_index(baseline) == before
    assert source_index(result.candidate_stage) == before
    assert len(attempts) == 1
    assert len([role for role, _ in calls if role == "backend"]) == 2
    assert run["targeted_repairs"]
    assert run["applied"] is False


def test_duplicate_ownership_rejected_before_worker(tmp_path):
    p = plan()
    p["worker_files"]["ui"] = ["src/Widget.txt"]
    p["ui_goal"] = "Also edit Widget"
    with pytest.raises(Exception):
        hive._normalize_plan(p)


def test_provenance_rejects_false_completion_and_out_of_scope(tmp_path):
    baseline, runs = fixture(tmp_path)
    original = source_index(baseline)
    assert_scoped_change(original, original, ("src/Widget.txt",), [], require_change=False)
    with pytest.raises(CandidateIntegrityError):
        assert_scoped_change(original, original, ("src/Widget.txt",), [])
    changed = dict(original)
    changed["src/Other.txt"] = {"sha256": "0" * 64, "size": 1}
    with pytest.raises(CandidateIntegrityError):
        assert_scoped_change(original, changed, ("src/Widget.txt",), ["src/Other.txt"])
    with pytest.raises(CandidateIntegrityError):
        assert_scoped_change(original, changed, ("src/Widget.txt",), ["src/Widget.txt"])


def test_promotion_is_unavailable_even_with_host_call(tmp_path):
    with pytest.raises(PromotionUnavailableError):
        hive.apply_run(tmp_path, "anything")
    with pytest.raises(PromotionUnavailableError):
        hive._apply_run_locked(tmp_path, "anything")
    with pytest.raises(PromotionUnavailableError):
        hive.rollback_run(tmp_path, "anything")


def test_symlink_escape_rejected(tmp_path):
    baseline, _ = fixture(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    link = baseline / "src" / "escape.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    with pytest.raises((ValueError, OSError)):
        source_index(baseline)


def test_review_schema_rejects_truthy_string():
    with pytest.raises(Exception):
        hive_review.validate_decision({"approve": "false", "summary": "x", "issues": [], "confidence": 1})


def test_frozen_acceptance_source_is_not_worker_context(monkeypatch, tmp_path):
    baseline, runs = fixture(tmp_path)
    (baseline / "build.gradle").write_text("plugins { id 'java' }\n")
    (baseline / "gradlew").write_text("#!/bin/sh\nexit 0\n")
    (baseline / "gradlew.bat").write_text("@echo off\r\nexit /b 0\r\n")
    wrapper = baseline / "gradle" / "wrapper"
    wrapper.mkdir(parents=True)
    (wrapper / "gradle-wrapper.jar").write_bytes(b"fixture wrapper jar")
    (wrapper / "gradle-wrapper.properties").write_text(
        "distributionUrl=https\\://services.gradle.org/distributions/gradle-9.2.1-bin.zip\n"
        "distributionSha256Sum=" + "a" * 64 + "\n")
    hidden = "// PRIVATE_FROZEN_SENTINEL_DO_NOT_SHOW_TO_MODEL\nclass HiddenAcceptance {}\n"
    frozen = ({"path": "src/test/java/example/HiddenAcceptance.java",
               "class_name": "example.HiddenAcceptance", "expected_cases": 1, "source": hidden},)
    monkeypatch.setattr(hive, "targeted_verify", lambda *_: {"passed": True, "checks": []})
    monkeypatch.setattr(hive, "verify_tree", lambda *_: {"passed": True, "checks": []})
    call, calls = scripted_call()
    result = asyncio.run(produce_candidate(spec(baseline, runs, frozen_junit_tests=frozen), call))
    assert result.software_verified
    assert all("PRIVATE_FROZEN_SENTINEL" not in prompt for _, prompt in calls)
    assert not (result.candidate_stage / frozen[0]["path"]).exists()


def test_absolute_verifier_import_is_bound_to_private_recovered_copy():
    import verification.nfrt_seed as historical_name
    from hive_canonical.legacy.verification import nfrt_seed as private_copy
    assert historical_name is private_copy
