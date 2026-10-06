"""Integration tests with scripted recipients, not learning experiments."""
from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest

from grow.continuation import EPISODE_SCHEMA, GrowContinuationExperiment
from grow.core import ExperimentInvalid, file_hash, hash_json, tree_manifest
from grow.experiment import Grow0Experiment
from tests.test_grow0 import good_candidate_source


ROOT = Path(__file__).resolve().parents[1]


def recipient(prompt):
    """A deliberately limited test double; instruction flags fix scripted faults."""
    values = []
    current = None
    for line in prompt.splitlines():
        if line.startswith(("Candidate value A:", "Candidate value B:", "STORED_STATE:", "CURRENT_CALL:")):
            value = ast.literal_eval(line.split(":", 1)[1].strip())
            values.append(value)
            if line.startswith("CURRENT_CALL:"):
                current = value
    if current is None:
        chosen = values[0]
    elif isinstance(current, int) and current < 0 and "PRESERVE_SIGN" not in prompt:
        chosen = values[0]
    elif isinstance(current, str) and "PRESERVE_TYPE" not in prompt:
        chosen = values[0]
    else:
        chosen = current
    return json.dumps({"selected_source": "current", "selected_value": chosen})


def proposal(source):
    return json.dumps({
        "hypothesis": "Preserve an additional distinction in the repair packet.",
        "mechanism_changed": "packet instructions",
        "expected_behavioral_change": "selection is invariant to presentation order",
        "possible_regressions": ["an earlier distinction may be lost"],
        "files": [{"path": "grow/workshop/repair_packet.py", "content": source}],
    })


def revised(source, flag):
    return source.replace("REPAIR DECISION PACKET", "REPAIR DECISION PACKET " + flag)


@pytest.fixture
def promoted(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "grow", repo / "grow", ignore=shutil.ignore_patterns("state", "__pycache__"))
    exp = Grow0Experiment(repo)
    _, snapshot = exp.freeze_g0(baseline_ref="scripted-integration-test", prior_suite={"passed": True})
    result = exp.one_generation(
        snapshot=snapshot, invoke_g0=recipient, invoke_g1=recipient,
        invoke_modifier=lambda _: proposal(good_candidate_source()),
        prior_suite_g1=lambda _: {"passed": True, "scope": "test-double"},
    )
    assert result["record"]["disposition"] == "PROMOTED"
    return repo, result


def episode(tmp_path, parent="G1-A", name="sign", strings=False):
    cases = []
    for suffix, stored, current in (("trigger", 12, -57), ("transfer", 25, -68)):
        if strings:
            stored, current = "old-" + suffix, "active-" + suffix
        cases.append({
            "case_id": name + "-" + suffix, "goal": "Choose the active value with its original representation.",
            "stored_value": stored, "current_value": current,
            "expected_source": "current", "expected_value": current,
        })
    value = {"schema": EPISODE_SCHEMA, "episode_id": name, "parent_id": parent,
             "trigger": cases[0], "transfer": cases[1]}
    path = tmp_path / (name + ".json")
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def continuation(repo, path, parent="G1-A"):
    return GrowContinuationExperiment(repo, parent_id=parent, episode_path=path, episode_sha256=file_hash(path))


def run(exp, source, *, modifier=None, prior=None, candidate=recipient):
    return exp.run(invoke_parent=recipient, invoke_candidate=candidate,
                   invoke_modifier=modifier or (lambda _: proposal(source)),
                   prior_suite=prior or (lambda _: {"passed": True, "scope": "test-double"}))


def test_two_continued_generations_inherit_code_and_retain_ancestors(promoted, tmp_path):
    repo, first = promoted
    original = hash_json(tree_manifest(repo))
    parent_source = (repo / "grow/state/generations/G1-A/workshop/grow/workshop/repair_packet.py").read_text()
    second_source = revised(parent_source, "PRESERVE_SIGN")
    second = continuation(repo, episode(tmp_path))
    seen = []

    def modify(prompt):
        context = json.loads(prompt)
        seen.append(context)
        assert context["mutable_file_content"] == parent_source
        assert context["failure_packet"]["current_workshop_behavior"] == parent_source
        assert context["failure_packet"]["generation"] == "G1-A"
        assert "STORED_STATE" in parent_source
        assert "CURRENT_CALL" in parent_source
        return proposal(second_source)

    result = run(second, second_source, modifier=modify)
    assert seen and result["record"]["disposition"] == "PROMOTED"
    assert result["record"]["generation_id"] == "G2-A"
    assert result["record"]["parent_id"] == "G1-A"
    assert result["record"]["before_hashes"] == first["record"]["after_hashes"]
    assert len(result["record"]["regression_results"]["inherited_retention"]) == 2
    assert result["record"]["benchmark_bundle_id"].startswith("continuation:")
    context = result["record"]["validation_results"]["continuation"]
    assert context["calls"] == context["call_budgets"] == {"parent": 4, "modifier": 1, "candidate": 8}

    # Reconstruct the controller from disk: G3 must start with the G2 changes.
    third = continuation(repo, episode(tmp_path, "G2-A", "type", strings=True), "G2-A")
    third_source = revised(second_source, "PRESERVE_TYPE")

    def modify_again(prompt):
        context = json.loads(prompt)
        assert context["mutable_file_content"] == second_source
        assert "PRESERVE_SIGN" in context["mutable_file_content"]
        assert context["failure_packet"]["generation"] == "G2-A"
        return proposal(third_source)

    final = run(third, third_source, modifier=modify_again)
    assert final["record"]["generation_id"] == "G3-A"
    assert final["record"]["parent_id"] == "G2-A"
    assert final["record"]["disposition"] == "PROMOTED"
    assert final["record"]["before_hashes"] == result["record"]["after_hashes"]
    assert len(final["record"]["regression_results"]["inherited_retention"]) == 4
    assert final["record"]["validation_results"]["continuation"]["calls"]["candidate"] == 12
    assert hash_json(tree_manifest(repo)) == original
    assert third.ledger.verify()


def test_new_fix_that_loses_an_inherited_capability_is_rejected(promoted, tmp_path):
    repo, _ = promoted
    second_source = revised(good_candidate_source(), "PRESERVE_SIGN")
    second = run(continuation(repo, episode(tmp_path)), second_source)
    assert second["record"]["disposition"] == "PROMOTED"
    third = continuation(repo, episode(tmp_path, "G2-A", "type", strings=True), "G2-A")
    # Fix the string episode while discarding the inherited sign instruction.
    regressing = revised(good_candidate_source(), "PRESERVE_TYPE")
    result = run(third, regressing)
    assert result["record"]["disposition"] == "REJECTED"
    assert "REJECTED_REGRESSION" in result["promotion"]["reasons"]
    assert third.ledger.parent_is_eligible("G3-A") is False
    assert "PRESERVE_SIGN" in (third.workshop_root / third.workshop_path).read_text()


def test_every_parent_evaluation_and_probe_uses_the_promoted_workshop(promoted, tmp_path):
    repo, _ = promoted
    exp = continuation(repo, episode(tmp_path))
    prompts = []

    def parent(prompt):
        prompts.append(prompt)
        assert "CURRENT_CALL:" in prompt
        assert "Candidate value A:" not in prompt
        return recipient(prompt)

    exp.run(invoke_parent=parent, invoke_candidate=recipient,
            invoke_modifier=lambda _: proposal(revised(good_candidate_source(), "PRESERVE_SIGN")),
            prior_suite=lambda _: {"passed": True})
    assert len(prompts) == 4


@pytest.mark.parametrize("mutation", ["workshop", "metadata", "root_workshop", "kernel", "missing_archive"])
def test_parent_or_kernel_drift_blocks_before_model_calls(promoted, tmp_path, mutation):
    repo, _ = promoted
    path = episode(tmp_path)
    exp = continuation(repo, path)
    archive = repo / "grow/state/generations/G1-A"
    targets = {
        "workshop": archive / "workshop/grow/workshop/repair_packet.py",
        "metadata": archive / "generation.json",
        "root_workshop": repo / "grow/workshop/repair_packet.py",
        "kernel": repo / "grow/kernel/promotion.py",
    }
    if mutation == "missing_archive":
        shutil.rmtree(archive)
    else:
        targets[mutation].write_text("changed")
    calls = []
    with pytest.raises(ExperimentInvalid):
        run(exp, "", modifier=lambda prompt: calls.append(prompt))
    assert not calls


def test_episode_hash_change_is_rejected(promoted, tmp_path):
    repo, _ = promoted
    path = episode(tmp_path)
    expected = file_hash(path)
    path.write_text(path.read_text() + " ")
    with pytest.raises(ExperimentInvalid, match="commitment"):
        GrowContinuationExperiment(repo, parent_id="G1-A", episode_path=path, episode_sha256=expected)


def test_candidate_change_inside_prior_validation_cannot_be_promoted(promoted, tmp_path):
    repo, _ = promoted
    exp = continuation(repo, episode(tmp_path))

    def mutate(candidate_root):
        (candidate_root / exp.workshop_path).write_text(good_candidate_source())
        return {"passed": True}

    with pytest.raises(ExperimentInvalid, match="candidate changed"):
        run(exp, revised(good_candidate_source(), "PRESERVE_SIGN"), prior=mutate)
    assert exp.ledger.get_generation("G2-A") is None


def test_modification_of_parent_during_model_call_is_detected(promoted, tmp_path):
    repo, _ = promoted
    exp = continuation(repo, episode(tmp_path))

    def mutate(prompt):
        (exp.workshop_root / exp.workshop_path).write_text("changed")
        return proposal(revised(good_candidate_source(), "PRESERVE_SIGN"))

    with pytest.raises(ExperimentInvalid, match="promoted bytes"):
        run(exp, "", modifier=mutate)
    assert exp.ledger.get_generation("G2-A") is None


def test_interruption_consumes_episode_and_prevents_silent_retry(promoted, tmp_path):
    repo, _ = promoted
    path = episode(tmp_path)
    exp = continuation(repo, path)

    def interrupted(prompt):
        raise RuntimeError("provider interrupted")

    with pytest.raises(RuntimeError, match="provider interrupted"):
        run(exp, "", modifier=interrupted)
    resumed = continuation(repo, path)
    with pytest.raises(ExperimentInvalid, match="already attempted"):
        run(resumed, revised(good_candidate_source(), "PRESERVE_SIGN"))


def test_rejected_parent_is_ineligible_even_with_existing_archive(promoted, tmp_path):
    repo, _ = promoted
    exp = continuation(repo, episode(tmp_path))
    rejected = run(exp, good_candidate_source() + "\n# unchanged behavior\n")
    assert rejected["record"]["disposition"] == "REJECTED"
    with pytest.raises(ExperimentInvalid, match="only promoted"):
        continuation(repo, episode(tmp_path, "G2-A", "type", True), "G2-A")


def test_duplicate_generation_ids_are_rejected(promoted, tmp_path):
    repo, _ = promoted
    exp = Grow0Experiment(repo)
    exp.ledger.append(exp.ledger.get_generation("G1-A"))
    with pytest.raises(ExperimentInvalid, match="duplicate generation"):
        continuation(repo, episode(tmp_path))


def test_next_candidate_id_is_unique_across_sibling_parents(promoted):
    repo, _ = promoted
    exp = Grow0Experiment(repo)
    exp.ledger.append({"record_type": "generation", "generation_id": "G2-A", "parent_id": "G1-B"})
    assert exp._next_candidate_id("G1-A") == "G2-B"


def test_old_frozen_entry_point_still_starts_from_g0(promoted):
    repo, _ = promoted
    exp = Grow0Experiment(repo)
    assert exp.parent_generation_id == "G0"
    assert exp.workshop_root == repo


def test_continuation_cannot_refreeze_or_use_uncommitted_entry_point(promoted, tmp_path):
    repo, _ = promoted
    exp = continuation(repo, episode(tmp_path))
    with pytest.raises(ExperimentInvalid, match="refreeze"):
        exp.freeze_g0()
    with pytest.raises(ExperimentInvalid, match="use run"):
        exp.one_generation()


@pytest.mark.parametrize("value", [None, "yes", 1])
def test_prior_suite_requires_an_actual_boolean(promoted, tmp_path, value):
    repo, _ = promoted
    exp = continuation(repo, episode(tmp_path))
    with pytest.raises(ExperimentInvalid, match="boolean"):
        run(exp, revised(good_candidate_source(), "PRESERVE_SIGN"), prior=lambda _: {"passed": value})


def test_symlinked_promoted_code_is_not_inherited(promoted, tmp_path):
    repo, _ = promoted
    code = repo / "grow/state/generations/G1-A/workshop/grow/workshop/repair_packet.py"
    external = tmp_path / "external.py"
    external.write_bytes(code.read_bytes())
    code.unlink()
    code.symlink_to(external)
    with pytest.raises(ExperimentInvalid, match="symlink"):
        continuation(repo, episode(tmp_path))


def test_reused_case_identity_is_not_a_new_episode(promoted, tmp_path):
    repo, _ = promoted
    path = episode(tmp_path)
    data = json.loads(path.read_text())
    data["trigger"]["case_id"] = "trigger-current-over-stored-01"
    path.write_text(json.dumps(data))
    with pytest.raises(ExperimentInvalid, match="new case identities"):
        continuation(repo, path)


def test_already_solved_new_challenge_stops_without_generating_a_patch(promoted, tmp_path):
    repo, _ = promoted
    path = episode(tmp_path)
    data = json.loads(path.read_text())
    for key in ("trigger", "transfer"):
        data[key]["current_value"] = data[key]["expected_value"] = 99
    path.write_text(json.dumps(data))
    exp = continuation(repo, path)
    calls = []
    with pytest.raises(ExperimentInvalid, match="G1-A failure"):
        run(exp, "", modifier=lambda prompt: calls.append(prompt))
    assert calls == []
    assert exp.ledger.get_generation("G2-A") is None


@pytest.mark.parametrize("text", ['{"schema":1,"schema":2}', '{"value":NaN}', '{"value":1e999}'])
def test_ambiguous_or_nonfinite_episode_json_is_rejected(promoted, tmp_path, text):
    repo, _ = promoted
    path = tmp_path / "invalid.json"
    path.write_text(text)
    with pytest.raises(ExperimentInvalid):
        continuation(repo, path)


def test_inherited_answer_in_candidate_is_rejected_before_evaluation(promoted, tmp_path):
    repo, _ = promoted
    exp = continuation(repo, episode(tmp_path))
    source = revised(good_candidate_source(), "PRESERVE_SIGN") + "\n# memorized old answer: 41\n"
    calls = []
    result = run(exp, source, candidate=lambda prompt: calls.append(prompt))
    assert result["record"]["disposition"] == "INVALID"
    assert not result["record"]["validation_results"]["integrity"]["checks"]["inherited_material_absent"]
    assert calls == []


def test_callback_cannot_append_to_the_controller_lineage(promoted, tmp_path):
    repo, _ = promoted
    exp = continuation(repo, episode(tmp_path))

    def forge(prompt):
        exp.ledger.append({"record_type": "forged-callback-event"})
        return proposal(revised(good_candidate_source(), "PRESERVE_SIGN"))

    with pytest.raises(ExperimentInvalid, match="controller lineage"):
        run(exp, "", modifier=forge)
    assert exp.ledger.get_generation("G2-A") is None


def test_generated_timestamp_is_not_mistaken_for_a_protected_answer(promoted, monkeypatch):
    repo, _ = promoted
    exp = Grow0Experiment(repo)
    stamp = "2026-09-08T12:00:00.206000+00:00"
    monkeypatch.setattr("grow.experiment.utc_now", lambda: stamp)
    exp.record_rejection_lesson(
        generation_id="G2-A", manifest=None, prediction="generic repair",
        contradicted_by=["REJECTED_NO_TRANSFER_GAIN"],
        diagnosis_or_implementation="implementation", avoid=["repeat identical repair"],
    )
    assert exp.lesson_ledger.entries()[-1]["timestamp"] == stamp
    sanitized = exp.lesson_ledger.sanitized_lessons(exp._sensitive_case_markers(exp._transfer))
    assert "timestamp" not in sanitized[-1]
    with pytest.raises(ExperimentInvalid, match="hidden transfer answer"):
        exp.record_rejection_lesson(
            generation_id="G2-B", manifest=None, prediction="hardcode 206",
            contradicted_by=[], diagnosis_or_implementation="implementation", avoid=[],
        )
