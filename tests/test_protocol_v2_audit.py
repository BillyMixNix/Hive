import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

import hive_llm

from kingdom.protocol_v2_audit import (
    AuditInvariantError,
    BudgetExceeded,
    ProtocolV2AuditStore,
)


MODEL_DIGEST = "d" * 64


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _artifact(audit: ProtocolV2AuditStore, sequence: int) -> dict:
    path = audit.calls_dir / f"call_{sequence:06d}.json"
    return json.loads(path.read_text(encoding="utf-8"))


class RecordingAsk:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        metadata = kwargs["metadata"]
        metadata.update(
            {
                "physical_attempts": 1,
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": 123,
                "eval_count": 456,
                "total_duration_ns": 789,
                "server": {"version": "fixture"},
            }
        )
        return self.responses.pop(0)


def _store(tmp_path: Path, ask, *, budget: int = 3) -> ProtocolV2AuditStore:
    return ProtocolV2AuditStore(
        ask,
        tmp_path / "evidence",
        model="qwen2.5-coder:7b",
        model_digest=MODEL_DIGEST,
        generation_calls_per_chapter=budget,
    )


def test_success_preserves_full_request_response_runtime_and_transport(tmp_path):
    prompt = "Full prompt\nwith Unicode: causality → obligation"
    response = "Raw response\n```json\n{\"exact\": true}\n```"
    ask = RecordingAsk([response])
    audit = _store(tmp_path, ask)

    returned = audit.ask(
        prompt,
        condition="baseline",
        chapter=2,
        purpose="chapter prose",
        role="writer",
        budget_class="generation",
    )

    assert returned == response
    assert ask.calls[0]["max_retries"] == 1
    assert ask.calls[0]["model"] == "qwen2.5-coder:7b"
    assert ask.calls[0]["timeout"] == 900
    assert ask.calls[0]["options"] == {
        "num_ctx": 32768,
        "num_predict": 2048,
        "temperature": 0.2,
        "seed": 42001,
    }

    artifact = _artifact(audit, 1)
    assert artifact["status"] == "completed"
    assert artifact["request"]["prompt"] == prompt
    assert artifact["response"]["text"] == response
    assert artifact["request"]["condition"] == "baseline"
    assert artifact["request"]["chapter"] == 2
    assert artifact["request"]["purpose"] == "chapter prose"
    assert artifact["request"]["role"] == "writer"
    assert artifact["request"]["budget_class"] == "generation"
    assert artifact["request"]["runtime"]["model_digest"] == MODEL_DIGEST
    assert artifact["transport"]["metadata"]["eval_count"] == 456
    assert artifact["request"]["prompt_sha256"] == hashlib.sha256(
        prompt.encode("utf-8")
    ).hexdigest()
    assert artifact["response"]["sha256"] == hashlib.sha256(
        response.encode("utf-8")
    ).hexdigest()
    assert artifact["timing"]["elapsed_ns"] >= 0

    events = _events(audit.events_path)
    assert [event["event"] for event in events] == ["call_started", "call_finished"]
    assert events[0]["request"]["prompt"] == prompt
    assert events[1]["artifact"] == "calls/call_000001.json"
    artifact_bytes = (audit.calls_dir / "call_000001.json").read_bytes()
    assert events[1]["artifact_file_sha256"] == hashlib.sha256(artifact_bytes).hexdigest()
    assert audit.generation_count("baseline", 2) == 1
    assert audit.last_call_id == "call_000001"
    assert audit.records[0].status == "completed"


def test_transport_failure_is_artifacted_and_journaled_before_reraise(tmp_path):
    def failing(prompt, *, metadata, **kwargs):
        metadata.update(
            {
                "physical_attempts": 1,
                "done": False,
                "done_reason": "transport_error",
                "socket": "closed by fixture",
            }
        )
        raise TimeoutError("fixture timed out exactly once")

    audit = _store(tmp_path, failing)
    with pytest.raises(TimeoutError, match="exactly once"):
        audit.ask(
            "state proposal prompt",
            condition="baseline",
            chapter=2,
            purpose="state proposal",
            role="extractor",
            budget_class="state",
        )

    artifact = _artifact(audit, 1)
    assert artifact["status"] == "transport_error"
    assert artifact["response"]["text"] == ""
    assert artifact["transport"]["error"]["message"] == (
        "fixture timed out exactly once"
    )
    assert "TimeoutError" in artifact["transport"]["error"]["traceback"]
    assert artifact["transport"]["metadata"]["socket"] == "closed by fixture"
    events = _events(audit.events_path)
    assert [event["event"] for event in events] == ["call_started", "call_finished"]
    assert events[-1]["status"] == "transport_error"
    assert audit.records[0].error_type.endswith("TimeoutError")
    assert audit.generation_count("baseline", 2) == 0


def test_hidden_retry_is_rejected_after_raw_response_is_preserved(tmp_path):
    raw_response = "response produced after an illicit retry"

    def retried(prompt, *, metadata, **kwargs):
        assert kwargs["max_retries"] == 1
        metadata.update(
            {"physical_attempts": 2, "done": True, "done_reason": "stop"}
        )
        return raw_response

    audit = _store(tmp_path, retried)
    with pytest.raises(AuditInvariantError, match="exactly one physical attempt"):
        audit.ask(
            "judge prompt",
            condition="shared",
            chapter=2,
            purpose="blind judge",
            role="reflector",
            budget_class="judge",
        )

    artifact = _artifact(audit, 1)
    assert artifact["status"] == "audit_invariant_error"
    assert artifact["response"]["text"] == raw_response
    assert artifact["transport"]["reported_physical_attempts"] == 2
    assert "exactly one" in artifact["audit_error"]["message"]
    assert _events(audit.events_path)[-1]["status"] == "audit_invariant_error"


@pytest.mark.parametrize(
    ("metadata", "message"),
    [
        ({"done": True, "done_reason": "stop"}, "reported None"),
        (
            {"physical_attempts": 1, "done": False, "done_reason": "stop"},
            "done=true",
        ),
        (
            {"physical_attempts": 1, "done": True, "done_reason": "length"},
            "truncated",
        ),
        (
            {
                "physical_attempts": 1,
                "done": True,
                "done_reason": None,
                "prompt_eval_count": 1,
                "eval_count": 1,
            },
            "done_reason='stop'",
        ),
    ],
)
def test_incomplete_transport_metadata_fails_closed_but_keeps_output(
    tmp_path, metadata, message
):
    def incomplete(prompt, **kwargs):
        kwargs["metadata"].update(metadata)
        return "raw output is evidence even though transport is invalid"

    audit = _store(tmp_path, incomplete)
    with pytest.raises(AuditInvariantError, match=message):
        audit.ask(
            "prompt",
            condition="kingdom",
            chapter=2,
            purpose="chapter prose",
        )
    assert _artifact(audit, 1)["response"]["text"].startswith("raw output")


@pytest.mark.parametrize(
    ("prompt_tokens", "output_tokens", "message"),
    [
        (None, 1, "prompt_eval_count"),
        (1, None, "eval_count"),
        (32768 - 2048, 1, "possible input truncation"),
        (1, 2049, "exceeded the frozen output-token limit"),
    ],
)
def test_token_metadata_fails_closed_on_missing_counts_or_context_risk(
    tmp_path, prompt_tokens, output_tokens, message
):
    def unsafe(prompt, *, metadata, **kwargs):
        metadata.update(
            {
                "physical_attempts": 1,
                "done": True,
                "done_reason": "stop",
                "prompt_eval_count": prompt_tokens,
                "eval_count": output_tokens,
            }
        )
        return "preserved output"

    audit = _store(tmp_path, unsafe)
    with pytest.raises(AuditInvariantError, match=message):
        audit.ask(
            "prompt",
            condition="baseline",
            chapter=2,
            purpose="token-boundary test",
            budget_class="evaluation",
        )
    assert _artifact(audit, 1)["response"]["text"] == "preserved output"


def test_live_adapter_preserves_missing_ollama_token_fields_as_missing(
    tmp_path, monkeypatch
):
    spec = importlib.util.spec_from_file_location(
        "hive_llm_protocol_v2_adapter", Path(hive_llm.__file__)
    )
    assert spec is not None and spec.loader is not None
    live_adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(live_adapter)

    class Response:
        status_code = 200

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "response": "raw adapter output",
                "done": True,
                "done_reason": "stop",
            }

    monkeypatch.setattr(
        live_adapter.requests, "post", lambda *args, **kwargs: Response()
    )
    audit = _store(tmp_path, live_adapter.ask_hive)

    with pytest.raises(AuditInvariantError, match="prompt_eval_count"):
        audit.ask(
            "adapter prompt",
            condition="baseline",
            chapter=2,
            purpose="adapter audit",
            budget_class="evaluation",
        )

    artifact = _artifact(audit, 1)
    assert artifact["response"]["text"] == "raw adapter output"
    assert artifact["transport"]["metadata"]["prompt_eval_count"] is None
    assert artifact["transport"]["metadata"]["eval_count"] is None


def test_generation_budget_is_per_condition_and_chapter(tmp_path):
    ask = RecordingAsk(["baseline", "kingdom", "later chapter"])
    audit = _store(tmp_path, ask, budget=1)

    audit.ask("p1", condition="baseline", chapter=2, purpose="draft")
    audit.ask("p2", condition="kingdom", chapter=2, purpose="draft")
    audit.ask("p3", condition="baseline", chapter=3, purpose="draft")
    with pytest.raises(BudgetExceeded, match="baseline chapter 2"):
        audit.ask("denied", condition="baseline", chapter=2, purpose="extra")

    assert len(ask.calls) == 3
    assert [record.call_id for record in audit.records] == [
        "call_000001",
        "call_000002",
        "call_000003",
    ]
    assert audit.generation_count("baseline", 2) == 1
    assert audit.generation_count("kingdom", 2) == 1
    assert audit.generation_count("baseline", 3) == 1


def test_failed_physical_generation_call_spends_budget_and_is_preserved(tmp_path):
    def failing(prompt, *, metadata, **kwargs):
        metadata.update(
            {
                "physical_attempts": 1,
                "done": False,
                "done_reason": "transport_error",
            }
        )
        raise TimeoutError("one failed generation request")

    audit = _store(tmp_path, failing, budget=1)
    with pytest.raises(TimeoutError, match="failed generation"):
        audit.ask(
            "failed",
            condition="baseline",
            chapter=2,
            purpose="draft",
            budget_class="generation",
        )
    with pytest.raises(BudgetExceeded, match="baseline chapter 2"):
        audit.ask(
            "retry forbidden",
            condition="baseline",
            chapter=2,
            purpose="draft retry",
            budget_class="generation",
        )

    assert audit.generation_count("baseline", 2) == 1
    assert len(audit.records) == 1
    assert _artifact(audit, 1)["status"] == "transport_error"


def test_generation_state_and_judge_responses_share_one_sequential_store(tmp_path):
    ask = RecordingAsk(["raw generation", "raw state JSON", "raw judge JSON"])
    audit = _store(tmp_path, ask)
    calls = [
        ("generation", "draft", "writer"),
        ("state", "state proposal", "extractor"),
        ("judge", "metric judge", "reflector"),
    ]
    for budget_class, purpose, role in calls:
        audit.ask(
            f"{purpose} prompt",
            condition="baseline" if budget_class != "judge" else "shared",
            chapter=2,
            purpose=purpose,
            role=role,
            budget_class=budget_class,
        )

    artifacts = [_artifact(audit, number) for number in range(1, 4)]
    assert [item["request"]["budget_class"] for item in artifacts] == [
        "generation",
        "state",
        "judge",
    ]
    assert [item["response"]["text"] for item in artifacts] == [
        "raw generation",
        "raw state JSON",
        "raw judge JSON",
    ]
    assert audit.manifest_index()["call_count"] == 3
    assert audit.manifest_index()["last_call_id"] == "call_000003"


def test_audit_directory_must_be_fresh_and_existing_evidence_is_untouched(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    sentinel = evidence / "frozen-v1.txt"
    sentinel.write_text("do not touch", encoding="utf-8")

    with pytest.raises(FileExistsError):
        ProtocolV2AuditStore(
            RecordingAsk(["unused"]),
            evidence,
            model="qwen2.5-coder:7b",
            model_digest=MODEL_DIGEST,
        )

    assert sentinel.read_text(encoding="utf-8") == "do not touch"
    assert sorted(path.name for path in evidence.iterdir()) == ["frozen-v1.txt"]


def test_config_is_frozen_at_creation_and_defensive_when_read(tmp_path):
    audit = _store(tmp_path, RecordingAsk(["unused"]))
    config = audit.frozen_config
    config["runtime"]["options"]["seed"] = -1

    assert audit.frozen_config["runtime"]["options"]["seed"] == 42001
    persisted = json.loads(audit.config_path.read_text(encoding="utf-8"))
    assert persisted["runtime"]["options"]["seed"] == 42001
    assert persisted["transport"]["authorized_physical_attempts_per_logical_call"] == 1
