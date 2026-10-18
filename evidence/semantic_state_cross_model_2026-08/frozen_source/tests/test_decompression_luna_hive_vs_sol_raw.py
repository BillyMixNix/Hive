from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from kingdom import decompression_luna_hive_vs_sol_raw as experiment


REPO_ROOT = Path(__file__).resolve().parents[1]


def _uncommitted_preflight():
    return experiment._derived_preflight(REPO_ROOT, require_committed=False)


class FakePair:
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
                "response_id": f"resp_pair_{number:03d}",
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


def test_plan_is_72_calls_and_matched_36_per_arm():
    _payload, _cases, calls, _preflight = _uncommitted_preflight()
    assert len(calls) == 72
    assert {
        condition: sum(call.condition == condition for call in calls)
        for condition in experiment.CONDITIONS
    } == {experiment.LUNA_C1: 36, experiment.SOL_RAW: 36}
    assert [call.global_sequence for call in calls] == list(range(1, 73))
    for condition in experiment.CONDITIONS:
        assert [
            call.local_sequence for call in calls if call.condition == condition
        ] == list(range(1, 37))


def test_progress_bar_reports_exact_bounds_and_context():
    assert experiment.render_progress(0, 72, detail="ready", width=10) == (
        "[----------]  0/72    0.0%  ready"
    )
    assert experiment.render_progress(36, 72, detail="rep 3/6", width=10) == (
        "[#####-----] 36/72   50.0%  rep 3/6"
    )
    assert experiment.render_progress(72, 72, detail="SOL_RAW", width=10) == (
        "[##########] 72/72  100.0%  SOL_RAW"
    )
    with pytest.raises(ValueError):
        experiment.render_progress(73, 72)


def test_schedule_is_exactly_counterbalanced():
    schedule = experiment.condition_schedule()
    for condition in experiment.CONDITIONS:
        assert sum(order[0] == condition for row in schedule for order in row) == 18
        assert sum(order[1] == condition for row in schedule for order in row) == 18
    for row in schedule:
        for order in row:
            assert sorted(order) == sorted(experiment.CONDITIONS)


def test_current_arms_share_every_solver_setting_except_model():
    luna = experiment.solver_config(experiment.LUNA_C1).to_mapping()
    sol = experiment.solver_config(experiment.SOL_RAW).to_mapping()
    assert luna.pop("model") == "gpt-5.6-luna"
    assert sol.pop("model") == "gpt-5.6-sol"
    assert luna == sol
    assert luna["reasoning_effort"] == "medium"
    assert luna["max_output_tokens"] == 16_384
    assert luna["max_attempts"] == 1
    assert luna["tool_permissions"] == []
    assert luna["store"] is False


def test_all_runtime_critical_helper_modules_are_source_locked():
    required = {
        "kingdom/decompression_frontier_luna.py",
        "kingdom/decompression_matched_semantic_control_luna.py",
        "kingdom/decompression_semantic_authority_luna.py",
        "kingdom/decompression_semantic_authority_luna_v1_2.py",
        "kingdom/decompression_test.py",
        "kingdom/decompression_test_v2.py",
    }
    assert required.issubset(set(experiment.SOURCE_FILES))


def test_only_shared_title_changes_from_sealed_prompts():
    _payload, _cases, calls, _preflight = _uncommitted_preflight()
    prior = experiment._prior_prompt_map(REPO_ROOT)
    for call in calls:
        previous = prior[(experiment.REPRESENTATIONS[call.condition], call.batch_id)]
        assert experiment._input_payload_text(call.prompt) == experiment._input_payload_text(
            previous
        )
        assert call.prompt.split("\n", 1)[1] == previous.split("\n", 1)[1]
        assert call.prompt.startswith(experiment._NEUTRAL_TITLE)
        assert not call.prompt.startswith(experiment._PRIOR_TITLE)


def test_exact_batch_cardinality_and_parser_are_shared():
    _payload, _cases, calls, _preflight = _uncommitted_preflight()
    by_shape = {}
    for call in calls:
        key = (call.batch_id, len(call.case_ids))
        by_shape.setdefault(key, {})[call.condition] = call.text_format
        schema = call.text_format["schema"]["properties"]["answers"]
        assert schema["minItems"] == len(call.case_ids)
        assert schema["maxItems"] == len(call.case_ids)
    assert all(set(row) == set(experiment.CONDITIONS) for row in by_shape.values())
    assert experiment.frontier.parse_structured_labels(
        json.dumps({"answers": ["A", "INSUFFICIENT"]}), 2
    ) == ("A", "INSUFFICIENT")
    with pytest.raises(experiment.grading.ConstrainedInterfaceFailure):
        experiment.frontier.parse_structured_labels(
            json.dumps({"answers": ["A"]}), 2
        )


def test_preflight_freezes_state_size_and_cost_below_authorization():
    _payload, cases, _calls, preflight = _uncommitted_preflight()
    assert len(cases) == 20
    state = preflight["representation_utf8_bytes_per_20_world_replication"]
    assert state[experiment.LUNA_C1] < state[experiment.SOL_RAW]
    assert preflight["cost"]["conservative_generation_cost_upper_bound_usd"] < 100
    assert preflight["cost"]["authorized_cost_ceiling_usd"] == 100


def test_sign_flip_uses_replications_and_does_not_call_ties_equivalence():
    all_positive = experiment.exact_two_sided_sign_flip([1, 1, 1, 1, 1, 1])
    assert all_positive["permutations"] == 64
    assert all_positive["p_value"] == 0.03125
    ties = experiment.exact_two_sided_sign_flip([0, 0, 0, 0, 0, 0])
    assert ties["p_value"] == 1.0
    assert ties["non_rejection_is_equivalence"] is False


def test_derived_constants_match_frozen_values_after_freeze():
    derived = experiment.derived_frozen_values(REPO_ROOT)
    frozen = {
        "schedule_sha256": experiment.FROZEN_SCHEDULE_SHA256,
        "request_plan_sha256": experiment.FROZEN_REQUEST_PLAN_SHA256,
        "solver_config_sha256": experiment.FROZEN_SOLVER_CONFIG_SHA256,
        "input_token_upper_bound": experiment.FROZEN_INPUT_TOKEN_UPPER_BOUND,
        "cost_upper_bound_usd": experiment.FROZEN_COST_UPPER_BOUND_USD,
    }
    if experiment.FROZEN_SCHEDULE_SHA256 == "FREEZE_ME":
        pytest.skip("implementation constants have not yet been frozen")
    assert derived == frozen


def test_perfect_fake_pair_run_is_valid_and_offline_verifies(tmp_path):
    _payload, cases, _calls, _preflight = _uncommitted_preflight()
    fake = FakePair(cases)
    progress = io.StringIO()
    run_dir = tmp_path / "pair"
    result = experiment.ComparisonRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
        progress_stream=progress,
    ).run()
    assert result["validity"] == "VALID"
    assert result["result_code"] == "VALID_OBSERVED_ACCURACY_TIE"
    assert result["conditions"][experiment.LUNA_C1]["exact_correct"] == 120
    assert result["conditions"][experiment.SOL_RAW]["exact_correct"] == 120
    assert result["primary_comparison"]["p_value"] == 1.0
    assert result["physical_generation_calls"] == 72
    assert len(fake.calls) == 72
    verified = experiment.verify_run(run_dir)
    assert verified["physical_generation_calls"] == 72
    assert verified["unique_response_ids"] == 72
    rendered_progress = progress.getvalue()
    assert " 0/72    0.0%  ready" in rendered_progress
    assert "72/72  100.0%" in rendered_progress
    assert rendered_progress.endswith("\n")


    # Even a resealed RESULT and correspondingly resealed index must fail when
    # it differs from independent reparse/regrade/reaggregation.
    result_path = run_dir / "RESULT.json"
    stored_result = json.loads(result_path.read_text(encoding="utf-8"))
    result_body = {
        key: value for key, value in stored_result.items() if key != "payload_sha256"
    }
    result_body["conditions"][experiment.LUNA_C1]["exact_correct"] = 119
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
    index_path.write_text(
        experiment._pretty_json(experiment._sealed(index_body)), encoding="utf-8"
    )
    with pytest.raises(experiment.ApparatusFailure, match="independent recomputation"):
        experiment.verify_run(run_dir)


def test_malformed_fake_pair_fails_closed_without_retry(tmp_path):
    _payload, cases, _calls, _preflight = _uncommitted_preflight()
    fake = FakePair(cases, malformed_call=2)
    progress = io.StringIO()
    run_dir = tmp_path / "pair-invalid"
    result = experiment.ComparisonRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
        progress_stream=progress,
    ).run()
    assert result["validity"] == "INVALID"
    assert result["result_code"] == "INVALID_APPARATUS"
    assert len(fake.calls) == 2
    assert "FAILED" in progress.getvalue()
    decisions = list(run_dir.glob("*/decisions/decision_*.json"))
    assert len(decisions) == 2
    rejected = json.loads(
        next(
            path
            for path in decisions
            if json.loads(path.read_text(encoding="utf-8"))["status"]
            == "parser_rejected"
        ).read_text(encoding="utf-8")
    )
    assert rejected["grader_status"] == "not_run"
    assert rejected["grader_agreement"] is None
    assert experiment.verify_run(run_dir)["validity"] == "INVALID"
