from __future__ import annotations

from dataclasses import dataclass

from .fidelity import (
    FIDELITY_BACKGROUND,
    FIDELITY_HIVE,
    FIDELITY_LEADER,
    FIDELITY_REACTIVE,
    FIDELITY_SCHEDULED,
    set_fidelity,
)
from .engine import TwinRealmsEngine
from .models import Character, Faction, Item, Location, ResourceNode, WorldState
from .models import ActionIntent


@dataclass(frozen=True)
class TarrowHeartbeatReport:
    scenario_id: str
    start_day: int
    end_day: int
    turns_advanced: int
    pressure_before: dict
    pressure_after: dict
    memory_counts_before: dict
    memory_counts_after: dict
    replay_consistent: bool
    state_digest: str

    @property
    def pressure_deltas(self):
        return {
            key: self.pressure_after.get(key, 0) - before
            for key, before in self.pressure_before.items()
            if self.pressure_after.get(key, before) != before
        }

    @property
    def memory_delta(self):
        return sum(self.memory_counts_after.values()) - sum(
            self.memory_counts_before.values()
        )

    @property
    def changed_without_player_force(self):
        return bool(self.pressure_deltas) and self.memory_delta > 0

    def to_dict(self):
        return {
            "scenario_id": self.scenario_id,
            "start_day": self.start_day,
            "end_day": self.end_day,
            "turns_advanced": self.turns_advanced,
            "pressure_before": dict(self.pressure_before),
            "pressure_after": dict(self.pressure_after),
            "pressure_deltas": self.pressure_deltas,
            "memory_counts_before": dict(self.memory_counts_before),
            "memory_counts_after": dict(self.memory_counts_after),
            "memory_delta": self.memory_delta,
            "changed_without_player_force": self.changed_without_player_force,
            "replay_consistent": self.replay_consistent,
            "state_digest": self.state_digest,
        }


def build_tarrow_aftermath_world(seed=17):
    """Build the first narrow living-world RPG proof slice."""

    locations = {
        "loc:tarrow_square": Location(
            id="loc:tarrow_square",
            name="Tarrow Square",
            connections=[
                "loc:shrine_road",
                "loc:low_fields",
                "loc:healer_hut",
                "loc:watch_post",
            ],
            danger=2,
            settlement_id="settlement:tarrow",
            tags=["residential", "market", "lawful"],
        ),
        "loc:shrine_road": Location(
            id="loc:shrine_road",
            name="Shrine Road",
            connections=["loc:tarrow_square", "loc:watch_post"],
            danger=4,
            settlement_id="settlement:tarrow",
            tags=["scarred", "road"],
        ),
        "loc:low_fields": Location(
            id="loc:low_fields",
            name="Low Fields",
            connections=["loc:tarrow_square", "loc:healer_hut"],
            danger=2,
            settlement_id="settlement:tarrow",
            tags=["farmland"],
        ),
        "loc:healer_hut": Location(
            id="loc:healer_hut",
            name="Healer Hut",
            connections=["loc:tarrow_square", "loc:low_fields"],
            danger=1,
            settlement_id="settlement:tarrow",
            tags=["healing", "refuge"],
        ),
        "loc:watch_post": Location(
            id="loc:watch_post",
            name="Old Watch Post",
            connections=["loc:tarrow_square", "loc:shrine_road"],
            danger=3,
            settlement_id="settlement:tarrow",
            tags=["guard_post"],
        ),
    }
    characters = {
        "char:player": Character(
            id="char:player",
            name="Wayfarer",
            location_id="loc:tarrow_square",
            realm=1,
            affinity="space",
            stamina=80,
            inventory=["item:iron_sword", "item:cultivation_manual"],
            skill_mastery={"swordsmanship": 1, "cultivation": 1},
            jobs={"villager": 1},
            faction_id="faction:tarrow_village",
            home_location_id="loc:tarrow_square",
            schedule=_schedule("loc:tarrow_square", "loc:tarrow_square"),
            needs=_needs(safety=55),
            coins=20,
            reputation={
                "faction:tarrow_village": 0,
                "faction:ash_wardens": 0,
            },
        ),
        "char:ren": Character(
            id="char:ren",
            name="Swordsman Ren",
            location_id="loc:watch_post",
            realm=4,
            affinity="metal",
            techniques=["sword_intent"],
            skill_mastery={"swordsmanship": 9, "leadership": 5},
            jobs={"guard": 7},
            faction_id="faction:ash_wardens",
            home_location_id="loc:watch_post",
            schedule=_schedule("loc:watch_post", "loc:shrine_road"),
            needs=_needs(safety=45),
            coins=35,
            reputation={
                "faction:tarrow_village": 8,
                "faction:ash_wardens": 15,
            },
            memories=[_memory(1, "survived_malformed_attack")],
            tags=["swordsman"],
        ),
        "char:mara": Character(
            id="char:mara",
            name="Elder Mara",
            location_id="loc:tarrow_square",
            realm=2,
            affinity="earth",
            skill_mastery={"leadership": 8, "lore": 4},
            jobs={"elder": 8},
            faction_id="faction:tarrow_village",
            home_location_id="loc:tarrow_square",
            schedule=_schedule("loc:tarrow_square", "loc:tarrow_square"),
            needs=_needs(safety=50),
            coins=80,
            reputation={
                "faction:tarrow_village": 20,
                "faction:ash_wardens": 2,
            },
            memories=[_memory(1, "counted_attack_dead")],
            tags=["village_elder"],
        ),
        "char:lio": Character(
            id="char:lio",
            name="Lio",
            location_id="loc:healer_hut",
            affinity="fire",
            skill_mastery={"smithing": 1},
            jobs={"apprentice": 1},
            faction_id="faction:tarrow_village",
            home_location_id="loc:tarrow_square",
            schedule=_schedule("loc:tarrow_square", "loc:healer_hut"),
            needs=_needs(safety=35),
            coins=3,
            reputation={
                "faction:tarrow_village": 0,
                "faction:ash_wardens": 0,
            },
            memories=[_memory(1, "hid_during_attack")],
            tags=["boy", "apprentice"],
        ),
        "char:sen": Character(
            id="char:sen",
            name="Herbalist Sen",
            location_id="loc:healer_hut",
            affinity="wood",
            skill_mastery={"healing": 7, "foraging": 5},
            jobs={"healer": 7},
            faction_id="faction:tarrow_village",
            home_location_id="loc:healer_hut",
            schedule=_schedule("loc:healer_hut", "loc:healer_hut"),
            needs=_needs(safety=60),
            coins=45,
            reputation={
                "faction:tarrow_village": 10,
                "faction:ash_wardens": 0,
            },
            tags=["healer"],
        ),
        "char:oru": Character(
            id="char:oru",
            name="Blacksmith Oru",
            location_id="loc:tarrow_square",
            affinity="fire",
            inventory=["item:smithing_hammer"],
            skill_mastery={"smithing": 6},
            jobs={"blacksmith": 6},
            faction_id="faction:tarrow_village",
            home_location_id="loc:tarrow_square",
            schedule=_schedule("loc:tarrow_square", "loc:tarrow_square"),
            needs=_needs(safety=55),
            coins=60,
            reputation={
                "faction:tarrow_village": 5,
                "faction:ash_wardens": 0,
            },
            tags=["merchant"],
        ),
        "char:vela": _villager("char:vela", "Farmer Vela", "farmer", "loc:low_fields", 42),
        "char:jori": _villager("char:jori", "Farmer Jori", "farmer", "loc:low_fields", 42),
        "char:penn": _villager("char:penn", "Miller Penn", "miller", "loc:low_fields", 45),
        "char:hada": _villager("char:hada", "Guard Hada", "guard", "loc:watch_post", 48),
        "char:tem": _villager("char:tem", "Guard Tem", "guard", "loc:watch_post", 48),
        "char:nara": _villager("char:nara", "Carpenter Nara", "carpenter", "loc:tarrow_square", 50),
        "char:suri": _villager("char:suri", "Cook Suri", "cook", "loc:tarrow_square", 50),
        "char:mina": _villager("char:mina", "Weaver Mina", "weaver", "loc:tarrow_square", 52),
        "char:alen": _villager("char:alen", "Runner Alen", "runner", "loc:shrine_road", 38),
        "char:bo": _villager("char:bo", "Stablehand Bo", "stablehand", "loc:tarrow_square", 45),
        "char:yara": _warden("char:yara", "Warden Yara", "loc:watch_post"),
        "char:teren": _warden("char:teren", "Warden Teren", "loc:shrine_road"),
        "char:malformed": Character(
            id="char:malformed",
            name="Malformed Remnant",
            location_id="loc:shrine_road",
            realm=2,
            affinity="corruption",
            health=0,
            max_health=70,
            alive=False,
            active=False,
            faction_id="faction:ash_wardens",
            home_location_id="loc:shrine_road",
            schedule=_schedule("loc:shrine_road", "loc:shrine_road"),
            needs=_needs(safety=0),
            tags=["malformed", "aftermath"],
        ),
        "char:raen": _villager("char:raen", "Widow Raen", "widow", "loc:tarrow_square", 35),
    }
    for character_id, character in characters.items():
        if character_id in {"char:mara", "char:ren"}:
            set_fidelity(character, FIDELITY_LEADER)
        elif character_id in {"char:lio", "char:sen", "char:oru"}:
            set_fidelity(character, FIDELITY_HIVE)
        elif character_id in {"char:vela", "char:jori", "char:hada", "char:yara"}:
            set_fidelity(character, FIDELITY_REACTIVE)
        elif character_id != "char:malformed":
            set_fidelity(character, FIDELITY_SCHEDULED)
        else:
            set_fidelity(character, FIDELITY_BACKGROUND)

    items = {
        "item:iron_sword": Item(
            id="item:iron_sword",
            name="Iron Sword",
            kind="weapon",
            slot="main_hand",
            power=4,
            skill="swordsmanship",
            value=35,
        ),
        "item:cultivation_manual": Item(
            id="item:cultivation_manual",
            name="Foundation Breathing Manual",
            kind="manual",
            skill="cultivation",
            value=40,
        ),
        "item:smithing_hammer": Item(
            id="item:smithing_hammer",
            name="Smithing Hammer",
            kind="tool",
            slot="tool",
            power=1,
            skill="smithing",
            value=20,
        ),
    }
    factions = {
        "faction:tarrow_village": Faction(
            id="faction:tarrow_village",
            name="Tarrow Village",
            headquarters_id="loc:tarrow_square",
            values=["survival", "kinship", "harvest"],
            relations={"faction:ash_wardens": 5},
            treasury=220,
            laws=["share_rations", "no_theft", "answer_the_bell"],
        ),
        "faction:ash_wardens": Faction(
            id="faction:ash_wardens",
            name="Ash Wardens",
            headquarters_id="loc:watch_post",
            values=["containment", "discipline", "sacrifice"],
            relations={"faction:tarrow_village": 5},
            treasury=140,
            laws=["hold_the_shrine_road", "burn_corruption"],
        ),
    }
    return WorldState(
        turn=1,
        seed=seed,
        player_id="char:player",
        characters=characters,
        locations=locations,
        items=items,
        ground_items={location_id: [] for location_id in locations},
        factions=factions,
        resource_nodes={
            "resource:tarrow_grain": ResourceNode(
                id="resource:tarrow_grain",
                location_id="loc:low_fields",
                resource_kind="grain",
                quantity=3,
                capacity=10,
                regen_interval=48,
                last_regen_turn=1,
                required_skill="farming",
            ),
            "resource:bitterleaf": ResourceNode(
                id="resource:bitterleaf",
                location_id="loc:healer_hut",
                resource_kind="medicine",
                quantity=2,
                capacity=8,
                regen_interval=36,
                last_regen_turn=1,
                required_skill="healing",
            ),
        },
        flags={
            "scenario_id": "tarrow_aftermath",
            "day_length": 24,
            "current_day": 1,
            "kingdom_alert_level": "medium",
            "twin_realm_stability": 76,
            "item_ids": sorted(items),
            "skills": [
                "cultivation",
                "farming",
                "foraging",
                "healing",
                "leadership",
                "smithing",
                "swordsmanship",
            ],
            "jobs": [
                "apprentice",
                "blacksmith",
                "carpenter",
                "cook",
                "elder",
                "farmer",
                "guard",
                "healer",
                "miller",
                "runner",
                "stablehand",
                "villager",
                "warden",
                "weaver",
                "widow",
            ],
            "job_sites": {
                "apprentice": ["loc:tarrow_square", "loc:healer_hut"],
                "blacksmith": ["loc:tarrow_square"],
                "carpenter": ["loc:tarrow_square"],
                "cook": ["loc:tarrow_square"],
                "elder": ["loc:tarrow_square"],
                "farmer": ["loc:low_fields"],
                "guard": ["loc:watch_post", "loc:shrine_road"],
                "healer": ["loc:healer_hut"],
                "miller": ["loc:low_fields"],
                "runner": ["loc:shrine_road"],
                "stablehand": ["loc:tarrow_square"],
                "villager": ["loc:tarrow_square"],
                "warden": ["loc:watch_post", "loc:shrine_road"],
                "weaver": ["loc:tarrow_square"],
                "widow": ["loc:tarrow_square"],
            },
            "village_pressures": {
                "fear": 72,
                "food": 38,
                "medicine": 30,
                "trust_in_ren": 54,
                "malformed_rumors": 66,
            },
            "world_pressures": {
                "malformed_aftermath": {
                    "source_id": "char:malformed",
                    "severity": 66,
                    "affected_locations": [
                        "loc:shrine_road",
                        "loc:tarrow_square",
                    ],
                },
                "resource_crisis": {
                    "source_id": "resource:tarrow_grain",
                    "severity": 62,
                    "affected_locations": [
                        "loc:low_fields",
                        "loc:tarrow_square",
                    ],
                },
            },
            "settlements": {
                "settlement:tarrow": {
                    "name": "Tarrow",
                    "locations": [
                        "loc:tarrow_square",
                        "loc:shrine_road",
                        "loc:low_fields",
                        "loc:healer_hut",
                        "loc:watch_post",
                    ],
                    "shops": {
                        "blacksmith": {
                            "location_id": "loc:tarrow_square",
                            "keeper_id": "char:oru",
                            "status": "open",
                        },
                        "healer": {
                            "location_id": "loc:healer_hut",
                            "keeper_id": "char:sen",
                            "status": "strained",
                        },
                    },
                    "workplaces": {
                        "fields": {
                            "location_id": "loc:low_fields",
                            "workers": ["char:vela", "char:jori", "char:penn"],
                            "status": "strained",
                        },
                        "watch": {
                            "location_id": "loc:watch_post",
                            "workers": ["char:ren", "char:hada", "char:tem", "char:yara"],
                            "status": "active",
                        },
                    },
                    "guards": ["char:ren", "char:hada", "char:tem", "char:yara", "char:teren"],
                    "civilians": [
                        "char:mara",
                        "char:lio",
                        "char:sen",
                        "char:oru",
                        "char:vela",
                        "char:jori",
                        "char:penn",
                        "char:nara",
                        "char:suri",
                        "char:mina",
                        "char:alen",
                        "char:bo",
                        "char:raen",
                    ],
                    "resources": {
                        "food": 38,
                        "medicine": 30,
                        "coin": 220,
                    },
                    "safety_level": 36,
                    "hostility_level": 64,
                    "defense_level": 45,
                    "prosperity": 38,
                    "population": {
                        "total": 19,
                        "present": 19,
                        "guard": 5,
                        "civilian": 13,
                        "wounded": 2,
                        "fled": 0,
                        "dead": 1,
                    },
                    "location_states": {
                        "loc:tarrow_square": "strained",
                        "loc:shrine_road": "damaged",
                        "loc:low_fields": "strained",
                        "loc:healer_hut": "strained",
                        "loc:watch_post": "defended",
                    },
                    "status": "defended",
                    "history": [],
                },
            },
            "rumors": [
                {
                    "id": "rumor:malformed_seen_after_death",
                    "subject_id": "char:malformed",
                    "origin_location_id": "loc:shrine_road",
                    "confidence": 0.7,
                }
            ],
        },
    )


def run_tarrow_heartbeat(*, days=7, seed=17, engine=None):
    """Advance Tarrow with world ticks only and report autonomous drift."""

    if days < 1:
        raise ValueError("days must be at least 1")
    engine = engine or TwinRealmsEngine(build_tarrow_aftermath_world(seed=seed))
    state = engine.state
    day_length = int(state.flags.get("day_length", 24))
    turns_to_advance = (days - 1) * day_length
    pressure_before = dict(state.flags.get("village_pressures", {}))
    memory_counts_before = {
        actor_id: len(character.memories)
        for actor_id, character in state.characters.items()
    }
    start_day = int(state.flags.get("current_day", 1))

    for _ in range(turns_to_advance):
        result = engine.apply_intent(ActionIntent("world_tick", state.player_id))
        if not result.event.accepted:
            raise RuntimeError(result.event.reason or "world tick was rejected")

    memory_counts_after = {
        actor_id: len(character.memories)
        for actor_id, character in state.characters.items()
    }
    return TarrowHeartbeatReport(
        scenario_id=state.flags.get("scenario_id"),
        start_day=start_day,
        end_day=int(state.flags.get("current_day", start_day)),
        turns_advanced=turns_to_advance,
        pressure_before=pressure_before,
        pressure_after=dict(state.flags.get("village_pressures", {})),
        memory_counts_before=memory_counts_before,
        memory_counts_after=memory_counts_after,
        replay_consistent=engine.verify_replay(),
        state_digest=engine.simulator.state_digest(state),
    )


def _villager(character_id, name, job, work_location, safety):
    return Character(
        id=character_id,
        name=name,
        location_id=work_location,
        affinity="none",
        skill_mastery={job: 3},
        jobs={job: 3},
        faction_id="faction:tarrow_village",
        home_location_id="loc:tarrow_square",
        schedule=_schedule("loc:tarrow_square", work_location),
        needs=_needs(safety=safety),
        coins=12,
        reputation={
            "faction:tarrow_village": 0,
            "faction:ash_wardens": 0,
        },
        memories=[_memory(1, "heard_malformed_attack")],
        tags=[job],
    )


def _warden(character_id, name, work_location):
    return Character(
        id=character_id,
        name=name,
        location_id=work_location,
        realm=2,
        affinity="metal",
        skill_mastery={"swordsmanship": 5, "leadership": 3},
        jobs={"warden": 5},
        faction_id="faction:ash_wardens",
        home_location_id="loc:watch_post",
        schedule=_schedule("loc:watch_post", work_location),
        needs=_needs(safety=48),
        coins=20,
        reputation={
            "faction:tarrow_village": 0,
            "faction:ash_wardens": 8,
        },
        memories=[_memory(1, "held_watch_after_attack")],
        tags=["warden"],
    )


def _schedule(home, work):
    return {
        "night": home,
        "dawn": home,
        "day": work,
        "dusk": work,
    }


def _needs(*, safety):
    return {
        "hunger": 18,
        "fatigue": 16,
        "safety": safety,
    }


def _memory(turn, event):
    return {
        "turn": turn,
        "event": event,
    }
