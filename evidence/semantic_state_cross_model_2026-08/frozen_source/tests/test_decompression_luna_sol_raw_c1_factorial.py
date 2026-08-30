from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from kingdom import decompression_luna_sol_raw_c1_factorial as experiment


REPO_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def _uncommitted_preflight():
    return experiment._derived_preflight(REPO_ROOT, require_committed=False)


class FakeFactorial:
    def __init__(self, cases, *, malformed_call=None):
        self.by_case = {case.case_id: case for case in cases}
        self.malformed_call = malformed_call
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
        payload = experiment.frontier._input_payload(prompt)
        case_ids = [item["case_id"] for item in payload["cases"]]
        labels = [self.by_case[case_id].correct_choice for case_id in case_ids]
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
                "returned_model": solver_config.model,
                "returned_service_tier": "default",
                "response_id": f"resp_factorial_{number:03d}",
                "response_status": "completed",
                "physical_attempts": 1,
                "latency_seconds": 0.01,
                "input_tokens": input_tokens,
                "cached_input_tokens": 0,
                "cache_write_input_tokens": 0,
                "output_tokens": output_tokens,
                "reasoning_tokens": 8,
                "total_tokens": input_tokens + output_tokens,
                "sdk_version": experiment.frontier.EXPECTED_OPENAI_SDK,
                "adapter_status": "completed",
                "incomplete_details": None,
                "response_error": None,
                "openai_text_format": openai_text_format,
                "openai_text_format_sha256": experiment.frontier._sha256_text(
                    experiment.frontier._canonical_json(openai_text_format)
                ),
            }
        )
        self.calls.append((role, solver_config.model, tuple(case_ids)))
        return response


def test_plan_is_192_calls_and_48_per_arm_with_contiguous_sequences():
    _payload, _cases, calls, _preflight = _uncommitted_preflight()
    assert len(calls) == 192
    assert Counter(call.condition for call in calls) == {
        condition: 48 for condition in experiment.CONDITIONS
    }
    assert [call.global_sequence for call in calls] == list(range(1, 193))
    for condition in experiment.CONDITIONS:
        assert [
            call.local_sequence for call in calls if call.condition == condition
        ] == list(range(1, 49))
    for replication in range(1, 9):
        selected = [call for call in calls if call.replication == replication]
        assert len(selected) == 24
        for condition in experiment.CONDITIONS:
            assert [
                call.batch_id for call in selected if call.condition == condition
            ] == list(range(1, 7))


def test_williams_schedule_has_exact_position_and_directed_carryover_balance():
    schedule = experiment.condition_schedule()
    orders = [order for row in schedule for order in row]
    assert len(schedule) == 8
    assert all(len(row) == 6 for row in schedule)
    assert len(orders) == 48
    assert all(tuple(order) in experiment.WILLIAMS_ORDERS for order in orders)
    assert Counter(orders) == {
        order: 12 for order in experiment.WILLIAMS_ORDERS
    }
    for condition in experiment.CONDITIONS:
        assert {
            position: sum(order[position - 1] == condition for order in orders)
            for position in range(1, 5)
        } == {1: 12, 2: 12, 3: 12, 4: 12}
    carryover = Counter(
        (left, right)
        for order in orders
        for left, right in zip(order, order[1:])
    )
    assert carryover == {
        (left, right): 12
        for left in experiment.CONDITIONS
        for right in experiment.CONDITIONS
        if left != right
    }


def test_model_representation_factors_are_orthogonal_and_prompts_match_by_representation():
    _payload, _cases, calls, _preflight = _uncommitted_preflight()
    assert {
        (
            experiment.MODEL_FACTOR[condition],
            experiment.REPRESENTATION_FACTOR[condition],
        )
        for condition in experiment.CONDITIONS
    } == {("LUNA", "RAW"), ("LUNA", "C1"), ("SOL", "RAW"), ("SOL", "C1")}

    assert experiment.solver_config(experiment.LUNA_RAW).to_mapping() == (
        experiment.solver_config(experiment.LUNA_C1).to_mapping()
    )
    assert experiment.solver_config(experiment.SOL_RAW).to_mapping() == (
        experiment.solver_config(experiment.SOL_C1).to_mapping()
    )
    luna = experiment.solver_config(experiment.LUNA_RAW).to_mapping()
    sol = experiment.solver_config(experiment.SOL_RAW).to_mapping()
    assert luna.pop("model") == "gpt-5.6-luna"
    assert sol.pop("model") == "gpt-5.6-sol"
    assert luna == sol

    by_cell = {
        (call.replication, call.batch_id, call.condition): call for call in calls
    }
    for replication in range(1, 9):
        for batch_id in range(1, 7):
            luna_raw = by_cell[(replication, batch_id, experiment.LUNA_RAW)]
            sol_raw = by_cell[(replication, batch_id, experiment.SOL_RAW)]
            luna_c1 = by_cell[(replication, batch_id, experiment.LUNA_C1)]
            sol_c1 = by_cell[(replication, batch_id, experiment.SOL_C1)]
            assert luna_raw.prompt == sol_raw.prompt
            assert luna_c1.prompt == sol_c1.prompt
            assert luna_raw.prompt != luna_c1.prompt
            assert luna_raw.case_ids == sol_raw.case_ids == luna_c1.case_ids == sol_c1.case_ids


def test_exact_batch_cardinality_schema_and_parser_are_shared_by_all_arms():
    _payload, _cases, calls, _preflight = _uncommitted_preflight()
    by_shape = {}
    for call in calls:
        key = (call.replication, call.batch_id, len(call.case_ids))
        by_shape.setdefault(key, {})[call.condition] = call.text_format
        answers = call.text_format["schema"]["properties"]["answers"]
        assert answers["minItems"] == len(call.case_ids)
        assert answers["maxItems"] == len(call.case_ids)
    for row in by_shape.values():
        assert set(row) == set(experiment.CONDITIONS)
        assert len({experiment._canonical_json(value) for value in row.values()}) == 1
    assert experiment.frontier.parse_structured_labels(
        json.dumps({"answers": ["A", "INSUFFICIENT"]}), 2
    ) == ("A", "INSUFFICIENT")
    with pytest.raises(experiment.grading.ConstrainedInterfaceFailure):
        experiment.frontier.parse_structured_labels(
            json.dumps({"answers": ["A"]}), 2
        )


def test_raw_and_c1_state_bytes_are_identical_across_models():
    _payload, cases, _calls, preflight = _uncommitted_preflight()
    assert len(cases) == 20
    state = preflight["representation_utf8_bytes_per_20_world_replication"]
    assert state[experiment.LUNA_RAW] == state[experiment.SOL_RAW]
    assert state[experiment.LUNA_C1] == state[experiment.SOL_C1]
    assert state[experiment.LUNA_C1] < state[experiment.LUNA_RAW]


def test_derived_constants_match_frozen_values_and_cost_stays_within_55_dollars():
    derived = experiment.derived_frozen_values(REPO_ROOT)
    assert derived == {
        "schedule_sha256": experiment.FROZEN_SCHEDULE_SHA256,
        "request_plan_sha256": experiment.FROZEN_REQUEST_PLAN_SHA256,
        "solver_config_sha256": experiment.FROZEN_SOLVER_CONFIG_SHA256,
        "input_token_upper_bound": experiment.FROZEN_INPUT_TOKEN_UPPER_BOUND,
        "cost_upper_bound_usd": experiment.FROZEN_COST_UPPER_BOUND_USD,
    }
    _payload, _cases, _calls, preflight = _uncommitted_preflight()
    assert preflight["cost"]["authorized_cost_ceiling_usd"] == 55
    assert preflight["cost"]["conservative_generation_cost_upper_bound_usd"] <= 55
    assert preflight["maximum_physical_generation_calls"] == 192


def test_eight_replication_sign_flip_retains_zero_differences():
    result = experiment.exact_two_sided_sign_flip([1, 0, 1, 0, 1, 0, 1, 0])
    assert result["permutations"] == 256
    assert result["extreme_assignments"] == 32
    assert result["p_value"] == 0.125
    assert result["zero_differences_retained"] is True
    all_zero = experiment.exact_two_sided_sign_flip([0] * 8)
    assert all_zero["permutations"] == 256
    assert all_zero["p_value"] == 1.0


def test_holm_family_is_exactly_three_and_adjustment_is_monotone():
    p_values = {"a": 0.01, "b": 0.03, "c": 0.04}
    assert experiment.holm_adjust(p_values) == {"a": 0.03, "b": 0.06, "c": 0.06}
    _payload, _cases, _calls, preflight = _uncommitted_preflight()
    assert preflight["statistics"]["confirmatory_family"] == [
        "LUNA_C1_MINUS_LUNA_RAW",
        "SOL_C1_MINUS_SOL_RAW",
        "REPRESENTATION_BY_MODEL_INTERACTION",
    ]
    assert "exactly three" in preflight["statistics"]["multiplicity"]


def _graded_scores(cases, condition, correct_count):
    scores = []
    for index, case in enumerate(cases):
        label = case.correct_choice
        if index >= correct_count:
            label = next(
                candidate
                for candidate in ("A", "B", "C", "D")
                if candidate != case.correct_choice
            )
        scores.append(experiment.grading.grade_label(case, label, condition=condition))
    return scores


def test_known_factorial_interaction_has_the_preregistered_sign():
    _payload, cases, _calls, preflight = _uncommitted_preflight()
    correct_counts = {
        experiment.LUNA_RAW: 18,
        experiment.LUNA_C1: 19,
        experiment.SOL_RAW: 20,
        experiment.SOL_C1: 18,
    }
    scores = {
        replication: {
            condition: _graded_scores(cases, condition, correct_counts[condition])
            for condition in experiment.CONDITIONS
        }
        for replication in range(1, 9)
    }
    result = experiment.aggregate_valid_result(
        cases=cases,
        scores=scores,
        audits={
            condition: SimpleNamespace(records=[])
            for condition in experiment.CONDITIONS
        },
        preflight=preflight,
    )
    primary = result["primary_confirmatory_comparisons"]
    assert primary["LUNA_C1_MINUS_LUNA_RAW"]["differences"] == [1] * 8
    assert primary["SOL_C1_MINUS_SOL_RAW"]["differences"] == [-2] * 8
    interaction = primary["REPRESENTATION_BY_MODEL_INTERACTION"]
    assert interaction["differences"] == [3] * 8
    assert interaction["aggregate_difference_answers"] == 24
    assert len(interaction["holm_family"]) == 3
    assert set(interaction["holm_family"]) == set(primary)
    pooled = result["secondary_comparisons"]["POOLED_C1_MINUS_RAW"]
    assert pooled["mean_doubled_factorial_contrast_answers"] == -1
    assert pooled["normalized_main_effect_answers_out_of_20"] == -0.5
    model = result["secondary_comparisons"]["POOLED_SOL_MINUS_LUNA"]
    assert model["mean_doubled_factorial_contrast_answers"] == 1
    assert model["normalized_main_effect_answers_out_of_20"] == 0.5


def test_raw_capability_boundary_and_asymmetric_claim_licensing():
    passing = experiment.raw_capability_disposition(
        {experiment.LUNA_RAW: 144, experiment.SOL_RAW: 144}
    )
    assert passing["top_level_result_code"] == "VALID_FACTORIAL_COMPLETE"
    assert all(passing["primary_claim_licenses"].values())

    luna_fails = experiment.raw_capability_disposition(
        {experiment.LUNA_RAW: 143, experiment.SOL_RAW: 144}
    )
    assert luna_fails["top_level_result_code"] == "VALID_CAPABILITY_WARNING"
    assert luna_fails["models"]["LUNA"]["passed"] is False
    assert luna_fails["models"]["SOL"]["passed"] is True
    assert luna_fails["primary_claim_licenses"] == {
        "LUNA_C1_MINUS_LUNA_RAW": False,
        "SOL_C1_MINUS_SOL_RAW": True,
        "REPRESENTATION_BY_MODEL_INTERACTION": False,
    }

    sol_fails = experiment.raw_capability_disposition(
        {experiment.LUNA_RAW: 144, experiment.SOL_RAW: 143}
    )
    assert sol_fails["top_level_result_code"] == "VALID_CAPABILITY_WARNING"
    assert sol_fails["models"]["LUNA"]["passed"] is True
    assert sol_fails["models"]["SOL"]["passed"] is False
    assert sol_fails["primary_claim_licenses"] == {
        "LUNA_C1_MINUS_LUNA_RAW": True,
        "SOL_C1_MINUS_SOL_RAW": False,
        "REPRESENTATION_BY_MODEL_INTERACTION": False,
    }

    _payload, cases, _calls, preflight = _uncommitted_preflight()

    def aggregate(luna_raw_counts, sol_raw_counts):
        scores = {
            replication: {
                experiment.LUNA_RAW: _graded_scores(
                    cases, experiment.LUNA_RAW, luna_raw_counts[replication - 1]
                ),
                experiment.LUNA_C1: _graded_scores(cases, experiment.LUNA_C1, 20),
                experiment.SOL_RAW: _graded_scores(
                    cases, experiment.SOL_RAW, sol_raw_counts[replication - 1]
                ),
                experiment.SOL_C1: _graded_scores(cases, experiment.SOL_C1, 20),
            }
            for replication in range(1, 9)
        }
        return experiment.aggregate_valid_result(
            cases=cases,
            scores=scores,
            audits={
                condition: SimpleNamespace(records=[])
                for condition in experiment.CONDITIONS
            },
            preflight=preflight,
        )

    luna_result = aggregate([17, 18, 18, 18, 18, 18, 18, 18], [18] * 8)
    luna_primary = luna_result["primary_confirmatory_comparisons"]
    assert luna_result["result_code"] == "VALID_CAPABILITY_WARNING"
    assert (
        luna_primary["LUNA_C1_MINUS_LUNA_RAW"]["licensed_decision"]
        == "NOT_LICENSED_CAPABILITY_WARNING"
    )
    assert (
        luna_primary["REPRESENTATION_BY_MODEL_INTERACTION"]["licensed_decision"]
        == "NOT_LICENSED_CAPABILITY_WARNING"
    )
    assert (
        luna_primary["SOL_C1_MINUS_SOL_RAW"]["licensed_decision"]
        == luna_primary["SOL_C1_MINUS_SOL_RAW"]["decision"]
    )

    sol_result = aggregate([18] * 8, [17, 18, 18, 18, 18, 18, 18, 18])
    sol_primary = sol_result["primary_confirmatory_comparisons"]
    assert sol_result["result_code"] == "VALID_CAPABILITY_WARNING"
    assert (
        sol_primary["SOL_C1_MINUS_SOL_RAW"]["licensed_decision"]
        == "NOT_LICENSED_CAPABILITY_WARNING"
    )
    assert (
        sol_primary["REPRESENTATION_BY_MODEL_INTERACTION"]["licensed_decision"]
        == "NOT_LICENSED_CAPABILITY_WARNING"
    )
    assert (
        sol_primary["LUNA_C1_MINUS_LUNA_RAW"]["licensed_decision"]
        == sol_primary["LUNA_C1_MINUS_LUNA_RAW"]["decision"]
    )


def test_runtime_critical_sources_are_locked():
    required = {
        experiment.MODULE_PATH,
        experiment.TEST_PATH,
        experiment.PROTOCOL_PATH,
        "kingdom/decompression_luna_hive_vs_sol_raw.py",
        "kingdom/decompression_frontier_luna.py",
        "kingdom/decompression_semantic_authority_luna.py",
        "kingdom/decompression_semantic_authority_luna_v1_2.py",
        "kingdom/decompression_test.py",
        "kingdom/decompression_test_v2.py",
        "hive_llm.py",
    }
    assert required.issubset(set(experiment.SOURCE_FILES))


def test_progress_renders_zero_half_and_complete_counts():
    zero = experiment.render_progress(0, 192)
    half = experiment.render_progress(96, 192)
    complete = experiment.render_progress(192, 192)
    assert "0/192" in zero and "0.0%" in zero
    assert "96/192" in half and "50.0%" in half
    assert "192/192" in complete and "100.0%" in complete
    assert zero.split("]", 1)[0][1:] == "-" * 28
    assert half.split("]", 1)[0][1:] == "#" * 14 + "-" * 14
    assert complete.split("]", 1)[0][1:] == "#" * 28


def test_perfect_fake_factorial_run_verifies_and_resealed_result_tamper_fails(tmp_path):
    _payload, cases, _calls, _preflight = _uncommitted_preflight()
    fake = FakeFactorial(cases)
    run_dir = tmp_path / "factorial"
    result = experiment.FactorialRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
        progress_stream=False,
    ).run()
    assert result["validity"] == "VALID"
    assert result["result_code"] == "VALID_FACTORIAL_COMPLETE"
    assert {
        condition: result["conditions"][condition]["exact_correct"]
        for condition in experiment.CONDITIONS
    } == {condition: 160 for condition in experiment.CONDITIONS}
    assert all(
        row["p_value"] == 1.0
        for row in result["primary_confirmatory_comparisons"].values()
    )
    assert result["physical_generation_calls"] == 192
    assert len(fake.calls) == 192
    verified = experiment.verify_run(run_dir)
    assert verified["physical_generation_calls"] == 192
    assert verified["decision_artifacts"] == 192
    assert verified["unique_response_ids"] == 192
    assert verified["returned_models"] == {
        condition: [experiment.MODELS[condition]]
        for condition in experiment.CONDITIONS
    }

    result_path = run_dir / "RESULT.json"
    index_path = run_dir / "EVIDENCE_INDEX.json"
    original_result_text = result_path.read_text(encoding="utf-8")
    original_index_text = index_path.read_text(encoding="utf-8")
    relabeled = {
        "schema_version": experiment.SCHEMA_VERSION,
        "protocol_id": experiment.PROTOCOL_ID,
        "protocol_version": experiment.PROTOCOL_VERSION,
        "source_revision": "TEST_UNCOMMITTED",
        "validity": "INVALID",
        "result_code": "INVALID_APPARATUS",
        "failed_global_sequence": 192,
        "failed_replication": 8,
        "failed_condition": experiment.LUNA_C1,
        "failed_batch_id": 6,
        "apparatus_failure": "fabricated failure",
    }
    result_path.write_text(
        experiment._pretty_json(experiment._sealed(relabeled)), encoding="utf-8"
    )
    stored_index = json.loads(original_index_text)
    index_body = {
        key: value for key, value in stored_index.items() if key != "payload_sha256"
    }
    result_row = next(row for row in index_body["files"] if row["path"] == "RESULT.json")
    result_row["bytes"] = result_path.stat().st_size
    result_row["sha256"] = experiment._sha256_bytes(result_path.read_bytes())
    index_body["total_bytes"] = sum(row["bytes"] for row in index_body["files"])
    index_path.write_text(
        experiment._pretty_json(experiment._sealed(index_body)), encoding="utf-8"
    )
    with pytest.raises(experiment.ApparatusFailure, match="independently verifiable"):
        experiment.verify_run(run_dir)

    result_path.write_text(original_result_text, encoding="utf-8")
    index_path.write_text(original_index_text, encoding="utf-8")
    stored_result = json.loads(result_path.read_text(encoding="utf-8"))
    result_body = {
        key: value for key, value in stored_result.items() if key != "payload_sha256"
    }
    result_body["conditions"][experiment.LUNA_RAW]["exact_correct"] = 159
    result_path.write_text(
        experiment._pretty_json(experiment._sealed(result_body)), encoding="utf-8"
    )
    stored_index = json.loads(index_path.read_text(encoding="utf-8"))
    index_body = {
        key: value for key, value in stored_index.items() if key != "payload_sha256"
    }
    result_row = next(row for row in index_body["files"] if row["path"] == "RESULT.json")
    result_row["bytes"] = result_path.stat().st_size
    result_row["sha256"] = experiment._sha256_bytes(result_path.read_bytes())
    index_body["total_bytes"] = sum(row["bytes"] for row in index_body["files"])
    index_path.write_text(
        experiment._pretty_json(experiment._sealed(index_body)), encoding="utf-8"
    )
    with pytest.raises(experiment.ApparatusFailure, match="independent recomputation"):
        experiment.verify_run(run_dir)


def test_malformed_second_call_fails_closed_without_retry(tmp_path):
    _payload, cases, _calls, _preflight = _uncommitted_preflight()
    fake = FakeFactorial(cases, malformed_call=2)
    run_dir = tmp_path / "factorial-invalid"
    result = experiment.FactorialRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
        progress_stream=False,
    ).run()
    assert result["validity"] == "INVALID"
    assert result["result_code"] == "INVALID_APPARATUS"
    assert result["failed_global_sequence"] == 2
    assert len(fake.calls) == 2
    assert result["usage"]["total"]["physical_generation_calls"] == 2
    decisions = list(run_dir.glob("*/decisions/decision_*.json"))
    assert len(decisions) == 2
    rejected = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in decisions
        if json.loads(path.read_text(encoding="utf-8"))["status"] == "parser_rejected"
    )
    assert rejected["parser_status"] == "failed"
    assert rejected["grader_status"] == "not_run"
    assert rejected["grader_agreement"] is None
    assert rejected["retry_attempted"] is False
    assert rejected["repair_attempted"] is False
    assert experiment.verify_run(run_dir)["validity"] == "INVALID"

    result_path = run_dir / "RESULT.json"
    stored_result = json.loads(result_path.read_text(encoding="utf-8"))
    result_body = {
        key: value for key, value in stored_result.items() if key != "payload_sha256"
    }
    result_body["apparatus_failure"] = "fabricated parser reason"
    result_body["failure_evidence"]["reason_sha256"] = experiment._sha256_text(
        result_body["apparatus_failure"]
    )
    result_path.write_text(
        experiment._pretty_json(experiment._sealed(result_body)), encoding="utf-8"
    )
    index_path = run_dir / "EVIDENCE_INDEX.json"
    stored_index = json.loads(index_path.read_text(encoding="utf-8"))
    index_body = {
        key: value for key, value in stored_index.items() if key != "payload_sha256"
    }
    result_row = next(row for row in index_body["files"] if row["path"] == "RESULT.json")
    result_row["bytes"] = result_path.stat().st_size
    result_row["sha256"] = experiment._sha256_bytes(result_path.read_bytes())
    index_body["total_bytes"] = sum(row["bytes"] for row in index_body["files"])
    index_path.write_text(
        experiment._pretty_json(experiment._sealed(index_body)), encoding="utf-8"
    )
    with pytest.raises(experiment.ApparatusFailure, match="failed-call evidence"):
        experiment.verify_run(run_dir)


def test_parser_failure_with_reused_response_id_cannot_be_resealed_as_valid_evidence(
    tmp_path,
):
    _payload, cases, _calls, _preflight = _uncommitted_preflight()
    run_dir = tmp_path / "factorial-invalid-duplicate-id"
    experiment.FactorialRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=FakeFactorial(cases, malformed_call=2),
        require_committed=False,
        progress_stream=False,
    ).run()
    decisions = [
        (path, json.loads(path.read_text(encoding="utf-8")))
        for path in run_dir.glob("*/decisions/decision_*.json")
    ]
    graded_path, graded = next(
        (path, payload) for path, payload in decisions if payload["status"] == "graded"
    )
    rejected_path, rejected = next(
        (path, payload)
        for path, payload in decisions
        if payload["status"] == "parser_rejected"
    )
    graded_call_path = (
        graded_path.parent.parent / "calls" / f"{graded['call_id']}.json"
    )
    rejected_call_path = (
        rejected_path.parent.parent / "calls" / f"{rejected['call_id']}.json"
    )
    graded_call = json.loads(graded_call_path.read_text(encoding="utf-8"))
    rejected_call = json.loads(rejected_call_path.read_text(encoding="utf-8"))
    rejected_call["transport_metadata"]["response_id"] = graded_call[
        "transport_metadata"
    ]["response_id"]
    rejected_call_path.write_text(
        experiment._pretty_json(
            experiment._sealed(
                {
                    key: value
                    for key, value in rejected_call.items()
                    if key != "payload_sha256"
                }
            )
        ),
        encoding="utf-8",
    )

    result_path = run_dir / "RESULT.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result_body = {
        key: value for key, value in result.items() if key != "payload_sha256"
    }
    result_body["failure_evidence"]["failed_call_artifact"][
        "file_sha256"
    ] = experiment._sha256_bytes(rejected_call_path.read_bytes())
    result_path.write_text(
        experiment._pretty_json(experiment._sealed(result_body)), encoding="utf-8"
    )

    index_path = run_dir / "EVIDENCE_INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index_body = {
        key: value for key, value in index.items() if key != "payload_sha256"
    }
    changed = {
        rejected_call_path.relative_to(run_dir).as_posix(): rejected_call_path,
        "RESULT.json": result_path,
    }
    for row in index_body["files"]:
        if row["path"] in changed:
            path = changed[row["path"]]
            row["bytes"] = path.stat().st_size
            row["sha256"] = experiment._sha256_bytes(path.read_bytes())
    index_body["total_bytes"] = sum(row["bytes"] for row in index_body["files"])
    index_path.write_text(
        experiment._pretty_json(experiment._sealed(index_body)), encoding="utf-8"
    )
    with pytest.raises(experiment.ApparatusFailure, match="reused"):
        experiment.verify_run(run_dir)
