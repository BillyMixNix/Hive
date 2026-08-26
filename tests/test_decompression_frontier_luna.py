import json
from dataclasses import replace
from pathlib import Path

import pytest

from kingdom import decompression_frontier_luna as frontier
from kingdom import decompression_test as v1


REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = REPO_ROOT / "benchmarks/decompression_test/CASE_PACK.json"


def _cases():
    payload, cases = v1.load_case_pack(CASE_PATH)
    v1.validate_case_pack(payload, cases)
    return payload, cases


class FakeLuna:
    def __init__(self, cases, *, wrong_raw=False, malformed_call=None, cached_call=None):
        self.by_case = {case.case_id: case for case in cases}
        self.wrong_raw = wrong_raw
        self.malformed_call = malformed_call
        self.cached_call = cached_call
        self.calls = []

    def __call__(
        self,
        prompt,
        *,
        role,
        solver_config,
        metadata,
        openai_text_format,
    ):
        number = len(self.calls) + 1
        payload = frontier._input_payload(prompt)
        case_ids = [item["case_id"] for item in payload["cases"]]
        labels = [self.by_case[case_id].correct_choice for case_id in case_ids]
        if self.wrong_raw and number == 1:
            labels[0] = next(label for label in "ABCD" if label != labels[0])
        response = json.dumps({"answers": labels}, separators=(",", ":"))
        if number == self.malformed_call:
            response = "```json\n" + response + "\n```"
        input_tokens = max(1, len(prompt.encode("utf-8")) // 4)
        output_tokens = 12
        metadata.clear()
        metadata.update(solver_config.to_mapping())
        metadata.update(
            {
                "configuration_hash": solver_config.configuration_hash,
                "requested_model": solver_config.model,
                "returned_model": "gpt-5.6-luna-test-snapshot",
                "returned_service_tier": "default",
                "response_id": f"resp_{number:03d}",
                "response_status": "completed",
                "physical_attempts": 1,
                "latency_seconds": 0.01,
                "input_tokens": input_tokens,
                "cached_input_tokens": 1 if number == self.cached_call else 0,
                "cache_write_input_tokens": 0,
                "output_tokens": output_tokens,
                "reasoning_tokens": 8,
                "total_tokens": input_tokens + output_tokens,
                "sdk_version": frontier.EXPECTED_OPENAI_SDK,
                "adapter_status": "completed",
                "incomplete_details": None,
                "response_error": None,
                "openai_text_format": openai_text_format,
                "openai_text_format_sha256": frontier._sha256_text(
                    frontier._canonical_json(openai_text_format)
                ),
            }
        )
        self.calls.append(
            {
                "number": number,
                "role": role,
                "case_ids": case_ids,
                "format": openai_text_format,
                "response": response,
            }
        )
        return response


def test_named_column_frontier_is_query_blind_projection():
    _, cases = _cases()
    case = cases[0]
    original = v1.compressed_packet(case)

    for level in frontier.LEVELS:
        projected = frontier.transform_compact_packet(original, level)
        frontier.validate_frontier_packet(projected, expected_level=level)
        columns = tuple(projected["record_columns"])
        assert columns == frontier.LEVEL_COLUMNS[level]
        indexes = [frontier.FULL_COLUMNS.index(name) for name in columns]
        assert projected["records"] == [
            [record[index] for index in indexes] for record in original["records"]
        ]
        serialized = frontier._canonical_json(projected)
        assert case.question not in serialized
        assert "correct_choice" not in serialized
        assert "options" not in serialized

    assert "record_t" in frontier.LEVEL_COLUMNS["C0"]
    assert "record_t" not in frontier.LEVEL_COLUMNS["C1"]
    assert set(("kind", "authority", "status")).isdisjoint(
        frontier.LEVEL_COLUMNS["C2"]
    )


def test_malformed_or_reindexed_frontier_packets_fail_closed():
    _, cases = _cases()
    packet = frontier.transform_compact_packet(
        v1.compressed_packet(cases[0]), "C1"
    )
    packet["records"][0].pop()
    with pytest.raises(ValueError, match="width"):
        frontier.validate_frontier_packet(packet, expected_level="C1")

    packet = frontier.transform_compact_packet(
        v1.compressed_packet(cases[0]), "C1"
    )
    packet["record_columns"][0], packet["record_columns"][1] = (
        packet["record_columns"][1],
        packet["record_columns"][0],
    )
    with pytest.raises(ValueError, match="columns"):
        frontier.validate_frontier_packet(packet, expected_level="C1")


@pytest.mark.parametrize("count", [3, 4])
def test_openai_schema_and_exact_parser_have_identical_cardinality(count):
    text_format = frontier.openai_text_format(count)
    schema = text_format["schema"]["properties"]["answers"]
    assert schema["minItems"] == schema["maxItems"] == count
    legal = json.dumps({"answers": ["A"] * count})
    assert v1 is not None  # keep the parser check visibly tied to the frozen suite
    assert frontier.parse_structured_labels(legal, count) == tuple("A" for _ in range(count))
    for bad_count in {2, 3, 4, 5} - {count}:
        with pytest.raises(frontier.v2.ConstrainedInterfaceFailure):
            frontier.parse_structured_labels(
                json.dumps({"answers": ["A"] * bad_count}), count
            )


def test_all_five_labels_pass_and_every_other_wrapper_fails_closed():
    labels = ["A", "B", "C", "D", "INSUFFICIENT"]
    assert frontier.parse_structured_labels(
        json.dumps({"answers": labels}), 5
    ) == tuple(labels)
    bad = (
        '```json\n{"answers":["A"]}\n```',
        '{"answers":["Ari"]}',
        '{"answers":["D|INSUFFICIENT"]}',
        '{"answers":["A"],"reasoning":"extra"}',
        '{"answers":["A"],"answers":["A"]}',
        '["A"]',
    )
    for raw in bad:
        with pytest.raises(frontier.v2.ConstrainedInterfaceFailure):
            frontier.parse_structured_labels(raw, 1)


def test_preflight_freezes_24_calls_and_counterbalances_levels():
    _, cases, calls, preflight = frontier.deterministic_preflight(
        REPO_ROOT, require_committed=False
    )
    assert len(cases) == 20
    assert len(calls) == 24
    assert [call.condition for call in calls[:6]] == ["raw_capability"] * 6
    assert {call.condition for call in calls[6:]} == set(frontier.LEVELS)
    assert all(
        len(call.case_ids)
        == call.text_format["schema"]["properties"]["answers"]["minItems"]
        == call.text_format["schema"]["properties"]["answers"]["maxItems"]
        for call in calls
    )
    assert preflight["frontier_position_counts"] == {
        level: [0, 0, 1, 1, 2, 2] for level in frontier.LEVELS
    }
    assert (
        preflight["cost"]["conservative_generation_cost_upper_bound_usd"]
        <= frontier.AUTHORIZED_COST_CEILING_USD
    )


def test_perfect_fake_run_reaches_right_censored_frontier_and_verifies(tmp_path):
    _, cases = _cases()
    fake = FakeLuna(cases)
    run_dir = tmp_path / "run"
    result = frontier.LunaFrontierRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()

    assert result["validity"] == "VALID"
    assert result["result_code"] == "VALID_RIGHT_CENSORED_ALL_PASS"
    assert result["raw"]["exact_correct"] == 20
    assert {level: result["frontier"][level]["exact_correct"] for level in frontier.LEVELS} == {
        "C0": 20,
        "C1": 20,
        "C2": 20,
    }
    assert result["representation_utf8_bytes"]["raw"] > result["representation_utf8_bytes"]["C0"]
    assert result["representation_utf8_bytes"]["C0"] > result["representation_utf8_bytes"]["C1"]
    assert result["representation_utf8_bytes"]["C1"] > result["representation_utf8_bytes"]["C2"]
    assert len(fake.calls) == 24
    assert result["usage"]["total"]["physical_generation_calls"] == 24
    assert all(call["role"] == "default" for call in fake.calls)
    assert frontier.verify_run(run_dir)["physical_generation_calls"] == 24


def test_raw_gate_failure_is_valid_and_stops_before_frontier(tmp_path):
    _, cases = _cases()
    fake = FakeLuna(cases, wrong_raw=True)
    result = frontier.LunaFrontierRunner(
        repo_root=REPO_ROOT,
        output_dir=tmp_path / "raw-fail",
        ask_fn=fake,
        require_committed=False,
    ).run()

    assert result["validity"] == "VALID"
    assert result["result_code"] == "VALID_RAW_CAPABILITY_FAIL"
    assert result["raw"]["exact_correct"] == 19
    assert result["frontier"] == "NOT_RUN"
    assert len(fake.calls) == 6


def test_parser_failure_is_invalid_without_salvage_or_retry(tmp_path):
    _, cases = _cases()
    fake = FakeLuna(cases, malformed_call=2)
    run_dir = tmp_path / "parser-fail"
    result = frontier.LunaFrontierRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()

    assert result["validity"] == "INVALID"
    assert result["result_code"] == "INVALID_APPARATUS"
    assert len(fake.calls) == 2
    decision = json.loads(
        (run_dir / "decisions/decision_000002.json").read_text(encoding="utf-8")
    )
    assert decision["parser_status"] == "failed"
    assert decision["grader_status"] == "not_run"
    assert decision["grader_agreement"] is None
    assert "```json" in json.loads(
        (run_dir / "calls/call_000002.json").read_text(encoding="utf-8")
    )["response"]["raw_text"]


def test_cache_metadata_failure_is_invalid_and_preserved(tmp_path):
    _, cases = _cases()
    fake = FakeLuna(cases, cached_call=1)
    run_dir = tmp_path / "cache-fail"
    result = frontier.LunaFrontierRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()

    assert result["validity"] == "INVALID"
    assert result["result_code"] == "INVALID_APPARATUS"
    assert len(fake.calls) == 1
    artifact = json.loads(
        (run_dir / "calls/call_000001.json").read_text(encoding="utf-8")
    )
    assert artifact["status"] == "metadata_rejected"
    assert artifact["transport_metadata"]["cached_input_tokens"] == 1


def test_transport_failure_with_unmeasured_usage_still_seals_invalid_run(tmp_path):
    def failing_transport(
        prompt,
        *,
        role,
        solver_config,
        metadata,
        openai_text_format,
    ):
        metadata.clear()
        metadata.update(solver_config.to_mapping())
        metadata.update(
            {
                "configuration_hash": solver_config.configuration_hash,
                "physical_attempts": 1,
                "adapter_status": "transport_error",
                "input_tokens": None,
                "cached_input_tokens": None,
                "cache_write_input_tokens": None,
                "output_tokens": None,
                "reasoning_tokens": None,
                "total_tokens": None,
                "latency_seconds": 0.02,
            }
        )
        raise RuntimeError("synthetic network failure")

    run_dir = tmp_path / "transport-fail"
    result = frontier.LunaFrontierRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=failing_transport,
        require_committed=False,
    ).run()

    assert result["validity"] == "INVALID"
    assert result["result_code"] == "INVALID_APPARATUS"
    assert result["usage"]["total"]["input_tokens"] == 0
    assert result["usage"]["total"]["output_tokens"] == 0
    verified = frontier.verify_run(run_dir)
    assert verified["call_artifacts"] == 1
    assert verified["physical_generation_calls"] == 1


def test_pretransport_failure_records_zero_physical_generation_calls(tmp_path):
    def client_failure(
        prompt,
        *,
        role,
        solver_config,
        metadata,
        openai_text_format,
    ):
        metadata.clear()
        metadata.update(solver_config.to_mapping())
        metadata.update(
            {
                "configuration_hash": solver_config.configuration_hash,
                "physical_attempts": 0,
                "adapter_status": "client_error",
                "input_tokens": None,
                "cached_input_tokens": None,
                "cache_write_input_tokens": None,
                "output_tokens": None,
                "reasoning_tokens": None,
                "total_tokens": None,
                "latency_seconds": None,
            }
        )
        raise RuntimeError("synthetic client initialization failure")

    run_dir = tmp_path / "client-fail"
    result = frontier.LunaFrontierRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=client_failure,
        require_committed=False,
    ).run()

    assert result["validity"] == "INVALID"
    assert result["usage"]["total"]["call_artifacts"] == 1
    assert result["usage"]["total"]["physical_generation_calls"] == 0
    verified = frontier.verify_run(run_dir)
    assert verified["call_artifacts"] == 1
    assert verified["physical_generation_calls"] == 0


def test_secondary_evaluator_failure_invalidates_instead_of_passing_gate(
    tmp_path, monkeypatch
):
    _, cases = _cases()
    original = frontier.v2.grade_label

    def failed_secondary(*args, **kwargs):
        score = original(*args, **kwargs)
        return replace(
            score,
            secondary_status="failed",
            chronology_authority_error=None,
            illegal_state_promotions=None,
            failure_reasons=(*score.failure_reasons, "secondary_metadata_failure"),
        )

    monkeypatch.setattr(frontier.v2, "grade_label", failed_secondary)
    run_dir = tmp_path / "secondary-fail"
    result = frontier.LunaFrontierRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=FakeLuna(cases),
        require_committed=False,
    ).run()

    assert result["validity"] == "INVALID"
    assert result["result_code"] == "INVALID_APPARATUS"
    assert result["raw"]["secondary_failures"] > 0
    decision = json.loads(
        (run_dir / "decisions/decision_000001.json").read_text(encoding="utf-8")
    )
    assert decision["status"] == "secondary_failed"
    assert frontier.verify_run(run_dir)["physical_generation_calls"] == 1


def test_existing_run_directory_refuses_before_any_model_call(tmp_path):
    _, cases = _cases()
    fake = FakeLuna(cases)
    run_dir = tmp_path / "existing"
    run_dir.mkdir()
    with pytest.raises(FileExistsError):
        frontier.LunaFrontierRunner(
            repo_root=REPO_ROOT,
            output_dir=run_dir,
            ask_fn=fake,
            require_committed=False,
        ).run()
    assert fake.calls == []


def test_tampered_artifact_fails_offline_verification(tmp_path):
    _, cases = _cases()
    run_dir = tmp_path / "tamper"
    frontier.LunaFrontierRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=FakeLuna(cases, wrong_raw=True),
        require_committed=False,
    ).run()
    path = run_dir / "decisions/decision_000001.json"
    value = path.read_text(encoding="utf-8").replace('"status": "graded"', '"status": "changed"')
    path.write_text(value, encoding="utf-8")
    with pytest.raises(frontier.ApparatusFailure, match="evidence changed"):
        frontier.verify_run(run_dir)


@pytest.mark.parametrize(
    "correct,expected",
    [
        ({"C0": 19, "C1": 20, "C2": 20}, "VALID_COMPRESSED_BASELINE_FAIL"),
        ({"C0": 20, "C1": 19, "C2": 18}, "VALID_FRONTIER_BOUNDARY_C0"),
        ({"C0": 20, "C1": 20, "C2": 19}, "VALID_FRONTIER_BOUNDARY_C1"),
        ({"C0": 20, "C1": 20, "C2": 20}, "VALID_RIGHT_CENSORED_ALL_PASS"),
        ({"C0": 20, "C1": 19, "C2": 20}, "VALID_NONMONOTONIC_DESCRIPTIVE"),
    ],
)
def test_frontier_classification_is_frozen(correct, expected):
    assert frontier.classify_frontier(correct) == expected
