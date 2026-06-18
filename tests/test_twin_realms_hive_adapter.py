import json

from HiveLessonMemory import LessonMemory

from twin_realms import (
    CognitionState,
    TwinRealmsEngine,
    TwinRealmsHiveAdapter,
    TwinRealmsRuntime,
    build_complexity_world,
    build_willow_region_world,
)
from twin_realms.models import ActionIntent


class FakeHive:
    def __init__(self, actions=None):
        self.actions = iter(actions or [])
        self.prompts = []

    def __call__(self, prompt, role="default"):
        self.prompts.append((role, prompt))
        phase = prompt.splitlines()[0].split(":", 1)[1].strip()
        packet = json.loads(prompt.split("Input packet:\n", 1)[1])
        if phase == "observe":
            return json.dumps({
                "summary": "The actor needs current local evidence.",
                "salient_facts": ["Only visible state is authoritative."],
                "questions": ["What is present here?"],
            })
        if phase == "investigate":
            return json.dumps({
                "needed": True,
                "question": "What is present here?",
                "preferred_action": "observe",
                "reason": "Local evidence is incomplete.",
            })
        if phase == "plan":
            return json.dumps({
                "goal": packet["goal"],
                "steps": ["Acquire evidence.", "Act on resolved truth."],
                "success_condition": "A valid action resolves.",
            })
        if phase == "learn":
            return json.dumps({
                "failure_pattern": packet["resolved_event"]["reason"],
                "retry_instruction": "Recover stamina before attacking again.",
                "trigger_pattern": "attack",
                "fix_strategy": "rest_then_retry",
            })
        requested = next(self.actions, "observe")
        choice = next(
            (
                option for option in packet["available_choices"]
                if requested in option["description"].lower()
            ),
            packet["available_choices"][0],
        )
        return json.dumps({
            "choice_id": choice["choice_id"],
            "confidence": 1.0,
        })


def test_hive_adapter_runs_observe_investigate_plan_act_contract():
    model = FakeHive(actions=["observe the current location"])
    engine = TwinRealmsEngine(build_willow_region_world())
    adapter = TwinRealmsHiveAdapter(model)
    runtime = TwinRealmsRuntime(engine, mode="hive")

    result = runtime.agent_turn(adapter)

    assert result.player_result.intent.action == "observe"
    assert result.player_result.intent.parameters["proposal_source"] == (
        "hive_agent_adapter"
    )
    assert [
        trace.phase for trace in adapter.cognition.traces
    ] == ["observe", "investigate", "plan", "act"]
    assert adapter.cognition.actors["char:player"].unresolved_questions
    assert engine.verify_replay()


def test_hive_action_contract_contains_unknown_ids():
    def malicious_model(prompt, role="default"):
        phase = prompt.splitlines()[0].split(":", 1)[1].strip()
        if phase == "act":
            return json.dumps({
                "choice_id": "char:invented_target",
                "action": "rewrite_reality",
                "target_id": "char:invented_target",
            })
        return "{}"

    engine = TwinRealmsEngine(build_willow_region_world())
    before = engine.simulator.state_digest(engine.state)
    adapter = TwinRealmsHiveAdapter(malicious_model)

    intent = adapter.propose(engine.state.player_id, engine.state)

    assert intent.action == "wait"
    assert intent.target_id is None
    assert adapter.metrics.invalid == 1
    assert adapter.phase_invalid["act"] == 1
    assert adapter.phase_fallbacks["act"] == 1
    assert engine.simulator.state_digest(engine.state) == before


def test_hive_transport_failure_opens_circuit_and_returns_safe_wait():
    calls = 0

    def unavailable(prompt, role="default"):
        nonlocal calls
        calls += 1
        raise RuntimeError("ollama unavailable")

    engine = TwinRealmsEngine(build_willow_region_world())
    adapter = TwinRealmsHiveAdapter(
        unavailable,
        transport_cooldown=60,
    )

    intent = adapter.propose("char:player", engine.state)

    assert intent.action == "wait"
    assert calls == 1
    assert adapter.transport_failures == 1
    assert adapter.phase_fallbacks == {
        "observe": 1,
        "investigate": 1,
        "plan": 1,
        "act": 1,
        "learn": 0,
    }


def test_hive_choice_presentation_is_deterministic_and_not_fixed_by_action():
    state = build_willow_region_world()
    adapter = TwinRealmsHiveAdapter(FakeHive())
    raw = adapter.affordances.build("char:player", state)

    first = adapter._present_options("char:player", state, raw)
    second = adapter._present_options("char:player", state, raw)
    later_state = build_willow_region_world()
    later_state.turn = 1
    later = adapter._present_options("char:player", later_state, raw)

    assert [
        (option["choice_id"], option["description"]) for option in first
    ] == [
        (option["choice_id"], option["description"]) for option in second
    ]
    assert {option["description"] for option in first} == {
        option["description"] for option in raw
    }
    assert [option["description"] for option in first] != [
        option["description"] for option in later
    ]


def test_hive_learning_stores_and_retrieves_rejection_lesson(tmp_path):
    state = build_complexity_world(tier=2)
    player = state.characters["char:player"]
    malformed = state.characters["char:malformed"]
    malformed.active = True
    malformed.location_id = player.location_id
    player.stamina = 0
    model = FakeHive(actions=["attack", "recover stamina"])
    memory = LessonMemory(tmp_path / "twin_realms_lessons.jsonl")
    engine = TwinRealmsEngine(state)
    adapter = TwinRealmsHiveAdapter(
        model,
        lesson_memory=memory,
        learning=True,
    )
    runtime = TwinRealmsRuntime(engine, mode="hive_learning")

    first = runtime.agent_turn(adapter)
    second = runtime.agent_turn(adapter)

    assert not first.player_result.event.accepted
    assert first.player_result.event.reason == "insufficient stamina"
    assert second.player_result.intent.action == "rest"
    actor = adapter.cognition.actors["char:player"]
    assert actor.lesson_ids
    assert second.player_result.intent.parameters["lesson_ids"]
    assert any('"lessons": [{' in prompt for _, prompt in model.prompts)
    assert engine.verify_replay()


def test_hive_cognition_persists_without_entering_world_replay(tmp_path):
    model = FakeHive(actions=["observe", "rest"])
    engine = TwinRealmsEngine(build_willow_region_world())
    adapter = TwinRealmsHiveAdapter(model)
    runtime = TwinRealmsRuntime(engine, mode="hive")
    runtime.agent_turn(adapter)
    runtime.agent_turn(adapter)
    path = tmp_path / "hive-world.json"
    world_digest = engine.simulator.state_digest(engine.state)

    engine.save(path)
    loaded = TwinRealmsEngine.load(path)
    restored = TwinRealmsHiveAdapter(
        FakeHive(),
        cognition=CognitionState(),
    )
    restored.attach_engine(loaded)

    assert loaded.cognition_state == engine.cognition_state
    assert restored.cognition.to_dict() == adapter.cognition.to_dict()
    assert loaded.simulator.state_digest(loaded.state) == world_digest
    assert loaded.verify_replay()


def test_hive_adapter_only_records_visible_events():
    engine = TwinRealmsEngine(build_willow_region_world())
    adapter = TwinRealmsHiveAdapter(FakeHive())
    adapter.attach_engine(engine)
    adapter.cognition.actor("char:player", "Observe.")

    remote = engine.apply_intent(ActionIntent(
        "observe",
        "char:miner",
    )).event
    adapter.observe_world_event(remote, engine.state)
    assert not adapter.cognition.actors["char:player"].visible_events

    local = engine.apply_intent(ActionIntent(
        "observe",
        "char:elder",
    )).event
    adapter.observe_world_event(local, engine.state)
    assert adapter.cognition.actors["char:player"].visible_events[-1][
        "actor_id"
    ] == "char:elder"


def test_hive_prompt_does_not_reveal_remote_hostile_locations():
    model = FakeHive()
    state = build_willow_region_world()
    engine = TwinRealmsEngine(state)
    adapter = TwinRealmsHiveAdapter(model)

    adapter.propose("char:player", engine.state)

    observe_prompt = next(
        prompt for _, prompt in model.prompts
        if prompt.startswith("PHASE: observe")
    )
    assert "char:bandit_scout" not in observe_prompt
    assert '"evidence_scope": "actor_visible"' in observe_prompt
    assert '"hostile_occupancy": "unknown"' in observe_prompt


def test_hive_prompt_exposes_only_visible_rule_derived_dispositions():
    model = FakeHive()
    state = build_willow_region_world()
    player = state.characters["char:player"]
    malformed = state.characters["char:malformed"]
    malformed.active = True
    malformed.location_id = player.location_id
    engine = TwinRealmsEngine(state)
    adapter = TwinRealmsHiveAdapter(model)

    adapter.propose("char:player", engine.state)

    observe_prompt = next(
        prompt for _, prompt in model.prompts
        if prompt.startswith("PHASE: observe")
    )
    packet = json.loads(observe_prompt.split("Input packet:\n", 1)[1])
    role = packet["visible_world"]["role_evidence"]
    malformed_disposition = next(
        item for item in role["visible_dispositions"]
        if item["actor_id"] == "char:malformed"
    )
    assert malformed_disposition["hostile_by_world_rule"]
    assert malformed_disposition["faction_relation"] == -80
    assert "char:bandit_scout" not in observe_prompt


def test_shared_hive_adapter_forwards_visible_player_event_to_npc():
    model = FakeHive(actions=["observe", "observe"])
    engine = TwinRealmsEngine(build_willow_region_world())
    adapter = TwinRealmsHiveAdapter(model)
    runtime = TwinRealmsRuntime(
        engine,
        mode="hive",
        npc_planner=adapter,
        npc_ids=["char:elder"],
    )

    runtime.agent_turn(adapter)

    elder_events = adapter.cognition.actors["char:elder"].visible_events
    assert elder_events
    assert elder_events[0]["actor_id"] == "char:player"


def test_accepted_action_progresses_plan_and_exposes_behavioral_evidence():
    model = FakeHive(actions=["wait", "wait"])
    engine = TwinRealmsEngine(build_willow_region_world())
    adapter = TwinRealmsHiveAdapter(model)
    runtime = TwinRealmsRuntime(engine, mode="hive")

    runtime.agent_turn(adapter)
    runtime.agent_turn(adapter)

    actor = adapter.cognition.actors["char:player"]
    assert actor.plans[-1]["status"] == "progressed"
    assert actor.visible_events[-1]["action"] == "wait"
    visible = adapter._visible_context(
        "char:player",
        engine.state,
        adapter.affordances.build("char:player", engine.state),
    )
    evidence = visible["behavioral_evidence"]
    assert evidence["recent_actions"][-2:] == ["wait", "wait"]
    assert evidence["repeated_action_streak"] == 2
    assert evidence["recent_plan_outcomes"][-1]["status"] == "progressed"
    act_prompt = next(
        prompt for _, prompt in reversed(model.prompts)
        if prompt.startswith("PHASE: act")
    )
    assert '"behavioral_evidence": {' in act_prompt
    assert '"role_evidence": {' in act_prompt
    assert '"situational_awareness": {' in act_prompt
    assert '"allowed_choice_ids": [' in act_prompt


def test_unrelated_accepted_action_is_not_successful_lesson_reuse():
    event = type("Event", (), {
        "intent": {"action": "drop"},
        "reason": None,
    })()
    lesson = {
        "failure_code": "insufficient stamina",
        "trigger_pattern": "attack",
        "fix_strategy": "rest_then_retry",
        "retry_instruction": "Recover stamina before attacking again.",
    }

    assert not TwinRealmsHiveAdapter._lesson_applied(lesson, event)
