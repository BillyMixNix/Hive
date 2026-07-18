from __future__ import annotations

from .content import build_complexity_world
from .models import Character, Faction, Item, Location, ResourceNode


def build_willow_region_world(seed=7):
    """Build the first complete Twin Realms region."""

    state = build_complexity_world(tier=2, seed=seed)
    state.flags["complexity_tier"] = 3
    state.flags["region_id"] = "region:willow_basin"
    state.flags["day_length"] = 24
    state.flags["settlements"] = {
        "settlement:willow_village": {
            "name": "Willow Village",
            "locations": [
                "loc:willow_village",
                "loc:village_market",
                "loc:terraced_farms",
                "loc:watchtower",
            ],
            "population": 86,
            "food_reserves": 72,
            "security": 58,
            "prosperity": 44,
        }
    }
    state.flags["world_pressures"] = {
        "malformed_corruption": {
            "source_id": "char:malformed",
            "severity": 25,
            "affected_locations": ["loc:broken_shrine"],
        },
        "hollow_hand_raids": {
            "source_id": "faction:hollow_hand",
            "severity": 20,
            "affected_locations": [
                "loc:forest_edge",
                "loc:river_crossing",
            ],
        },
    }
    state.flags["rumors"] = [
        {
            "id": "rumor:folded_roads",
            "subject_id": "item:sealed_journal",
            "origin_location_id": "loc:ash_monastery",
            "confidence": 0.4,
        },
        {
            "id": "rumor:shrine_corruption",
            "subject_id": "char:malformed",
            "origin_location_id": "loc:willow_village",
            "confidence": 0.7,
        },
    ]
    state.flags["cultivation_stages"] = [
        "body",
        "breath",
        "foundation",
        "core",
        "ascendant",
    ]

    state.locations.update({
        "loc:village_market": Location(
            id="loc:village_market",
            name="Willow Market",
            connections=["loc:willow_village", "loc:river_crossing"],
            danger=1,
            settlement_id="settlement:willow_village",
            tags=["market", "lawful"],
        ),
        "loc:terraced_farms": Location(
            id="loc:terraced_farms",
            name="Terraced Farms",
            connections=["loc:willow_village", "loc:river_crossing"],
            danger=1,
            settlement_id="settlement:willow_village",
            tags=["farmland"],
        ),
        "loc:stone_quarry": Location(
            id="loc:stone_quarry",
            name="Stone Quarry",
            connections=["loc:forest_edge", "loc:watchtower"],
            danger=2,
            tags=["mine"],
        ),
        "loc:river_crossing": Location(
            id="loc:river_crossing",
            name="Reedwater Crossing",
            connections=[
                "loc:village_market",
                "loc:terraced_farms",
                "loc:ash_monastery",
            ],
            danger=2,
            tags=["river", "trade_route"],
        ),
        "loc:watchtower": Location(
            id="loc:watchtower",
            name="North Watchtower",
            connections=["loc:willow_village", "loc:stone_quarry"],
            danger=2,
            settlement_id="settlement:willow_village",
            tags=["guard_post", "lawful"],
        ),
        "loc:ash_monastery": Location(
            id="loc:ash_monastery",
            name="Ashen Reed Monastery",
            connections=["loc:river_crossing", "loc:broken_shrine"],
            danger=1,
            tags=["cultivation_site", "sanctuary"],
        ),
    })
    _connect(state, "loc:willow_village", "loc:village_market")
    _connect(state, "loc:willow_village", "loc:terraced_farms")
    _connect(state, "loc:willow_village", "loc:watchtower")
    _connect(state, "loc:forest_edge", "loc:stone_quarry")
    _connect(state, "loc:broken_shrine", "loc:ash_monastery")
    for location in state.locations.values():
        location.region_id = "region:willow_basin"
    state.locations["loc:willow_village"].settlement_id = (
        "settlement:willow_village"
    )
    state.locations["loc:willow_village"].tags = ["residential", "lawful"]
    state.locations["loc:forest_edge"].tags = ["wilderness", "foraging"]
    state.locations["loc:broken_shrine"].tags = ["ruin", "corruption"]

    state.factions = {
        "faction:willow_council": Faction(
            id="faction:willow_council",
            name="Willow Council",
            headquarters_id="loc:willow_village",
            values=["stability", "trade", "mutual_defense"],
            relations={
                "faction:ashen_reed": 35,
                "faction:hollow_hand": -80,
            },
            treasury=800,
            laws=["no_theft", "no_unprovoked_violence", "market_tax"],
        ),
        "faction:ashen_reed": Faction(
            id="faction:ashen_reed",
            name="Ashen Reed Sect",
            headquarters_id="loc:ash_monastery",
            values=["discipline", "cultivation", "contain_corruption"],
            relations={
                "faction:willow_council": 35,
                "faction:hollow_hand": -60,
            },
            treasury=500,
            laws=["protect_journals", "respect_sanctuary"],
        ),
        "faction:hollow_hand": Faction(
            id="faction:hollow_hand",
            name="Hollow Hand",
            headquarters_id="loc:broken_shrine",
            values=["secrecy", "plunder", "corruption"],
            relations={
                "faction:willow_council": -80,
                "faction:ashen_reed": -60,
            },
            treasury=120,
            laws=[],
        ),
    }

    state.characters.update({
        "char:guard_captain": Character(
            id="char:guard_captain",
            name="Captain Dena",
            location_id="loc:watchtower",
            realm=2,
            affinity="metal",
            techniques=["shield_line"],
            inventory=["item:guard_spear"],
            skill_mastery={"swordsmanship": 7, "leadership": 8},
            jobs={"guard": 8},
            tags=["guard"],
        ),
        "char:guard_mira": Character(
            id="char:guard_mira",
            name="Guard Mira",
            location_id="loc:village_market",
            affinity="earth",
            inventory=["item:guard_shield"],
            skill_mastery={"swordsmanship": 4},
            jobs={"guard": 4},
            tags=["guard"],
        ),
        "char:innkeeper": Character(
            id="char:innkeeper",
            name="Innkeeper Pell",
            location_id="loc:willow_village",
            inventory=["item:pantry_key"],
            skill_mastery={"cooking": 6, "barter": 4},
            jobs={"innkeeper": 7},
            tags=["merchant"],
        ),
        "char:carpenter": Character(
            id="char:carpenter",
            name="Carpenter Nara",
            location_id="loc:village_market",
            affinity="wood",
            inventory=["item:carpenter_adze"],
            skill_mastery={"carpentry": 7},
            jobs={"carpenter": 7},
        ),
        "char:miner": Character(
            id="char:miner",
            name="Miner Jori",
            location_id="loc:stone_quarry",
            affinity="earth",
            inventory=["item:mining_pick"],
            skill_mastery={"mining": 6},
            jobs={"miner": 6},
        ),
        "char:ferryman": Character(
            id="char:ferryman",
            name="Ferryman Su",
            location_id="loc:river_crossing",
            affinity="water",
            inventory=["item:fishing_net"],
            skill_mastery={"fishing": 6},
            jobs={"fisher": 6},
        ),
        "char:archivist": Character(
            id="char:archivist",
            name="Archivist Yara",
            location_id="loc:ash_monastery",
            realm=2,
            affinity="air",
            inventory=["item:sealed_journal"],
            skill_mastery={"cultivation": 8, "lore": 9},
            jobs={"archivist": 8},
            tags=["scholar"],
        ),
        "char:disciple": Character(
            id="char:disciple",
            name="Disciple Teren",
            location_id="loc:ash_monastery",
            realm=2,
            affinity="fire",
            techniques=["ember_palm"],
            inventory=["item:sect_robes"],
            skill_mastery={"cultivation": 6, "unarmed": 5},
            jobs={"disciple": 5},
            tags=["cultivator"],
        ),
        "char:bandit_scout": Character(
            id="char:bandit_scout",
            name="Hollow Scout",
            location_id="loc:forest_edge",
            affinity="shadow",
            inventory=["item:bandit_knife"],
            skill_mastery={"stealth": 5, "swordsmanship": 3},
            jobs={"raider": 4},
            tags=["hostile", "bandit"],
        ),
        "char:bandit_chief": Character(
            id="char:bandit_chief",
            name="Hollow Chief",
            location_id="loc:broken_shrine",
            realm=2,
            affinity="corruption",
            health=120,
            max_health=120,
            inventory=["item:corrupted_blade"],
            techniques=["dread_aura"],
            skill_mastery={"swordsmanship": 8},
            jobs={"raider": 9},
            tags=["hostile", "bandit", "leader"],
        ),
    })

    state.items.update({
        "item:guard_spear": Item(
            id="item:guard_spear", name="Guard Spear", kind="weapon",
            slot="main_hand", power=5, skill="swordsmanship", value=45,
        ),
        "item:guard_shield": Item(
            id="item:guard_shield", name="Willow Shield", kind="armor",
            slot="off_hand", power=3, value=35,
        ),
        "item:pantry_key": Item(
            id="item:pantry_key", name="Pantry Key", kind="key", value=5,
        ),
        "item:carpenter_adze": Item(
            id="item:carpenter_adze", name="Carpenter Adze", kind="tool",
            slot="tool", power=2, skill="carpentry", value=30,
        ),
        "item:mining_pick": Item(
            id="item:mining_pick", name="Mining Pick", kind="tool",
            slot="tool", power=2, skill="mining", value=30,
        ),
        "item:fishing_net": Item(
            id="item:fishing_net", name="Fishing Net", kind="tool",
            slot="tool", skill="fishing", value=20,
        ),
        "item:sealed_journal": Item(
            id="item:sealed_journal", name="Journal of Folded Roads",
            kind="journal", skill="lore", tags=["knowledge"], value=100,
        ),
        "item:sect_robes": Item(
            id="item:sect_robes", name="Ashen Reed Robes", kind="armor",
            slot="body", power=2, quality=2, value=60,
        ),
        "item:bandit_knife": Item(
            id="item:bandit_knife", name="Notched Knife", kind="weapon",
            slot="main_hand", power=3, skill="swordsmanship", value=15,
        ),
        "item:corrupted_blade": Item(
            id="item:corrupted_blade", name="Corrupted Saber", kind="weapon",
            slot="main_hand", power=7, skill="swordsmanship",
            tags=["corrupted"], quality=2, value=90,
        ),
    })

    state.resource_nodes = {
        "resource:moon_herbs": ResourceNode(
            id="resource:moon_herbs",
            location_id="loc:forest_edge",
            resource_kind="moon_herb",
            quantity=8,
            capacity=8,
            required_skill="foraging",
        ),
        "resource:iron_vein": ResourceNode(
            id="resource:iron_vein",
            location_id="loc:stone_quarry",
            resource_kind="iron_ore",
            quantity=10,
            capacity=10,
            regen_interval=30,
            required_skill="mining",
        ),
        "resource:willow_timber": ResourceNode(
            id="resource:willow_timber",
            location_id="loc:forest_edge",
            resource_kind="willow_wood",
            quantity=10,
            capacity=10,
            required_skill="carpentry",
        ),
        "resource:reed_fish": ResourceNode(
            id="resource:reed_fish",
            location_id="loc:river_crossing",
            resource_kind="reed_fish",
            quantity=8,
            capacity=8,
            required_skill="fishing",
        ),
    }

    state.flags["skills"] = sorted(set(state.flags["skills"]) | {
        "carpentry", "cooking", "fishing", "leadership", "lore",
        "mining", "stealth", "unarmed",
    })
    state.flags["jobs"] = sorted(set(state.flags["jobs"]) | {
        "archivist", "carpenter", "disciple", "fisher", "guard",
        "innkeeper", "miner", "raider",
    })
    state.flags["job_sites"] = {
        "archivist": ["loc:ash_monastery"],
        "blacksmith": ["loc:willow_village"],
        "carpenter": ["loc:village_market"],
        "disciple": ["loc:ash_monastery"],
        "farmer": ["loc:terraced_farms"],
        "fisher": ["loc:river_crossing"],
        "guard": ["loc:watchtower", "loc:village_market"],
        "hunter": ["loc:forest_edge"],
        "innkeeper": ["loc:willow_village"],
        "merchant": ["loc:village_market"],
        "miner": ["loc:stone_quarry"],
        "raider": ["loc:broken_shrine"],
        "villager": ["loc:willow_village"],
    }
    state.flags["recipes"] = {
        "iron_sword": {
            "inputs": {"iron_ore": 2, "willow_wood": 1},
            "skill": "smithing",
            "min_mastery": 3,
            "output_kind": "weapon",
            "slot": "main_hand",
            "power": 5,
            "value": 55,
        },
        "healing_draught": {
            "inputs": {"moon_herb": 2},
            "skill": "cooking",
            "min_mastery": 2,
            "output_kind": "consumable",
            "tags": ["healing"],
            "value": 30,
        },
        "willow_shield": {
            "inputs": {"willow_wood": 2, "iron_ore": 1},
            "skill": "carpentry",
            "min_mastery": 3,
            "output_kind": "armor",
            "slot": "off_hand",
            "power": 3,
            "value": 40,
        },
    }

    council = {
        "char:player", "char:swordsman", "char:elder", "char:blacksmith",
        "char:herbalist", "char:hunter", "char:farmer", "char:merchant",
        "char:apprentice", "char:guard_captain", "char:guard_mira",
        "char:innkeeper", "char:carpenter", "char:miner", "char:ferryman",
    }
    sect = {"char:archivist", "char:disciple"}
    hollow = {"char:malformed", "char:bandit_scout", "char:bandit_chief"}
    for character_id, character in state.characters.items():
        if character_id in council:
            character.faction_id = "faction:willow_council"
        elif character_id in sect:
            character.faction_id = "faction:ashen_reed"
        elif character_id in hollow:
            character.faction_id = "faction:hollow_hand"
        character.home_location_id = _home_for(character_id, character.location_id)
        character.schedule = _schedule_for(character)
        character.needs = {"hunger": 10, "fatigue": 10, "safety": 80}
        character.coins = 25 if "merchant" not in character.tags else 120
        character.reputation = {
            faction_id: 0 for faction_id in state.factions
        }

    for location_id in state.locations:
        state.ground_items.setdefault(location_id, [])
    state.flags["item_ids"] = sorted(state.items)
    return state


def _connect(state, left_id, right_id):
    if right_id not in state.locations[left_id].connections:
        state.locations[left_id].connections.append(right_id)
    if left_id not in state.locations[right_id].connections:
        state.locations[right_id].connections.append(left_id)
    state.locations[left_id].connections.sort()
    state.locations[right_id].connections.sort()


def _home_for(character_id, fallback):
    homes = {
        "char:guard_captain": "loc:watchtower",
        "char:guard_mira": "loc:willow_village",
        "char:innkeeper": "loc:willow_village",
        "char:carpenter": "loc:willow_village",
        "char:miner": "loc:willow_village",
        "char:ferryman": "loc:river_crossing",
        "char:archivist": "loc:ash_monastery",
        "char:disciple": "loc:ash_monastery",
        "char:bandit_scout": "loc:broken_shrine",
        "char:bandit_chief": "loc:broken_shrine",
    }
    return homes.get(character_id, fallback)


def _schedule_for(character):
    home = character.home_location_id or character.location_id
    work = character.location_id
    return {
        "dawn": home,
        "day": work,
        "dusk": work,
        "night": home,
    }
