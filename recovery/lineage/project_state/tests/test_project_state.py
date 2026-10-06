from __future__ import annotations

import hashlib
import json

import pytest

from hive_reference.project_state import ProjectStateError, load_project, main, render_text


def _record(rid, value, *, time=1, recorded=None, source="report", excerpt=None, **extra):
    return dict(id=rid, subject="repair", predicate="status", value=value,
                effective_time=time, recorded_at=recorded or time,
                basis="observed", truth="accepted", authority="canonical",
                source=source, excerpt=excerpt or value, **extra)


def _manifest(tmp_path, records, *, text="blocked\nimplemented\ncompleted\nfailed\n", source_time=0):
    document = tmp_path / "report.md"
    document.write_text(text, encoding="utf-8")
    data = dict(schema_version=1, project="Example", sources=[dict(
        id="report", path="report.md", recorded_at=source_time,
        sha256=hashlib.sha256(document.read_bytes()).hexdigest(),
    )], records=records)
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_supersession_changes_current_state_and_preserves_earlier_knowledge(tmp_path):
    path = _manifest(tmp_path, [
        _record("old", "blocked"),
        _record("new", "implemented", time=2, recorded=3, supersedes=["old"]),
    ])
    ledger = load_project(path)
    assert ledger.view()["current"][0]["value"] == "implemented"
    assert ledger.view()["other_records"][0]["status"] == "superseded"
    earlier = ledger.view(known_at=1)
    assert earlier["current"][0]["value"] == "blocked"
    assert earlier["other_records"] == []
    assert "implemented" not in json.dumps(earlier)
    historical = ledger.view(valid_at=1, known_at=3)
    assert historical["current"][0]["value"] == "blocked"
    assert historical["other_records"][0]["status"] == "future"
    evidence = ledger.view()["current"][0]["evidence"]
    assert evidence["line"] == 2
    assert evidence["excerpt"] == "implemented"


@pytest.mark.parametrize("basis", ["planned", "proposed", "predicted"])
def test_intention_does_not_complete_or_supersede_work(tmp_path, basis):
    plan = _record("plan", "completed", time=2, supersedes=["old"])
    plan["basis"] = basis
    path = _manifest(tmp_path, [_record("old", "blocked"), plan])
    view = load_project(path).view()
    assert view["current"][0]["value"] == "blocked"
    assert view["other_records"][0]["status"] == "not_applied"
    assert view["other_records"][0]["reason"] == "non_promotable_basis"


def test_conflicting_simultaneous_observations_are_unknown(tmp_path):
    path = _manifest(tmp_path, [
        _record("one", "completed", time=1, recorded=1),
        _record("two", "failed", time=1, recorded=2),
    ])
    view = load_project(path).view()
    assert view["current"] == []
    assert view["conflicts"] == [dict(subject="repair", predicate="status", claim_ids=["one", "two"])]
    assert "UNKNOWN" in render_text(view)


def test_later_record_needs_explicit_supersession(tmp_path):
    path = _manifest(tmp_path, [_record("old", "blocked"), _record("new", "completed", time=2)])
    view = load_project(path).view()
    assert view["current"][0]["id"] == "old"
    assert view["other_records"][0]["reason"] == "unlicensed_supersession"


def test_external_report_cannot_override_canonical_record(tmp_path):
    external = _record("external", "completed", time=2, supersedes=["old"])
    external["authority"] = "external"
    path = _manifest(tmp_path, [_record("old", "blocked"), external])
    view = load_project(path).view()
    assert view["current"][0]["value"] == "blocked"
    assert view["other_records"][0]["reason"] == "observed_claim_not_canonical"


def test_changed_source_aborts_without_emitting_old_state(tmp_path, capsys):
    path = _manifest(tmp_path, [_record("old", "blocked")])
    (tmp_path / "report.md").write_text("completed\n", encoding="utf-8")
    assert main([str(path), "--format", "json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "source hash mismatch" in captured.err


def test_nonexistent_evidence_excerpt_is_rejected(tmp_path):
    path = _manifest(tmp_path, [_record("bad", "invented")])
    with pytest.raises(ProjectStateError, match="excerpt not found"):
        load_project(path)


def test_source_cannot_be_known_after_claim(tmp_path):
    path = _manifest(tmp_path, [_record("early", "blocked")], source_time=2)
    with pytest.raises(ValueError, match="evidence cannot be recorded after"):
        load_project(path)


def test_source_path_cannot_escape_package(tmp_path):
    path = _manifest(tmp_path, [_record("old", "blocked")])
    data = json.loads(path.read_text())
    data["sources"][0]["path"] = "../outside.md"
    path.write_text(json.dumps(data))
    with pytest.raises(ProjectStateError, match="beneath"):
        load_project(path)


def test_duplicate_json_keys_are_rejected(tmp_path):
    path = _manifest(tmp_path, [])
    path.write_text('{"schema_version": 1, "schema_version": 2}')
    with pytest.raises(ProjectStateError, match="duplicate JSON key"):
        load_project(path)


@pytest.mark.parametrize("time", [True, -1, 1.5])
def test_invalid_record_times_are_rejected(tmp_path, time):
    record = _record("old", "blocked")
    record["recorded_at"] = time
    path = _manifest(tmp_path, [record])
    with pytest.raises(ProjectStateError, match="nonnegative integer"):
        load_project(path)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_values_are_rejected(tmp_path, value):
    record = _record("bad", value, excerpt="blocked")
    path = _manifest(tmp_path, [record])
    with pytest.raises(ProjectStateError, match="non-finite"):
        load_project(path)


def test_record_order_does_not_change_state_or_digest(tmp_path):
    old = _record("old", "blocked")
    new = _record("new", "completed", time=2, supersedes=["old"])
    path = _manifest(tmp_path, [old, new])
    expected = load_project(path).view()
    data = json.loads(path.read_text())
    data["records"].reverse()
    path.write_text(json.dumps(data))
    assert load_project(path).view() == expected


def test_cli_outputs_json_with_evidence_and_no_model(tmp_path, capsys):
    path = _manifest(tmp_path, [_record("old", "blocked")])
    assert main([str(path), "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["scope"] == "operator_curated_documented_state"
    assert result["current"][0]["evidence"]["excerpt"] == "blocked"


def test_expired_claim_is_not_reported_current(tmp_path):
    path = _manifest(tmp_path, [_record("old", "blocked", valid_to=2)])
    view = load_project(path).view(valid_at=2)
    assert view["current"] == []
    assert view["other_records"][0]["status"] == "expired"
