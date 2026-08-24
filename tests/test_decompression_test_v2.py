from __future__ import annotations

import inspect
import importlib.util
import json
from pathlib import Path

import pytest

import hive_llm
import kingdom.decompression_test as v1
import kingdom.decompression_test_v2 as v2


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "decompression_test" / "CASE_PACK.json"


@pytest.fixture(scope="module")
def pack():
    return v1.load_case_pack(PACK)


@pytest.mark.parametrize("value", v2.LABELS)
def test_all_five_exact_primary_values_pass(value):
    assert v2.parse_primary_value(value) == value
    assert v2.parse_primary_value(f" \t{value}\r\n") == value


@pytest.mark.parametrize(
    "value",
    [
        "```json\nA\n```",
        "Ari",
        "D|INSUFFICIENT",
        '"A"',
        "A trailing",
        "a",
        "\\u0041",
        "\ufeffA",
        "",
    ],
)
def test_every_non_exact_primary_value_fails(value):
    with pytest.raises(v2.ConstrainedInterfaceFailure):
        v2.parse_primary_value(value)


def test_batch_wrapper_accepts_only_literal_values_and_expected_length():
    assert v2.parse_batch('["A", "B",\n"INSUFFICIENT"]', 3) == (
        "A",
        "B",
        "INSUFFICIENT",
    )
    invalid = [
        '```json\n["A","B","C"]\n```',
        '["Ari","B","C"]',
        '["D|INSUFFICIENT","B","C"]',
        '["\\u0041","B","C"]',
        '["A","B"]',
        '["A","B","C","D"]',
        '["A","B","C","D","A"]',
        '{"answers":["A","B","C"]}',
        '["A","B","C"] trailing',
    ]
    for value in invalid:
        with pytest.raises(v2.ConstrainedInterfaceFailure):
            v2.parse_batch(value, 3)


def test_three_case_schema_and_parser_reject_every_wrong_cardinality():
    assert "condition" not in inspect.signature(v2.parse_batch).parameters
    assert "condition" not in inspect.signature(v2.output_schema).parameters
    schema = v2.output_schema(3)
    assert schema["items"]["enum"] == list(v2.LABELS)
    assert schema["minItems"] == schema["maxItems"] == 3
    for count in (2, 4, 5):
        raw = json.dumps(["A"] * count, separators=(",", ":"))
        with pytest.raises(v2.ConstrainedInterfaceFailure):
            v2.parse_batch(raw, 3)
    for _condition in (*v2.CONDITIONS, "compressed_ablation"):
        assert v2.parse_batch('["A","B","C"]', 3) == ("A", "B", "C")


def test_exact_cardinality_schema_supports_only_frozen_batch_sizes():
    for count in (3, 4, 5):
        schema = v2.output_schema(count)
        assert schema["minItems"] == schema["maxItems"] == count
        assert schema["items"] == {
            "type": "string",
            "enum": list(v2.LABELS),
        }
    for invalid in (2, 6, True, 3.0):
        with pytest.raises(ValueError):
            v2.output_schema(invalid)


def test_hive_transport_sends_native_ollama_format(monkeypatch):
    observed = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": '["A","B","C"]',
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 10,
                "eval_count": 7,
                "total_duration": 1,
            }

    def post(url, *, json, timeout):
        observed.update({"url": url, "payload": json, "timeout": timeout})
        return Response()

    spec = importlib.util.spec_from_file_location(
        "hive_llm_decompression_v2_adapter", Path(hive_llm.__file__)
    )
    assert spec is not None and spec.loader is not None
    live_adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(live_adapter)
    monkeypatch.setattr(live_adapter.requests, "post", post)
    metadata = {}
    result = live_adapter.ask_model(
        "prompt",
        model=v2.MODEL,
        timeout=900,
        options={
            "num_ctx": 32768,
            "num_predict": 2048,
            "temperature": 0.0,
            "seed": 73021,
        },
        max_retries=1,
        metadata=metadata,
        response_format=v2.output_schema(3),
    )
    assert result == '["A","B","C"]'
    assert observed["payload"]["format"] == v2.output_schema(3)
    assert metadata["response_format"] == v2.output_schema(3)


def test_primary_correctness_is_independent_of_secondary_metadata(pack):
    _, cases = pack
    case = cases[0]

    def broken_secondary(_case, _label):
        raise RuntimeError("secondary failed")

    score = v2.grade_label(
        case,
        case.correct_choice,
        condition="compressed",
        secondary_fn=broken_secondary,
    )
    assert score.answer_correct is True
    assert score.grader_status == "ran"
    assert score.grader_agreement is True
    assert score.secondary_status == "failed"
    assert score.chronology_authority_error is None
    assert score.illegal_state_promotions is None


def test_not_run_graders_report_null_not_agreement(pack):
    _, cases = pack
    score = v2.rejected_score(cases[0], "raw")
    assert score.grader_status == "not_run"
    assert score.grader_agreement is None
    assert score.answer_correct is None


def test_chronology_authority_and_promotion_derive_from_selected_option(pack):
    _, cases = pack
    case = cases[0]
    labels = {
        claim.truth_class: label
        for label, statement in case.options.items()
        for claim in case.claims
        if claim.statement == statement
    }
    assert v2.grade_label(
        case, labels["current"], condition="raw"
    ).illegal_state_promotions == 0
    for truth, status in (
        ("historical", "historical_state_selected"),
        ("planned", "planned_state_selected"),
        ("hallucinated", "unsupported_state_selected"),
    ):
        score = v2.grade_label(case, labels[truth], condition="raw")
        assert score.chronology_authority_status == status
        assert score.chronology_authority_error is True
        assert score.illegal_state_promotions == 1


def test_v2_changes_only_prompt_output_contract_not_frozen_inputs(pack):
    payload, cases = pack
    by_case = {case.case_id: case for case in cases}
    for batch in payload["batches"]:
        selected = [by_case[case_id] for case_id in batch["case_ids"]]
        for condition in v2.CONDITIONS:
            assert v2._input_part(v2.build_solver_prompt(selected, condition)) == (
                v2._input_part(v1.build_solver_prompt(selected, condition))
            )
    assert "ordered_event_refs" not in v2.SOLVER_PROMPT_PREFIX
    assert '"reasoning_code"' not in v2.SOLVER_PROMPT_PREFIX
    for code in v1.REASONING_CODES:
        assert code in v2.SOLVER_PROMPT_PREFIX
    assert (
        v2._sha256_text(v2.SOLVER_PROMPT_PREFIX)
        == "fcc8159eb6901aa3d8f1a95531ef007efb4d7a877b76ad01a949609cb88cf058"
    )


class PerfectAsk:
    def __init__(self, pack, invalid_condition=None):
        payload, cases = pack
        self.by_case = {case.case_id: case for case in cases}
        self.aliases = {
            v1._ablation_alias(case_id, role): (self.by_case[case_id], role)
            for case_id in payload["ablation"]["essential_case_ids"]
            for role in ("essential", "control")
        }
        self.invalid_condition = invalid_condition
        self.calls = []

    def __call__(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        metadata = kwargs["metadata"]
        payload = json.loads(v2._input_part(prompt))
        expected_schema = v2.output_schema(len(payload["cases"]))
        assert kwargs["response_format"] == expected_schema
        metadata.update(
            {
                "physical_attempts": 1,
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": max(1, len(prompt) // 4),
                "eval_count": 8,
                "total_duration_ns": 1,
                "response_format": expected_schema,
            }
        )
        condition = payload["condition_representation"]
        if condition == self.invalid_condition:
            return "```json\n[]\n```"
        labels = []
        for item in payload["cases"]:
            if condition == "compressed_ablation":
                case, role = self.aliases[item["case_id"]]
                labels.append("INSUFFICIENT" if role == "essential" else case.correct_choice)
            else:
                labels.append(self.by_case[item["case_id"]].correct_choice)
        return json.dumps(labels, separators=(",", ":"))


def _runner(tmp_path, pack, ask):
    payload, cases = pack
    return v2.DecompressionV2Runner(
        repo_root=ROOT,
        output_dir=tmp_path / "smoke-v2",
        case_pack_payload=payload,
        cases=cases,
        source_revision="a" * 40,
        source_file_sha256={"fixture": "b" * 64},
        model_digest=v2.MODEL_DIGEST,
        v1_seal={
            "source_commit": v2.FROZEN_V1_COMMIT,
            "result": "VALID / NOT_SUPPORTED",
            "file_count": 47,
            "total_bytes": v2.FROZEN_V1_TOTAL_BYTES,
            "inventory_sha256": v2.FROZEN_V1_INVENTORY_SHA256,
        },
        v2_seal={
            "source_commit": v2.FROZEN_V2_COMMIT,
            "result": "INVALID / INCONCLUSIVE_INVALID_SMOKE",
            "file_count": v2.FROZEN_V2_FILE_COUNT,
            "total_bytes": v2.FROZEN_V2_TOTAL_BYTES,
            "inventory_sha256": v2.FROZEN_V2_INVENTORY_SHA256,
            "result_file_sha256": v2.FROZEN_V2_RESULT_SHA256,
            "solver_prompt_template_sha256": v2._sha256_text(
                v2.SOLVER_PROMPT_PREFIX
            ),
        },
        ask_fn=ask,
    )


def test_minimal_full_fake_run_preserves_20_calls_and_grades_70_values(tmp_path, pack):
    ask = PerfectAsk(pack)
    result = _runner(tmp_path, pack, ask).run()
    assert len(ask.calls) == 20
    assert result["validity"] == "VALID"
    assert result["hypothesis_result"] == "SUPPORTED"
    assert len(result["case_scores"]) == 60
    assert len(result["ablation"]["scores"]) == 10
    assert result["condition_summaries"]["compressed"]["exact_correct"] == 20
    assert result["ablation"]["essential_detected"] == 5
    assert result["ablation"]["control_passes"] == 5
    observed_by_batch = {}
    for prompt, kwargs in ask.calls:
        payload = json.loads(v2._input_part(prompt))
        count = len(payload["cases"])
        schema = kwargs["response_format"]
        assert schema == v2.output_schema(count)
        if payload["condition_representation"] != "compressed_ablation":
            key = tuple(item["case_id"] for item in payload["cases"])
            observed_by_batch.setdefault(key, []).append(schema)
    assert len(observed_by_batch) == 6
    assert all(
        len(schemas) == 3 and all(schema == schemas[0] for schema in schemas)
        for schemas in observed_by_batch.values()
    )


def test_constrained_failure_is_invalid_and_does_not_claim_grader_agreement(tmp_path, pack):
    ask = PerfectAsk(pack, invalid_condition="retrieval")
    result = _runner(tmp_path, pack, ask).run()
    output = tmp_path / "smoke-v2"
    status = json.loads((output / "RUN_STATUS.json").read_text(encoding="utf-8"))
    decision = json.loads((output / "decisions" / "decision_000002.json").read_text(encoding="utf-8"))
    assert len(ask.calls) == 20
    assert result["validity"] == "INVALID"
    assert status["validity"] == "INVALID"
    assert status["call_count"] == 20
    assert decision["grader_status"] == "not_run"
    assert decision["grader_agreement"] is None
    assert result["condition_summaries"]["retrieval"]["parser_failures"] == 20


def test_local_sealed_v1_inventory_is_still_exact():
    run = ROOT / ".hive" / "benchmarks" / "decompression_test" / "smoke-v1-001"
    if not run.exists():
        pytest.skip("sealed local v1 evidence is not present")
    seal = v2.verify_v1_artifacts(run)
    assert seal["source_commit"] == v2.FROZEN_V1_COMMIT
    assert seal["inventory_sha256"] == v2.FROZEN_V1_INVENTORY_SHA256


def test_local_sealed_v2_inventory_is_still_exact():
    run = ROOT / ".hive" / "benchmarks" / "decompression_test" / "smoke-v2-001"
    if not run.exists():
        pytest.skip("sealed local v2 evidence is not present")
    seal = v2.verify_v2_artifacts(run)
    assert seal["source_commit"] == v2.FROZEN_V2_COMMIT
    assert seal["result"] == "INVALID / INCONCLUSIVE_INVALID_SMOKE"
    assert seal["inventory_sha256"] == v2.FROZEN_V2_INVENTORY_SHA256
