import hashlib
import subprocess
from pathlib import Path

import pytest

from kingdom import decompression_frontier_luna as luna_v1
from kingdom import decompression_semantic_authority_luna as v1
from kingdom import decompression_semantic_authority_luna_v1_1 as v1_1


REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_repo(path):
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "protocol@example.invalid")
    _git(path, "config", "user.name", "Protocol Test")
    (path / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")


def _commit_all(repo, message):
    _git(repo, "add", "--all")
    _git(repo, "commit", "-q", "-m", message)


def _preflight(revision, sha256, blob_oids):
    return {
        "source_revision": revision,
        "source_file_sha256": sha256,
        "source_file_git_blob_oid": blob_oids,
    }


def test_actual_mixed_eol_hive_llm_passes_git_filtered_source_guard():
    eol = _git(REPO_ROOT, "ls-files", "--eol", "--", "hive_llm.py")
    assert "w/mixed" in eol
    revision, sha256, blob_oids = v1_1._source_maps(
        REPO_ROOT, ("hive_llm.py",)
    )
    assert hashlib.sha256((REPO_ROOT / "hive_llm.py").read_bytes()).hexdigest() != sha256[
        "hive_llm.py"
    ]
    v1_1._assert_sources_unchanged(
        REPO_ROOT,
        _preflight(revision, sha256, blob_oids),
        ("hive_llm.py",),
    )


def test_semantic_worktree_modification_fails_filtered_source_guard(tmp_path):
    repo = tmp_path / "semantic"
    _init_repo(repo)
    source = repo / "sample.py"
    source.write_bytes(b"VALUE = 1\r\n")
    _commit_all(repo, "base")
    revision, sha256, blob_oids = v1_1._source_maps(repo, ("sample.py",))
    source.write_bytes(b"VALUE = 2\r\n")

    with pytest.raises(luna_v1.ApparatusFailure, match="direct worktree"):
        v1_1._assert_sources_unchanged(
            repo,
            _preflight(revision, sha256, blob_oids),
            ("sample.py",),
        )


def test_malicious_clean_filter_cannot_hide_a_semantic_worktree_edit(tmp_path):
    repo = tmp_path / "filter"
    _init_repo(repo)
    filter_script = repo / ".git" / "hide_edit.py"
    filter_script.write_text(
        "import sys\n"
        "data = sys.stdin.buffer.read()\n"
        "sys.stdout.buffer.write(data.replace(b'VALUE = 999', b'VALUE = 1'))\n",
        encoding="utf-8",
    )
    _git(repo, "config", "filter.hide.clean", "python .git/hide_edit.py")
    (repo / ".gitattributes").write_text(
        "* text=auto\nsample.py filter=hide\n", encoding="utf-8"
    )
    source = repo / "sample.py"
    source.write_bytes(b"VALUE = 1\r\n")
    _commit_all(repo, "base")
    revision, sha256, blob_oids = v1_1._source_maps(repo, ("sample.py",))
    source.write_bytes(b"VALUE = 999\r\n")

    old_filtered_oid = _git(
        repo, "hash-object", "--path", "sample.py", "--", "sample.py"
    )
    assert old_filtered_oid == blob_oids["sample.py"]
    with pytest.raises(luna_v1.ApparatusFailure, match="direct worktree"):
        v1_1._assert_sources_unchanged(
            repo,
            _preflight(revision, sha256, blob_oids),
            ("sample.py",),
        )


def test_empty_source_maps_fail_closed_even_when_both_are_empty():
    revision = _git(REPO_ROOT, "rev-parse", "HEAD")
    with pytest.raises(luna_v1.ApparatusFailure, match="source maps"):
        v1_1._assert_sources_unchanged(
            REPO_ROOT,
            _preflight(revision, {}, {}),
            v1_1.SOURCE_FILES,
        )


def test_head_revision_drift_fails_before_source_comparison(tmp_path):
    repo = tmp_path / "revision"
    _init_repo(repo)
    (repo / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(repo, "base")
    revision, sha256, blob_oids = v1_1._source_maps(repo, ("sample.py",))
    (repo / "unrelated.txt").write_text("new revision\n", encoding="utf-8")
    _commit_all(repo, "advance")

    with pytest.raises(luna_v1.ApparatusFailure, match="revision changed"):
        v1_1._assert_sources_unchanged(
            repo,
            _preflight(revision, sha256, blob_oids),
            ("sample.py",),
        )


def test_sealed_v1_invalid_artifact_is_unchanged_and_still_verifies():
    run_dir = REPO_ROOT / v1_1.SEALED_V1_RUN_DIR
    before = {
        path.relative_to(run_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in run_dir.rglob("*")
        if path.is_file()
    }
    bound = v1_1.verify_sealed_v1_failure(REPO_ROOT)
    after = {
        path.relative_to(run_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in run_dir.rglob("*")
        if path.is_file()
    }

    assert before == after == v1_1.SEALED_V1_ARTIFACT_SHA256
    assert bound["sealed_v1_evidence_commit"] == v1_1.SEALED_V1_EVIDENCE_COMMIT
    assert bound["sealed_v1_implementation_commit"] == v1_1.SEALED_V1_IMPLEMENTATION_COMMIT
    assert bound["sealed_v1_evidence_tree_oid"] == v1_1.SEALED_V1_EVIDENCE_TREE_OID
    assert bound["sealed_v1_verification"]["result_code"] == "INVALID_APPARATUS"
    assert bound["sealed_v1_verification"]["physical_generation_calls"] == 0


def test_new_live_directory_is_absent():
    assert v1_1.PROTOCOL_ID == "hive-luna-semantic-authority-decomposition-v1-1"
    assert v1_1.PROTOCOL_VERSION == "1.1"
    assert v1_1.RUN_DIR == Path(
        ".hive/benchmarks/decompression_test/"
        "luna-semantic-authority-decomposition-v1-1-001"
    )
    assert not (REPO_ROOT / v1_1.RUN_DIR).exists()


def test_complete_v1_1_source_list_must_be_committed(tmp_path):
    repo = tmp_path / "sources"
    _init_repo(repo)
    for index, relative in enumerate(v1_1.SOURCE_FILES):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"source {index}\n", encoding="utf-8")
    omitted = v1_1.SOURCE_FILES[-1]
    _git(repo, "add", ".gitattributes")
    for relative in v1_1.SOURCE_FILES[:-1]:
        _git(repo, "add", "--", relative)
    _git(repo, "commit", "-q", "-m", "incomplete")

    with pytest.raises(luna_v1.ApparatusFailure, match=f"not committed: {omitted}"):
        v1_1._source_maps(repo)

    _git(repo, "add", "--", omitted)
    _git(repo, "commit", "-q", "-m", "complete")
    _, sha256, blob_oids = v1_1._source_maps(repo)
    assert set(sha256) == set(blob_oids) == set(v1_1.SOURCE_FILES)
    assert len(v1_1.SOURCE_FILES) == len(set(v1_1.SOURCE_FILES))
    assert set(v1.SOURCE_FILES).issubset(v1_1.SOURCE_FILES)


def test_v1_1_preflight_preserves_every_inference_contract_hash():
    _, cases, calls, preflight = v1_1.deterministic_preflight(
        REPO_ROOT, require_committed=False
    )

    assert len(cases) == 20
    assert len(calls) == 384
    assert preflight["protocol_id"] == v1_1.PROTOCOL_ID
    assert preflight["protocol_version"] == v1_1.PROTOCOL_VERSION
    assert preflight["request_plan_sha256"] == v1.FROZEN_REQUEST_PLAN_SHA256
    assert preflight["condition_schedule_sha256"] == v1.FROZEN_SCHEDULE_SHA256
    assert preflight["solver_config"] == v1.solver_config().to_mapping()
    assert preflight["solver_config_sha256"] == v1.solver_config().configuration_hash
    assert preflight["source_file_git_blob_oid"] == {}
    assert preflight["source_guard"] == {
        "version": "direct-crlf-normalized-bytes-v1.1",
        "head_revision_required": True,
        "head_blob_must_match_preflight": True,
        "direct_worktree_crlf_to_lf_must_equal_committed_bytes": True,
        "canonical_git_show_sha256_must_match_preflight": True,
        "git_clean_filters_consulted_for_worktree_equality": False,
    }
    assert preflight["cost"]["authorized_cost_ceiling_usd"] == 100.0
    assert preflight["c1_prior_byte_equivalence"] is True
    assert preflight["kas_prior_c2_byte_equivalence"] is True
    assert [call.prompt for call in calls] == [
        call.prompt for call in v1.build_call_plan(*_case_pack())
    ]
    assert v1.PROTOCOL_ID == "hive-luna-semantic-authority-decomposition-v1"


def _case_pack():
    from kingdom import decompression_test as worlds

    payload, cases = worlds.load_case_pack(
        REPO_ROOT / "benchmarks/decompression_test/CASE_PACK.json"
    )
    return payload, cases
