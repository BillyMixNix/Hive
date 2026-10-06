from pathlib import Path

from control_request import build_direct_request


def test_direct_payload_is_one_bounded_persistent_session_turn_without_hive(tmp_path: Path):
    source = tmp_path / "src/main/java/demo/Widget.java"
    source.parent.mkdir(parents=True)
    source.write_text("public class Widget {}\n", encoding="utf-8")
    task = "Add Widget.label()"
    body, manifest = build_direct_request(tmp_path, task, model="gpt-6-astra")
    assert body["environment"] == {"type": "none"}
    assert body["agent"]["multi_agent"] == {"enabled": False}
    assert "tools" not in body and "tool_choice" not in body
    assert len(body["input"]) == 1
    assert len(body["input"][0]["content"]) == 1
    assert body["input"][0]["content"][0]["type"] == "input_text"
    assert task in body["input"][0]["content"][0]["text"]
    assert manifest["request_fields"]["input[0].content[0].text"] < 400_001
