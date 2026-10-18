import copy
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from kingdom import decompression_frontier_luna as luna_v1
from kingdom import decompression_matched_semantic_control_luna as experiment
from kingdom import decompression_test as worlds
from tests.test_decompression_frontier_luna_v1_1 import FakeCompletionLuna


REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = REPO_ROOT / "benchmarks/decompression_test/CASE_PACK.json"


def _cases():
    payload, cases = worlds.load_case_pack(CASE_PATH)
    worlds.validate_case_pack(payload, cases)
    return payload, cases


class ExactFakeCompletion(FakeCompletionLuna):
    def __call__(self, prompt, **kwargs):
        response = super().__call__(prompt, **kwargs)
        kwargs["metadata"]["returned_model"] = experiment.MODEL
        return response


class DuplicateResponseCompletion(ExactFakeCompletion):
    def __call__(self, prompt, **kwargs):
        response = super().__call__(prompt, **kwargs)
        if len(self.calls) == 2:
            kwargs["metadata"]["response_id"] = "resp_001"
        return response


class ParserFailureCompletion(ExactFakeCompletion):
    def __call__(self, prompt, **kwargs):
        response = super().__call__(prompt, **kwargs)
        if len(self.calls) == 2:
            return "```json\n" + response + "\n```"
        return response


def _preflight():
    return experiment._derive_preflight(REPO_ROOT, require_committed=False)


@pytest.fixture(scope="module")
def completed_run(tmp_path_factory):
    _, cases = _cases()
    fake = ExactFakeCompletion(cases)
    run_dir = tmp_path_factory.mktemp("matched-semantic-control") / "complete"
    result = experiment.MatchedSemanticControlRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()
    return run_dir, result, fake


def _stat(p_value, mean):
    return {
        "p_value": p_value,
        "effect": {"mean_answers_out_of_20": mean},
    }


def test_required_lineage_resolves_and_study2_evidence_verifies():
    sealed = experiment.verify_sealed_study2(REPO_ROOT)
    assert sealed["starting_checkpoint"] == experiment.SEALED_STUDY2_CHECKPOINT
    assert sealed["implementation"] == experiment.SEALED_STUDY2_IMPLEMENTATION
    assert sealed["evidence"] == experiment.SEALED_STUDY2_EVIDENCE
    assert sealed["evidence_tree"] == experiment.SEALED_STUDY2_TREE
    assert sealed["verification"]["physical_generation_calls"] == 384


def test_exact_three_conditions_and_144_call_plan():
    _, _, calls, preflight = _preflight()
    assert experiment.CONDITIONS == ("C1", "M3", "KAS-")
    assert len(calls) == 144
    assert preflight["maximum_physical_generation_calls"] == 144
    assert preflight["replication_count"] == 8
    assert preflight["batches_per_condition"] == 6


def test_schedule_is_exactly_position_and_precedence_balanced():
    _, _, _, preflight = _preflight()
    assert preflight["ordinal_position_counts"] == {
        "C1": [16, 16, 16],
        "M3": [16, 16, 16],
        "KAS-": [16, 16, 16],
    }
    assert set(preflight["pairwise_precedence_counts"].values()) == {24}
    assert preflight["condition_schedule_sha256"] == experiment.FROZEN_SCHEDULE_SHA256


def test_m3_generator_has_only_structural_row_count_input():
    contract = experiment._m3_construction_contract()
    assert contract["generator_parameters"] == ["record_count"]
    assert contract["generated_alphanumeric_tokens"] == []
    assert contract["all_frozen_semantic_codes_are_one_unescaped_ascii_byte"] is True
    assert (
        luna_v1._sha256_text(luna_v1._canonical_json(contract))
        == experiment.FROZEN_M3_CONSTRUCTION_SHA256
    )


def test_m3_is_semantically_independent_under_arbitrary_kas_changes():
    _, cases = _cases()
    source = experiment._c1_packet(cases[0])
    expected = experiment.project_packet(source, "M3")
    mutated = copy.deepcopy(source)
    for index, row in enumerate(mutated["records"]):
        row[2] = {"different": [index]}
        row[3] = ["unrelated", index]
        row[4] = None
    assert experiment.project_packet(mutated, "M3") == expected


def test_m3_is_query_oracle_grading_and_decoy_blind():
    _, cases = _cases()
    case = cases[0]
    altered = replace(
        case,
        question="changed question",
        options={"A": "x", "B": "y", "C": "z", "D": "w"},
        correct_choice="D" if case.correct_choice != "D" else "A",
        reasoning_code="changed",
        required_event_refs=("changed",),
        allowed_event_refs=("changed",),
        rejected_event_refs=("changed",),
        current_claim_ids=("changed",),
    )
    for condition in experiment.CONDITIONS:
        assert experiment.batch_representations((case,), condition) == (
            experiment.batch_representations((altered,), condition)
        )


def test_m3_is_deterministic_and_detached_from_mutable_aliases():
    _, cases = _cases()
    source = experiment._c1_packet(cases[0])
    source = json.loads(json.dumps(source))
    source["records"][1][5] = source["records"][0][5]
    projected = experiment.project_packet(source, "M3")
    frozen = luna_v1._canonical_json(projected)
    source["records"][0][5].append(["mutated", "==", True])
    assert luna_v1._canonical_json(projected) == frozen
    assert projected["records"][0][5] is not projected["records"][1][5]
    reordered = {
        "records": copy.deepcopy(source["records"]),
        "record_columns": list(experiment.C1_COLUMNS),
        "format": "compact_named_columns_frontier_v1",
    }
    assert luna_v1._canonical_json(experiment.project_packet(reordered, "M3")) == (
        luna_v1._canonical_json(experiment.project_packet(source, "M3"))
    )


def test_condition_isolation_is_exact_named_column_change_only():
    _, cases = _cases()
    source = experiment._c1_packet(cases[0])
    c1 = experiment.project_packet(source, "C1")
    kas = experiment.project_packet(source, "KAS-")
    m3 = experiment.project_packet(source, "M3")
    assert c1["record_columns"] == list(experiment.C1_COLUMNS)
    assert kas["record_columns"] == list(experiment.KAS_COLUMNS)
    assert m3["record_columns"] == list(experiment.M3_COLUMNS)
    stripped = {
        "format": m3["format"],
        "record_columns": list(experiment.KAS_COLUMNS),
        "records": [[row[0], row[1], row[5], row[6]] for row in m3["records"]],
    }
    assert stripped == kas


def test_semantic_vocabulary_guard_includes_one_character_codes_without_exemption():
    contract = experiment._m3_construction_contract()
    assert all(not any(char.isalnum() for char in value) for value in (*experiment.M3_FIELDS, *experiment.M3_VALUES))
    assert "one-character codes" in contract["semantic_vocabulary_rule"]
    assert contract["field_name_length_matching"] == "aggregate_only_not_positionwise"
    assert contract["field_name_utf8_lengths"] == [1, 7, 11]
    assert contract["semantic_field_name_utf8_lengths"] == [4, 9, 6]
    assert contract["field_name_total_utf8_bytes"] == 19
    assert contract["semantic_field_name_total_utf8_bytes"] == 19


def test_every_case_batch_and_complete_prompt_is_exactly_byte_matched():
    _, _, _, preflight = _preflight()
    for sizes in preflight["representation_utf8_bytes_by_case"].values():
        assert sizes["M3"] == sizes["C1"]
    for row in preflight["size_rows"]:
        assert row["canonical_representation_list_utf8_bytes"]["M3"] == row[
            "canonical_representation_list_utf8_bytes"
        ]["C1"]
        assert row["complete_prompt_utf8_bytes"]["M3"] == row[
            "complete_prompt_utf8_bytes"
        ]["C1"]
        assert row["m3_minus_c1_absolute_bytes"] == 0
        assert row["m3_minus_c1_percentage"] == 0
    assert preflight["size_match_tolerance_bytes"] == 0
    assert preflight["representation_utf8_bytes_per_20_world_replication"] == {
        "C1": 32482,
        "M3": 32482,
        "KAS-": 27122,
    }


def test_c1_and_kas_prompts_are_exact_study2_controls_and_m3_hides_condition_id():
    payload, cases = _cases()
    by_case = {case.case_id: case for case in cases}
    prior = experiment._prior_prompt_map(REPO_ROOT)
    for batch in payload["batches"]:
        selected = tuple(by_case[case_id] for case_id in batch["case_ids"])
        batch_id = batch["batch_id"]
        assert experiment.build_solver_prompt(selected, "C1") == prior[("C1", batch_id)]
        assert experiment.build_solver_prompt(selected, "KAS-") == prior[("KAS-", batch_id)]
        for condition in experiment.CONDITIONS:
            prompt = experiment.build_solver_prompt(selected, condition)
            assert '"condition":' not in prompt
            assert '"M3"' not in prompt
            assert '"KAS-"' not in prompt


def test_solver_schema_settings_hashes_and_cost_are_frozen():
    _, _, calls, preflight = _preflight()
    assert preflight["solver_config_sha256"] == experiment.FROZEN_SOLVER_CONFIG_SHA256
    assert preflight["request_plan_sha256"] == experiment.FROZEN_REQUEST_PLAN_SHA256
    assert preflight["cost"]["request_utf8_bytes_input_token_upper_bound"] == 3_886_160
    assert preflight["cost"]["output_token_upper_bound"] == 2_359_296
    assert preflight["cost"]["conservative_generation_cost_upper_bound_usd"] == pytest.approx(3.6083872)
    assert preflight["cost"]["authorized_cost_ceiling_usd"] == 100.0
    assert all(call.text_format == luna_v1.openai_text_format(len(call.case_ids)) for call in calls)
    config = experiment.solver_config()
    assert config.max_output_tokens == 16_384
    assert config.max_attempts == 1
    assert config.tool_permissions == ()
    assert config.store is False


def test_exact_sign_flip_known_vectors_and_ties():
    all_harmful = experiment.exact_comparison(
        [19] * 8,
        [20] * 8,
        comparison_id="x",
        difference_definition="x",
        inferential_role="test",
    )
    assert all_harmful["differences"] == [-1] * 8
    assert all_harmful["p_value"] == 2 / 256
    assert all_harmful["effect"]["tie_replications"] == 0
    ties = experiment.exact_comparison(
        [20] * 8,
        [20] * 8,
        comparison_id="x",
        difference_definition="x",
        inferential_role="test",
    )
    assert ties["p_value"] == 1.0
    assert ties["permutations"] == 256
    assert ties["effect"]["tie_replications"] == 8
    assert ties["multiplicity_adjustment"] is None
    partial_ties = experiment.exact_comparison(
        [19, 19, 19, 19, 20, 20, 20, 20],
        [20] * 8,
        comparison_id="x",
        difference_definition="x",
        inferential_role="test",
    )
    assert partial_ties["differences"] == [-1, -1, -1, -1, 0, 0, 0, 0]
    assert partial_ties["p_value"] == 32 / 256
    assert partial_ties["permutations"] == 256


def test_secondary_is_preregistered_mechanistic_not_posthoc_exploration():
    _, _, _, preflight = _preflight()
    secondary = preflight["statistics"]["secondary"]
    assert secondary["role"] == "preregistered_secondary_mechanistic"
    assert secondary["multiplicity_adjustment"] is None
    assert secondary["may_inform_frozen_outcome_classification"] is True


def test_exact_comparison_rejects_pseudoreplicated_or_incomplete_vectors():
    with pytest.raises(ValueError, match="eight complete"):
        experiment.exact_comparison(
            [1] * 160,
            [1] * 160,
            comparison_id="x",
            difference_definition="x",
            inferential_role="test",
        )
    with pytest.raises(ValueError, match="eight complete"):
        experiment.exact_comparison(
            [20] * 7,
            [20] * 7,
            comparison_id="x",
            difference_definition="x",
            inferential_role="test",
        )


@pytest.mark.parametrize(
    "totals,primary,secondary,control,expected,outcome",
    [
        (
            {"C1": 160, "M3": 30, "KAS-": 26},
            _stat(2 / 256, -16),
            _stat(1.0, 0.5),
            _stat(2 / 256, -16.75),
            "VALID_SUPPORTED_SEMANTIC_CONTROL",
            "M3_FAILED_TO_RECOVER_C1",
        ),
        (
            {"C1": 160, "M3": 100, "KAS-": 26},
            _stat(2 / 256, -7.5),
            _stat(2 / 256, 9.25),
            _stat(2 / 256, -16.75),
            "VALID_MIXED_RESULT",
            "BOTH_STRUCTURE_AND_SEMANTICS_CONTRIBUTE",
        ),
        (
            {"C1": 160, "M3": 159, "KAS-": 26},
            _stat(1.0, -0.125),
            _stat(2 / 256, 16.625),
            _stat(2 / 256, -16.75),
            "VALID_STRUCTURAL_ALTERNATIVE_SUPPORTED",
            "M3_NEAR_C1_AND_IMPROVED_OVER_KAS",
        ),
        (
            {"C1": 150, "M3": 151, "KAS-": 25},
            _stat(2 / 256, 0.125),
            _stat(2 / 256, 15.75),
            _stat(2 / 256, -15.625),
            "VALID_STRUCTURAL_ALTERNATIVE_SUPPORTED",
            "M3_EXCEEDED_C1",
        ),
        (
            {"C1": 160, "M3": 20, "KAS-": 26},
            _stat(2 / 256, -17.5),
            _stat(1.0, -0.75),
            _stat(2 / 256, -16.75),
            "VALID_INCONCLUSIVE",
            "CONTROL_DISTRACTION_M3_BELOW_KAS",
        ),
        (
            {"C1": 143, "M3": 140, "KAS-": 25},
            _stat(2 / 256, -0.375),
            _stat(2 / 256, 14.375),
            _stat(2 / 256, -14.75),
            "VALID_INCONCLUSIVE",
            "BASELINE_DRIFT",
        ),
        (
            {"C1": 160, "M3": 100, "KAS-": 159},
            _stat(2 / 256, -7.5),
            _stat(2 / 256, -7.375),
            _stat(1.0, -0.125),
            "VALID_INCONCLUSIVE",
            "CONTEMPORANEOUS_CONTROL_NOT_REPLICATED",
        ),
    ],
)
def test_classification_truth_table(totals, primary, secondary, control, expected, outcome):
    result = experiment._classify_result(
        totals=totals, primary=primary, secondary=secondary, control=control
    )
    assert result["result_code"] == expected
    assert result["outcome"] == outcome
    assert result["non_rejection_is_equivalence"] is False


def test_baseline_boundary_144_is_not_drift():
    result = experiment._classify_result(
        totals={"C1": 144, "M3": 100, "KAS-": 20},
        primary=_stat(2 / 256, -5.5),
        secondary=_stat(2 / 256, 10),
        control=_stat(2 / 256, -15.5),
    )
    assert result["baseline_drift"] is False


def test_nonsignificance_cannot_promote_a_strongly_intermediate_m3_result():
    result = experiment._classify_result(
        totals={"C1": 160, "M3": 120, "KAS-": 0},
        primary=_stat(0.125, -5.0),
        secondary=_stat(2 / 256, 15.0),
        control=_stat(2 / 256, -20.0),
    )
    assert result["result_code"] == "VALID_INCONCLUSIVE"
    assert result["approximately_c1"] is False
    assert result["non_rejection_is_equivalence"] is False


@pytest.mark.parametrize(
    "m3_total,expected",
    [
        (156, "VALID_STRUCTURAL_ALTERNATIVE_SUPPORTED"),
        (155, "VALID_INCONCLUSIVE"),
    ],
)
def test_approximate_c1_descriptive_margin_has_frozen_inclusive_boundary(
    m3_total, expected
):
    result = experiment._classify_result(
        totals={"C1": 160, "M3": m3_total, "KAS-": 20},
        primary=_stat(0.125, (m3_total - 160) / 8),
        secondary=_stat(2 / 256, (m3_total - 20) / 8),
        control=_stat(2 / 256, -17.5),
    )
    assert result["result_code"] == expected
    assert result["approximately_c1"] is (m3_total == 156)
    _, _, _, preflight = _preflight()
    assert (
        preflight["statistics"]["approximately_c1_max_aggregate_deficit_answers"]
        == 4
    )


def test_fake_complete_run_has_144_unique_one_attempt_calls_and_verifies(completed_run):
    run_dir, result, fake = completed_run
    assert result["validity"] == "VALID"
    assert result["result_code"] == "VALID_INCONCLUSIVE"
    assert len(fake.calls) == 144
    assert all(row["max_output_tokens"] == 16_384 for row in fake.calls)
    verified = experiment.verify_run(run_dir)
    assert verified["physical_generation_calls"] == 144
    assert verified["unique_response_ids"] == 144
    assert verified["returned_models"] == [experiment.MODEL]
    assert verified["returned_service_tiers"] == ["default"]


def test_fake_run_records_no_parser_grader_transport_or_incomplete_failures(completed_run):
    _, result, _ = completed_run
    for condition in experiment.CONDITIONS:
        row = result["conditions"][condition]
        assert row["admissible"] == 160
        assert row["parser_failures"] == 0
        assert row["grader_failures"] == 0
        assert row["transport_failures"] == 0
        assert row["incomplete_responses"] == 0


def test_duplicate_response_id_fails_closed_without_retry(tmp_path):
    _, cases = _cases()
    fake = DuplicateResponseCompletion(cases)
    result = experiment.MatchedSemanticControlRunner(
        repo_root=REPO_ROOT,
        output_dir=tmp_path / "duplicate",
        ask_fn=fake,
        require_committed=False,
    ).run()
    assert result["validity"] == "INVALID"
    assert result["result_code"] == "INVALID_APPARATUS"
    assert result["failed_sequence"] == 2
    assert len(fake.calls) == 2
    assert result["retry_attempted"] is False
    assert result["repair_attempted"] is False


def test_parser_failure_fails_closed_without_salvage_or_retry(tmp_path):
    _, cases = _cases()
    fake = ParserFailureCompletion(cases)
    run_dir = tmp_path / "parser"
    result = experiment.MatchedSemanticControlRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()
    assert result["validity"] == "INVALID"
    assert result["failed_sequence"] == 2
    decision = json.loads(
        (run_dir / "decisions" / "decision_000002.json").read_text(encoding="utf-8")
    )
    assert decision["parser_status"] == "failed"
    assert decision["grader_status"] == "not_run"
    assert decision["scores"] == []
    assert len(fake.calls) == 2


def test_transport_failure_stops_schedule_and_preserves_partial_evidence(tmp_path):
    _, cases = _cases()
    fake = ExactFakeCompletion(cases, network_failure_call=2)
    run_dir = tmp_path / "transport"
    result = experiment.MatchedSemanticControlRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()
    assert result["validity"] == "INVALID"
    assert result["failed_sequence"] == 2
    assert result["partial_artifacts_preserved"] is True
    assert len(list((run_dir / "calls").glob("call_*.json"))) == 2
    assert len(fake.calls) == 2


def test_verifier_rejects_any_physical_artifact_tamper(completed_run, tmp_path):
    original, _, _ = completed_run
    copied = tmp_path / "tampered"
    shutil.copytree(original, copied)
    path = copied / "calls" / "call_000001.json"
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(luna_v1.ApparatusFailure, match="sealed evidence changed"):
        experiment.verify_run(copied)


def test_frozen_commit_chronology_and_fresh_live_directory():
    if not (REPO_ROOT / experiment.PROTOCOL_PATH).is_file():
        pytest.skip("protocol-only freeze commit has not been created yet")
    frozen = experiment._freeze_chronology(REPO_ROOT)
    assert frozen["implementation_parent"] == experiment.SEALED_STUDY2_EVIDENCE
    assert frozen["implementation_paths"] == sorted(
        (experiment.MODULE_PATH, experiment.TEST_PATH)
    )
    assert frozen["protocol_paths"] == [experiment.PROTOCOL_PATH]
    assert not (REPO_ROOT / experiment.RUN_DIR).exists()
