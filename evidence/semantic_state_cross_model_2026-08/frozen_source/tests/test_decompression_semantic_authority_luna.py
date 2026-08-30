import inspect
import json
from dataclasses import replace
from pathlib import Path

import pytest

from kingdom import decompression_frontier_luna as luna_v1
from kingdom import decompression_semantic_authority_luna as experiment
from kingdom import decompression_test_v2 as grading
from tests.test_decompression_frontier_luna_v1_1 import FakeCompletionLuna, _cases


REPO_ROOT = Path(__file__).resolve().parents[1]


class DuplicateResponseLuna(FakeCompletionLuna):
    def __call__(self, prompt, **kwargs):
        response = super().__call__(prompt, **kwargs)
        kwargs["metadata"]["response_id"] = "resp_reused"
        return response


class ServiceTierDriftLuna(FakeCompletionLuna):
    def __call__(self, prompt, **kwargs):
        response = super().__call__(prompt, **kwargs)
        if len(self.calls) == 2:
            kwargs["metadata"]["returned_service_tier"] = "priority"
        return response


class SecretFailureLuna(FakeCompletionLuna):
    def __call__(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt})
        raise RuntimeError(f"synthetic transport failure {__import__('os').environ['OPENAI_API_KEY']}")


def _preflight():
    return experiment.deterministic_preflight(REPO_ROOT, require_committed=False)


def _stat(p, mean):
    return {
        "p_value": p,
        "holm_adjusted_p_value": p,
        "effect": {"mean_answers_out_of_20": mean},
    }


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


def _refresh_call_finished_event(run_dir, call_relative):
    call_path = run_dir / call_relative
    call = json.loads(call_path.read_text(encoding="utf-8"))
    events_path = run_dir / "events.jsonl"
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]
    finished = events[2 * (call["sequence"] - 1) + 1]
    finished["status"] = call["status"]
    finished["artifact_file_sha256"] = luna_v1._sha256_bytes(
        call_path.read_bytes()
    )
    events_path.write_text(
        "".join(luna_v1._canonical_json(event) + "\n" for event in events),
        encoding="utf-8",
        newline="\n",
    )
    index_path = run_dir / "EVIDENCE_INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index.pop("payload_sha256")
    row = next(row for row in index["files"] if row["path"] == "events.jsonl")
    row["bytes"] = events_path.stat().st_size
    row["sha256"] = luna_v1._sha256_bytes(events_path.read_bytes())
    index["total_bytes"] = sum(row["bytes"] for row in index["files"])
    index_path.write_text(
        luna_v1._pretty_json(luna_v1._sealed(index)),
        encoding="utf-8",
        newline="\n",
    )


def _rewrite_indexed_text(run_dir, relative, text):
    path = run_dir / relative
    path.write_text(text, encoding="utf-8", newline="\n")
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


@pytest.fixture(scope="module")
def verifier_tamper_run(tmp_path_factory):
    _, cases = _cases()
    run_dir = tmp_path_factory.mktemp("semantic-verifier") / "sealed"
    result = experiment.SemanticDecompositionRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=FakeCompletionLuna(cases),
        require_committed=False,
    ).run()
    assert result["validity"] == "VALID"
    assert experiment.verify_run(run_dir)["physical_generation_calls"] == 384
    return run_dir


def test_parent_lineage_and_all_prior_sealed_hashes_verify():
    lineage = experiment.verify_sealed_parent(REPO_ROOT)

    assert lineage["sealed_parent"] == (
        "7b13c99c237315fb6a6330f3607c3591edeaa9c5"
    )
    assert lineage["sealed_implementation_parent"] == (
        "a87e54e1af7960dfb67d55c3f4e6c818bc28983f"
    )
    assert lineage["v1_3_verification"]["physical_generation_calls"] == 144
    assert lineage["v1_3_verification"]["unique_response_ids"] == 144


def test_eight_pure_projections_are_exact_and_query_blind():
    _, cases = _cases()
    case = cases[0]
    c1 = experiment._c1_packet(case)
    before = json.loads(json.dumps(c1))

    assert tuple(inspect.signature(experiment.project_c1_packet).parameters) == (
        "packet",
        "condition",
    )
    for condition in experiment.CONDITIONS:
        projected = experiment.project_c1_packet(c1, condition)
        columns = experiment.CONDITION_COLUMNS[condition]
        indexes = [experiment.C1_COLUMNS.index(name) for name in columns]
        assert projected["record_columns"] == list(columns)
        assert projected["records"] == [
            [record[index] for index in indexes] for record in c1["records"]
        ]
        experiment.validate_projection(projected, condition=condition)
    assert c1 == before

    altered = replace(
        case,
        question="LEAK SENTINEL",
        options={"A": "x", "B": "y", "C": "z", "D": "q"},
        correct_choice="A",
    )
    for condition in experiment.CONDITIONS:
        original_representation = experiment._case_payload(case, condition)[
            "representation"
        ]
        altered_representation = experiment._case_payload(altered, condition)[
            "representation"
        ]
        assert original_representation == altered_representation


def test_preflight_freezes_equivalence_schedule_requests_cardinality_and_cost():
    payload, cases, calls, preflight = _preflight()

    assert len(cases) == 20
    assert len(payload["batches"]) == 6
    assert len(calls) == 384
    assert preflight["replication_count"] == 8
    assert preflight["maximum_physical_generation_calls"] == 384
    assert preflight["condition_schedule_sha256"] == (
        "9b411628e56d291a26b5a0e44bca54577484957b26adc945f38199fabce596cd"
    )
    assert preflight["request_plan_sha256"] == (
        "29706dd5d1361f0bdf66a48b58cd00c453850740f740046c169847069a5e6640"
    )
    assert preflight["c1_prior_byte_equivalence"] is True
    assert preflight["kas_prior_c2_byte_equivalence"] is True
    assert preflight["equivalence_exclusions"] == []
    assert preflight["prior_c2_minus_c1_vector"] == [-17, -17, -17, -16, -17, -17]
    assert preflight["solver_config"]["max_output_tokens"] == 2048
    assert preflight["intentional_solver_difference_from_sealed_v1_3"] == {
        "field": "max_output_tokens",
        "sealed_v1_3": 4096,
        "experiment_2": 2048,
        "reason": "explicit Experiment-2 protocol requirement",
    }
    assert preflight["cost"]["request_utf8_bytes_input_token_upper_bound"] == 10_091_776
    assert preflight["cost"]["output_token_upper_bound"] == 384 * 2048
    assert preflight["cost"]["conservative_generation_cost_upper_bound_usd"] == pytest.approx(
        2.9620736
    )
    assert preflight["cost"]["authorized_cost_ceiling_usd"] == 100.0
    assert preflight["cost"]["conservative_generation_cost_upper_bound_usd"] < 100

    for replication in range(1, 9):
        selected = [call for call in calls if call.replication == replication]
        assert len(selected) == 48
        for batch_id in range(1, 7):
            assert tuple(
                call.condition for call in selected if call.batch_id == batch_id
            ) == experiment.CONDITION_SCHEDULE[replication - 1]
        for condition in experiment.CONDITIONS:
            condition_calls = [call for call in selected if call.condition == condition]
            assert [call.batch_id for call in condition_calls] == [1, 2, 3, 4, 5, 6]
            assert sum(len(call.case_ids) for call in condition_calls) == 20
    for position in range(8):
        assert {
            experiment.CONDITION_SCHEDULE[row][position] for row in range(8)
        } == set(experiment.CONDITIONS)

    assert all(
        call.text_format["schema"]["properties"]["answers"]["minItems"]
        == len(call.case_ids)
        == call.text_format["schema"]["properties"]["answers"]["maxItems"]
        for call in calls
    )


def test_c1_and_kas_prompts_are_byte_identical_to_prior_c1_and_c2():
    _, _, calls, _ = _preflight()
    prior = experiment._prior_prompt_map(REPO_ROOT)
    for call in calls:
        if call.condition == "C1":
            assert call.prompt == prior[("C1", call.batch_id)]
        elif call.condition == "KAS-":
            assert call.prompt == prior[("C2", call.batch_id)]


def test_strict_schema_and_parser_have_no_condition_specific_path():
    assert tuple(inspect.signature(luna_v1.parse_structured_labels).parameters) == (
        "raw",
        "expected_count",
    )
    for label in ("A", "B", "C", "D", "INSUFFICIENT"):
        raw = json.dumps({"answers": [label] * 3}, separators=(",", ":"))
        assert luna_v1.parse_structured_labels(raw, 3) == (label, label, label)
    for invalid in (
        '{"answers":["A","B"]}',
        '{"answers":["A","B","C","D"]}',
        '{"answers":["A","B","C","D","A"]}',
        '```json\n{"answers":["A","B","C"]}\n```',
        '{"answers":["Ari","B","C"]}',
        '{"answers":["D|INSUFFICIENT","B","C"]}',
    ):
        with pytest.raises(grading.ConstrainedInterfaceFailure):
            luna_v1.parse_structured_labels(invalid, 3)


def test_frozen_statistics_holm_and_disposition_precedence():
    sign_flip = experiment.exact_two_sided_sign_flip([-1] * 8)
    assert sign_flip["permutations"] == 256
    assert sign_flip["p_value"] == 2 / 256

    adjusted = experiment.holm_adjust(
        {
            "H_KIND": {"p_value": 2 / 256},
            "H_AUTHORITY": {"p_value": 1.0},
            "H_STATUS": {"p_value": 0.5},
        }
    )
    assert adjusted["H_KIND"]["holm_adjusted_p_value"] == 6 / 256
    assert adjusted["H_KIND"]["holm_reject_at_0_05"] is True

    same_behavior = experiment.exact_kas_replication_permutation(
        [-17, -17, -17, -16, -17, -17, -17, -17]
    )
    assert same_behavior["allocations"] == 3003
    assert same_behavior["replication_failure"] is False
    drifted_behavior = experiment.exact_kas_replication_permutation([0] * 8)
    assert drifted_behavior["replication_failure"] is True

    no_effect = {name: _stat(1.0, 0) for name in experiment.PRIMARY_COMPARISONS}
    no_interaction = {name: _stat(1.0, 0) for name in experiment.SECONDARY_INTERACTIONS}
    stable_kas = {"p_value": 1.0}
    baseline = experiment._classify(
        totals={"C1": 143},
        primary={"H_KIND": _stat(0.001, -2), **{name: no_effect[name] for name in ("H_AUTHORITY", "H_STATUS")}},
        interactions=no_interaction,
        kas_replication={"p_value": 0.001},
    )
    assert baseline["result_code"] == "VALID_BASELINE_DRIFT"
    kas_failure = experiment._classify(
        totals={"C1": 144},
        primary=no_effect,
        interactions=no_interaction,
        kas_replication={"p_value": 0.01},
    )
    assert kas_failure["result_code"] == "VALID_KAS_REPLICATION_FAILURE"
    one_field = experiment._classify(
        totals={"C1": 160},
        primary={"H_KIND": _stat(0.01, -1), **{name: no_effect[name] for name in ("H_AUTHORITY", "H_STATUS")}},
        interactions=no_interaction,
        kas_replication=stable_kas,
    )
    assert one_field["result_code"] == "VALID_SUPPORTED_KIND_LOAD_BEARING"
    distributed = experiment._classify(
        totals={"C1": 160},
        primary={
            "H_KIND": _stat(0.01, -1),
            "H_AUTHORITY": _stat(0.01, -2),
            "H_STATUS": _stat(1.0, 0),
        },
        interactions=no_interaction,
        kas_replication=stable_kas,
    )
    assert distributed["result_code"] == "VALID_SUPPORTED_DISTRIBUTED_BUNDLE"
    interaction = experiment._classify(
        totals={"C1": 160},
        primary=no_effect,
        interactions={"I_KA": _stat(0.01, -2), **{name: no_interaction[name] for name in ("I_KS", "I_AS", "I_KAS")}},
        kas_replication=stable_kas,
    )
    assert interaction["result_code"] == "VALID_SUPPORTED_MULTIFIELD_INTERACTION"
    null = experiment._classify(
        totals={"C1": 160},
        primary=no_effect,
        interactions=no_interaction,
        kas_replication=stable_kas,
    )
    assert null["result_code"] == "VALID_NO_SINGLE_FIELD_EFFECT"
    assert null["no_detected_single_effect_is_equivalence"] is False


def test_full_384_call_fake_run_seals_and_independently_verifies(tmp_path):
    _, cases = _cases()
    fake = FakeCompletionLuna(cases)
    run_dir = tmp_path / "complete"
    result = experiment.SemanticDecompositionRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()

    assert result["validity"] == "VALID"
    assert result["result_code"] == "VALID_KAS_REPLICATION_FAILURE"
    assert len(fake.calls) == 384
    assert all(result["conditions"][condition]["exact_correct"] == 160 for condition in experiment.CONDITIONS)
    assert all(
        result["usage"]["by_condition"][condition]["physical_generation_calls"] == 48
        for condition in experiment.CONDITIONS
    )
    assert {call["max_output_tokens"] for call in fake.calls} == {2048}
    verified = experiment.verify_run(run_dir)
    assert verified["physical_generation_calls"] == 384
    assert verified["unique_response_ids"] == 384
    assert verified["decision_artifacts"] == 384
    assert verified["returned_service_tiers"] == ["default"]


def test_valid_verifier_rejects_a_zero_physical_attempt_artifact(tmp_path):
    _, cases = _cases()
    run_dir = tmp_path / "zero-attempt"
    experiment.SemanticDecompositionRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=FakeCompletionLuna(cases),
        require_committed=False,
    ).run()

    call_path = run_dir / "calls/call_000001.json"
    call = json.loads(call_path.read_text(encoding="utf-8"))
    call.pop("payload_sha256")
    call["transport_metadata"]["physical_attempts"] = 0
    call_path.write_text(
        luna_v1._pretty_json(luna_v1._sealed(call)), encoding="utf-8", newline="\n"
    )
    index_path = run_dir / "EVIDENCE_INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index.pop("payload_sha256")
    row = next(row for row in index["files"] if row["path"] == "calls/call_000001.json")
    row["bytes"] = call_path.stat().st_size
    row["sha256"] = luna_v1._sha256_bytes(call_path.read_bytes())
    index["total_bytes"] = sum(row["bytes"] for row in index["files"])
    index_path.write_text(
        luna_v1._pretty_json(luna_v1._sealed(index)), encoding="utf-8", newline="\n"
    )
    _refresh_call_finished_event(run_dir, "calls/call_000001.json")

    with pytest.raises(luna_v1.ApparatusFailure, match="physical_attempts"):
        experiment.verify_run(run_dir)


def test_verifier_regrades_and_rejects_forged_stored_score_fields(
    verifier_tamper_run,
):
    run_dir = verifier_tamper_run
    relative = "decisions/decision_000001.json"
    path = run_dir / relative
    index_path = run_dir / "EVIDENCE_INDEX.json"
    original_decision = path.read_bytes()
    original_index = index_path.read_bytes()
    for field, value in (
        ("answer_correct", False),
        ("illegal_state_promotions", 1),
        ("failure_reasons", ["forged_failure"]),
    ):
        decision = json.loads(original_decision.decode("utf-8"))
        decision["scores"][0][field] = value
        _rewrite_indexed_json(run_dir, relative, decision)
        try:
            with pytest.raises(
                luna_v1.ApparatusFailure,
                match="independent deterministic regrading",
            ):
                experiment.verify_run(run_dir)
        finally:
            path.write_bytes(original_decision)
            index_path.write_bytes(original_index)
    assert experiment.verify_run(run_dir)["physical_generation_calls"] == 384


def test_verifier_rejects_decision_label_that_differs_from_raw_response(
    verifier_tamper_run,
):
    run_dir = verifier_tamper_run
    relative = "decisions/decision_000001.json"
    path = run_dir / relative
    index_path = run_dir / "EVIDENCE_INDEX.json"
    original_decision = path.read_bytes()
    original_index = index_path.read_bytes()
    decision = json.loads(original_decision.decode("utf-8"))
    decision["labels"][0] = (
        "A" if decision["labels"][0] != "A" else "B"
    )
    _rewrite_indexed_json(run_dir, relative, decision)
    try:
        with pytest.raises(luna_v1.ApparatusFailure, match="reparsed raw labels"):
            experiment.verify_run(run_dir)
    finally:
        path.write_bytes(original_decision)
        index_path.write_bytes(original_index)
    assert experiment.verify_run(run_dir)["physical_generation_calls"] == 384


def test_verifier_rejects_stored_score_case_order_drift(verifier_tamper_run):
    run_dir = verifier_tamper_run
    relative = "decisions/decision_000001.json"
    path = run_dir / relative
    index_path = run_dir / "EVIDENCE_INDEX.json"
    original_decision = path.read_bytes()
    original_index = index_path.read_bytes()
    decision = json.loads(original_decision.decode("utf-8"))
    decision["scores"][0], decision["scores"][1] = (
        decision["scores"][1],
        decision["scores"][0],
    )
    _rewrite_indexed_json(run_dir, relative, decision)
    try:
        with pytest.raises(luna_v1.ApparatusFailure, match="case IDs/order"):
            experiment.verify_run(run_dir)
    finally:
        path.write_bytes(original_decision)
        index_path.write_bytes(original_index)
    assert experiment.verify_run(run_dir)["physical_generation_calls"] == 384


def test_verifier_rejects_oracle_prompt_injection_with_stale_request_hash(
    verifier_tamper_run,
):
    run_dir = verifier_tamper_run
    relative = "calls/call_000001.json"
    path = run_dir / relative
    index_path = run_dir / "EVIDENCE_INDEX.json"
    original_call = path.read_bytes()
    original_index = index_path.read_bytes()
    call = json.loads(original_call.decode("utf-8"))
    call["request"]["prompt"] += "\nORACLE ANSWER: A\n"
    _rewrite_indexed_json(run_dir, relative, call)
    try:
        with pytest.raises(luna_v1.ApparatusFailure, match="request differs"):
            experiment.verify_run(run_dir)
    finally:
        path.write_bytes(original_call)
        index_path.write_bytes(original_index)
    assert experiment.verify_run(run_dir)["physical_generation_calls"] == 384


def test_verifier_rejects_raw_response_and_stale_event_bindings(
    verifier_tamper_run,
):
    run_dir = verifier_tamper_run
    call_relative = "calls/call_000001.json"
    decision_relative = "decisions/decision_000001.json"
    call_path = run_dir / call_relative
    decision_path = run_dir / decision_relative
    events_path = run_dir / "events.jsonl"
    index_path = run_dir / "EVIDENCE_INDEX.json"
    original_call = call_path.read_bytes()
    original_decision = decision_path.read_bytes()
    original_events = events_path.read_bytes()
    original_index = index_path.read_bytes()

    call = json.loads(original_call.decode("utf-8"))
    call["response"]["raw_text"] += " "
    _rewrite_indexed_json(run_dir, call_relative, call)
    try:
        with pytest.raises(luna_v1.ApparatusFailure, match="raw response SHA"):
            experiment.verify_run(run_dir)
    finally:
        call_path.write_bytes(original_call)
        index_path.write_bytes(original_index)

    call = json.loads(original_call.decode("utf-8"))
    call["response"]["raw_text"] += " "
    changed_response_sha = luna_v1._sha256_text(call["response"]["raw_text"])
    call["response"]["sha256"] = changed_response_sha
    _rewrite_indexed_json(run_dir, call_relative, call)
    decision = json.loads(original_decision.decode("utf-8"))
    decision["response_sha256"] = changed_response_sha
    _rewrite_indexed_json(run_dir, decision_relative, decision)
    try:
        with pytest.raises(luna_v1.ApparatusFailure, match="call_finished"):
            experiment.verify_run(run_dir)
    finally:
        call_path.write_bytes(original_call)
        decision_path.write_bytes(original_decision)
        events_path.write_bytes(original_events)
        index_path.write_bytes(original_index)

    events = [json.loads(line) for line in original_events.decode("utf-8").splitlines()]
    events[0]["prompt_sha256"] = "0" * 64
    _rewrite_indexed_text(
        run_dir,
        "events.jsonl",
        "".join(luna_v1._canonical_json(event) + "\n" for event in events),
    )
    try:
        with pytest.raises(luna_v1.ApparatusFailure, match="call_started"):
            experiment.verify_run(run_dir)
    finally:
        events_path.write_bytes(original_events)
        index_path.write_bytes(original_index)
    assert experiment.verify_run(run_dir)["physical_generation_calls"] == 384


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("returned_model", None),
        ("returned_model", "gpt-5.6-luna-forged"),
        ("returned_service_tier", None),
        ("returned_service_tier", "priority"),
        ("sdk_max_retries", 1),
        ("provider_fallback", True),
        ("cached_input_tokens", 1),
        ("cache_write_input_tokens", 1),
        ("provider", "ollama"),
        ("response_status", "incomplete"),
        ("incomplete_details", {"reason": "max_output_tokens"}),
        ("adapter_status", "rejected"),
        ("max_attempts", 2),
        ("tool_permissions", ["web"]),
        ("store", True),
        ("truncation", "auto"),
        ("reasoning_context", "previous_turn"),
        ("previous_response_id", "resp_prior"),
    ),
)
def test_verifier_replays_full_valid_metadata_contract(
    verifier_tamper_run, field, value
):
    run_dir = verifier_tamper_run
    relative = "calls/call_000001.json"
    path = run_dir / relative
    events_path = run_dir / "events.jsonl"
    index_path = run_dir / "EVIDENCE_INDEX.json"
    original_call = path.read_bytes()
    original_events = events_path.read_bytes()
    original_index = index_path.read_bytes()
    call = json.loads(original_call.decode("utf-8"))
    call["transport_metadata"][field] = value
    _rewrite_indexed_json(run_dir, relative, call)
    _refresh_call_finished_event(run_dir, relative)
    try:
        with pytest.raises(luna_v1.ApparatusFailure):
            experiment.verify_run(run_dir)
    finally:
        path.write_bytes(original_call)
        events_path.write_bytes(original_events)
        index_path.write_bytes(original_index)
    assert experiment.verify_run(run_dir)["physical_generation_calls"] == 384


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("status", "transport_error"),
        ("transport_error", {"type": "RuntimeError", "message": "forged"}),
        ("admission_error", {"type": "ApparatusFailure", "message": "forged"}),
    ),
)
def test_valid_verifier_rejects_noncompleted_or_error_call_envelopes(
    verifier_tamper_run, field, value
):
    run_dir = verifier_tamper_run
    relative = "calls/call_000001.json"
    path = run_dir / relative
    events_path = run_dir / "events.jsonl"
    index_path = run_dir / "EVIDENCE_INDEX.json"
    original_call = path.read_bytes()
    original_events = events_path.read_bytes()
    original_index = index_path.read_bytes()
    call = json.loads(original_call.decode("utf-8"))
    call[field] = value
    _rewrite_indexed_json(run_dir, relative, call)
    _refresh_call_finished_event(run_dir, relative)
    try:
        with pytest.raises(luna_v1.ApparatusFailure, match="valid call envelope"):
            experiment.verify_run(run_dir)
    finally:
        path.write_bytes(original_call)
        events_path.write_bytes(original_events)
        index_path.write_bytes(original_index)
    assert experiment.verify_run(run_dir)["physical_generation_calls"] == 384


def test_response_reuse_and_service_tier_drift_fail_closed_without_retry(tmp_path):
    _, cases = _cases()
    duplicate = DuplicateResponseLuna(cases)
    duplicate_dir = tmp_path / "duplicate"
    result = experiment.SemanticDecompositionRunner(
        repo_root=REPO_ROOT,
        output_dir=duplicate_dir,
        ask_fn=duplicate,
        require_committed=False,
    ).run()
    assert result["validity"] == "INVALID"
    assert result["result_code"] == "INVALID_APPARATUS"
    assert result["failed_sequence"] == 2
    assert len(duplicate.calls) == 2
    assert experiment.verify_run(duplicate_dir)["physical_generation_calls"] == 2

    drift = ServiceTierDriftLuna(cases)
    drift_dir = tmp_path / "tier-drift"
    result = experiment.SemanticDecompositionRunner(
        repo_root=REPO_ROOT,
        output_dir=drift_dir,
        ask_fn=drift,
        require_committed=False,
    ).run()
    assert result["validity"] == "INVALID"
    assert result["failed_sequence"] == 2
    assert len(drift.calls) == 2
    assert experiment.verify_run(drift_dir)["physical_generation_calls"] == 2


def test_existing_directory_and_noncanonical_live_path_are_rejected(tmp_path):
    _, cases = _cases()
    fake = FakeCompletionLuna(cases)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(luna_v1.ApparatusFailure, match="already exists"):
        experiment.SemanticDecompositionRunner(
            repo_root=REPO_ROOT,
            output_dir=existing,
            ask_fn=fake,
            require_committed=False,
        ).run()
    assert fake.calls == []
    with pytest.raises(luna_v1.ApparatusFailure, match="locked"):
        experiment.SemanticDecompositionRunner(
            repo_root=REPO_ROOT,
            output_dir=tmp_path / "alternate-live",
            ask_fn=fake,
            require_committed=True,
        ).run()
    assert fake.calls == []


def test_transport_error_is_redacted_preserved_and_never_retried(tmp_path, monkeypatch):
    secret = "sk-experiment-two-secret-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    _, cases = _cases()
    fake = SecretFailureLuna(cases)
    run_dir = tmp_path / "secret-failure"
    result = experiment.SemanticDecompositionRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()

    assert result["validity"] == "INVALID"
    assert len(fake.calls) == 1
    assert secret not in json.dumps(result)
    assert all(secret not in path.read_text(encoding="utf-8") for path in run_dir.rglob("*") if path.is_file())
    verified = experiment.verify_run(run_dir)
    assert verified["call_artifacts"] == 1
