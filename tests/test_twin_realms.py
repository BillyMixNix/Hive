import json

import pytest

from twin_realms import TwinRealmsEngine, WorldKnowledge, build_foundation_world
from twin_realms.models import ActionIntent


def test_space_fold_resolves_truth_before_narration():
    prompts = []
    engine = TwinRealmsEngine()
    engine.narrator.llm = lambda prompt: prompts.append(prompt) or "The world stretches."

    result = engine.turn("I fold space 6m and move behind the malformed.")

    player = engine.state.characters["char:player"]
    assert result.event.accepted
    assert result.event.event_type == "space_folded"
    assert result.event.facts["positioned_behind"] == "char:malformed"
    assert player.stamina == 54
    assert engine.state.flags["twin_realm_stability"] == 82
    assert "resolved_facts" in prompts[0]
    assert '"stamina_after": 54' in prompts[0]


def test_invalid_space_fold_changes_only_turn():
    engine = TwinRealmsEngine()
    before = engine.state.to_dict()

    result = engine.turn("Fold space 40m behind the malformed.")

    assert not result.event.accepted
    assert result.event.reason == "distance exceeds stable range"
    assert engine.state.turn == before["turn"] + 1
    assert engine.state.characters["char:player"].stamina == before["characters"]["char:player"]["stamina"]
    assert engine.state.flags["twin_realm_stability"] == before["flags"]["twin_realm_stability"]


def test_lessons_require_explicit_promotion():
    knowledge = WorldKnowledge()
    for _ in range(3):
        knowledge.observe(
            "space_fold_extended_range",
            "A stable fold can reach twelve meters.",
            confirmed=True,
        )
    unpromoted = TwinRealmsEngine(knowledge=knowledge)
    rejected = unpromoted.turn("Fold space 12m behind the malformed.")
    assert not rejected.event.accepted

    promoted = TwinRealmsEngine(knowledge=knowledge)
    promoted.promote_knowledge("space_fold_extended_range")
    accepted = promoted.turn("Fold space 12m behind the malformed.")
    assert accepted.event.accepted


def test_snapshot_round_trip_and_replay(tmp_path):
    engine = TwinRealmsEngine()
    commands = [
        "Observe the malformed.",
        "Attack the malformed.",
        "Rest and recover.",
        "Fold space behind the malformed.",
    ]
    for command in commands:
        engine.turn(command)
    path = tmp_path / "world.json"
    engine.save(path)

    loaded = TwinRealmsEngine.load(path)

    assert loaded.snapshot() == engine.snapshot()
    assert loaded.verify_replay()
    assert json.loads(path.read_text(encoding="utf-8"))["state"]["turn"] == 4


def test_replay_detects_tampered_history():
    engine = TwinRealmsEngine()
    engine.turn("Attack the malformed.")
    event = engine.events[0].to_dict()
    event["facts"]["damage"] += 99
    engine.events[0] = type(engine.events[0]).from_dict(event)

    with pytest.raises(AssertionError, match="replay diverged"):
        engine.replay()


def test_one_thousand_turns_remain_coherent_and_replayable():
    engine = TwinRealmsEngine(build_foundation_world(seed=19))
    pattern = [
        ActionIntent("observe", "char:player", target_id="char:malformed"),
        ActionIntent("attack", "char:player", target_id="char:malformed"),
        ActionIntent("rest", "char:player"),
        ActionIntent("space_fold", "char:player", target_id="char:malformed", distance=5),
        ActionIntent("rest", "char:player"),
    ]

    for index in range(1000):
        engine.apply_intent(pattern[index % len(pattern)])

    assert engine.state.turn == 1000
    assert len(engine.events) == 1000
    assert engine.simulator.assert_invariants(engine.state)
    assert engine.verify_replay()


def test_realm_stability_remains_bounded_after_repeated_folds():
    engine = TwinRealmsEngine()
    fold = ActionIntent("space_fold", "char:player", distance=5)
    rest = ActionIntent("rest", "char:player")

    for _ in range(100):
        engine.apply_intent(fold)
        engine.apply_intent(rest)

    assert engine.state.flags["twin_realm_stability"] == 0
    assert engine.verify_replay()
