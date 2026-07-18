from .models import Character, Faction, Item, Location, ResourceNode, WorldState


def build_core_loop_world(seed=3):
    locations = {
        "loc:camp": Location(
            id="loc:camp",
            name="Camp",
            connections=["loc:den", "loc:field"],
            danger=0,
        ),
        "loc:den": Location(
            id="loc:den",
            name="Den",
            connections=["loc:camp"],
            danger=2,
        ),
        "loc:field": Location(
            id="loc:field",
            name="Field",
            connections=["loc:camp"],
            danger=0,
        ),
    }
    characters = {
        "char:player": Character(
            id="char:player",
            name="Player",
            location_id="loc:camp",
            realm=1,
            stamina=40,
            max_stamina=40,
            health=42,
            max_health=42,
            inventory=["item:short_sword"],
            equipment={"main_hand": "item:short_sword"},
            skill_mastery={"swordsmanship": 2},
        ),
        "char:hostile": Character(
            id="char:hostile",
            name="Hostile",
            location_id="loc:den",
            realm=1,
            stamina=40,
            max_stamina=40,
            health=48,
            max_health=48,
            skill_mastery={"swordsmanship": 2},
            tags=["hostile"],
        ),
        "char:worker": Character(
            id="char:worker",
            name="Worker",
            location_id="loc:camp",
            realm=1,
            stamina=32,
            max_stamina=32,
            health=30,
            max_health=30,
            inventory=["item:field_ration"],
            relationships={"char:player": 0},
            skill_mastery={"labor": 2},
            jobs={"worker": 2},
            faction_id="faction:camp",
            home_location_id="loc:camp",
            schedule={
                "night": "loc:camp",
                "dawn": "loc:field",
                "day": "loc:field",
                "dusk": "loc:camp",
            },
            needs={"hunger": 20, "fatigue": 10, "safety": 80},
            tags=["worker"],
        ),
    }
    items = {
        "item:short_sword": Item(
            id="item:short_sword",
            name="Short Sword",
            kind="weapon",
            slot="main_hand",
            power=4,
            skill="swordsmanship",
        ),
        "item:field_ration": Item(
            id="item:field_ration",
            name="Field Ration",
            kind="consumable",
            value=2,
        ),
    }
    factions = {
        "faction:camp": Faction(
            id="faction:camp",
            name="Camp",
            headquarters_id="loc:camp",
            values=["safety", "work"],
        ),
    }
    return WorldState(
        turn=0,
        seed=seed,
        player_id="char:player",
        characters=characters,
        locations=locations,
        items=items,
        ground_items={location_id: [] for location_id in locations},
        factions=factions,
        resource_nodes={
            "resource:field_supplies": ResourceNode(
                id="resource:field_supplies",
                location_id="loc:field",
                resource_kind="supplies",
                quantity=2,
                capacity=2,
                regen_interval=99,
            ),
        },
        flags={
            "scenario_id": "core_loop",
            "core_loop": True,
            "game_over": False,
            "victory": False,
            "defeat": False,
            "twin_realm_stability": 100,
            "item_ids": sorted(items),
            "day_length": 24,
            "current_day": 1,
            "skills": ["labor", "swordsmanship"],
            "jobs": ["worker"],
            "job_sites": {"worker": ["loc:field"]},
            "world_pressures": {
                "camp_supply_shortage": {
                    "source_id": "resource:field_supplies",
                    "severity": 0,
                    "affected_locations": ["loc:camp"],
                },
                "field_danger": {
                    "source_id": "loc:field",
                    "severity": 0,
                    "affected_locations": ["loc:field"],
                },
            },
            "rumors": [],
            "emergent_events": {},
            "event_history": [],
        },
    )


def build_foundation_world(seed=7, *, malformed_spawn_turn=0):
    locations = {
        "loc:willow_village": Location(
            id="loc:willow_village",
            name="Willow Village",
            connections=["loc:broken_shrine", "loc:forest_edge"],
            danger=1,
        ),
        "loc:broken_shrine": Location(
            id="loc:broken_shrine",
            name="Broken Shrine",
            connections=["loc:willow_village", "loc:forest_edge"],
            danger=3,
        ),
        "loc:forest_edge": Location(
            id="loc:forest_edge",
            name="Forest Edge",
            connections=["loc:willow_village", "loc:broken_shrine"],
            danger=2,
        ),
    }
    characters = {
        "char:player": Character(
            id="char:player",
            name="Wayfarer",
            location_id="loc:broken_shrine",
            realm=3,
            affinity="space",
            stamina=72,
            techniques=["space_fold", "iron_sword"],
            injuries=["strained_meridian"],
            inventory=["item:iron_sword", "item:cultivation_manual"],
            relationships={
                "char:swordsman": 61,
                "char:elder": 20,
            },
        ),
        "char:malformed": Character(
            id="char:malformed",
            name="Malformed",
            location_id="loc:broken_shrine",
            realm=2,
            affinity="corruption",
            stamina=80,
            health=70,
            max_health=70,
            techniques=["distortion_hide"],
            tags=["hostile", "malformed"],
            active=malformed_spawn_turn <= 0,
            spawn_turn=malformed_spawn_turn or None,
        ),
        "char:swordsman": Character(
            id="char:swordsman",
            name="Swordsman Ren",
            location_id="loc:willow_village",
            realm=4,
            affinity="metal",
            techniques=["sword_intent"],
        ),
        "char:elder": Character(
            id="char:elder",
            name="Elder Mara",
            location_id="loc:willow_village",
            realm=2,
            affinity="earth",
            tags=["village_elder"],
        ),
        "char:blacksmith": Character(
            id="char:blacksmith",
            name="Blacksmith Oru",
            location_id="loc:willow_village",
            realm=1,
            affinity="fire",
            inventory=["item:smithing_hammer"],
            tags=["merchant"],
        ),
        "char:herbalist": Character(
            id="char:herbalist",
            name="Herbalist Sen",
            location_id="loc:forest_edge",
            realm=1,
            affinity="wood",
            tags=["healer"],
        ),
    }
    items = {
        "item:iron_sword": Item(
            id="item:iron_sword",
            name="Iron Sword",
            kind="weapon",
            slot="main_hand",
            power=4,
            skill="swordsmanship",
        ),
        "item:cultivation_manual": Item(
            id="item:cultivation_manual",
            name="Foundation Breathing Manual",
            kind="manual",
            skill="cultivation",
        ),
        "item:smithing_hammer": Item(
            id="item:smithing_hammer",
            name="Smithing Hammer",
            kind="tool",
            slot="tool",
            power=1,
            skill="smithing",
        ),
    }
    return WorldState(
        turn=0,
        seed=seed,
        player_id="char:player",
        characters=characters,
        locations=locations,
        items=items,
        ground_items={location_id: [] for location_id in locations},
        flags={
            "kingdom_alert_level": "low",
            "twin_realm_stability": 84,
            "item_ids": [
                "item:iron_sword",
                "item:cultivation_manual",
                "item:smithing_hammer",
            ],
            "complexity_tier": 0,
            "cultivation_stages": [
                "body",
                "breath",
                "foundation",
                "core",
                "ascendant",
            ],
        },
    )


def build_complexity_world(tier=1, seed=7):
    if tier == 3:
        from .region import build_willow_region_world

        return build_willow_region_world(seed=seed)
    if tier not in {1, 2}:
        raise ValueError("complexity tier must be 1, 2, or 3")
    state = build_foundation_world(seed=seed, malformed_spawn_turn=50)
    state.flags["complexity_tier"] = tier
    player = state.characters["char:player"]
    player.location_id = "loc:willow_village"
    player.injuries = []
    player.realm = 1
    player.stamina = player.max_stamina
    player.techniques = ["iron_sword"]
    player.skill_mastery = {
        "swordsmanship": 1,
        "cultivation": 1,
        "foraging": 0,
    }
    player.jobs = {"villager": 1}
    state.characters.update({
        "char:hunter": Character(
            id="char:hunter",
            name="Hunter Vale",
            location_id="loc:forest_edge",
            affinity="wood",
            inventory=["item:hunting_bow"],
            techniques=["aimed_shot"],
            skill_mastery={"archery": 3, "foraging": 2},
            jobs={"hunter": 3},
            tags=["hunter"],
        ),
        "char:farmer": Character(
            id="char:farmer",
            name="Farmer Ilya",
            location_id="loc:willow_village",
            affinity="earth",
            inventory=["item:field_hoe"],
            skill_mastery={"farming": 3},
            jobs={"farmer": 3},
            tags=["farmer"],
        ),
        "char:merchant": Character(
            id="char:merchant",
            name="Merchant Tov",
            location_id="loc:willow_village",
            affinity="none",
            inventory=["item:travel_cloak"],
            skill_mastery={"barter": 3},
            jobs={"merchant": 3},
            tags=["merchant"],
        ),
        "char:apprentice": Character(
            id="char:apprentice",
            name="Apprentice Lio",
            location_id="loc:willow_village",
            affinity="fire",
            skill_mastery={"smithing": 1},
            jobs={"blacksmith": 1},
            tags=["apprentice"],
        ),
    })
    state.items.update({
        "item:hunting_bow": Item(
            id="item:hunting_bow",
            name="Hunting Bow",
            kind="weapon",
            slot="main_hand",
            power=3,
            skill="archery",
        ),
        "item:field_hoe": Item(
            id="item:field_hoe",
            name="Field Hoe",
            kind="tool",
            slot="tool",
            power=1,
            skill="farming",
        ),
        "item:travel_cloak": Item(
            id="item:travel_cloak",
            name="Travel Cloak",
            kind="armor",
            slot="body",
            power=2,
        ),
        "item:healing_herb": Item(
            id="item:healing_herb",
            name="Healing Herb",
            kind="consumable",
            tags=["healing"],
        ),
        "item:wood_bundle": Item(
            id="item:wood_bundle",
            name="Wood Bundle",
            kind="material",
        ),
    })
    state.ground_items["loc:forest_edge"].extend([
        "item:healing_herb",
        "item:wood_bundle",
    ])
    state.flags["item_ids"] = sorted(state.items)
    state.flags["skills"] = [
        "archery",
        "barter",
        "cultivation",
        "farming",
        "foraging",
        "smithing",
        "swordsmanship",
    ]
    state.flags["jobs"] = [
        "blacksmith",
        "farmer",
        "hunter",
        "merchant",
        "villager",
    ]
    if tier == 2:
        state.characters["char:swordsman"].skill_mastery["swordsmanship"] = 5
        state.characters["char:blacksmith"].skill_mastery["smithing"] = 5
        state.characters["char:blacksmith"].jobs["blacksmith"] = 5
    return state
