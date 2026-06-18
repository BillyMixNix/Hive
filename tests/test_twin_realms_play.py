from twin_realms import (
    TerminalPlayer,
    TwinRealmsEngine,
    TwinRealmsHiveAdapter,
    TwinRealmsRuntime,
    build_willow_region_world,
)
import json
from twin_realms.models import ActionIntent


class RecordingPlanner:
    def __init__(self):
        self.observed = []

    def observe_world_event(self, event, state):
        self.observed.append(event.to_dict())

    def propose(self, actor_id, state):
        return ActionIntent("wait", actor_id)


def build_session(tmp_path, *, runtime=None):
    outputs = []
    runtime = runtime or TwinRealmsRuntime(
        TwinRealmsEngine(),
        mode="baseline",
    )
    session = TerminalPlayer(
        runtime,
        save_path=tmp_path / "human-save.json",
        output_fn=outputs.append,
    )
    return session, outputs


def test_terminal_inspection_commands_do_not_advance_world(tmp_path):
    session, outputs = build_session(tmp_path)

    for command in (
        "look", "status", "inventory", "people", "actions", "history"
    ):
        assert session.handle(command)

    assert session.engine.state.turn == 0
    assert any("Broken Shrine" in output for output in outputs)
    assert any("Available actions:" in output for output in outputs)
    actions = next(
        output for output in outputs if output.startswith("Available actions:")
    )
    assert "Move to Willow Village." in actions
    assert "loc:" not in actions


def test_terminal_numbered_action_executes_exact_affordance(tmp_path):
    session, outputs = build_session(tmp_path)
    session.handle("actions")
    rest_index = next(
        index for index, option in enumerate(
            session._numbered_actions,
            start=1,
        )
        if option["intent"].action == "rest"
    )

    session.handle(f"do {rest_index}")

    assert session.engine.events[-1].intent["action"] == "rest"
    assert session.engine.events[-1].accepted
    assert session.engine.verify_replay()
    assert any("recovers" in output for output in outputs)


def test_terminal_free_text_and_save_round_trip(tmp_path):
    session, outputs = build_session(tmp_path)

    session.handle("observe the malformed")
    session.handle("save")

    loaded = TwinRealmsEngine.load(session.save_path)
    assert loaded.events[-1].intent["action"] == "observe"
    assert loaded.verify_replay()
    assert any("Saved turn 1" in output for output in outputs)


def test_human_event_is_forwarded_to_hive_style_npc_observer(tmp_path):
    planner = RecordingPlanner()
    runtime = TwinRealmsRuntime(
        TwinRealmsEngine(),
        mode="hive",
        npc_planner=planner,
        npc_ids=["char:malformed"],
    )
    session, _ = build_session(tmp_path, runtime=runtime)

    session.handle("rest")

    assert planner.observed
    assert planner.observed[0]["actor_id"] == "char:player"
    assert planner.observed[0]["intent"]["action"] == "rest"
    assert runtime.engine.events[-1].actor_id == "char:malformed"
    assert runtime.engine.verify_replay()


def test_quit_saves_and_stops_session(tmp_path):
    session, outputs = build_session(tmp_path)

    assert not session.handle("quit")
    assert session.save_path.exists()
    assert any("Saved turn 0" in output for output in outputs)


def test_terminal_reports_hive_npc_degraded_mode_without_crashing(tmp_path):
    def unavailable(prompt, role="default"):
        raise RuntimeError("ollama unavailable")

    adapter = TwinRealmsHiveAdapter(
        unavailable,
        transport_cooldown=60,
    )
    runtime = TwinRealmsRuntime(
        TwinRealmsEngine(),
        mode="hive",
        npc_planner=adapter,
        npc_scope="local",
    )
    session, outputs = build_session(tmp_path, runtime=runtime)

    session.handle("rest")
    session.handle("save")

    assert any(
        "Hive NPC transport is unavailable" in output
        for output in outputs
    )
    assert session.save_path.exists()
    assert runtime.engine.verify_replay()


def test_local_npc_scope_schedules_every_active_colocated_actor():
    engine = TwinRealmsEngine(build_willow_region_world())
    runtime = TwinRealmsRuntime(
        engine,
        mode="hive",
        npc_planner=RecordingPlanner(),
        npc_scope="local",
    )

    scheduled = runtime._npc_ids_for_turn()

    assert "char:swordsman" in scheduled
    assert "char:elder" in scheduled
    assert "char:herbalist" not in scheduled
    assert "char:malformed" not in scheduled


def test_all_npc_scope_schedules_remote_active_actors():
    engine = TwinRealmsEngine(build_willow_region_world())
    runtime = TwinRealmsRuntime(
        engine,
        mode="hive",
        npc_planner=RecordingPlanner(),
        npc_scope="all",
    )

    scheduled = runtime._npc_ids_for_turn()

    assert "char:herbalist" in scheduled
    assert "char:malformed" not in scheduled


def test_dynamic_local_hive_npcs_keep_independent_cognition():
    def model(prompt, role="default"):
        phase = prompt.splitlines()[0].split(":", 1)[1].strip()
        packet = json.loads(prompt.split("Input packet:\n", 1)[1])
        if phase == "observe":
            return '{"summary":"Visible local evidence received."}'
        if phase == "investigate":
            return (
                '{"needed":false,"question":null,'
                '"preferred_action":null,"reason":"Enough evidence."}'
            )
        if phase == "plan":
            return (
                '{"goal":"Act locally.","steps":["Choose an action."],'
                '"success_condition":"The action resolves."}'
            )
        return json.dumps({
            "choice_id": packet["allowed_choice_ids"][0],
            "confidence": 1.0,
        })

    engine = TwinRealmsEngine(build_willow_region_world())
    adapter = TwinRealmsHiveAdapter(model)
    runtime = TwinRealmsRuntime(
        engine,
        mode="hive",
        npc_planner=adapter,
        npc_scope="local",
        npc_limit=2,
    )

    runtime.turn("rest")

    assert set(adapter.cognition.actors) == {
        "char:swordsman",
        "char:elder",
    }
    for actor_id in adapter.cognition.actors:
        actor = adapter.cognition.actors[actor_id]
        assert actor.observations
        assert actor.plans
        assert any(
            event["actor_id"] == "char:player"
            for event in actor.visible_events
        )
    assert engine.verify_replay()
