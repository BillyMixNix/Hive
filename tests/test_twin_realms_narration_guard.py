from twin_realms import NarrativeGenerator, TwinRealmsEngine, build_foundation_world
from twin_realms.models import WorldEvent


def test_living_target_cannot_be_narrated_as_killed():
    narrator = NarrativeGenerator(llm=lambda prompt: "You kill the malformed instantly.")
    engine = TwinRealmsEngine(narrator=narrator)

    result = engine.turn("Attack the malformed.")

    assert result.event.facts["target_alive"]
    assert "kill" not in result.narrative.lower()
    assert narrator.last_guard_violations == ["living_target_described_as_dead"]


def test_missed_attack_cannot_be_narrated_as_a_hit():
    narrator = NarrativeGenerator(llm=lambda prompt: "Your blade strikes and kills it.")
    state = build_foundation_world()
    event = WorldEvent(
        id="turn:1",
        turn=1,
        event_type="attack_resolved",
        actor_id="char:player",
        target_id="char:malformed",
        accepted=True,
        facts={
            "missed": True,
            "damage": 0,
            "target_health_after": 70,
            "target_alive": True,
            "stamina_spent": 10,
            "stamina_after": 62,
        },
        intent={},
    )

    narrative = narrator.render(event, state)

    assert narrative == "Wayfarer's attack misses Malformed."
    assert narrator.last_guard_violations == [
        "miss_described_as_hit",
        "living_target_described_as_dead",
    ]


def test_rejected_fold_cannot_be_narrated_as_successful_teleportation():
    narrator = NarrativeGenerator(llm=lambda prompt: "You successfully teleport behind it.")
    engine = TwinRealmsEngine(narrator=narrator)

    result = engine.turn("Fold space 40m behind the malformed.")

    assert "fails" in result.narrative.lower()
    assert narrator.last_guard_violations == ["rejected_action_described_as_success"]


def test_narration_transport_failure_uses_resolved_fallback():
    def unavailable(prompt):
        raise RuntimeError("model server unavailable")

    narrator = NarrativeGenerator(
        llm=unavailable,
        transport_cooldown=60,
    )
    engine = TwinRealmsEngine(narrator=narrator)

    first = engine.turn("Rest and recover.")
    second = engine.turn("Rest and recover.")

    assert "recovers" in first.narrative
    assert "recovers" in second.narrative
    assert narrator.llm_failure_count == 1
    assert narrator.last_llm_error == "model server unavailable"
    assert engine.verify_replay()
