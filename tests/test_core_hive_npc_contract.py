import json

from twin_realms import (
    TwinRealmsEngine,
    TwinRealmsHiveAdapter,
    TwinRealmsRuntime,
    build_core_loop_world,
)
from twin_realms.models import ActionIntent


class LocalHive:
    def __init__(self, *, requested_text="loc:field", invalid_choice=False):
        self.requested_text = requested_text
        self.invalid_choice = invalid_choice
        self.prompts = []

    def __call__(self, prompt, role="default"):
        self.prompts.append((role, prompt))
        phase = prompt.splitlines()[0].split(":", 1)[1].strip()
        packet = json.loads(prompt.split("Input packet:\n", 1)[1])
        if phase == "observe":
            return json.dumps({
                "summary": "Local state and affordances observed.",
            })
        if phase == "investigate":
            return json.dumps({
                "needed": False,
                "question": None,
                "preferred_action": None,
                "reason": "Visible local state is enough.",
            })
        if phase == "plan":
            return json.dumps({
                "goal": packet["goal"],
                "steps": ["Choose one listed local action."],
                "success_condition": "The simulator resolves the action.",
            })
        if self.invalid_choice:
            return json.dumps({
                "choice_id": "invented-choice",
                "confidence": 1.0,
            })
        choice = next(
            option
            for option in packet["available_choices"]
            if self.requested_text in option["description"]
        )
        return json.dumps({
            "choice_id": choice["choice_id"],
            "confidence": 1.0,
        })


def test_local_hive_controls_nearby_npc_through_valid_affordance():
    model = LocalHive(requested_text="loc:field")
    adapter = TwinRealmsHiveAdapter(model)
    engine = TwinRealmsEngine(build_core_loop_world())
    runtime = TwinRealmsRuntime(
        engine,
        mode="hive",
        npc_planner=adapter,
        npc_scope="local",
    )

    result = runtime.turn("rest")
    worker = engine.state.characters["char:worker"]
    log = adapter.cognition.actors["char:worker"].decision_log[-1]

    assert result.npc_results[0].event.accepted
    assert result.npc_results[0].intent.actor_id == "char:worker"
    assert result.npc_results[0].intent.action == "move"
    assert worker.location_id == "loc:field"
    assert log["observation"]["summary"] == "Local state and affordances observed."
    assert log["goal"]
    assert log["chosen_action"]["action"] == "move"
    assert log["result"]["event_type"] == "moved"
    assert any(
        choice["action"] == log["chosen_action"]["action"]
        and choice["destination_id"] == log["chosen_action"]["destination_id"]
        for choice in log["available_affordances"]
    )
    assert engine.verify_replay()


def test_local_hive_invalid_choice_falls_back_to_valid_wait():
    model = LocalHive(invalid_choice=True)
    adapter = TwinRealmsHiveAdapter(model)
    engine = TwinRealmsEngine(build_core_loop_world())
    runtime = TwinRealmsRuntime(
        engine,
        mode="hive",
        npc_planner=adapter,
        npc_scope="local",
    )

    result = runtime.turn("rest")
    log = adapter.cognition.actors["char:worker"].decision_log[-1]

    assert result.npc_results[0].event.accepted
    assert result.npc_results[0].intent.action == "wait"
    assert adapter.metrics.invalid == 1
    assert adapter.phase_invalid["act"] == 1
    assert log["chosen_action"]["action"] == "wait"
    assert log["result"]["event_type"] == "waited"
    assert any(choice["action"] == "wait" for choice in log["available_affordances"])
    assert engine.verify_replay()


def test_invented_planner_action_is_rejected_by_simulator_and_replays():
    class InventingPlanner:
        def observe_world_event(self, event, state):
            pass

        def propose(self, actor_id, state):
            return ActionIntent("rewrite_truth", actor_id)

    engine = TwinRealmsEngine(build_core_loop_world())
    runtime = TwinRealmsRuntime(
        engine,
        mode="hive",
        npc_planner=InventingPlanner(),
        npc_ids=["char:worker"],
    )

    result = runtime.turn("rest")
    npc_event = result.npc_results[0].event

    assert npc_event.accepted is False
    assert npc_event.reason == "intent could not be interpreted"
    assert npc_event.intent["action"] == "rewrite_truth"
    assert engine.verify_replay()
