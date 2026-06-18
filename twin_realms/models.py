from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Character:
    id: str
    name: str
    location_id: str
    realm: int = 1
    affinity: str = "none"
    stamina: int = 100
    max_stamina: int = 100
    health: int = 100
    max_health: int = 100
    alive: bool = True
    techniques: list[str] = field(default_factory=list)
    injuries: list[str] = field(default_factory=list)
    inventory: list[str] = field(default_factory=list)
    relationships: dict[str, int] = field(default_factory=dict)
    memories: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    active: bool = True
    spawn_turn: int | None = None
    level: int = 1
    experience: int = 0
    skill_mastery: dict[str, int] = field(default_factory=dict)
    equipment: dict[str, str] = field(default_factory=dict)
    jobs: dict[str, int] = field(default_factory=dict)
    faction_id: str | None = None
    home_location_id: str | None = None
    schedule: dict[str, str] = field(default_factory=dict)
    needs: dict[str, int] = field(default_factory=dict)
    coins: int = 0
    reputation: dict[str, int] = field(default_factory=dict)
    cultivation_stage: str = "body"
    cultivation_progress: int = 0


@dataclass
class Item:
    id: str
    name: str
    kind: str
    slot: str | None = None
    power: int = 0
    skill: str | None = None
    tags: list[str] = field(default_factory=list)
    quality: int = 1
    value: int = 1
    crafted_by: str | None = None


@dataclass
class Location:
    id: str
    name: str
    realm: str = "mortal"
    connections: list[str] = field(default_factory=list)
    danger: int = 0
    region_id: str = "region:willow"
    settlement_id: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class Faction:
    id: str
    name: str
    headquarters_id: str
    values: list[str] = field(default_factory=list)
    relations: dict[str, int] = field(default_factory=dict)
    treasury: int = 0
    laws: list[str] = field(default_factory=list)


@dataclass
class ResourceNode:
    id: str
    location_id: str
    resource_kind: str
    quantity: int
    capacity: int
    regen_interval: int = 20
    last_regen_turn: int = 0
    required_skill: str | None = None


@dataclass
class WorldState:
    turn: int
    seed: int
    player_id: str
    characters: dict[str, Character]
    locations: dict[str, Location]
    items: dict[str, Item] = field(default_factory=dict)
    ground_items: dict[str, list[str]] = field(default_factory=dict)
    factions: dict[str, Faction] = field(default_factory=dict)
    resource_nodes: dict[str, ResourceNode] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)
    version: int = 3

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        characters = {
            entity_id: Character(**record)
            for entity_id, record in data["characters"].items()
        }
        locations = {
            entity_id: Location(**record)
            for entity_id, record in data["locations"].items()
        }
        items = {
            entity_id: Item(**record)
            for entity_id, record in (data.get("items") or {}).items()
        }
        factions = {
            entity_id: Faction(**record)
            for entity_id, record in (data.get("factions") or {}).items()
        }
        resource_nodes = {
            entity_id: ResourceNode(**record)
            for entity_id, record in (data.get("resource_nodes") or {}).items()
        }
        ground_items = {
            location_id: list(items)
            for location_id, items in (data.get("ground_items") or {}).items()
        }
        for location_id in locations:
            ground_items.setdefault(location_id, [])
        flags = dict(data.get("flags") or {})
        if "item_ids" not in flags:
            flags["item_ids"] = sorted({
                item_id
                for character in characters.values()
                for item_id in character.inventory
            } | {
                item_id
                for items in ground_items.values()
                for item_id in items
            })
        if not items:
            items = {
                item_id: Item(
                    id=item_id,
                    name=item_id.split(":", 1)[-1].replace("_", " ").title(),
                    kind="legacy",
                )
                for item_id in flags.get("item_ids", [])
            }
        return cls(
            turn=int(data["turn"]),
            seed=int(data["seed"]),
            player_id=data["player_id"],
            characters=characters,
            locations=locations,
            items=items,
            ground_items=ground_items,
            factions=factions,
            resource_nodes=resource_nodes,
            flags=flags,
            version=int(data.get("version", 1)),
        )


@dataclass(frozen=True)
class ActionIntent:
    action: str
    actor_id: str
    target_id: str | None = None
    destination_id: str | None = None
    distance: int | None = None
    raw_text: str = ""
    confidence: float = 1.0
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


@dataclass(frozen=True)
class WorldEvent:
    id: str
    turn: int
    event_type: str
    actor_id: str
    target_id: str | None
    accepted: bool
    facts: dict[str, Any]
    reason: str | None = None
    intent: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


@dataclass(frozen=True)
class TurnResult:
    intent: ActionIntent
    event: WorldEvent
    narrative: str
    state_digest: str


@dataclass(frozen=True)
class KnowledgeEvent:
    turn: int
    key: str
    statement: str
    confirmed: bool
    promoted: bool
    source: str = "adaptive_agent"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)
