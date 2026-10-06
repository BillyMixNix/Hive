"""Local apparatus checks only; never contact Agents or execute a benchmark."""

import json
from pathlib import Path

import executor
import make_freeze
from control_request import build_direct_request
from direct_context import MAX_REQUEST_FIELD_CHARS


def _groups():
    replication = make_freeze.group(
        "replication", make_freeze.HISTORICAL, "TASKS.md", "frozen-tests", "T")
    novel = make_freeze.group(
        "novel", make_freeze.HERE, "NOVEL-TASKS.md", "novel-frozen-tests", "N")
    return replication, novel


def test_both_preregistered_groups_have_distinct_frozen_tests():
    replication, novel = _groups()
    ids = [task["id"] for group in (replication, novel) for task in group["tasks"]]
    assert ids == [f"T{i:03d}" for i in range(1, 9)] + [f"N{i:03d}" for i in range(1, 9)]
    tests = [task["baseline_test_path"] for group in (replication, novel)
             for task in group["tasks"]]
    assert len(set(tests)) == len(tests)
    assert sorted(task["expected_cases"] for task in replication["tasks"]) == [1] * 7 + [2]
    assert all(task["expected_cases"] == 1 for task in novel["tasks"])


def test_all_frozen_task_inputs_fit_local_provider_field_bound_without_test_leakage():
    old = json.loads((make_freeze.HISTORICAL / "FREEZE-v2.json").read_text(encoding="utf-8"))
    baseline = Path(old["baseline"]["root"])
    replication, novel = _groups()
    groups = (replication, novel)
    forbidden = [task["baseline_test_path"] for group in groups for task in group["tasks"]]
    for group in groups:
        for task in group["tasks"]:
            body, manifest = build_direct_request(
                baseline, task["request"], model="gpt-6-astra", frozen_test_paths=forbidden)
            field = body["input"][0]["content"][0]["text"]
            assert len(field) <= MAX_REQUEST_FIELD_CHARS < 1_048_576
            assert task["request"] in field
            assert manifest["request_field_chars"] == len(field)
            assert all(row["path"].casefold() not in {path.casefold() for path in forbidden}
                       for row in manifest["files"] if row["included_sections"])


def test_every_control_file_and_historical_result_is_checked_before_a_pair(tmp_path, monkeypatch):
    challenge = tmp_path / "HIVE-ASTRA-002"
    history = tmp_path / "HIVE-ASTRA-001"
    challenge.mkdir()
    (history / "execution-v2").mkdir(parents=True)
    control = challenge / "control.py"
    raw = history / "execution-v2" / "raw_results.json"
    events = history / "execution-v2" / "events.ndjson"
    control.write_text("original", encoding="utf-8")
    raw.write_text("[]", encoding="utf-8")
    events.write_text("event\n", encoding="utf-8")
    frozen = {
        "control_apparatus": {"files": {"control.py": executor.sha(control.read_bytes())}},
        "relationship_to_001": {
            "raw_results_sha256": executor.sha(raw.read_bytes()),
            "event_log_sha256": executor.sha(events.read_bytes()),
        },
    }
    monkeypatch.setattr(executor, "CHALLENGE", challenge)
    monkeypatch.setattr(executor, "HISTORICAL", history)
    assert executor.apparatus_manifest_ok(frozen)
    control.write_text("modified", encoding="utf-8")
    assert not executor.apparatus_manifest_ok(frozen)
    control.write_text("original", encoding="utf-8")
    raw.write_text("[{}]", encoding="utf-8")
    assert not executor.apparatus_manifest_ok(frozen)
