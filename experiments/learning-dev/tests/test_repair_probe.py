"""Probe evaluator checks using scripted adapters, never model requests."""
from pathlib import Path
import json

import pytest

from hive_learning.repair_probe import run_probe


@pytest.mark.parametrize("behavior,verdict", [("repair", "REPAIR_VERIFIED"),
    ("claim_only", "REPAIR_NOT_VERIFIED"), ("alter_tests", "INVALID")])
def test_probe_requires_an_actual_source_repair_and_unchanged_tests(tmp_path, behavior, verdict):
    class ScriptedFixture:
        def work(self, root, goal, lessons, calls, *, acceptance_oracle):
            assert not lessons and calls == 36
            assert not (root / "test_protected.py").exists()
            if behavior == "repair":
                (root / "capacity.py").write_text("def admit(quantity, capacity):\n    return quantity <= capacity\n")
                assert acceptance_oracle(root) is True
            elif behavior == "alter_tests":
                (root / "test_visible.py").write_text("def test_fake():\n    assert True\n")
            return {"calls": 1, "prompt_tokens": 0, "output_tokens": 0}, {"decision": "SATISFIED"}
        def observed_usage(self):
            return [{"calls": 1, "prompt_tokens": 0, "output_tokens": 0, "complete": True}]
    path = Path(__file__).resolve().parents[1] / "examples/repair-probe.json"
    report = run_probe(ScriptedFixture(), tmp_path / "work", path)
    assert report["before"]["valid"] and not report["before"]["passed"]
    assert report["acceptance_checks"][0]["passed"] is False
    assert report["verdict"] == verdict and report["promotion_eligible"] is False
    if behavior == "repair":
        assert report["after"]["passed"] and report["source_changed"]


def test_real_controller_reaches_completion_with_observed_actions_and_required_checker(tmp_path):
    from hive_learning.adapter import OllamaHive

    # Replay the action sequence actually observed in continuation 5 through the
    # unchanged controller. Only controller-generated IDs are substituted.
    traces = Path(__file__).resolve().parents[1] / "results/2026-09-08-cont5/responses"
    captured = []
    for path in sorted(traces.glob("*.json")):
        response = json.loads(path.read_text())["response"]
        for item in response["output"]:
            if item["type"] == "function_call":
                action = json.loads(item["arguments"])
                captured.append({"name": action["name"], "arguments": json.loads(action["arguments_json"])})

    class RecordedMeter:
        failed = False
        def __init__(self):
            self.usage = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0}
        def __call__(self, messages, **kwargs):
            index = self.usage["calls"]
            assert index < len(captured), "recorded sequence did not satisfy controller gates"
            action = json.loads(json.dumps(captured[index]))
            packet = json.loads(next(m["content"] for m in messages if m["role"] == "user"))
            if action["name"] == "submit_location":
                action["arguments"] = {"callable_id": packet["locked_callable_id"],
                                       "choice_id": packet["source_line_choices"][0]["choice_id"]}
            elif action["name"] == "confirm_candidate":
                action["arguments"]["candidate_location_id"] = packet["candidate_source_location"]["location_id"]
            elif action["name"] == "submit_mechanism":
                action["arguments"]["location_id"] = packet["accepted_source_location"]["location_id"]
            self.usage["calls"] += 1
            return json.dumps(action)

    class RecordedHive(OllamaHive):
        def _new_meter(self, *args, **kwargs):
            meter = RecordedMeter()
            self.meters.append(meter)
            return meter

    path = Path(__file__).resolve().parents[1] / "examples/repair-probe.json"
    report = run_probe(RecordedHive("recorded-actions-not-a-model"), tmp_path / "work", path)
    assert report["verdict"] == "REPAIR_VERIFIED", report
    assert report["controller"]["decision"] == "SATISFIED"
    assert report["controller"]["task_state"]["acceptance_oracle_pass"] is True
    assert report["usage"]["calls"] == 9
