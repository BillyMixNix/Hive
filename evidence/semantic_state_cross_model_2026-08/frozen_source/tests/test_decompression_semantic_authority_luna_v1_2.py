import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from kingdom import decompression_frontier_luna as luna_v1
from kingdom import decompression_semantic_authority_luna as v1
from kingdom import decompression_semantic_authority_luna_v1_1 as v1_1
from kingdom import decompression_semantic_authority_luna_v1_2 as v1_2
from kingdom import decompression_test_v2 as grading
from tests.test_decompression_frontier_luna_v1_1 import FakeCompletionLuna, _cases


REPO_ROOT = Path(__file__).resolve().parents[1]


class FailFirstTransportThenComplete(FakeCompletionLuna):
    def __call__(self, prompt, **kwargs):
        if not self.calls:
            self.calls.append({"prompt": prompt, **kwargs})
            kwargs["metadata"].update(
                {
                    **kwargs["solver_config"].to_mapping(),
                    "configuration_hash": kwargs[
                        "solver_config"
                    ].configuration_hash,
                    "requested_model": kwargs["solver_config"].model,
                    "returned_model": None,
                    "returned_service_tier": None,
                    "response_id": None,
                    "physical_attempts": 1,
                    "response_status": None,
                    "input_tokens": None,
                    "cached_input_tokens": None,
                    "cache_write_input_tokens": None,
                    "output_tokens": None,
                    "reasoning_tokens": None,
                    "total_tokens": None,
                    "latency_seconds": 0.01,
                    "sdk_version": luna_v1.EXPECTED_OPENAI_SDK,
                    "adapter_status": "transport_error",
                    "openai_text_format": kwargs["openai_text_format"],
                    "openai_text_format_sha256": luna_v1._sha256_text(
                        luna_v1._canonical_json(kwargs["openai_text_format"])
                    ),
                }
            )
            raise TimeoutError("isolated synthetic transport timeout")
        response = super().__call__(prompt, **kwargs)
        kwargs["metadata"]["returned_model"] = kwargs["solver_config"].model
        return response


class IncompleteResponseIdThenDuplicateCompletion(FakeCompletionLuna):
    def __call__(self, prompt, **kwargs):
        if not self.calls:
            self.calls.append({"prompt": prompt, **kwargs})
            config = kwargs["solver_config"]
            text_format = kwargs["openai_text_format"]
            kwargs["metadata"].update(
                {
                    **config.to_mapping(),
                    "configuration_hash": config.configuration_hash,
                    "requested_model": config.model,
                    "returned_model": config.model,
                    "returned_service_tier": config.service_tier,
                    "response_id": "resp_duplicate",
                    "response_status": "incomplete",
                    "physical_attempts": 1,
                    "latency_seconds": 0.01,
                    "input_tokens": 10,
                    "cached_input_tokens": 0,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 1,
                    "reasoning_tokens": 1,
                    "total_tokens": 11,
                    "sdk_version": luna_v1.EXPECTED_OPENAI_SDK,
                    "adapter_status": "rejected",
                    "openai_text_format": text_format,
                    "openai_text_format_sha256": luna_v1._sha256_text(
                        luna_v1._canonical_json(text_format)
                    ),
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "response_error": None,
                    "partial_output_text": "",
                }
            )
            raise RuntimeError(
                "OpenAI response rejected: response status is 'incomplete'"
            )
        response = super().__call__(prompt, **kwargs)
        kwargs["metadata"]["returned_model"] = kwargs["solver_config"].model
        kwargs["metadata"]["response_id"] = "resp_duplicate"
        return response


def _rewrite_indexed_json(run_dir, relative, payload):
    path = run_dir / relative
    rewritten = dict(payload)
    rewritten.pop("payload_sha256", None)
    path.write_text(
        luna_v1._pretty_json(luna_v1._sealed(rewritten)),
        encoding="utf-8",
        newline="\n",
    )
    index_path = run_dir / "EVIDENCE_INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index.pop("payload_sha256")
    row = next(row for row in index["files"] if row["path"] == relative)
    row["bytes"] = path.stat().st_size
    row["sha256"] = luna_v1._sha256_bytes(path.read_bytes())
    index["total_bytes"] = sum(row["bytes"] for row in index["files"])
    index_path.write_text(
        luna_v1._pretty_json(luna_v1._sealed(index)),
        encoding="utf-8",
        newline="\n",
    )


def _refresh_indexed_file(run_dir, relative):
    path = run_dir / relative
    index_path = run_dir / "EVIDENCE_INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index.pop("payload_sha256")
    row = next(row for row in index["files"] if row["path"] == relative)
    row["bytes"] = path.stat().st_size
    row["sha256"] = luna_v1._sha256_bytes(path.read_bytes())
    index["total_bytes"] = sum(row["bytes"] for row in index["files"])
    index_path.write_text(
        luna_v1._pretty_json(luna_v1._sealed(index)),
        encoding="utf-8",
        newline="\n",
    )


def _rebuild_index(run_dir):
    index_path = run_dir / "EVIDENCE_INDEX.json"
    source_revision = json.loads(index_path.read_text(encoding="utf-8"))[
        "source_revision"
    ]
    index_path.unlink()
    with v1_2._activated_protocol():
        v1._write_evidence_index(run_dir, source_revision=source_revision)


@pytest.fixture(scope="module")
def continued_run(tmp_path_factory):
    _, cases = _cases()
    fake = FailFirstTransportThenComplete(cases)
    run_dir = tmp_path_factory.mktemp("semantic-v12-verifier") / "continued"
    original_guard = v1_2._assert_sources_unchanged
    v1_2._assert_sources_unchanged = lambda *_: None
    try:
        result = v1_2.SemanticDecompositionV12Runner(
            repo_root=REPO_ROOT,
            output_dir=run_dir,
            ask_fn=fake,
            require_committed=False,
        ).run()
    finally:
        v1_2._assert_sources_unchanged = original_guard
    verified = v1_2.verify_run(run_dir)
    assert result["validity"] == "VALID"
    assert verified["physical_generation_calls"] == 384
    return run_dir, result, fake, verified


def _perfect_scores():
    _, cases = _cases()
    result = {
        replication: {condition: [] for condition in v1.CONDITIONS}
        for replication in range(1, 9)
    }
    for replication in range(1, 9):
        for condition in v1.CONDITIONS:
            result[replication][condition] = [
                grading.grade_label(case, case.correct_choice, condition=condition)
                for case in cases
            ]
    return result


def _set_correct_count(scores, replication, condition, correct):
    scores[replication][condition] = [
        row if index < correct else replace(row, answer_correct=False)
        for index, row in enumerate(scores[replication][condition])
    ]


def _classify_scores(scores):
    analysis = v1_2.matched_primary_analysis(scores)
    secondary = v1_2.matched_secondary_analysis(analysis)
    kas = v1_2.kas_replication_analysis(analysis)
    return v1_2._classification(analysis, secondary, kas)


def test_cap_and_request_parity_except_cap_and_config_hash():
    _, _, calls, preflight = v1_2.deterministic_preflight(
        REPO_ROOT, require_committed=False
    )
    _, _, old_calls, old_preflight = v1_1.deterministic_preflight(
        REPO_ROOT, require_committed=False
    )
    assert preflight["solver_config"]["max_output_tokens"] == 16_384
    assert preflight["solver_config_sha256"] == v1_2.FROZEN_SOLVER_CONFIG_SHA256
    assert preflight["request_plan_sha256"] == v1_2.FROZEN_REQUEST_PLAN_SHA256
    assert preflight["cost"]["request_utf8_bytes_input_token_upper_bound"] == 10_092_160
    assert preflight["cost"]["output_token_upper_bound"] == 6_291_456
    assert preflight["cost"]["conservative_generation_cost_upper_bound_usd"] == 9.5681792
    assert len(calls) == len(old_calls) == 384
    assert [
        (c.sequence, c.replication, c.condition_position, c.batch_id, c.condition, c.case_ids, c.prompt, c.text_format)
        for c in calls
    ] == [
        (c.sequence, c.replication, c.condition_position, c.batch_id, c.condition, c.case_ids, c.prompt, c.text_format)
        for c in old_calls
    ]
    changed = {
        key
        for key in preflight["solver_config"]
        if preflight["solver_config"][key] != old_preflight["solver_config"][key]
    }
    assert changed == {"max_output_tokens"}


def test_isolated_transport_failure_is_recorded_then_schedule_continues_without_retry(
    continued_run,
):
    run_dir, result, fake, verified = continued_run

    assert result["validity"] == "VALID"
    assert result["isolated_call_failure_count"] == 1
    assert result["isolated_call_failures"][0]["category"] == "transient_timeout"
    assert result["isolated_call_failures"][0]["physical_attempts"] == 1
    assert len(fake.calls) == 384
    assert len(list((run_dir / "calls").glob("call_*.json"))) == 384
    assert (run_dir / "calls/call_000002.json").is_file()
    decision = json.loads((run_dir / "decisions/decision_000001.json").read_text())
    assert decision["retry_attempted"] is False
    assert decision["repair_attempted"] is False
    assert result["usage"]["total"]["physical_generation_calls"] == 384
    first_call = json.loads((run_dir / "calls/call_000001.json").read_text())
    metadata = first_call["transport_metadata"]
    assert metadata["adapter_status"] == "transport_error"
    assert metadata["response_status"] is None
    assert metadata["response_id"] is None
    assert all(
        metadata[name] is None
        for name in (
            "input_tokens",
            "cached_input_tokens",
            "cache_write_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        )
    )
    assert verified["unique_response_ids"] == 383
    assert verified["execution_disposition"] == "VALID_WITH_ISOLATED_CALL_FAILURES"
    assert result["execution_disposition"] == "VALID_WITH_ISOLATED_CALL_FAILURES"
    status = json.loads((run_dir / "RUN_STATUS.json").read_text(encoding="utf-8"))
    assert status["unique_response_ids"] == 383


@pytest.mark.parametrize(
    ("message", "expected"),
    (
        ("request timed out", "transient_timeout"),
        ("APIConnectionError: temporary network failure", "transient_network"),
        ("HTTP status code 503", "transient_http_5xx"),
        ("HTTP 429 rate limit temporarily exceeded", "transient_http_429"),
        ("insufficient_quota: no credits remaining", None),
        ("permission denied", None),
        ("billing account inactive", None),
        ("unknown provider exception", None),
    ),
)
def test_failure_taxonomy_is_allowlisted_and_unknown_is_systemic(message, expected):
    call = {
        "status": "transport_error",
        "transport_error": {"type": "RuntimeError", "message": message},
        "transport_metadata": {},
    }
    assert v1_2._classify_isolated_call_failure(call) == expected


def test_wrong_returned_model_is_systemic_on_first_completed_call(tmp_path, monkeypatch):
    _, cases = _cases()
    fake = FakeCompletionLuna(cases)
    monkeypatch.setattr(v1_2, "_assert_sources_unchanged", lambda *_: None)
    result = v1_2.SemanticDecompositionV12Runner(
        repo_root=REPO_ROOT,
        output_dir=tmp_path / "wrong-model",
        ask_fn=fake,
        require_committed=False,
    ).run()
    assert result["validity"] == "INVALID"
    assert result["failed_sequence"] == 1
    assert "returned model differs" in result["apparatus_failure"]
    assert len(fake.calls) == 1


def test_failed_response_ids_are_global_and_duplicate_completion_aborts(
    tmp_path, monkeypatch
):
    _, cases = _cases()
    fake = IncompleteResponseIdThenDuplicateCompletion(cases)
    monkeypatch.setattr(v1_2, "_assert_sources_unchanged", lambda *_: None)
    run_dir = tmp_path / "duplicate-response-id"
    result = v1_2.SemanticDecompositionV12Runner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()
    assert result["validity"] == "INVALID"
    assert result["failed_sequence"] == 2
    assert "response ID was reused" in result["apparatus_failure"]
    assert len(fake.calls) == 2
    status = json.loads((run_dir / "RUN_STATUS.json").read_text(encoding="utf-8"))
    assert status["unique_response_ids"] == 1


def test_missing_secondary_condition_does_not_change_primary_analysis():
    scores = _perfect_scores()
    complete = v1_2.matched_primary_analysis(scores)["primary"]
    scores[1]["KA-"] = []
    secondary_missing = v1_2.matched_primary_analysis(scores)["primary"]
    assert secondary_missing == complete
    assert all(row["test_status"] == "ran" for row in secondary_missing.values())
    all_analysis = v1_2.matched_primary_analysis(scores)
    secondary = v1_2.matched_secondary_analysis(all_analysis)
    assert secondary["I_KA"]["test_status"].startswith("not_run")
    assert secondary["I_KAS"]["test_status"].startswith("not_run")
    assert secondary["I_KS"]["test_status"] == "ran"
    assert secondary["I_AS"]["test_status"] == "ran"


def test_missing_primary_pair_excludes_and_flags_whole_hypothesis():
    scores = _perfect_scores()
    for replication in range(1, 9):
        _set_correct_count(scores, replication, "KAS-", 3)
    scores[3]["K-"] = []
    primary = v1_2.matched_primary_analysis(scores)["primary"]
    kind = primary["H_KIND"]
    assert kind["test_status"] == "not_run_incomplete_matched_replications"
    assert kind["matched_replications"] == [1, 2, 4, 5, 6, 7, 8]
    assert kind["missing_matched_replications"] == [3]
    assert kind["differences"] == []
    assert kind["raw_p_value"] is None
    assert kind["p_value"] == 1.0
    assert primary["H_AUTHORITY"]["test_status"] == "ran"
    assert primary["H_STATUS"]["test_status"] == "ran"
    classification = _classify_scores(scores)
    assert classification["result_code"] == "VALID_PARTIAL_PRIMARY_NOT_SUPPORTED"
    assert classification["analyzable_primary_hypotheses"] == [
        "H_AUTHORITY",
        "H_STATUS",
    ]


def test_missing_c1_makes_every_primary_hypothesis_nonanalyzable():
    scores = _perfect_scores()
    scores[2]["C1"] = []
    primary = v1_2.matched_primary_analysis(scores)["primary"]
    assert all(row["test_status"].startswith("not_run") for row in primary.values())
    assert _classify_scores(scores)["result_code"] == "VALID_NO_ANALYZABLE_PRIMARY"


def test_baseline_drift_precedes_unrelated_isolated_secondary():
    scores = _perfect_scores()
    for replication in range(1, 9):
        _set_correct_count(scores, replication, "C1", 17)
    scores[1]["KA-"] = []
    classification = _classify_scores(scores)
    assert classification["result_code"] == "VALID_BASELINE_DRIFT"
    assert classification["baseline_c1_exact_correct"] == 136
    assert "I_KA" in classification["incomplete_secondary_interactions"]


def test_analyzable_kas_replication_failure_precedes_unrelated_isolated_secondary():
    scores = _perfect_scores()
    scores[1]["KA-"] = []
    classification = _classify_scores(scores)
    assert classification["kas_replication_analyzable"] is True
    assert classification["result_code"] == "VALID_KAS_REPLICATION_FAILURE"
    assert "I_KA" in classification["incomplete_secondary_interactions"]


def test_analyzable_interaction_support_survives_different_secondary_missing():
    scores = _perfect_scores()
    for replication in range(1, 9):
        _set_correct_count(scores, replication, "KA-", 0)
        _set_correct_count(scores, replication, "KAS-", 3)
    scores[1]["KS-"] = []
    classification = _classify_scores(scores)
    assert classification["result_code"] == "VALID_SUPPORTED_MULTIFIELD_INTERACTION"
    assert classification["harmful_secondary_interactions"] == ["I_KA"]
    assert "I_KS" in classification["incomplete_secondary_interactions"]


def test_kas_failure_is_not_erased_by_missing_kind_primary():
    scores = _perfect_scores()
    scores[1]["K-"] = []
    classification = _classify_scores(scores)
    assert classification["result_code"] == "VALID_KAS_REPLICATION_FAILURE"
    assert classification["incomplete_primary_hypotheses"] == ["H_KIND"]
    assert classification["kas_replication_analyzable"] is True


def test_harmful_i_as_is_not_erased_by_missing_kind_primary():
    scores = _perfect_scores()
    for replication in range(1, 9):
        _set_correct_count(scores, replication, "AS-", 0)
        _set_correct_count(scores, replication, "KAS-", 3)
    scores[1]["K-"] = []
    classification = _classify_scores(scores)
    assert classification["result_code"] == "VALID_SUPPORTED_MULTIFIELD_INTERACTION"
    assert classification["incomplete_primary_hypotheses"] == ["H_KIND"]
    assert classification["harmful_secondary_interactions"] == ["I_AS"]


def test_complete_execution_disposition_is_explicit(monkeypatch):
    scores = _perfect_scores()
    monkeypatch.setattr(
        v1,
        "aggregate_valid_result",
        lambda **_: {"validity": "VALID", "result_code": "VALID_TEST"},
    )
    result = v1_2.aggregate_partial_result(
        cases=_cases()[1],
        scores=scores,
        records=[],
        preflight={},
        isolated_failures=[],
    )
    assert result["execution_disposition"] == "VALID_COMPLETE_CALLS"
    assert result["isolated_call_failure_count"] == 0
    assert result["isolated_call_failures"] == []


def test_verifier_rejects_forged_failure_taxonomy_and_scores(continued_run):
    run_dir, _, _, _ = continued_run
    relative = "decisions/decision_000001.json"
    path = run_dir / relative
    index_path = run_dir / "EVIDENCE_INDEX.json"
    original_decision = path.read_bytes()
    original_index = index_path.read_bytes()
    try:
        decision = json.loads(original_decision.decode("utf-8"))
        decision["failure_category"] = "transient_network"
        _rewrite_indexed_json(run_dir, relative, decision)
        with pytest.raises(luna_v1.ApparatusFailure, match="taxonomy"):
            v1_2.verify_run(run_dir)
    finally:
        path.write_bytes(original_decision)
        index_path.write_bytes(original_index)
    try:
        decision = json.loads(original_decision.decode("utf-8"))
        decision["scores"] = [{"answer_correct": True}]
        _rewrite_indexed_json(run_dir, relative, decision)
        with pytest.raises(luna_v1.ApparatusFailure, match="imputed/salvaged"):
            v1_2.verify_run(run_dir)
    finally:
        path.write_bytes(original_decision)
        index_path.write_bytes(original_index)
    assert v1_2.verify_run(run_dir)["isolated_call_failures"] == 1


def test_verifier_rejects_post_failure_schedule_omission(continued_run, tmp_path):
    source, _, _, _ = continued_run
    run_dir = tmp_path / "omitted-tail"
    shutil.copytree(source, run_dir)
    (run_dir / "calls/call_000384.json").unlink()
    (run_dir / "decisions/decision_000384.json").unlink()
    events_path = run_dir / "events.jsonl"
    events = events_path.read_text(encoding="utf-8").splitlines()
    events_path.write_text("\n".join(events[:-2]) + "\n", encoding="utf-8", newline="\n")
    _rebuild_index(run_dir)
    with pytest.raises(luna_v1.ApparatusFailure, match="all 384"):
        v1_2.verify_run(run_dir)


@pytest.mark.parametrize("field", ("cached_input_tokens", "cache_write_input_tokens"))
def test_verifier_rejects_cache_usage_tamper(continued_run, field):
    run_dir, _, _, _ = continued_run
    relative = "calls/call_000002.json"
    path = run_dir / relative
    events_path = run_dir / "events.jsonl"
    index_path = run_dir / "EVIDENCE_INDEX.json"
    original_call = path.read_bytes()
    original_events = events_path.read_bytes()
    original_index = index_path.read_bytes()
    try:
        call = json.loads(original_call.decode("utf-8"))
        call["transport_metadata"][field] = 1
        _rewrite_indexed_json(run_dir, relative, call)
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
        ]
        events[3]["artifact_file_sha256"] = luna_v1._sha256_bytes(path.read_bytes())
        events_path.write_text(
            "".join(luna_v1._canonical_json(event) + "\n" for event in events),
            encoding="utf-8",
            newline="\n",
        )
        _refresh_indexed_file(run_dir, "events.jsonl")
        with pytest.raises(luna_v1.ApparatusFailure, match="cache"):
            v1_2.verify_run(run_dir)
    finally:
        path.write_bytes(original_call)
        events_path.write_bytes(original_events)
        index_path.write_bytes(original_index)


def test_systemic_source_failure_aborts_without_a_physical_call(tmp_path, monkeypatch):
    _, cases = _cases()
    fake = FakeCompletionLuna(cases)

    def systemic(*_):
        raise luna_v1.ApparatusFailure("synthetic source integrity failure")

    monkeypatch.setattr(v1_2, "_assert_sources_unchanged", systemic)
    result = v1_2.SemanticDecompositionV12Runner(
        repo_root=REPO_ROOT,
        output_dir=tmp_path / "systemic",
        ask_fn=fake,
        require_committed=False,
    ).run()
    assert result["validity"] == "INVALID"
    assert result["result_code"] == "INVALID_APPARATUS"
    assert result["usage"]["total"]["physical_generation_calls"] == 0
    assert fake.calls == []


def test_source_guard_maps_are_inherited_and_v1_2_sources_are_bound():
    assert set(v1_1.SOURCE_FILES).issubset(v1_2.SOURCE_FILES)
    assert {
        "kingdom/decompression_semantic_authority_luna_v1_2.py",
        "benchmarks/decompression_test/PROTOCOL_SEMANTIC_AUTHORITY_LUNA_V1_2.md",
        "tests/test_decompression_semantic_authority_luna_v1_2.py",
    }.issubset(v1_2.SOURCE_FILES)
    assert len(v1_2.SOURCE_FILES) == len(set(v1_2.SOURCE_FILES))


def test_sealed_v1_1_lineage_and_fresh_directory():
    sealed = v1_2.verify_sealed_v1_1(REPO_ROOT)
    assert sealed["sealed_v1_1_evidence_commit"] == v1_2.SEALED_V1_1_EVIDENCE_COMMIT
    assert sealed["sealed_v1_1_evidence_tree_oid"] == v1_2.SEALED_V1_1_EVIDENCE_TREE_OID
    assert sealed["sealed_v1_1_verification"]["physical_generation_calls"] == 35
    assert not (REPO_ROOT / v1_2.RUN_DIR).exists()
