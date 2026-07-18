from twin_realms import TwinRealmsEngine, build_foundation_world
from twin_realms.models import ActionIntent


def test_dropped_inventory_remains_on_ground_until_an_event_moves_it():
    engine = TwinRealmsEngine()
    dropped = engine.turn("Drop the iron sword.")

    assert dropped.event.event_type == "item_dropped"
    assert "item:iron_sword" not in engine.state.characters["char:player"].inventory
    assert "item:iron_sword" in engine.state.ground_items["loc:broken_shrine"]

    for _ in range(100):
        engine.apply_intent(ActionIntent("rest", "char:player"))

    assert "item:iron_sword" in engine.state.ground_items["loc:broken_shrine"]
    assert engine.simulator.assert_invariants(engine.state)


def test_witnessed_theft_persists_in_npc_memory_and_trust():
    world = build_foundation_world()
    world.characters["char:player"].location_id = "loc:willow_village"
    engine = TwinRealmsEngine(world)

    result = engine.turn("Steal the smithing hammer from the blacksmith.")

    assert result.event.event_type == "item_stolen"
    assert result.event.facts["witnessed_by"] == [
        "char:blacksmith",
        "char:elder",
        "char:swordsman",
    ]
    for witness_id in result.event.facts["witnessed_by"]:
        witness = engine.state.characters[witness_id]
        assert witness.relationships["char:player"] == -15
        assert witness.memories[-1] == {
            "turn": 1,
            "event": "witnessed_theft",
            "actor_id": "char:player",
            "target_id": "char:blacksmith",
            "item_id": "item:smithing_hammer",
        }

    for _ in range(25):
        engine.apply_intent(ActionIntent("rest", "char:player"))

    assert engine.state.characters["char:elder"].relationships["char:player"] == -15
    assert engine.state.characters["char:elder"].memories[0]["event"] == "witnessed_theft"
    assert engine.verify_replay()


def test_item_invariant_rejects_duplicate_ownership():
    world = build_foundation_world()
    world.ground_items["loc:broken_shrine"].append("item:iron_sword")

    try:
        TwinRealmsEngine(world).simulator.assert_invariants(world)
    except AssertionError as exc:
        assert "exactly one location" in str(exc)
    else:
        raise AssertionError("duplicate item ownership was accepted")


def test_out_of_range_space_fold_is_rejected_without_state_cost():
    engine = TwinRealmsEngine()
    before = engine.state.to_dict()

    result = engine.turn("Fold space 40m behind the malformed.")

    assert not result.event.accepted
    assert result.event.reason == "distance exceeds stable range"
    assert engine.state.characters["char:player"].stamina == before["characters"]["char:player"]["stamina"]
    assert engine.state.flags["twin_realm_stability"] == before["flags"]["twin_realm_stability"]


def test_dead_character_cannot_act():
    world = build_foundation_world()
    malformed = world.characters["char:malformed"]
    malformed.health = 0
    malformed.alive = False
    engine = TwinRealmsEngine(world)

    result = engine.apply_intent(ActionIntent("rest", "char:malformed"))

    assert not result.event.accepted
    assert result.event.reason == "actor is unavailable"
    assert engine.verify_replay()
