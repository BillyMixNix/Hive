from twin_realms import (
    TerminalPlayer,
    TwinRealmsEngine,
    TwinRealmsRuntime,
    build_tarrow_aftermath_world,
)
from twin_realms.models import ActionIntent


def _tick(engine, count=1):
    result = None
    for _ in range(count):
        result = engine.apply_intent(ActionIntent("world_tick", engine.state.player_id))
    return result


def _tarrow(state):
    return state.flags["settlements"]["settlement:tarrow"]


def test_tarrow_settlement_layer_starts_inspectable():
    state = build_tarrow_aftermath_world()
    tarrow = _tarrow(state)

    assert tarrow["name"] == "Tarrow"
    assert tarrow["resources"] == {"food": 38, "medicine": 30, "coin": 220}
    assert tarrow["shops"]["blacksmith"]["status"] == "open"
    assert tarrow["shops"]["healer"]["status"] == "strained"
    assert tarrow["workplaces"]["fields"]["status"] == "strained"
    assert len(tarrow["guards"]) == 5
    assert len(tarrow["civilians"]) == 13
    assert tarrow["location_states"]["loc:shrine_road"] == "damaged"
    assert tarrow["location_states"]["loc:watch_post"] == "defended"


def test_tarrow_settlement_updates_from_world_pressures_and_replays():
    engine = TwinRealmsEngine(build_tarrow_aftermath_world())

    result = _tick(engine)
    tarrow = _tarrow(engine.state)

    assert result.event.facts["settlement_changes"]
    assert tarrow["resources"]["food"] == engine.state.flags["village_pressures"]["food"]
    assert tarrow["resources"]["medicine"] == engine.state.flags["village_pressures"]["medicine"]
    assert tarrow["defense_level"] >= 50
    assert tarrow["status"] == "defended"
    assert tarrow["history"]
    assert engine.verify_replay()


def test_tarrow_can_become_poorer_damaged_and_abandoned_from_events():
    state = build_tarrow_aftermath_world()
    state.flags["village_pressures"].update({
        "food": 10,
        "medicine": 15,
        "fear": 90,
        "malformed_rumors": 92,
        "trust_in_ren": 15,
    })
    engine = TwinRealmsEngine(state)

    _tick(engine)
    tarrow = _tarrow(engine.state)

    assert tarrow["prosperity"] == 0
    assert tarrow["hostility_level"] >= 92
    assert tarrow["status"] == "abandoned"
    assert tarrow["population"]["fled"] == 11
    assert tarrow["location_states"]["loc:low_fields"] == "abandoned"
    assert tarrow["location_states"]["loc:watch_post"] == "damaged"
    assert tarrow["shops"]["healer"]["status"] == "strained"
    assert engine.verify_replay()


def test_tarrow_can_become_safer_restored_and_improved_from_events():
    state = build_tarrow_aftermath_world()
    state.flags["village_pressures"].update({
        "food": 70,
        "medicine": 65,
        "fear": 20,
        "malformed_rumors": 20,
        "trust_in_ren": 80,
    })
    engine = TwinRealmsEngine(state)

    _tick(engine)
    tarrow = _tarrow(engine.state)

    assert tarrow["safety_level"] >= 70
    assert tarrow["prosperity"] >= 60
    assert tarrow["status"] == "improved"
    assert tarrow["location_states"]["loc:shrine_road"] == "restored"
    assert tarrow["location_states"]["loc:healer_hut"] == "restored"
    assert tarrow["shops"]["healer"]["status"] == "open"
    assert engine.verify_replay()


def test_carpenter_work_can_restore_damaged_tarrow_location():
    state = build_tarrow_aftermath_world()
    player = state.characters[state.player_id]
    player.jobs["carpenter"] = 1
    engine = TwinRealmsEngine(state)

    result = engine.turn("work carpenter")
    tarrow = _tarrow(engine.state)

    assert result.event.accepted
    assert result.event.facts["settlement_changes"] == [{
        "field": "location_states.loc:shrine_road",
        "before": "damaged",
        "after": "restored",
    }]
    assert tarrow["location_states"]["loc:shrine_road"] == "restored"
    assert tarrow["history"][-1]["actor_id"] == state.player_id
    assert engine.verify_replay()


def test_terminal_village_command_surfaces_settlement_layer(tmp_path):
    outputs = []
    runtime = TwinRealmsRuntime(
        TwinRealmsEngine(build_tarrow_aftermath_world()),
        mode="baseline",
    )
    session = TerminalPlayer(
        runtime,
        save_path=tmp_path / "tarrow-settlement-save.json",
        output_fn=outputs.append,
    )

    assert session.handle("village")

    output = outputs[-1]
    assert "Settlements:" in output
    assert "Tarrow | status defended" in output
    assert "population" in output
    assert "resources coin 220, food 38, medicine 30" in output
    assert "Shrine Road damaged" in output
    assert "shops blacksmith open, healer strained" in output
    assert "workplaces fields strained, watch active" in output
