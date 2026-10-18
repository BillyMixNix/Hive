import json
from pathlib import Path

import pytest

from kingdom import decompression_frontier_luna as v1
from kingdom import decompression_frontier_luna_v1_1 as repair
from kingdom import decompression_test as worlds


REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = REPO_ROOT / "benchmarks/decompression_test/CASE_PACK.json"


def _cases():
    payload, cases = worlds.load_case_pack(CASE_PATH)
    worlds.validate_case_pack(payload, cases)
    return payload, cases


class FakeCompletionLuna:
    def __init__(self, cases, *, budget_calls=(), network_failure_call=None):
        self.by_case = {case.case_id: case for case in cases}
        self.budget_calls = set(budget_calls)
        self.network_failure_call = network_failure_call
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
        payload = v1._input_payload(prompt)
        case_ids = [item["case_id"] for item in payload["cases"]]
        self.calls.append(
            {
                "number": number,
                "case_ids": case_ids,
                "condition": payload["representation_family"],
                "max_output_tokens": solver_config.max_output_tokens,
            }
        )
        input_tokens = max(1, len(prompt.encode("utf-8")) // 4)
        metadata.clear()
        metadata.update(solver_config.to_mapping())
        metadata.update(
            {
                "configuration_hash": solver_config.configuration_hash,
                "requested_model": solver_config.model,
                "returned_model": "gpt-5.6-luna-test-snapshot",
                "returned_service_tier": "default",
                "response_id": f"resp_{number:03d}",
                "physical_attempts": 1,
                "latency_seconds": 0.01,
                "input_tokens": input_tokens,
                "cached_input_tokens": 0,
                "cache_write_input_tokens": 0,
                "sdk_version": v1.EXPECTED_OPENAI_SDK,
                "response_error": None,
                "openai_text_format": openai_text_format,
                "openai_text_format_sha256": v1._sha256_text(
                    v1._canonical_json(openai_text_format)
                ),
            }
        )
        if number == self.network_failure_call:
            metadata.update(
                {
                    "adapter_status": "transport_error",
                    "response_status": None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "reasoning_tokens": None,
                    "total_tokens": None,
                    "incomplete_details": None,
                }
            )
            raise RuntimeError("synthetic network failure")
        if number in self.budget_calls:
            partial = json.dumps(
                {"answers": ["A"] * len(case_ids)}, separators=(",", ":")
            )
            metadata.update(
                {
                    "adapter_status": "rejected",
                    "response_status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "partial_output_text": partial,
                    "output_tokens": solver_config.max_output_tokens,
                    "reasoning_tokens": solver_config.max_output_tokens,
                    "total_tokens": input_tokens + solver_config.max_output_tokens,
                    "error_type": "OpenAIResponseRejected",
                    "error_message": "response status is incomplete",
                }
            )
            raise RuntimeError("OpenAI response rejected: max_output_tokens")
        labels = [self.by_case[case_id].correct_choice for case_id in case_ids]
        response = json.dumps({"answers": labels}, separators=(",", ":"))
        metadata.update(
            {
                "adapter_status": "completed",
                "response_status": "completed",
                "incomplete_details": None,
                "partial_output_text": response,
                "output_tokens": 12,
                "reasoning_tokens": 8,
                "total_tokens": input_tokens + 12,
            }
        )
        return response


def test_preflight_changes_only_matched_output_allowance_and_protocol_binding():
    original = {
        "protocol_id": v1.PROTOCOL_ID,
        "max_output_tokens": v1.MAX_OUTPUT_TOKENS,
        "source_files": v1.SOURCE_FILES,
        "audit_store": v1.OpenAIAuditStore,
    }
    _, _, old_calls, old_preflight = v1.deterministic_preflight(
        REPO_ROOT, require_committed=False
    )
    _, _, calls, preflight = repair.deterministic_preflight(
        REPO_ROOT, require_committed=False
    )
    assert [call.prompt for call in calls] == [call.prompt for call in old_calls]
    assert [call.case_ids for call in calls] == [call.case_ids for call in old_calls]
    assert [call.condition for call in calls] == [call.condition for call in old_calls]
    assert [call.text_format for call in calls] == [call.text_format for call in old_calls]
    assert preflight["protocol_id"] == repair.PROTOCOL_ID
    assert preflight["schema_version"] == 2
    assert preflight["solver_config"]["max_output_tokens"] == 4096
    assert old_preflight["solver_config"]["max_output_tokens"] == 2048
    assert preflight["cost"]["output_token_upper_bound"] == 24 * 4096
    assert preflight["cost"][
        "conservative_generation_cost_upper_bound_usd"
    ] == pytest.approx(0.2865348)
    assert v1.PROTOCOL_ID == original["protocol_id"]
    assert v1.MAX_OUTPUT_TOKENS == original["max_output_tokens"]
    assert v1.SOURCE_FILES == original["source_files"]
    assert v1.OpenAIAuditStore is original["audit_store"]


def test_budget_exhaustion_is_scored_without_salvage_and_run_completes(tmp_path):
    _, cases = _cases()
    fake = FakeCompletionLuna(cases, budget_calls={17})
    run_dir = tmp_path / "complete"
    result = repair.CompletionRunner(
        repo_root=REPO_ROOT,
        output_dir=run_dir,
        ask_fn=fake,
        require_committed=False,
    ).run()

    assert result["validity"] == "VALID"
    assert result["result_code"] == "VALID_FRONTIER_BOUNDARY_C1"
    assert len(fake.calls) == 24
    assert {call["max_output_tokens"] for call in fake.calls} == {4096}
    assert result["raw"]["exact_correct"] == 20
    assert result["frontier"]["C0"]["exact_correct"] == 20
    assert result["frontier"]["C1"]["exact_correct"] == 20
    assert result["frontier"]["C2"]["exact_correct"] == 17
    assert result["frontier"]["C2"]["solver_budget_exhaustions"] == 3
    call = json.loads((run_dir / "calls/call_000017.json").read_text(encoding="utf-8"))
    decision = json.loads(
        (run_dir / "decisions/decision_000017.json").read_text(encoding="utf-8")
    )
    assert call["status"] == "solver_budget_exhausted"
    assert call["response"]["raw_text"] is None
    assert call["transport_metadata"]["partial_output_text"] == json.dumps(
        {"answers": ["A"] * 3}, separators=(",", ":")
    )
    assert decision["status"] == "solver_budget_exhausted"
    assert decision["partial_output_salvaged"] is False
    assert decision["grader_status"] == "not_run"
    assert decision["grader_agreement"] is None
    assert all(score["answer_correct"] is False for score in decision["scores"])
    assert all(score["illegal_state_promotions"] is None for score in decision["scores"])
    assert repair.verify_run(run_dir)["physical_generation_calls"] == 24


def test_raw_budget_failure_finishes_gate_but_does_not_run_frontier(tmp_path):
    _, cases = _cases()
    fake = FakeCompletionLuna(cases, budget_calls={1})
    result = repair.CompletionRunner(
        repo_root=REPO_ROOT,
        output_dir=tmp_path / "raw-budget",
        ask_fn=fake,
        require_committed=False,
    ).run()
    assert result["validity"] == "VALID"
    assert result["result_code"] == "VALID_RAW_CAPABILITY_FAIL"
    assert result["raw"]["solver_budget_exhaustions"] == 4
    assert len(fake.calls) == 6
    assert result["frontier"] == "NOT_RUN"


def test_non_budget_transport_failure_remains_invalid_and_stops(tmp_path):
    _, cases = _cases()
    fake = FakeCompletionLuna(cases, network_failure_call=17)
    result = repair.CompletionRunner(
        repo_root=REPO_ROOT,
        output_dir=tmp_path / "network-fail",
        ask_fn=fake,
        require_committed=False,
    ).run()
    assert result["validity"] == "INVALID"
    assert result["result_code"] == "INVALID_APPARATUS"
    assert len(fake.calls) == 17
    assert repair.verify_run(tmp_path / "network-fail")["physical_generation_calls"] == 17
