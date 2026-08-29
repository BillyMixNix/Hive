import json

from hive_compressor.coding_agent import adapt_coding_session


def test_latest_human_message_stays_verbatim_even_when_interpreted():
    text = "Checkout is done. Start the OAuth work."
    result = adapt_coding_session([
        {
            "id": "m1",
            "kind": "human_message",
            "text": text,
            "directives": [
                {
                    "kind": "task",
                    "status": "active",
                    "confidence": 0.99,
                    "effects": {"op": "set", "path": "task.current", "value": "oauth_migration"},
                }
            ],
        }
    ])

    assert result["model_context"]["verbatim_sources"][0]["text"] == text
    assert result["model_context"]["compressed_state"][0]["authority"] == "user_instruction"
    assert text not in json.dumps(result["model_context"]["compressed_state"])
    assert result["fallback"]["required"] is False


def test_uninterpreted_human_message_fails_open_to_verbatim_source_not_lossy_summary():
    text = "I guess OAuth might be worth considering eventually, but don't worry about it."
    result = adapt_coding_session([
        {"id": "m1", "kind": "human_message", "text": text},
        {"id": "t1", "kind": "test_run", "suite": "pytest", "passed": 12, "failed": 0},
    ])

    assert result["fallback"]["required"] is True
    assert "source:m1" in result["fallback"]["source_refs"]
    assert any(item["text"] == text for item in result["model_context"]["verbatim_sources"])
    assert all(text not in json.dumps(record) for record in result["model_context"]["compressed_state"])


def test_low_confidence_directive_does_not_become_machine_truth():
    text = "Maybe change auth later."
    result = adapt_coding_session([
        {
            "id": "m1",
            "kind": "human_message",
            "text": text,
            "directives": [
                {
                    "kind": "plan",
                    "status": "planned",
                    "confidence": 0.55,
                    "effects": {"op": "set", "path": "auth.plan", "value": "oauth"},
                }
            ],
        }
    ], min_confidence=0.9)

    assert result["model_context"]["compressed_state"] == []
    assert result["fallback"]["required"] is True
    assert result["fallback"]["reasons"]["source:m1"] == "human_source_not_fully_interpreted"


def test_machine_events_turn_into_compact_operational_state_with_lineage():
    result = adapt_coding_session([
        {"id": "call-1", "kind": "tool_call", "tool": "pytest", "target": "tests/test_checkout.py"},
        {"id": "test-1", "kind": "test_run", "suite": "checkout", "passed": 18, "failed": 0, "skipped": 1},
        {"id": "file-1", "kind": "file_change", "path": "checkout.py", "change": "modified"},
    ])

    records = result["model_context"]["compressed_state"]
    assert [r["kind"] for r in records] == ["action", "test", "change"]
    assert result["lineage"]["state:test-1:1"] == ["source:test-1"]
    assert result["fallback"]["required"] is False


def test_unknown_machine_event_is_kept_as_fallback_evidence():
    event = {"id": "x1", "kind": "mystery_telemetry", "payload": {"x": 1}}
    result = adapt_coding_session([event])

    assert result["model_context"]["compressed_state"] == []
    assert result["fallback"]["required"] is True
    source = result["model_context"]["verbatim_sources"][0]
    assert source["source_type"] == "machine_event"
    assert json.loads(source["text"]) == event


def test_large_tool_output_is_not_embedded_in_compressed_state():
    huge = "trace line\n" * 5000
    result = adapt_coding_session([
        {
            "id": "tool-1",
            "kind": "tool_result",
            "tool": "pytest",
            "ok": True,
            "output": huge,
            "state_effects": {"op": "test_complete", "passed": 954, "failed": 0},
        }
    ])

    state_text = json.dumps(result["model_context"]["compressed_state"])
    assert huge not in state_text
    assert result["source_evidence"][0]["text"].find("trace line") >= 0
    assert result["shadow"]["hive_model_context_bytes"] < result["shadow"]["raw_history_bytes"]


def test_historical_interpreted_human_message_can_leave_repeated_context_but_remains_recoverable():
    old_text = "Do not touch auth until checkout passes."
    new_text = "Checkout passes. Continue."
    result = adapt_coding_session([
        {
            "id": "m1",
            "kind": "human_message",
            "text": old_text,
            "directives": [
                {
                    "kind": "constraint",
                    "confidence": 1.0,
                    "effects": {"op": "set", "path": "auth.change_allowed", "value": False},
                }
            ],
        },
        {
            "id": "m2",
            "kind": "human_message",
            "text": new_text,
            "directives": [
                {
                    "kind": "instruction",
                    "confidence": 1.0,
                    "effects": {"op": "set", "path": "work.continue", "value": True},
                }
            ],
        },
    ])

    model_texts = [item["text"] for item in result["model_context"]["verbatim_sources"]]
    assert new_text in model_texts
    assert old_text not in model_texts
    evidence_texts = [item["text"] for item in result["source_evidence"]]
    assert old_text in evidence_texts
