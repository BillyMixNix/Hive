from pathlib import Path

import pytest

from validation.archive import read_events
from validation.gate import evaluate, promote_candidate, rollback_deployment


BASE_SOURCE = "def adjust(x):\n    return x\n"

BENEFICIAL_PATCH = (
    "TARGET_FILE: target.py\n"
    "CHANGE_TYPE: diff_patch\n"
    "STATUS: proposed\n"
    "REASON: Correct the adjustment by adding one.\n"
    "PATCH:\n"
    "--- target.py\n"
    "+++ target.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def adjust(x):\n"
    "-    return x\n"
    "+    return x + 1\n"
)

HARMFUL_PATCH = BENEFICIAL_PATCH.replace(
    "Correct the adjustment by adding one.",
    "Incorrectly subtract one.",
).replace("return x + 1", "return x - 1")

NEUTRAL_PATCH = (
    "TARGET_FILE: target.py\n"
    "PATCH:\n"
    "--- target.py\n"
    "+++ target.py\n"
    "@@ -1,2 +1,3 @@\n"
    " def adjust(x):\n"
    "+    # Keep the existing behavior.\n"
    "     return x\n"
)

BROKEN_PATCH = (
    "TARGET_FILE: target.py\n"
    "PATCH:\n"
    "--- target.py\n"
    "+++ target.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def adjust(x):\n"
    "-    return x\n"
    "+    return (\n"
)


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "target.py").write_text(BASE_SOURCE, encoding="utf-8")
    (repo / "benchmark_harness.py").write_text("# protected\n", encoding="utf-8")
    return repo


def behavioral_score(repo: Path) -> float:
    text = (repo / "target.py").read_text(encoding="utf-8")
    if "return x + 1" in text:
        return 1.0
    if "return x - 1" in text:
        return 0.0
    return 0.5


def test_harmful_patch_is_rejected_and_live_repo_is_untouched(tmp_path):
    repo = make_repo(tmp_path)
    archive = tmp_path / "archive.jsonl"

    record = evaluate(
        HARMFUL_PATCH,
        "Make adjust return x plus one.",
        repo_root=repo,
        scorer=behavioral_score,
        archive_path=archive,
        n=3,
    )

    assert record["decision"] == "reject"
    assert record["delta"] == pytest.approx(-0.5)
    assert (repo / "target.py").read_text(encoding="utf-8") == BASE_SOURCE


def test_neutral_patch_is_rejected_for_no_measured_gain(tmp_path):
    repo = make_repo(tmp_path)
    archive = tmp_path / "archive.jsonl"

    record = evaluate(
        NEUTRAL_PATCH,
        "Document adjust without changing behavior.",
        repo_root=repo,
        scorer=behavioral_score,
        archive_path=archive,
        n=3,
    )

    assert record["decision"] == "reject"
    assert record["delta"] == pytest.approx(0.0)
    assert "no significant gain" in record["reason"]
    assert (repo / "target.py").read_text(encoding="utf-8") == BASE_SOURCE


def test_beneficial_patch_becomes_candidate_but_is_not_auto_deployed(tmp_path):
    repo = make_repo(tmp_path)
    archive = tmp_path / "archive.jsonl"

    record = evaluate(
        BENEFICIAL_PATCH,
        "Make adjust return x plus one.",
        repo_root=repo,
        scorer=behavioral_score,
        archive_path=archive,
        n=3,
    )

    assert record["decision"] == "candidate"
    assert record["delta"] == pytest.approx(0.5)
    assert record["deployment_status"] == "not_deployed"
    assert (repo / "target.py").read_text(encoding="utf-8") == BASE_SOURCE

    with pytest.raises(PermissionError):
        promote_candidate(
            record["evaluation_id"],
            repo_root=repo,
            archive_path=archive,
        )

    deployment = promote_candidate(
        record["evaluation_id"],
        repo_root=repo,
        archive_path=archive,
        pilot_approved=True,
    )
    assert deployment["status"] == "deployed"
    assert "return x + 1" in (repo / "target.py").read_text(encoding="utf-8")


def test_deployment_refuses_stale_live_source(tmp_path):
    repo = make_repo(tmp_path)
    archive = tmp_path / "archive.jsonl"
    record = evaluate(
        BENEFICIAL_PATCH,
        "Make adjust return x plus one.",
        repo_root=repo,
        scorer=behavioral_score,
        archive_path=archive,
        n=2,
    )
    (repo / "target.py").write_text("def adjust(x):\n    return x * 2\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed after evaluation"):
        promote_candidate(
            record["evaluation_id"],
            repo_root=repo,
            archive_path=archive,
            pilot_approved=True,
        )


def test_protected_grader_patch_is_rejected_before_application(tmp_path):
    repo = make_repo(tmp_path)
    archive = tmp_path / "archive.jsonl"
    patch = (
        "TARGET_FILE: benchmark_harness.py\n"
        "PATCH:\n"
        "--- benchmark_harness.py\n"
        "+++ benchmark_harness.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-# protected\n"
        "+# easier grader\n"
    )

    record = evaluate(
        patch,
        "Make the benchmark easier.",
        repo_root=repo,
        scorer=behavioral_score,
        archive_path=archive,
        n=2,
    )

    assert record["decision"] == "reject"
    assert record["reason"].startswith("grader_tamper_rejected")
    assert (repo / "benchmark_harness.py").read_text(encoding="utf-8") == "# protected\n"


def test_syntax_failure_is_rejected_before_scoring(tmp_path):
    repo = make_repo(tmp_path)
    archive = tmp_path / "archive.jsonl"
    calls = {"count": 0}

    def counting_score(path):
        calls["count"] += 1
        return behavioral_score(path)

    record = evaluate(
        BROKEN_PATCH,
        "Break the target syntax.",
        repo_root=repo,
        scorer=counting_score,
        archive_path=archive,
        n=2,
    )

    assert record["decision"] == "reject"
    assert record["reason"].startswith("self_verification_failed")
    assert calls["count"] == 0
    assert (repo / "target.py").read_text(encoding="utf-8") == BASE_SOURCE


def test_deployed_candidate_can_be_rolled_back_with_pilot_approval(tmp_path):
    repo = make_repo(tmp_path)
    archive = tmp_path / "archive.jsonl"
    record = evaluate(
        BENEFICIAL_PATCH,
        "Make adjust return x plus one.",
        repo_root=repo,
        scorer=behavioral_score,
        archive_path=archive,
        n=2,
    )
    promote_candidate(
        record["evaluation_id"],
        repo_root=repo,
        archive_path=archive,
        pilot_approved=True,
    )

    with pytest.raises(PermissionError):
        rollback_deployment(
            record["evaluation_id"],
            repo_root=repo,
            archive_path=archive,
        )

    rollback = rollback_deployment(
        record["evaluation_id"],
        repo_root=repo,
        archive_path=archive,
        pilot_approved=True,
    )
    assert rollback["status"] == "rolled_back"
    assert (repo / "target.py").read_text(encoding="utf-8") == BASE_SOURCE


def test_archive_records_evaluation_and_deployment_provenance(tmp_path):
    repo = make_repo(tmp_path)
    archive = tmp_path / "archive.jsonl"
    record = evaluate(
        BENEFICIAL_PATCH,
        "Make adjust return x plus one.",
        repo_root=repo,
        scorer=behavioral_score,
        archive_path=archive,
        n=2,
    )
    promote_candidate(
        record["evaluation_id"],
        repo_root=repo,
        archive_path=archive,
        pilot_approved=True,
    )

    events = read_events(archive)
    assert [event["event_type"] for event in events] == ["evaluation", "deployment"]
    evaluation = events[0]
    assert evaluation["pre_patch_sha256"]
    assert evaluation["candidate_sha256"]
    assert evaluation["patch_text"] == BENEFICIAL_PATCH
    assert events[1]["pilot_approved"] is True
