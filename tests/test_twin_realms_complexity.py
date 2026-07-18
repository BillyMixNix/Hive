from twin_realms import (
    ComplexityStressRunner,
    IntentInterpreter,
    TwinRealmsEngine,
    build_complexity_world,
)
from twin_realms.models import ActionIntent


def test_tier_one_delays_malformed_until_turn_fifty():
    engine = TwinRealmsEngine(build_complexity_world(tier=1))
    interpreter = IntentInterpreter()

    assert not engine.state.characters["char:malformed"].active
    assert interpreter.interpret(
        "Observe the malformed.",
        engine.state,
    ).target_id is None

    for _ in range(49):
        result = engine.apply_intent(ActionIntent("wait", "char:player"))

    assert engine.state.turn == 49
    assert not engine.state.characters["char:malformed"].active
    result = engine.apply_intent(ActionIntent("wait", "char:player"))

    assert result.event.facts["activated_entities"] == ["char:malformed"]
    assert engine.state.characters["char:malformed"].active
    assert engine.verify_replay()


def test_equipment_requires_ownership_and_affects_combat_facts():
    engine = TwinRealmsEngine(build_complexity_world(tier=2))

    equipped = engine.apply_intent(ActionIntent(
        "equip",
        "char:player",
        parameters={"item_id": "item:iron_sword"},
    ))
    attack = engine.apply_intent(ActionIntent(
        "attack",
        "char:player",
        target_id="char:elder",
    ))

    assert equipped.event.accepted
    assert engine.state.characters["char:player"].equipment["main_hand"] == "item:iron_sword"
    assert attack.event.facts["weapon_power"] == 4
    assert attack.event.facts["combat_mastery"] == 1


def test_training_jobs_and_leveling_are_persistent_and_replayable():
    engine = TwinRealmsEngine(build_complexity_world(tier=2))
    for _ in range(12):
        engine.apply_intent(ActionIntent(
            "work",
            "char:player",
            parameters={"job_id": "villager"},
        ))
        engine.apply_intent(ActionIntent("rest", "char:player"))
    engine.apply_intent(ActionIntent(
        "train",
        "char:player",
        parameters={"skill_id": "swordsmanship"},
    ))

    player = engine.state.characters["char:player"]
    assert player.level >= 2
    assert player.jobs["villager"] > 1
    assert player.skill_mastery["swordsmanship"] > 1
    assert engine.verify_replay()


def test_complexity_tiers_expand_world_and_remain_drift_auditable():
    reports = []
    for tier in (0, 1, 2):
        engine, report = ComplexityStressRunner().run(tier, turns=200)
        reports.append(report)
        assert report.replay_consistent
        assert report.invalid_reference_rejections == 0
        assert report.unavailable_actor_rejections == 0
        assert engine.simulator.assert_invariants(engine.state)

    assert reports[0].total_characters < reports[1].total_characters
    assert reports[0].total_items < reports[1].total_items
    assert reports[0].action_diversity < reports[2].action_diversity
