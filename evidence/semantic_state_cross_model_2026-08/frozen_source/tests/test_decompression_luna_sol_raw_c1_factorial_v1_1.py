from __future__ import annotations

import json
from pathlib import Path

import pytest

from kingdom import decompression_luna_sol_raw_c1_factorial as v1
from kingdom import decompression_luna_sol_raw_c1_factorial_v1_1 as v1_1
from tests.test_decompression_luna_sol_raw_c1_factorial import FakeFactorial


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v1_1_is_an_exact_fresh_realization_of_v1():
    _payload_v1, cases_v1, calls_v1, preflight_v1 = v1._derived_preflight(
        REPO_ROOT, require_committed=False
    )
    _payload_v1_1, cases_v1_1, calls_v1_1, preflight_v1_1 = (
        v1_1.deterministic_preflight(REPO_ROOT, require_committed=False)
    )
    assert cases_v1_1 == cases_v1
    assert calls_v1_1 == calls_v1
    assert len(calls_v1_1) == 192
    allowed_preflight_differences = {
        "protocol_id",
        "protocol_version",
        "lineage",
        "payload_sha256",
        "source_file_sha256",
    }
    assert {
        key: value
        for key, value in preflight_v1_1.items()
        if key not in allowed_preflight_differences
    } == {
        key: value
        for key, value in preflight_v1.items()
        if key not in allowed_preflight_differences
    }
    assert preflight_v1_1["protocol_id"] == v1_1.PROTOCOL_ID
    assert preflight_v1_1["protocol_version"] == "1.1"
    assert preflight_v1_1["lineage"]["v1_outputs_excluded_from_v1_1"] is True
    assert preflight_v1_1["lineage"]["common_sources_match_sealed_v1"] is True
    assert preflight_v1_1["lineage"]["common_source_count"] == len(v1.SOURCE_FILES)
    assert preflight_v1_1["lineage"]["common_sources_sha256"] == (
        v1_1.SEALED_V1_COMMON_SOURCES_SHA256
    )
    common_sources = set(v1.SOURCE_FILES)
    assert set(preflight_v1_1["source_file_sha256"]) - common_sources == {
        v1_1.MODULE_PATH,
        v1_1.PROTOCOL_PATH,
        v1_1.TEST_PATH,
    }
    assert v1.PROTOCOL_ID == "hive-luna-sol-raw-c1-factorial-v1"


def test_v1_1_frozen_hashes_configs_cost_and_statistics_equal_v1():
    derived_v1 = v1.derived_frozen_values(REPO_ROOT)
    derived_v1_1 = v1_1.derived_frozen_values(REPO_ROOT)
    assert derived_v1_1 == derived_v1
    _p0, _c0, _calls0, preflight_v1 = v1._derived_preflight(
        REPO_ROOT, require_committed=False
    )
    _p1, _c1, _calls1, preflight_v1_1 = v1_1.deterministic_preflight(
        REPO_ROOT, require_committed=False
    )
    for key in (
        "condition_schedule_sha256",
        "request_plan_sha256",
        "solver_config_sha256",
        "solver_configs",
        "statistics",
        "capability_gate",
        "cost",
        "maximum_physical_generation_calls",
        "retry",
        "repair",
        "resume",
        "overwrite",
    ):
        assert preflight_v1_1[key] == preflight_v1[key]


def test_sealed_v1_failure_is_verified_and_excluded():
    lineage = v1_1.verify_sealed_v1(REPO_ROOT)
    assert lineage["restart_parent"] == v1_1.SEALED_V1_EVIDENCE_COMMIT
    assert lineage["v1_disposition"] == "INVALID_APPARATUS"
    assert lineage["v1_outputs_excluded_from_v1_1"] is True
    assert lineage["v1_verification"]["physical_generation_calls"] == 22
    assert lineage["v1_verification"]["decision_artifacts"] == 21
    assert lineage["v1_run_tree_oid"] == v1_1.SEALED_V1_RUN_TREE_OID
    assert lineage["v1_response_id_count"] == 21
    assert lineage["v1_response_ids_sha256"] == (
        v1_1.SEALED_V1_RESPONSE_IDS_SHA256
    )
    assert lineage["common_sources_match_sealed_v1"] is True


def test_fresh_run_path_is_distinct_absent_and_live_locked(tmp_path):
    assert v1_1.RUN_DIR != v1.RUN_DIR
    assert not (REPO_ROOT / v1_1.RUN_DIR).exists()
    with pytest.raises(v1.ApparatusFailure, match="locked to the frozen run directory"):
        v1_1.RestartRunner(
            repo_root=REPO_ROOT,
            output_dir=tmp_path / "wrong-live-dir",
            ask_fn=lambda *_args, **_kwargs: "",
            require_committed=True,
            progress_stream=False,
        ).run()


def test_complete_fake_v1_1_run_uses_new_identity_and_verifies(tmp_path):
    _payload, cases, _calls, _preflight = v1_1.deterministic_preflight(
        REPO_ROOT, require_committed=False
    )
    fake = FakeFactorial(cases)
    run_dir = tmp_path / "v1-1-complete"
    result = v1_1.RestartRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
        progress_stream=False,
    ).run()
    assert result["validity"] == "VALID"
    assert result["protocol_id"] == v1_1.PROTOCOL_ID
    assert result["source_revision"] == "TEST_UNCOMMITTED"
    assert result["physical_generation_calls"] == 192
    assert len(fake.calls) == 192
    verified = v1_1.verify_run(run_dir)
    assert verified["verified"] is True
    assert verified["protocol_id"] == v1_1.PROTOCOL_ID
    assert verified["physical_generation_calls"] == 192
    assert verified["unique_response_ids"] == 192
    assert verified["sealed_v1_response_id_overlap"] == 0

    old_id = sorted(v1_1.sealed_v1_response_ids(REPO_ROOT))[0]
    call_path = sorted(run_dir.glob("*/calls/call_*.json"))[0]
    call = json.loads(call_path.read_text(encoding="utf-8"))
    call["transport_metadata"]["response_id"] = old_id
    call_path.write_text(
        v1._pretty_json(
            v1._sealed(
                {key: value for key, value in call.items() if key != "payload_sha256"}
            )
        ),
        encoding="utf-8",
    )
    decision_path = (
        call_path.parent.parent
        / "decisions"
        / f"decision_{call['sequence']:06d}.json"
    )
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision["response_id"] = old_id
    decision_path.write_text(
        v1._pretty_json(
            v1._sealed(
                {
                    key: value
                    for key, value in decision.items()
                    if key != "payload_sha256"
                }
            )
        ),
        encoding="utf-8",
    )
    index_path = run_dir / "EVIDENCE_INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index_body = {
        key: value for key, value in index.items() if key != "payload_sha256"
    }
    changed = {
        call_path.relative_to(run_dir).as_posix(): call_path,
        decision_path.relative_to(run_dir).as_posix(): decision_path,
    }
    for row in index_body["files"]:
        if row["path"] in changed:
            path = changed[row["path"]]
            row["bytes"] = path.stat().st_size
            row["sha256"] = v1._sha256_bytes(path.read_bytes())
    index_body["total_bytes"] = sum(row["bytes"] for row in index_body["files"])
    index_path.write_text(
        v1._pretty_json(v1._sealed(index_body)), encoding="utf-8"
    )
    with pytest.raises(v1.ApparatusFailure, match="sealed-v1"):
        v1_1.verify_run(run_dir)


def test_activation_restores_v1_and_v1_artifacts_cannot_verify_as_v1_1():
    original = (v1.PROTOCOL_ID, v1.PROTOCOL_VERSION, v1.RUN_DIR, v1.SOURCE_FILES)
    with pytest.raises(RuntimeError, match="probe"):
        with v1_1._v1_1_bindings():
            assert v1.PROTOCOL_ID == v1_1.PROTOCOL_ID
            assert v1.RUN_DIR == v1_1.RUN_DIR
            raise RuntimeError("probe")
    assert (v1.PROTOCOL_ID, v1.PROTOCOL_VERSION, v1.RUN_DIR, v1.SOURCE_FILES) == original
    with pytest.raises(v1.ApparatusFailure):
        v1_1.verify_run(REPO_ROOT / v1.RUN_DIR)


def test_parser_failure_in_v1_1_stops_without_retry_and_verifies(tmp_path):
    _payload, cases, _calls, _preflight = v1_1.deterministic_preflight(
        REPO_ROOT, require_committed=False
    )
    fake = FakeFactorial(cases, malformed_call=2)
    run_dir = tmp_path / "v1-1-parser-failure"
    result = v1_1.RestartRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
        progress_stream=False,
    ).run()
    assert result["validity"] == "INVALID"
    assert result["failed_global_sequence"] == 2
    assert result["retry_attempted"] is False
    assert result["repair_attempted"] is False
    assert result["usage"]["total"]["physical_generation_calls"] == 2
    assert v1_1.verify_run(run_dir)["validity"] == "INVALID"


def test_live_guard_rejects_a_real_sealed_v1_response_id_before_grading(tmp_path):
    _payload, cases, _calls, _preflight = v1_1.deterministic_preflight(
        REPO_ROOT, require_committed=False
    )
    old_id = sorted(v1_1.sealed_v1_response_ids(REPO_ROOT))[0]

    class OldIdentityFake(FakeFactorial):
        def __call__(self, prompt, **kwargs):
            response = super().__call__(prompt, **kwargs)
            kwargs["metadata"]["response_id"] = old_id
            return response

    fake = OldIdentityFake(cases)
    run_dir = tmp_path / "v1-1-old-identity"
    result = v1_1.RestartRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
        progress_stream=False,
    ).run()
    assert result["validity"] == "INVALID"
    assert result["failed_global_sequence"] == 1
    assert result["usage"]["total"]["physical_generation_calls"] == 1
    assert result["retry_attempted"] is False
    call = json.loads(next(run_dir.glob("*/calls/call_*.json")).read_text(encoding="utf-8"))
    assert call["status"] == "metadata_rejected"
    assert call["transport_metadata"]["response_id"] is None
    assert call["transport_metadata"]["sealed_v1_response_id_rejected"] == old_id
    verified = v1_1.verify_run(run_dir)
    assert verified["validity"] == "INVALID"
    assert verified["sealed_v1_response_id_overlap"] == 0
    assert verified["sealed_v1_response_id_rejections"] == 1


def test_v1_1_runtime_sources_include_wrapper_protocol_and_tests():
    assert {
        v1_1.MODULE_PATH,
        v1_1.PROTOCOL_PATH,
        v1_1.TEST_PATH,
    }.issubset(v1_1.SOURCE_FILES)
    assert set(v1.SOURCE_FILES).issubset(v1_1.SOURCE_FILES)
