import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

import pytest

from research.recursive_improvement.experiment3.cases import build_cases
from research.recursive_improvement.experiment3.run import (
    RepairTransport, public_feedback, score_plans,
)


HERE = Path(__file__).parent / "experiment3"
ORIGINAL = 'import json\nclass PlannerAgent:\n    def _extract_json_object(self, raw_response):\n        return raw_response\n    def other(self):\n        return 7\n'
PLAN = {"target_file": "planner.py", "target_symbol": "_extract_json_object",
        "objective": "extract_first_json_object", "approach": "Parse JSON and extract the first valid object."}
CODE = {"method_source": 'def _extract_json_object(self, raw_response):\n    return "{}"\n'}


def response(data):
    return io.BytesIO(json.dumps({"done": True, "done_reason": "stop", "response": json.dumps(data),
                                 "prompt_eval_count": 10, "eval_count": 5}).encode())


def test_fresh_cases_are_frozen_distinct_and_fit_the_input_envelope():
    built = build_cases()
    for name, cases in zip(("public_cases.json", "heldout_cases.json", "plan_cases.json"), built):
        assert json.loads((HERE / name).read_text()) == cases
        assert len({c["input"] for c in cases}) == len(cases)
        assert len(json.dumps({"inputs": [{"id": c["id"], "input": c["input"]} for c in cases]}).encode()) < 65536
    public, heldout, plans = built
    assert (len(public), len(heldout), len(plans)) == (14, 96, 8)
    previous = set()
    for study in ("experiment1", "experiment2"):
        for name in ("public_cases.json", "heldout_cases.json"):
            previous.update(c["input"] for c in json.loads((HERE.parent / study / name).read_text()))
    assert not previous.intersection(c["input"] for group in built for c in group)
    assert not {c["input"] for c in public}.intersection(c["input"] for c in heldout)


def test_public_feedback_drops_untrusted_grades_and_unrelated_fields():
    feedback = public_feedback({"valid": True, "scores": [{"case_id": "public", "correct": False,
        "response": {"error": "ValueError", "expected_secret": "never include", "grade": 1}}]})
    assert feedback["outcomes"][0]["returned"] == {"error": "ValueError"}
    assert "never include" not in json.dumps(feedback)


def test_transport_runs_only_one_plan_and_two_coder_requests_and_records_feedback():
    protocol = json.loads((HERE / "protocol.json").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "seed"; output.mkdir()
        calls = []
        transport = RepairTransport(protocol, 4242, ORIGINAL, [{"id": "public", "input": "{}", "expected": {}}], output, calls)
        with patch("urllib.request.urlopen", side_effect=[response(PLAN), response(CODE), response(CODE)]) as network:
            with pytest.raises(RuntimeError):
                transport("denied", role="coder")
            transport("original plan", role="planner")
            transport("original first code", role="coder")
            transport.feedback = {"public_case": "failed public marker"}
            transport("original retry", role="coder")
            for role in ("planner", "coder", "other"):
                with pytest.raises(RuntimeError):
                    transport("denied", role=role)
            assert network.call_count == 3
        assert [c["seed"] for c in calls] == [4242, 4242, 104242]
        assert "failed public marker" not in (output / "1-coder-actual-prompt.txt").read_text()
        assert "failed public marker" in (output / "2-coder-actual-prompt.txt").read_text()
        assert (output.parent / "all-model-calls.json").exists()
        assert len(transport.patches) == 2  # Parsed as data, never executed.


def test_global_request_cap_denies_network():
    protocol = json.loads((HERE / "protocol.json").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        transport = RepairTransport(protocol, 4242, ORIGINAL, [], Path(tmp), [{} for _ in range(9)])
        with patch("urllib.request.urlopen") as network:
            with pytest.raises(RuntimeError):
                transport("denied", role="planner")
            network.assert_not_called()


def test_planning_oracle_rejects_fallbacks_spoofed_correctness_and_duplicate_ids():
    cases = [{"id": "one", "expected_goal": "wanted"}]
    plan = {"source": "llm", "status": "planned", "goal": "wanted",
            "tasks": [{"target_file": "planner.py", "target_symbol": "_extract_json_object",
                       "change_intent": "modify_existing_logic"}]}
    assert score_plans(cases, [{"id": "one", "plan": plan}])[0]["correct"]
    for change in ({"source": "narrow_fallback"}, {"goal": "wrong"}, {"tasks": []}):
        assert not score_plans(cases, [{"id": "one", "plan": {**plan, **change}, "correct": True}])[0]["correct"]
    with pytest.raises(ValueError):
        score_plans(cases, [{"id": "one", "plan": plan}, {"id": "one", "plan": plan}])


def test_clean_frozen_planning_response_is_valid_for_trusted_baseline(monkeypatch):
    # Current checked-in planner.py is trusted and unchanged. No generated method
    # is imported or applied here. Subject variants use Docker only.
    import planner
    case = build_cases()[2][0]
    monkeypatch.setattr(planner, "ask_hive", lambda *args, **kwargs: case["input"])
    task = {"id": case["id"], "target_file": "planner.py", "target_symbol": "_extract_json_object",
            "task_type": "bugfix", "note": "Repair JSON extraction in planner.py.",
            "metadata": {"target_file": "planner.py", "target_symbol": "_extract_json_object"}}
    plan = planner.PlannerAgent().plan_task(task)
    assert score_plans([case], [{"id": case["id"], "plan": plan}])[0]["correct"]
