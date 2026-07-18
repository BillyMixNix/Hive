import pytest

from twin_realms import (
    FrontendBoundary,
    TwinRealmsEngine,
    TwinRealmsRuntime,
    build_core_loop_world,
    build_tarrow_aftermath_world,
)
from twin_realms.models import ActionIntent


def _boundary(state):
    runtime = TwinRealmsRuntime(TwinRealmsEngine(state), mode="baseline")
    return FrontendBoundary(runtime)


def test_frontend_exports_world_state_positions_and_player_commands():
    boundary = _boundary(build_core_loop_world())

    exported = boundary.export_world_state()

    assert exported["schema"] == "twin_realms.frontend.v1"
    assert exported["player_id"] == "char:player"
    assert exported["state_digest"] == boundary.engine.simulator.state_digest(
        boundary.engine.state
    )
    assert exported["locations"]["loc:camp"]["position"].keys() == {"x", "y", "z"}
    assert exported["entities"]["char:player"]["is_player"] is True
    assert exported["entities"]["char:player"]["position"].keys() == {"x", "y", "z"}
    assert exported["resources"]["resource:field_supplies"]["kind"] == "supplies"
    assert {
        command["command"] for command in exported["available_player_commands"]
    } >= {"wait", "rest", "observe", "move"}
    assert any(
        command["intent"]["destination_id"] == "loc:den"
        for command in exported["available_player_commands"]
        if command["command"] == "move"
    )


def test_frontend_submits_intention_and_receives_resolved_hooks():
    boundary = _boundary(build_core_loop_world())
    move_to_den = next(
        command
        for command in boundary.player_commands()
        if command["command"] == "move"
        and command["intent"]["destination_id"] == "loc:den"
    )

    result = boundary.submit_player_intention(move_to_den)

    assert result["schema"] == "twin_realms.frontend.turn.v1"
    assert result["accepted"] is True
    assert result["after_state_digest"] == result["world_state"]["state_digest"]
    assert boundary.engine.state.characters["char:player"].location_id == "loc:den"
    assert result["events"][0]["source"] == "player"
    assert result["events"][0]["animation"] == "move"
    assert result["events"][0]["event_type"] == "moved"
    hostile_events = [
        event for event in result["events"] if event["actor_id"] == "char:hostile"
    ]
    assert hostile_events
    assert hostile_events[0]["combat"]["damage"] > 0
    assert hostile_events[0]["message"] == hostile_events[0]["combat"]["log"]
    assert boundary.engine.verify_replay()


def test_frontend_cannot_directly_control_non_player_actor():
    boundary = _boundary(build_core_loop_world())
    before = boundary.engine.simulator.state_digest(boundary.engine.state)

    with pytest.raises(ValueError):
        boundary.submit_player_intention(
            ActionIntent("move", "char:worker", destination_id="loc:field")
        )

    assert boundary.engine.simulator.state_digest(boundary.engine.state) == before
    assert boundary.engine.events == []


def test_frontend_invalid_player_intention_is_rejected_by_backend():
    boundary = _boundary(build_core_loop_world())

    result = boundary.submit_player_intention({"command": "spawn_gold"})

    assert result["accepted"] is False
    assert result["events"][0]["animation"] == "reject"
    assert result["events"][0]["reason"] == "intent could not be interpreted"
    assert "spawn_gold" not in boundary.engine.state.flags
    assert boundary.engine.verify_replay()


def test_frontend_exports_tarrow_settlement_and_world_tick_events():
    boundary = _boundary(build_tarrow_aftermath_world())

    initial = boundary.export_world_state()
    result = boundary.submit_player_intention("rest")

    assert "settlement:tarrow" in initial["settlements"]
    assert "settlement:tarrow" in result["world_state"]["settlements"]
    world_events = [
        event for event in result["events"] if event["source"] == "world"
    ]
    assert world_events
    assert world_events[-1]["animation"] == "world_tick"
    assert world_events[-1]["facts"]["settlement_changes"]
    assert boundary.engine.verify_replay()
