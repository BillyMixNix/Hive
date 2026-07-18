from twin_realms import (
    TerminalPlayer,
    TwinRealmsEngine,
    TwinRealmsRuntime,
    build_core_loop_world,
)
from twin_realms.models import ActionIntent


def _tick(engine, count=1):
    result = None
    for _ in range(count):
        result = engine.apply_intent(ActionIntent("world_tick", engine.state.player_id))
    return result


def test_world_tick_triggers_request_shortage_and_rumor_without_player_action():
    engine = TwinRealmsEngine(build_core_loop_world())

    result = _tick(engine, 2)
    events = engine.state.flags["emergent_events"]
    worker = engine.state.characters["char:worker"]

    assert result.event.facts["emergent_event_changes"] == [{
        "event_id": "core_supply_shortage",
        "change": "triggered",
        "kind": "resource_shortage",
        "requester_id": "char:worker",
        "deadline_turn": 6,
    }]
    assert events["core_supply_shortage"]["status"] == "active"
    assert worker.memories[-1]["event"] == "requested_supply_help"
    assert engine.state.flags["world_pressures"]["camp_supply_shortage"]["severity"] == 35
    assert engine.state.flags["rumors"][-1]["event"] == "worker_requests_supply_help"
    assert engine.verify_replay()


def test_ignored_questless_event_changes_world_state():
    engine = TwinRealmsEngine(build_core_loop_world())

    result = _tick(engine, 6)
    events = engine.state.flags["emergent_events"]
    worker = engine.state.characters["char:worker"]

    assert events["core_supply_shortage"]["status"] == "ignored"
    assert worker.memories[-1]["event"] == "supply_shortage_ignored"
    assert worker.health == 25
    assert engine.state.flags["world_pressures"]["camp_supply_shortage"]["severity"] == 70
    assert engine.state.flags["emergent_events"]["field_danger_tracks"]["status"] == "active"
    assert engine.state.locations["loc:field"].danger == 1
    assert any(
        change["event_id"] == "core_supply_shortage"
        and change["change"] == "ignored"
        for change in result.event.facts["emergent_event_changes"]
    )
    assert engine.verify_replay()


def test_player_can_intervene_without_quest_journal():
    engine = TwinRealmsEngine(build_core_loop_world())
    _tick(engine, 2)

    move = engine.turn("move to Field")
    gather = engine.turn("gather supplies")
    worker = engine.state.characters["char:worker"]
    event = engine.state.flags["emergent_events"]["core_supply_shortage"]

    assert move.event.accepted
    assert gather.event.accepted
    assert event["status"] == "resolved"
    assert event["resolved_by"] == "char:player"
    assert gather.event.facts["event_changes"] == [{
        "event_id": "core_supply_shortage",
        "change": "resolved",
        "kind": "player_intervention",
        "pressure_after": 10,
    }]
    assert worker.memories[-1]["event"] == "player_answered_supply_request"
    assert worker.relationships["char:player"] == 10
    assert engine.state.flags["rumors"][-1]["event"] == "supplies_recovered"

    _tick(engine, 4)

    assert engine.state.flags["emergent_events"]["core_supply_shortage"]["status"] == "resolved"
    assert worker.health == 30
    assert engine.verify_replay()


def test_wait_day_surfaces_questless_event_changes(tmp_path):
    outputs = []
    runtime = TwinRealmsRuntime(
        TwinRealmsEngine(build_core_loop_world()),
        mode="baseline",
    )
    session = TerminalPlayer(
        runtime,
        save_path=tmp_path / "questless-save.json",
        output_fn=outputs.append,
    )

    assert session.handle("wait day")

    rendered = "\n".join(outputs)
    assert "core supply shortage triggered" in rendered
    assert "core supply shortage ignored" in rendered
    assert "field danger tracks triggered" in rendered
    assert session.engine.verify_replay()
