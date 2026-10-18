import json
from pathlib import Path

import pytest

from kingdom import decompression_frontier_luna as v1
from kingdom import decompression_frontier_luna_v1_2 as v1_2
from kingdom import decompression_frontier_luna_v1_3 as v1_3
from tests.test_decompression_frontier_luna_v1_1 import FakeCompletionLuna, _cases


REPO_ROOT = Path(__file__).resolve().parents[1]


class ReplicatedConditionErrorLuna(FakeCompletionLuna):
    def __init__(self, cases, *, wrong):
        super().__init__(cases)
        self.wrong = dict(wrong)
        _, _, calls, _ = v1_2.deterministic_preflight(
            REPO_ROOT, require_committed=False
        )
        self.condition_by_local_sequence = {
            call.sequence: call.condition for call in calls
        }

    def __call__(
        self,
        prompt,
        *,
        role,
        solver_config,
        metadata,
        openai_text_format,
    ):
        global_sequence = len(self.calls) + 1
        replication = (global_sequence - 1) // v1_3.CALLS_PER_REPLICATION + 1
        local_sequence = (global_sequence - 1) % v1_3.CALLS_PER_REPLICATION + 1
        response = super().__call__(
            prompt,
            role=role,
            solver_config=solver_config,
            metadata=metadata,
            openai_text_format=openai_text_format,
        )
        payload = v1._input_payload(prompt)
        labels = json.loads(response)["answers"]
        condition = self.condition_by_local_sequence[local_sequence]
        for index, item in enumerate(payload["cases"]):
            replacement = self.wrong.get(
                (replication, condition, item["case_id"])
            )
            if replacement is not None:
                labels[index] = replacement
        changed = json.dumps({"answers": labels}, separators=(",", ":"))
        metadata["partial_output_text"] = changed
        return changed


class AllWrongLuna(FakeCompletionLuna):
    def __call__(
        self,
        prompt,
        *,
        role,
        solver_config,
        metadata,
        openai_text_format,
    ):
        response = super().__call__(
            prompt,
            role=role,
            solver_config=solver_config,
            metadata=metadata,
            openai_text_format=openai_text_format,
        )
        payload = v1._input_payload(prompt)
        labels = []
        for item in payload["cases"]:
            correct = self.by_case[item["case_id"]].correct_choice
            labels.append(next(label for label in ("A", "B", "C", "D") if label != correct))
        changed = json.dumps({"answers": labels}, separators=(",", ":"))
        metadata["partial_output_text"] = changed
        return changed


class ModelDriftLuna(FakeCompletionLuna):
    def __call__(self, prompt, **kwargs):
        response = super().__call__(prompt, **kwargs)
        if len(self.calls) > 24:
            kwargs["metadata"]["returned_model"] = "gpt-5.6-luna-other-snapshot"
        return response


def _comparison(*, delta=0, chronology=0, promotions=0, quality=True, zero=True):
    return {
        "exact_correct_delta_candidate_minus_baseline": delta,
        "chronology_authority_error_delta_candidate_minus_baseline": chronology,
        "illegal_state_promotion_delta_candidate_minus_baseline": promotions,
        "quality_not_worse_than_baseline": quality,
        "per_case_zero_distortion": zero,
    }


def test_preflight_repeats_the_exact_v1_2_schedule_six_times():
    _, _, old_calls, old_preflight = v1_2.deterministic_preflight(
        REPO_ROOT, require_committed=False
    )
    _, _, calls, preflight = v1_3.deterministic_preflight(
        REPO_ROOT, require_committed=False
    )

    assert [call.prompt for call in calls] == [call.prompt for call in old_calls]
    assert [call.case_ids for call in calls] == [call.case_ids for call in old_calls]
    assert [call.condition for call in calls] == [call.condition for call in old_calls]
    assert [call.text_format for call in calls] == [
        call.text_format for call in old_calls
    ]
    assert preflight["solver_config"] == old_preflight["solver_config"]
    assert preflight["call_plan"] == old_preflight["call_plan"]
    assert preflight["replication_count"] == 6
    assert preflight["calls_per_replication"] == 24
    assert preflight["maximum_physical_generation_calls"] == 144
    assert preflight["prior_v1_2_result_in_confirmatory_sample"] is False
    assert preflight["interim_success_stop"] is False
    assert preflight["cost"][
        "conservative_generation_cost_upper_bound_usd"
    ] == 6 * old_preflight["cost"][
        "conservative_generation_cost_upper_bound_usd"
    ]
    assert preflight["frozen_v1_2_inference_sha256"] == (
        "e563686089680920898c8cdaaf07c98754b2bd2e67e85e6c82b45d4cd96d891e"
    )
    assert v1_2.PROTOCOL_ID == "hive-luna-compression-frontier-v1.2"


def test_frozen_stability_classes_require_six_run_level_results():
    stable = v1_3._classify_stability([_comparison()] * 6)
    assert stable["result_code"] == "VALID_OBSERVED_C0_ZERO_DISTORTION_ALL_SIX"
    assert stable["stability_class"] == "OBSERVED_NO_REGRESSION_ALL_SIX"
    assert stable["statistical_equivalence_established"] is False

    regression = v1_3._classify_stability(
        [_comparison(delta=-1, quality=False, zero=False)] * 6
    )
    assert regression["result_code"] == (
        "VALID_SYSTEMATIC_C0_CORRECTNESS_REGRESSION"
    )
    assert regression["correctness_sign_test"]["p_value"] == 0.03125
    assert regression["systematic_correctness_loss"] is True

    mixed = v1_3._classify_stability(
        [_comparison(delta=-1, quality=False, zero=False)] * 3
        + [_comparison()] * 3
    )
    assert mixed["result_code"] == "VALID_MIXED_C0_STABILITY"
    assert mixed["absence_of_significance_proves_equivalence"] is False


def test_six_complete_fake_replications_are_sealed_and_verified(tmp_path):
    _, cases = _cases()
    fake = FakeCompletionLuna(cases)
    run_dir = tmp_path / "all-pass"
    result = v1_3.ReplicationRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()

    assert result["validity"] == "VALID"
    assert result["result_code"] == "VALID_OBSERVED_C0_ZERO_DISTORTION_ALL_SIX"
    assert result["conditions"]["raw"]["exact_correct"] == 120
    assert result["conditions"]["C0"]["exact_correct"] == 120
    assert result["pooled_paired_comparisons"]["C0_vs_Raw"][
        "both_correct"
    ] == 120
    assert len(fake.calls) == 144
    verified = v1_3.verify_run(run_dir)
    assert verified["physical_generation_calls"] == 144
    assert verified["unique_response_ids"] == 144
    assert verified["replications"] == 6


def test_same_c0_loss_in_all_six_runs_is_reported_not_repaired(tmp_path):
    _, cases = _cases()
    wrong = {
        (replication, "C0", "DT-TA-SH"): "A"
        for replication in range(1, 7)
    }
    fake = ReplicatedConditionErrorLuna(cases, wrong=wrong)
    run_dir = tmp_path / "systematic-loss"
    result = v1_3.ReplicationRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()

    inference = result["C0_replication_inference"]
    assert result["validity"] == "VALID"
    assert result["result_code"] == "VALID_SYSTEMATIC_C0_CORRECTNESS_REGRESSION"
    assert result["conditions"]["raw"]["exact_correct"] == 120
    assert result["conditions"]["C0"]["exact_correct"] == 114
    assert inference["correctness_sign_test"]["p_value"] == 0.03125
    assert inference["same_Raw_only_case_in_all_six_replications"] == [
        "DT-TA-SH"
    ]
    assert len(fake.calls) == 144
    assert v1_3.verify_run(run_dir)["physical_generation_calls"] == 144


def test_six_equal_near_zero_runs_remain_low_capability_inconclusive(tmp_path):
    _, cases = _cases()
    fake = AllWrongLuna(cases)
    result = v1_3.ReplicationRunner(
        repo_root=REPO_ROOT,
        output_dir=tmp_path / "low-capability",
        ask_fn=fake,
        require_committed=False,
    ).run()

    assert result["validity"] == "VALID"
    assert result["result_code"] == "VALID_INCONCLUSIVE_LOW_SOLVER_CAPABILITY"
    assert result["C0_replication_inference"]["evidence_label"] == "INCONCLUSIVE"
    assert result["C0_replication_inference"]["stability_class"] == (
        "NOT_ASSESSED_LOW_SOLVER_CAPABILITY"
    )
    assert result["C0_replication_inference"][
        "low_solver_capability_replication_ids"
    ] == [1, 2, 3, 4, 5, 6]
    assert len(fake.calls) == 144


def test_cross_replication_model_drift_fails_closed(tmp_path):
    _, cases = _cases()
    fake = ModelDriftLuna(cases)
    run_dir = tmp_path / "model-drift"
    result = v1_3.ReplicationRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()

    assert result["validity"] == "INVALID"
    assert result["failed_replication"] == 2
    assert result["replications_completed"] == 2
    assert result["replications_started"] == 2
    assert result["apparatus_failure"] == (
        "returned model drifted between replications"
    )
    assert len(fake.calls) == 48
    assert v1_3.verify_run(run_dir)["physical_generation_calls"] == 48


def test_live_runner_rejects_non_preregistered_or_existing_directory(tmp_path):
    _, cases = _cases()
    fake = FakeCompletionLuna(cases)
    with pytest.raises(v1.ApparatusFailure, match="locked to the preregistered"):
        v1_3.ReplicationRunner(
            repo_root=REPO_ROOT,
            output_dir=tmp_path / "alternate-live-sample",
            ask_fn=fake,
            require_committed=True,
        ).run()
    assert fake.calls == []

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(v1.ApparatusFailure, match="already exists"):
        v1_3.ReplicationRunner(
            repo_root=REPO_ROOT,
            output_dir=existing,
            ask_fn=fake,
            require_committed=False,
        ).run()
    assert fake.calls == []


def test_child_precheck_cannot_drift_from_root_binding(tmp_path):
    _, _, _, root = v1_3.deterministic_preflight(
        REPO_ROOT, require_committed=False
    )
    with v1_3._v1_3_bindings():
        _, _, _, child = v1_2.deterministic_preflight(
            REPO_ROOT, require_committed=False
        )
    child_dir = tmp_path / "replicate-001"
    v1._write_exclusive(
        child_dir / "PRECHECK.json", v1._pretty_json(child)
    )
    v1_3._assert_child_artifact_binding(child_dir, root_preflight=root)

    drifted = dict(child)
    drifted.pop("payload_sha256")
    drifted["source_revision"] = "different-revision"
    (child_dir / "PRECHECK.json").write_text(
        v1._pretty_json(v1._sealed(drifted)), encoding="utf-8", newline="\n"
    )
    with pytest.raises(v1.ApparatusFailure, match="differs from the root"):
        v1_3._assert_child_artifact_binding(child_dir, root_preflight=root)


def test_apparatus_failure_stops_without_replacement_replication(tmp_path):
    _, cases = _cases()
    fake = FakeCompletionLuna(cases, network_failure_call=25)
    run_dir = tmp_path / "apparatus-failure"
    result = v1_3.ReplicationRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()

    assert result["validity"] == "INVALID"
    assert result["result_code"] == "INVALID_REPLICATION_APPARATUS"
    assert result["failed_replication"] == 2
    assert result["replications_completed"] == 1
    assert len(fake.calls) == 25
    verified = v1_3.verify_run(run_dir)
    assert verified["replications"] == 2
    assert verified["physical_generation_calls"] == 25
