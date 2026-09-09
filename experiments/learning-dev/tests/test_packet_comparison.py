import json
from pathlib import Path
import pytest
from analysis import packet_comparison as runner
from analysis.packet_audit import audit


def test_schedule_complete_deterministic():
    study = {"cases": [{"id": str(i)} for i in range(15)]}
    rows = runner.schedule(study)
    assert rows == runner.schedule(study) and len(rows) == 45
    assert len({(r["case_id"], r["arm"]) for r in rows}) == 45
    for i in range(0, 45, 3):
        assert len({r["case_id"] for r in rows[i:i+3]}) == 1


def test_schedule_rejects_duplicate_cases():
    with pytest.raises(ValueError): runner.schedule({"cases": [{"id": "same"}]*15})


def test_commitment_tamper(tmp_path):
    path = tmp_path/"plan.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="commitment"): runner.check(path, "0"*64)


def test_expired_guard_stops_before_key_loading(tmp_path, monkeypatch):
    plan = tmp_path/"plan.json"
    plan.write_text("{}")
    monkeypatch.setattr(runner, "check", lambda *a: ({}, {}))
    def expired(*a, **k):
        raise ValueError("expired pricing")
    monkeypatch.setattr(runner, "SpendingGuard", expired)
    monkeypatch.setattr(runner, "load_api_key", lambda: pytest.fail("must not load a key"))
    result = runner.run(plan, runner.sha(plan), tmp_path/"run")
    assert result["status"] == "INCOMPLETE" and result["spending"] is None
    with pytest.raises(FileExistsError): runner.run(plan, runner.sha(plan), tmp_path/"second")


def test_audit_detects_artifact_tampering(tmp_path):
    (tmp_path/"report.json").write_text("{}")
    (tmp_path/"checksums.json").write_text(json.dumps({"report.json": "0"*64}))
    with pytest.raises(ValueError, match="bytes"): audit(tmp_path, "0"*64)


def test_audit_detects_extra_artifacts(tmp_path):
    (tmp_path/"extra").write_text("unlisted")
    (tmp_path/"checksums.json").write_text("{}")
    with pytest.raises(ValueError, match="inventory"): audit(tmp_path, "0"*64)


def test_audit_rescores_and_rejects_wrong_charge(tmp_path, monkeypatch):
    from analysis import packet_audit as auditor
    from analysis.state_packet import compile_packet
    from analysis.indexed_checkpoint import indexed_tools
    from hive_learning.ledger import digest
    root = tmp_path/"source"
    (root/"examples").mkdir(parents=True)
    monkeypatch.setattr(auditor, "ROOT", root)
    case = {"id": "fixture", "goal": "Return one", "files": {"subject.py": "def f(): return 1\n"},
            "protected_tests": {"test_private.py": "from subject import f\ndef test_f(): assert f() == 1\n"}, "acceptance_tests": {}}
    study = root/"examples/contract-rerun.json"
    study.write_text(json.dumps({"cases": [case], "lessons": []}))
    output = tmp_path/"evidence"
    output.mkdir()
    def save(name, value):
        path = output/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    plan = {"study_sha256": runner.sha(study), "schedule": [{"case_id": "fixture", "arm": "packet"}], "model": "offline"}
    save("plan.json", plan)
    snapshot = {"objective": case["goal"], "files": case["files"], "constraints": [],
        "allowed_actions": ["submit_mechanism"], "events": [], "uncertainties": [], "verification": ["test"]}
    packet = compile_packet(snapshot)
    task = {"authority": {"allowed_tools": ["submit_mechanism"]},
        "tool_contracts": [{"name": "submit_mechanism", "arguments": {"location_id": "id", "mechanism": "text"}}],
        "hive_state_context": json.dumps(packet)}
    messages = [{"role": "user", "content": json.dumps(task)}]
    tools = indexed_tools(messages)
    record = {"condition": "packet", "packet": packet, "snapshot_sha256": packet["snapshot_sha256"],
        "output_messages_sha256": auditor.packet_digest(messages), "tools_sha256": auditor.packet_digest(tools)}
    save("transport/fixture-packet/packets.jsonl", record)
    save("transport/fixture-packet/responses/response-0001.json", {"request": {"input": messages, "tools": tools},
        "response": {"model": "offline", "service_tier": "default", "usage": {"input_tokens": 10, "output_tokens": 2}}})
    result = {"candidate": case["files"], "candidate_sha256": digest(case["files"]), "passed": True,
        "guidance_sha256": digest([]), "controller": {"decision": "SATISFIED"},
        "usage": {"calls": 1, "prompt_tokens": 10, "output_tokens": 2}}
    save("recipients/fixture-packet/result.json", result)
    cost = 10*auditor.INPUT_NUSD + 2*auditor.OUTPUT_NUSD
    spending = {"prior_upper_nano_usd": 0, "total_upper_nano_usd": cost,
        "measured_usage_upper_nano_usd": cost, "unresolved_reservation_nano_usd": 0, "requests_reserved": 1}
    report = {"status": "COMPLETED", "rows": [{"case_id": "fixture", "arm": "packet", "result": result}], "spending": spending}
    save("report.json", report)
    save("spending.jsonl", spending)
    def seal():
        save("checksums.json", {p.relative_to(output).as_posix(): runner.sha(p)
            for p in output.rglob("*") if p.is_file() and p.name != "checksums.json"})
    seal()
    assert audit(output, runner.sha(output/"plan.json"))["totals"]["packet"]["correct"] == 1
    spending["measured_usage_upper_nano_usd"] += 1
    save("report.json", report)
    seal()
    with pytest.raises(ValueError, match="charge"): audit(output, runner.sha(output/"plan.json"))
