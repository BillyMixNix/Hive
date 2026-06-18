import json

from twin_realms import (
    AffordanceBuilder,
    GroundedLLMAgent,
    SituationalAwarenessBuilder,
    TwinRealmsEngine,
    TwinRealmsRuntime,
    build_complexity_world,
)
from twin_realms.models import ActionIntent, WorldEvent
from twin_realms.behavior import analyze_agent_behavior


def test_affordances_exclude_absent_targets_and_include_tier_two_systems():
    state = build_complexity_world(tier=2)
    options = AffordanceBuilder().build("char:player", state)
    intents = [option["intent"] for option in options]

    assert all(intent.target_id != "char:malformed" for intent in intents)
    assert any(intent.action == "equip" for intent in intents)
    assert any(intent.action == "train" for intent in intents)
    assert any(intent.action == "work" for intent in intents)


def test_rejected_choice_is_suppressed_on_next_proposal():
    prompts = []

    def model(prompt):
        prompts.append(json.loads(prompt.split("\n\n")[-1]))
        return '{"choice_id":"a1","confidence":1.0}'

    state = build_complexity_world(tier=2)
    agent = GroundedLLMAgent(model)
    first = agent.propose("char:player", state)
    agent.reflect(WorldEvent(
        id="turn:1",
        turn=1,
        event_type="action_rejected",
        actor_id="char:player",
        target_id=first.target_id,
        accepted=False,
        facts={},
        reason="test rejection",
        intent=first.to_dict(),
    ), state)
    agent.propose("char:player", state)

    first_choices = prompts[0]["available_choices"]
    second_choices = prompts[1]["available_choices"]
    assert len(second_choices) == len(first_choices) - 1
    assert agent.repeated_failure_blocks == 1


def test_grounded_agents_use_progression_and_replay():
    choices = iter(["a12", "a1", "a13", "a1", "a4", "a1"])

    def model(prompt):
        packet = json.loads(prompt.split("\n\n")[-1])
        requested = next(choices, "a1")
        valid_ids = {choice["choice_id"] for choice in packet["available_choices"]}
        choice_id = requested if requested in valid_ids else next(iter(valid_ids))
        return json.dumps({"choice_id": choice_id, "confidence": 1.0})

    engine = TwinRealmsEngine(build_complexity_world(tier=2))
    player_agent = GroundedLLMAgent(model)
    runtime = TwinRealmsRuntime(engine, mode="assisted")

    for _ in range(6):
        runtime.agent_turn(player_agent)

    actions = {event.intent["action"] for event in engine.events}
    assert actions & {"work", "train", "equip", "move"}
    assert engine.verify_replay()


def test_repeated_no_progress_action_is_suppressed_after_two_successes():
    packets = []

    def model(prompt):
        packet = json.loads(prompt.split("\n\n")[-1])
        packets.append(packet)
        observe = next(
            (
                choice for choice in packet["available_choices"]
                if choice["description"] == "Observe the current location."
            ),
            packet["available_choices"][0],
        )
        return json.dumps({"choice_id": observe["choice_id"], "confidence": 1.0})

    engine = TwinRealmsEngine(build_complexity_world(tier=2))
    agent = GroundedLLMAgent(model)
    runtime = TwinRealmsRuntime(engine, mode="assisted")
    for _ in range(3):
        runtime.agent_turn(agent)

    assert engine.events[0].intent["action"] == "observe"
    assert engine.events[1].intent["action"] == "observe"
    assert engine.events[2].intent["action"] != "observe"
    assert agent.repeated_failure_blocks >= 1


def test_present_hostile_is_ranked_ahead_of_progression_actions():
    packets = []

    def model(prompt):
        packet = json.loads(prompt.split("\n\n")[-1])
        packets.append(packet)
        return '{"choice_id":"a1","confidence":1.0}'

    state = build_complexity_world(tier=2)
    state.characters["char:malformed"].location_id = (
        state.characters["char:player"].location_id
    )
    state.characters["char:malformed"].active = True
    agent = GroundedLLMAgent(model)

    intent = agent.propose("char:player", state)

    assert packets[0]["available_choices"][0]["description"].startswith("Attack ")
    assert intent.action == "attack"
    assert intent.target_id == "char:malformed"


def test_situational_awareness_reports_world_derived_threat_evidence():
    state = build_complexity_world(tier=2)
    player = state.characters["char:player"]
    malformed = state.characters["char:malformed"]
    malformed.active = True
    malformed.location_id = player.location_id
    player.health = 31
    player.stamina = 7
    options = AffordanceBuilder().build(player.id, state)
    incoming = WorldEvent(
        id="turn:50",
        turn=50,
        event_type="attack_resolved",
        actor_id=malformed.id,
        target_id=player.id,
        accepted=True,
        facts={"damage": 19, "target_alive": True},
        intent={"action": "attack"},
    )

    packet = SituationalAwarenessBuilder().build(
        player.id,
        state,
        options,
        [incoming],
    )

    assert packet["visible_hostiles"] == ["char:malformed"]
    assert packet["hostile_proximity"][0]["graph_distance"] == 0
    assert packet["recent_damage"]["total"] == 19
    assert packet["health_stamina_risk"]["stamina_band"] == "critical"
    assert packet["goal_conflict_flags"]["low_stamina_while_hostile_present"]
    assert packet["safe_exits"]
    assert packet["terminal_risk_score"] > 0.5


def test_awareness_packet_does_not_change_available_choice_order():
    packets = []

    def model(prompt):
        packet = json.loads(prompt.split("\n\n")[-1])
        packets.append(packet)
        return '{"choice_id":"a1","confidence":1.0}'

    state = build_complexity_world(tier=2)
    plain = GroundedLLMAgent(model)
    aware = GroundedLLMAgent(model, situational_awareness=True)

    plain_intent = plain.propose("char:player", state)
    aware_intent = aware.propose("char:player", state)

    assert packets[0]["available_choices"] == packets[1]["available_choices"]
    assert "situational_awareness" not in packets[0]
    assert "situational_awareness" in packets[1]
    assert plain_intent.action == aware_intent.action


def test_behavior_analysis_uses_replayed_pre_action_threat_state():
    state = build_complexity_world(tier=2)
    player = state.characters["char:player"]
    malformed = state.characters["char:malformed"]
    malformed.active = True
    malformed.location_id = player.location_id
    player.health = 10
    engine = TwinRealmsEngine(state)

    engine.apply_intent(ActionIntent(
        "equip",
        player.id,
        parameters={"item_id": "item:iron_sword"},
    ))
    engine.apply_intent(ActionIntent(
        "attack",
        malformed.id,
        target_id=player.id,
    ))
    engine.apply_intent(ActionIntent("rest", player.id))

    metrics = analyze_agent_behavior(engine)

    assert metrics["pre_death_accepted_rate"] == 1.0
    assert metrics["survival_turns"]["world_turns"] == 2
    assert metrics["hostile_present_action_mix"] == {"equip": 1}
    assert metrics["progression"]["after_threat"]["accepted_events"] == 1
    assert metrics["terminal_state_rejections"] == 1
    assert metrics["replay_consistent"]
