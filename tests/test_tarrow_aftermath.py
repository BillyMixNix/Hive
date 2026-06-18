from twin_realms import (
    TwinRealmsEngine,
    build_tarrow_aftermath_world,
)
from twin_realms.fidelity import (
    FIDELITY_BACKGROUND,
    FIDELITY_HIVE,
    FIDELITY_LEADER,
    FIDELITY_REACTIVE,
    FIDELITY_SCHEDULED,
    get_fidelity,
)
from twin_realms.models import ActionIntent


def test_tarrow_aftermath_has_composable_demo_parts():
    state = build_tarrow_aftermath_world()
    tiers = {
        get_fidelity(character)
        for character in state.characters.values()
    }

    assert state.flags["scenario_id"] == "tarrow_aftermath"
    assert len(state.characters) == 20
    assert len(state.locations) == 5
    assert len(state.factions) == 2
    assert set(state.flags["village_pressures"]) == {
        "fear",
        "food",
        "medicine",
        "trust_in_ren",
        "malformed_rumors",
    }
    assert {
        FIDELITY_BACKGROUND,
        FIDELITY_SCHEDULED,
        FIDELITY_REACTIVE,
        FIDELITY_HIVE,
        FIDELITY_LEADER,
    }.issubset(tiers)
    assert TwinRealmsEngine(state).verify_replay()


def test_tarrow_day_seven_differs_without_player_forcing_changes(tmp_path):
    engine = TwinRealmsEngine(build_tarrow_aftermath_world())
    initial_pressures = dict(engine.state.flags["village_pressures"])
    initial_memories = {
        actor_id: len(character.memories)
        for actor_id, character in engine.state.characters.items()
    }

    for _ in range(6 * 24):
        result = engine.apply_intent(ActionIntent(
            "world_tick",
            engine.state.player_id,
        ))
        assert result.event.accepted

    changed_pressures = engine.state.flags["village_pressures"]
    changed_memories = {
        actor_id: len(character.memories)
        for actor_id, character in engine.state.characters.items()
    }

    assert engine.state.flags["current_day"] == 7
    assert changed_pressures != initial_pressures
    assert any(
        changed_memories[actor_id] > count
        for actor_id, count in initial_memories.items()
    )
    assert engine.verify_replay()

    save_path = tmp_path / "tarrow-day-seven.json"
    engine.save(save_path)
    loaded = TwinRealmsEngine.load(save_path)
    assert loaded.snapshot() == engine.snapshot()
