import pytest

from continuation_protocol import ContinuationDecision, ContinuationStatus
from hive_supervisor import HiveSupervisor


def test_continue_requires_executable_next_objective():
    with pytest.raises(ValueError, match="next_objective"):
        ContinuationDecision.from_dict({"status": "CONTINUE", "reason": "more work exists"})


def test_supervisor_reinvokes_until_milestone_without_human_continue():
    calls = []

    def worker(state):
        step = state.get("step", 0)
        calls.append(step)
        if step < 3:
            return {
                "state_updates": {"step": step + 1},
                "continuation": {
                    "status": "CONTINUE",
                    "reason": "Delegated work remains and no human authority is required.",
                    "next_objective": f"complete stage {step + 1}",
                },
            }
        return {
            "state_updates": {"done": True},
            "continuation": {
                "status": "MILESTONE_COMPLETE",
                "reason": "Defined multi-stage checkpoint is satisfied.",
                "milestone_reached": True,
            },
        }

    result = HiveSupervisor(max_iterations=10).run(
        {"step": 0}, worker, lambda _state, output: {"verified": bool(output.get("state_updates"))}
    )

    assert calls == [0, 1, 2, 3]
    assert result.status is ContinuationStatus.MILESTONE_COMPLETE
    assert result.iterations == 4
    assert result.unnecessary_human_interventions == 0


def test_supervisor_yields_only_for_real_human_authority():
    def worker(_state):
        return {
            "continuation": {
                "status": "HUMAN_AUTHORITY_REQUIRED",
                "reason": "Two incompatible product directions require owner choice.",
                "human_input_required": True,
            }
        }

    result = HiveSupervisor().run({}, worker, lambda _state, _output: {"verified": True})
    assert result.status is ContinuationStatus.HUMAN_AUTHORITY_REQUIRED
    assert result.iterations == 1


def test_wait_external_does_not_masquerade_as_human_checkpoint():
    def worker(_state):
        return {
            "continuation": {
                "status": "WAIT_EXTERNAL",
                "reason": "CI result has not arrived.",
                "wait_condition": "workflow completion",
            }
        }

    result = HiveSupervisor().run({}, worker, lambda _state, _output: {"verified": True})
    assert result.status is ContinuationStatus.WAIT_EXTERNAL
    assert result.last_decision.human_input_required is False


def test_supervisor_blocks_runaway_identical_continue_loop():
    def worker(_state):
        return {
            "continuation": {
                "status": "CONTINUE",
                "reason": "keep going",
                "next_objective": "same objective",
            }
        }

    result = HiveSupervisor(max_iterations=10, max_stagnant_iterations=2).run(
        {}, worker, lambda _state, _output: {"verified": False}
    )
    assert result.status is ContinuationStatus.BLOCKED
    assert "identical continuation state" in result.last_decision.reason
