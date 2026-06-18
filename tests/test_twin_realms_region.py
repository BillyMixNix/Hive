from twin_realms import (
    AffordanceBuilder,
    SituationalAwarenessBuilder,
    TwinRealmsEngine,
    build_willow_region_world,
)
from twin_realms.models import ActionIntent


def test_region_has_connected_social_and_economic_structure():
    state = build_willow_region_world()
    engine = TwinRealmsEngine(state)

    assert len(state.characters) == 20
    assert len(state.locations) == 9
    assert len(state.factions) == 3
    assert len(state.resource_nodes) == 4
    assert all(character.home_location_id for character in state.characters.values())
    assert all(character.schedule for character in state.characters.values())
    assert all(character.needs for character in state.characters.values())
    assert engine.simulator.assert_invariants(state)
    assert engine.verify_replay()


def test_resources_feed_deterministic_crafting_and_replay():
    engine = TwinRealmsEngine(build_willow_region_world(seed=23))
    blacksmith = "char:blacksmith"

    engine.apply_intent(ActionIntent(
        "move", blacksmith, destination_id="loc:forest_edge"
    ))
    engine.apply_intent(ActionIntent(
        "move", blacksmith, destination_id="loc:stone_quarry"
    ))
    for _ in range(2):
        gathered = engine.apply_intent(ActionIntent(
            "gather",
            blacksmith,
            parameters={"resource_node_id": "resource:iron_vein"},
        ))
        assert gathered.event.accepted
    engine.apply_intent(ActionIntent(
        "move", blacksmith, destination_id="loc:forest_edge"
    ))
    engine.apply_intent(ActionIntent(
        "gather",
        blacksmith,
        parameters={"resource_node_id": "resource:willow_timber"},
    ))
    engine.apply_intent(ActionIntent(
        "move", blacksmith, destination_id="loc:willow_village"
    ))
    crafted = engine.apply_intent(ActionIntent(
        "craft",
        blacksmith,
        parameters={"recipe_id": "iron_sword"},
    ))

    item_id = crafted.event.facts["item_id"]
    assert crafted.event.accepted
    assert item_id in engine.state.characters[blacksmith].inventory
    assert engine.state.items[item_id].crafted_by == blacksmith
    assert engine.state.items[item_id].power >= 5
    assert engine.verify_replay()


def test_trade_transfers_currency_item_and_faction_reputation():
    engine = TwinRealmsEngine(build_willow_region_world())
    player = engine.state.characters["char:player"]
    blacksmith = engine.state.characters["char:blacksmith"]
    before_coins = player.coins

    traded = engine.apply_intent(ActionIntent(
        "trade",
        player.id,
        target_id=blacksmith.id,
        parameters={"item_id": "item:smithing_hammer"},
    ))

    assert traded.event.accepted
    assert "item:smithing_hammer" in player.inventory
    assert player.coins < before_coins
    assert player.reputation["faction:willow_council"] == 1
    assert engine.verify_replay()


def test_schedule_moves_actor_to_world_defined_destination():
    engine = TwinRealmsEngine(build_willow_region_world())
    guard = engine.state.characters["char:guard_mira"]
    assert guard.location_id == "loc:village_market"

    followed = engine.apply_intent(ActionIntent(
        "follow_schedule",
        guard.id,
    ))

    assert followed.event.accepted
    assert followed.event.facts["period"] == "night"
    assert guard.location_id == "loc:willow_village"
    assert engine.verify_replay()


def test_cultivation_site_supports_breakthrough():
    engine = TwinRealmsEngine(build_willow_region_world())
    player_id = engine.state.player_id
    for destination_id in (
        "loc:village_market",
        "loc:river_crossing",
        "loc:ash_monastery",
    ):
        engine.apply_intent(ActionIntent(
            "move", player_id, destination_id=destination_id
        ))
    for _ in range(25):
        engine.apply_intent(ActionIntent("cultivate", player_id))
        engine.apply_intent(ActionIntent("rest", player_id))

    player = engine.state.characters[player_id]
    assert player.cultivation_stage == "breath"
    assert player.realm == 2
    assert engine.verify_replay()


def test_theft_changes_faction_reputation_and_alert_level():
    engine = TwinRealmsEngine(build_willow_region_world())
    result = engine.apply_intent(ActionIntent(
        "steal",
        "char:player",
        target_id="char:blacksmith",
        parameters={"item_id": "item:smithing_hammer"},
    ))

    assert result.event.accepted
    assert engine.state.characters["char:player"].reputation[
        "faction:willow_council"
    ] == -10
    assert engine.state.flags["kingdom_alert_level"] == "medium"
    assert engine.verify_replay()


def test_region_systems_are_visible_to_agents_without_forcing_actions():
    state = build_willow_region_world()
    options = AffordanceBuilder().build(state.player_id, state)
    packet = SituationalAwarenessBuilder().build(
        state.player_id,
        state,
        options,
        [],
    )
    actions = {option["intent"].action for option in options}

    assert {"cultivate", "trade", "work"}.issubset(actions)
    assert packet["regional_context"]["faction_id"] == (
        "faction:willow_council"
    )
    assert packet["regional_context"]["needs"]["safety"] == 80


def test_equipment_defense_and_world_pressure_changes_are_resolved_truth():
    state = build_willow_region_world()
    state.characters["char:bandit_scout"].health = 1
    engine = TwinRealmsEngine(state)
    guard = "char:guard_mira"
    engine.apply_intent(ActionIntent(
        "equip",
        guard,
        parameters={"item_id": "item:guard_shield"},
    ))
    engine.apply_intent(ActionIntent(
        "move",
        "char:player",
        destination_id="loc:village_market",
    ))
    defended = engine.apply_intent(ActionIntent(
        "attack",
        "char:player",
        target_id=guard,
    ))
    assert defended.event.facts["defense_power"] == 3

    scout = engine.state.characters["char:bandit_scout"]
    engine.apply_intent(ActionIntent(
        "move",
        "char:player",
        destination_id="loc:willow_village",
    ))
    engine.apply_intent(ActionIntent(
        "move",
        "char:player",
        destination_id="loc:forest_edge",
    ))
    resolved = engine.apply_intent(ActionIntent(
        "attack",
        "char:player",
        target_id=scout.id,
    ))

    assert resolved.event.facts["world_pressure_changes"][
        "hollow_hand_raids"
    ] == {"before": 20, "after": 12}
    assert engine.verify_replay()
