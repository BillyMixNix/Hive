from pathlib import Path

import pytest

from validation.live_loop import (
    completion_score,
    deploy_approved_patch,
    evaluate_patch_result,
    rollback_approved_patch,
)


BASE_SOURCE = "def adjust(x):\n    return x\n"
PATCH = (
    "TARGET_FILE: target.py\n"
    "CHANGE_TYPE: diff_patch\n"
    "STATUS: proposed\n"
    "REASON: Add one to the input.\n"
    "PATCH:\n"
    "--- target.py\n"
    "+++ target.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def adjust(x):\n"
    "-    return x\n"
    "+    return x + 1\n"
)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "target.py").write_text(BASE_SOURCE, encoding="utf-8")
    return repo


def proposed_result() -> dict:
    return {
        "status": "proposed",
        "target_file": "target.py",
        "patch": PATCH,
        "reason": "Add one to the input.",
    }


def test_completion_score_has_headroom_for_task_specific_change(tmp_path):
    repo = make_repo(tmp_path)
    assert completion_score(repo, "target.py", ["return x + 1"]) == 0.0
    (repo / "target.py").write_text("def adjust(x):\n    return x + 1\n", encoding="utf-8")
    assert completion_score(repo, "target.py", ["return x + 1"]) == 1.0


def test_live_adapter_turns_measured_improvement_into_candidate(tmp_path):
    repo = make_repo(tmp_path)
    archive = tmp_path / "archive.jsonl"

    result = evaluate_patch_result(
        proposed_result(),
        task_note="Make adjust return x plus one.",
        repo_root=repo,
        completion_cues=["return x + 1"],
        archive_path=archive,
        benchmark_scorer=lambda _root: 1.0,
    )

    assert result["status"] == "candidate"
    assert result["empirical_validation"]["decision"] == "candidate"
    assert result["empirical_validation"]["delta"] == pytest.approx(1.0)
    assert (repo / "target.py").read_text(encoding="utf-8") == BASE_SOURCE


def test_live_adapter_rejects_missing_completion_cues(tmp_path):
    repo = make_repo(tmp_path)

    result = evaluate_patch_result(
        proposed_result(),
        task_note="Make adjust better.",
        repo_root=repo,
        completion_cues=[],
        benchmark_scorer=lambda _root: 1.0,
    )

    assert result["status"] == "blocked"
    assert result["llm_error"] == "empirical_gate_requires_completion_cues"


def test_regression_guard_rejects_candidate_before_task_scoring(tmp_path):
    repo = make_repo(tmp_path)
    archive = tmp_path / "archive.jsonl"

    def benchmark(root: Path) -> float:
        text = (Path(root) / "target.py").read_text(encoding="utf-8")
        return 0.5 if "return x + 1" in text else 1.0

    result = evaluate_patch_result(
        proposed_result(),
        task_note="Make adjust return x plus one.",
        repo_root=repo,
        completion_cues=["return x + 1"],
        archive_path=archive,
        benchmark_scorer=benchmark,
    )

    assert result["status"] == "blocked"
    assert "regression detected" in result["empirical_validation"]["verification_reason"]
    assert (repo / "target.py").read_text(encoding="utf-8") == BASE_SOURCE


def test_explicit_pilot_deploy_and_rollback_use_archived_candidate(tmp_path):
    repo = make_repo(tmp_path)
    archive = tmp_path / "archive.jsonl"
    result = evaluate_patch_result(
        proposed_result(),
        task_note="Make adjust return x plus one.",
        repo_root=repo,
        completion_cues=["return x + 1"],
        archive_path=archive,
        benchmark_scorer=lambda _root: 1.0,
    )

    deployment = deploy_approved_patch(result, repo_root=repo, archive_path=archive)
    assert deployment["status"] == "deployed"
    assert "return x + 1" in (repo / "target.py").read_text(encoding="utf-8")

    rollback = rollback_approved_patch(result, repo_root=repo, archive_path=archive)
    assert rollback["status"] == "rolled_back"
    assert (repo / "target.py").read_text(encoding="utf-8") == BASE_SOURCE
