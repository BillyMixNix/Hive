"""Exercise actual repair, review, final-acceptance and resume boundaries offline."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hive_orchestrator import Authority, HiveConfig, ReviewerAgent, TaskState
from hive_learning.evaluate import write_files
from analysis.contract_checked_hive import ContractCheckedExecutive, ContractCheckedHive
from analysis.lesson_checkpoint import ContextHiveExecutive
from analysis.public_contracts import InputPreservation, PublicContractGate

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT/"examples/input-preservation-regression.json").read_text())


def no_model(*args, **kwargs):
    raise AssertionError("offline regression must not request a model")


def setup_controller(root, *, revised=True, oracle=lambda workspace: True, candidate=None):
    root.mkdir()
    write_files(root, FIXTURE["public_files"])
    options = {"worker_chat": no_model, "judge_chat": no_model,
               "config": HiveConfig.atomic(call_budget=36, max_model_concurrency=1),
               "acceptance_oracle": oracle}
    if revised:
        options["public_contract_gate"] = PublicContractGate(
            FIXTURE["public_files"], [InputPreservation(**c) for c in FIXTURE["contracts"]])
    cls = ContractCheckedExecutive if revised else ContextHiveExecutive
    hive = cls(root, FIXTURE["goal"], [FIXTURE["goal"]], **options)
    hive.objective.task_state = TaskState(**deepcopy(FIXTURE["saved_task_state"]))
    write_files(root, candidate or FIXTURE["saved_bad_patches"][1]["candidate"])
    return hive


def test_actual_repair_gate_rejects_and_rolls_back_previously_green_patch(tmp_path):
    candidate = FIXTURE["saved_bad_patches"][1]["candidate"]
    run = SimpleNamespace(edited_files=[FIXTURE["contracts"][0]["source_file"]])
    original = setup_controller(tmp_path/"original", revised=False)
    assert original._verify_repair(candidate, run)[0] is True
    revised = setup_controller(tmp_path/"revised")
    with pytest.raises(ValueError, match="Public input contract failed"):
        revised._verify_repair(candidate, run)
    assert revised.objective.task_state.source_repaired is False
    assert revised.objective.task_state.acceptance_oracle_pass is False
    assert revised.objective.task_state.review_pass is False
    for path, content in FIXTURE["public_files"].items():
        assert (revised.root/path).read_text() == content
    assert revised.public_contract_reports[-1]["accepted"] is False


def test_reviewer_pass_cannot_override_failed_contract(tmp_path):
    candidate = FIXTURE["saved_bad_patches"][1]["candidate"]
    reviewer = ReviewerAgent()
    task = SimpleNamespace(authority=SimpleNamespace(write_scopes=[]), task_id="recorded-review")
    run = SimpleNamespace(edited_files=[])
    observations = [{"tool": "review_snapshot", "arguments": {}},
                    {"tool": "submit_review", "arguments": {"verdict": "PASS", "findings": []}}]
    old = setup_controller(tmp_path/"old", revised=False)
    reviewer.apply_gate(old, task, run, "COMPLETED", "", observations, candidate)
    assert old.objective.task_state.review_pass
    new = setup_controller(tmp_path/"new")
    with pytest.raises(ValueError, match="Public input contract failed"):
        reviewer.apply_gate(new, task, run, "COMPLETED", "", observations, candidate)
    assert new.objective.task_state.review_pass is False


def test_final_completion_rechecks_even_if_recorded_state_and_weak_oracle_pass(tmp_path):
    old = setup_controller(tmp_path/"old", revised=False)
    assert old.objective.task_state.complete
    assert old.validate_objective().accepted
    new = setup_controller(tmp_path/"new")
    assert new.objective.task_state.complete
    validation = new.validate_objective()
    assert validation.accepted is False
    assert new.objective.state != "SATISFIED"
    assert new.objective.task_state.acceptance_oracle_pass is False


def test_new_gate_keeps_existing_oracle_and_does_not_cache_across_edits(tmp_path):
    good = FIXTURE["reference"]
    hive = setup_controller(tmp_path/"blocked", oracle=lambda workspace: False, candidate=good)
    assert hive.acceptance_oracle(hive.root) is False
    hive = setup_controller(tmp_path/"changing", candidate=good)
    assert hive.acceptance_oracle(hive.root) is True
    first = hive.public_contract_reports[-1]["candidate_sha256"]
    write_files(hive.root, FIXTURE["saved_bad_patches"][1]["candidate"])
    assert hive.acceptance_oracle(hive.root) is False
    assert hive.public_contract_reports[-1]["candidate_sha256"] != first


def test_review_receives_public_requirements_and_resume_requires_same_policy(tmp_path):
    hive = setup_controller(tmp_path/"work")
    snapshot = hive._review_snapshot()
    assert FIXTURE["goal"] in snapshot and "preserve_argument_values" in snapshot
    assert '"status":"FAILED"' in snapshot
    task = SimpleNamespace(task_id="review", authority=Authority(["review_snapshot", "submit_review"], [], []))
    packet = hive._compile_reviewer_packet(task, {})
    assert packet["public_objective"] == FIXTURE["goal"]
    assert packet["authority"]["write_scopes"] == []
    assert "test_independent.py" not in json.dumps(packet)
    hive._persist()
    resumed = ContractCheckedExecutive.resume(hive.root, hive.objective.objective_id,
        public_contract_gate=hive.public_contract_gate, worker_chat=no_model, judge_chat=no_model,
        config=HiveConfig.atomic(call_budget=36))
    assert resumed.acceptance_oracle(resumed.root) is False
    changed = PublicContractGate(FIXTURE["public_files"], [InputPreservation("unit_9e5c6035ea.py", "process", ("keys",))])
    with pytest.raises(ValueError, match="original public contract policy"):
        ContractCheckedExecutive.resume(hive.root, hive.objective.objective_id, public_contract_gate=changed)


def test_full_adapter_still_completes_known_good_repair_with_recorded_actions(tmp_path):
    from hive_learning.repair_probe import run_probe
    captured = []
    for path in sorted((ROOT/"results/2026-09-08-cont5/responses").glob("*.json")):
        for item in json.loads(path.read_text())["response"]["output"]:
            if item["type"] == "function_call":
                action = json.loads(item["arguments"])
                captured.append({"name": action["name"], "arguments": json.loads(action["arguments_json"])})
    assert len(captured) == 9

    class RecordedMeter:
        failed = False
        failure_code = None

        def __init__(self):
            self.usage = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0}

        def __call__(self, messages, **kwargs):
            action = deepcopy(captured[self.usage["calls"]])
            packet = json.loads(next(m["content"] for m in messages if m["role"] == "user"))
            if action["name"] == "submit_location":
                action["arguments"] = {"callable_id": packet["locked_callable_id"], "choice_id": packet["source_line_choices"][0]["choice_id"]}
            elif action["name"] == "confirm_candidate":
                action["arguments"]["candidate_location_id"] = packet["candidate_source_location"]["location_id"]
            elif action["name"] == "submit_mechanism":
                action["arguments"]["location_id"] = packet["accepted_source_location"]["location_id"]
            self.usage["calls"] += 1
            return json.dumps(action)

        worker = __call__

    class RecordedHive(ContractCheckedHive):
        def _new_meter(self, *args, **kwargs):
            meter = RecordedMeter()
            self.meters.append(meter)
            return meter

    adapter = RecordedHive("recorded-actions-not-a-model", "fixture_not_a_real_key", max_requests=9,
        contracts=[InputPreservation("capacity.py", "admit", ("quantity", "capacity"))])
    report = run_probe(adapter, tmp_path/"work", ROOT/"examples/repair-probe.json")
    assert report["verdict"] == "REPAIR_VERIFIED", report
    assert report["usage"]["calls"] == 9
    assert report["controller"]["public_contract_checks"]
    assert report["controller"]["public_contract_checks"][-1]["accepted"]
