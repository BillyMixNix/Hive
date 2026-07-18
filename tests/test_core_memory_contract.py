from twin_realms import TwinRealmsEngine, build_core_loop_world
from twin_realms.models import ActionIntent


def test_player_removing_hostile_is_remembered_and_improves_reputation():
    state = build_core_loop_world()
    state.characters["char:player"].location_id = "loc:den"
    state.characters["char:hostile"].health = 5
    engine = TwinRealmsEngine(state)

    result = engine.turn("attack hostile")
    worker = engine.state.characters["char:worker"]
    player = engine.state.characters["char:player"]

    assert result.event.accepted
    assert engine.state.characters["char:hostile"].alive is False
    assert worker.memories[-1]["event"] == "player_removed_hostile"
    assert worker.relationships["char:player"] == 15
    assert player.reputation["faction:camp"] == 10
    assert result.event.facts["consequence_changes"]["memory_events"] == [
        {"actor_id": "char:worker", "event": "player_removed_hostile"}
    ]
    assert engine.verify_replay()


def test_player_harming_npc_changes_memory_reputation_and_behavior():
    state = build_core_loop_world()
    state.characters["char:player"].location_id = "loc:field"
    state.characters["char:worker"].location_id = "loc:field"
    engine = TwinRealmsEngine(state)

    attack = engine.turn("attack worker")
    worker = engine.state.characters["char:worker"]
    player = engine.state.characters["char:player"]

    assert attack.event.accepted
    assert worker.alive is True
    assert worker.memories[-1]["event"] == "player_harmed_me"
    assert worker.relationships["char:player"] == -20
    assert player.reputation["faction:camp"] == -15

    tick = engine.apply_intent(ActionIntent("world_tick", engine.state.player_id))
    update = tick.event.facts["npc_updates"][0]

    assert update["task"] == "avoid_player"
    assert update["location_after"] == "loc:camp"
    assert engine.verify_replay()


def test_theft_records_compact_memory_and_faction_reputation():
    engine = TwinRealmsEngine(build_core_loop_world())

    result = engine.turn("steal ration from worker")
    worker = engine.state.characters["char:worker"]
    player = engine.state.characters["char:player"]

    assert result.event.accepted
    assert "item:field_ration" in player.inventory
    assert worker.memories[-1] == {
        "turn": 1,
        "event": "player_stole_from_me",
        "actor_id": "char:player",
        "target_id": "char:worker",
        "item_id": "item:field_ration",
    }
    assert worker.relationships["char:player"] == -15
    assert player.reputation["faction:camp"] == -10
    assert result.event.facts["witnessed_by"] == ["char:worker"]
    assert engine.verify_replay()
