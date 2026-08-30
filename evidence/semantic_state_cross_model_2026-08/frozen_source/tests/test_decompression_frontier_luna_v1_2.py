import json
from pathlib import Path

from kingdom import decompression_frontier_luna as v1
from kingdom import decompression_frontier_luna_v1_1 as v1_1
from kingdom import decompression_frontier_luna_v1_2 as v1_2
from tests.test_decompression_frontier_luna_v1_1 import FakeCompletionLuna, _cases


REPO_ROOT = Path(__file__).resolve().parents[1]


class ConditionErrorLuna(FakeCompletionLuna):
    def __init__(self, cases, *, wrong):
        super().__init__(cases)
        self.wrong = dict(wrong)
        _, _, calls, _ = v1_2.deterministic_preflight(
            REPO_ROOT, require_committed=False
        )
        self.condition_by_sequence = {call.sequence: call.condition for call in calls}

    def __call__(
        self,
        prompt,
        *,
        role,
        solver_config,
        metadata,
        openai_text_format,
    ):
        sequence = len(self.calls) + 1
        response = super().__call__(
            prompt,
            role=role,
            solver_config=solver_config,
            metadata=metadata,
            openai_text_format=openai_text_format,
        )
        payload = v1._input_payload(prompt)
        condition = self.condition_by_sequence[sequence]
        labels = json.loads(response)["answers"]
        for index, item in enumerate(payload["cases"]):
            replacement = self.wrong.get((condition, item["case_id"]))
            if replacement is not None:
                labels[index] = replacement
        changed = json.dumps({"answers": labels}, separators=(",", ":"))
        metadata["partial_output_text"] = changed
        return changed


def test_preflight_preserves_every_call_and_changes_only_protocol_binding():
    _, _, old_calls, old_preflight = v1_1.deterministic_preflight(
        REPO_ROOT, require_committed=False
    )
    _, _, calls, preflight = v1_2.deterministic_preflight(
        REPO_ROOT, require_committed=False
    )
    assert [call.prompt for call in calls] == [call.prompt for call in old_calls]
    assert [call.case_ids for call in calls] == [call.case_ids for call in old_calls]
    assert [call.condition for call in calls] == [call.condition for call in old_calls]
    assert [call.text_format for call in calls] == [call.text_format for call in old_calls]
    assert preflight["protocol_id"] == v1_2.PROTOCOL_ID
    assert preflight["solver_config"] == old_preflight["solver_config"]
    assert preflight["cost"] == old_preflight["cost"]
    assert "raw_gate" not in preflight
    assert preflight["raw_baseline"]["stops_frontier_on_solver_error"] is False
    assert preflight["all_conditions_run_unless_apparatus_failure"] is True
    assert len(calls) == 24


def test_imperfect_raw_becomes_baseline_and_all_conditions_run(tmp_path):
    _, cases = _cases()
    fake = ConditionErrorLuna(
        cases,
        wrong={
            ("raw_capability", "DT-TR-DL"): "B",
            ("raw_capability", "DT-CO-SH"): "A",
        },
    )
    run_dir = tmp_path / "imperfect-raw"
    result = v1_2.MatchedBaselineRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()

    assert result["validity"] == "VALID"
    assert result["result_code"] == "VALID_SUPPORTED_C0_VS_RAW"
    assert len(fake.calls) == 24
    assert result["raw"]["exact_correct"] == 18
    assert all(result["frontier"][level]["exact_correct"] == 20 for level in v1.LEVELS)
    c0 = result["paired_vs_raw"]["C0"]
    assert c0["candidate_only_correct"] == 2
    assert c0["baseline_only_correct"] == 0
    assert c0["candidate_only_correct_case_ids"] == ["DT-CO-SH", "DT-TR-DL"]
    assert c0["exact_correct_delta_candidate_minus_baseline"] == 2
    assert c0["quality_not_worse_than_baseline"] is True
    assert c0["per_case_zero_distortion"] is True
    assert result["primary_hypothesis"]["evidence_label"] == "SUPPORTED"
    assert result["primary_hypothesis"]["per_case_zero_distortion"] == "SUPPORTED"
    assert result["paired_adjacent_frontier"]["C1_vs_C0"][
        "quality_not_worse_than_baseline"
    ] is True
    assert result["relative_frontier"]["deepest_consecutive_passing_level"] == "C2"
    assert v1_2.verify_run(run_dir)["physical_generation_calls"] == 24


def test_raw_budget_exhaustion_is_scored_and_does_not_stop_comparison(tmp_path):
    _, cases = _cases()
    fake = FakeCompletionLuna(cases, budget_calls={1})
    run_dir = tmp_path / "raw-budget"
    result = v1_2.MatchedBaselineRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()

    assert result["validity"] == "VALID"
    assert len(fake.calls) == 24
    assert result["raw"]["solver_budget_exhaustions"] == 4
    assert result["frontier"]["C0"]["total"] == 20
    assert result["paired_vs_raw"]["C0"]["candidate_only_correct"] == 4
    decision = json.loads(
        (run_dir / "decisions/decision_000001.json").read_text(encoding="utf-8")
    )
    assert decision["status"] == "solver_budget_exhausted"
    assert decision["partial_output_salvaged"] is False


def test_c0_regression_is_reported_not_supported(tmp_path):
    _, cases = _cases()
    fake = ConditionErrorLuna(cases, wrong={("C0", "DT-TR-DL"): "B"})
    result = v1_2.MatchedBaselineRunner(
        repo_root=REPO_ROOT,
        output_dir=tmp_path / "c0-regression",
        ask_fn=fake,
        require_committed=False,
    ).run()

    assert result["validity"] == "VALID"
    assert result["result_code"] == "VALID_NOT_SUPPORTED_C0_VS_RAW"
    assert result["paired_vs_raw"]["C0"]["baseline_only_correct"] == 1
    assert result["paired_vs_raw"]["C0"]["quality_not_worse_than_baseline"] is False
    assert result["primary_hypothesis"]["evidence_label"] == "NOT_SUPPORTED"


def test_equal_totals_cannot_hide_swapped_compression_error(tmp_path):
    _, cases = _cases()
    fake = ConditionErrorLuna(
        cases,
        wrong={
            ("raw_capability", "DT-TR-DL"): "B",
            ("C0", "DT-CO-SH"): "A",
        },
    )
    result = v1_2.MatchedBaselineRunner(
        repo_root=REPO_ROOT,
        output_dir=tmp_path / "swapped-error",
        ask_fn=fake,
        require_committed=False,
    ).run()

    c0 = result["paired_vs_raw"]["C0"]
    assert c0["baseline_exact_correct"] == c0["candidate_exact_correct"] == 19
    assert c0["baseline_only_correct_case_ids"] == ["DT-CO-SH"]
    assert c0["candidate_only_correct_case_ids"] == ["DT-TR-DL"]
    assert c0["per_case_zero_distortion"] is False
    assert result["primary_hypothesis"]["aggregate_usable_performance"] == "SUPPORTED"
    assert result["primary_hypothesis"]["per_case_zero_distortion"] == "NOT_SUPPORTED"
