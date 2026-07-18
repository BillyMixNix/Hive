from __future__ import annotations

import random

from .content import build_complexity_world, build_foundation_world
from .drift import DriftAuditor
from .engine import TwinRealmsEngine
from .models import ActionIntent


class ComplexityStressRunner:
    def run(self, tier, turns=500, seed=20260610):
        state = (
            build_foundation_world(seed=seed)
            if tier == 0
            else build_complexity_world(tier=tier, seed=seed)
        )
        engine = TwinRealmsEngine(state)
        rng = random.Random(seed + tier)
        for _ in range(turns):
            engine.apply_intent(self._intent(engine, tier, rng))
        return engine, DriftAuditor().audit(engine)

    def _intent(self, engine, tier, rng):
        player = engine.state.characters[engine.state.player_id]
        actions = [
            ActionIntent("rest", player.id),
            ActionIntent("observe", player.id),
            ActionIntent("move", player.id, destination_id=rng.choice(
                engine.state.locations[player.location_id].connections
            )),
        ]
        if tier >= 1:
            actions.extend([
                ActionIntent(
                    "equip",
                    player.id,
                    parameters={"item_id": "item:iron_sword"},
                ),
                ActionIntent(
                    "train",
                    player.id,
                    parameters={"skill_id": "swordsmanship"},
                ),
                ActionIntent(
                    "work",
                    player.id,
                    parameters={"job_id": "villager"},
                ),
            ])
        if tier >= 2:
            actions.extend([
                ActionIntent(
                    "train",
                    player.id,
                    parameters={"skill_id": "cultivation"},
                ),
                ActionIntent(
                    "work",
                    player.id,
                    parameters={"job_id": "hunter"},
                ),
            ])
        if tier >= 3:
            actions.append(ActionIntent("cultivate", player.id))
            if player.schedule:
                actions.append(ActionIntent("follow_schedule", player.id))
            for node in engine.state.resource_nodes.values():
                if (
                    node.location_id == player.location_id
                    and node.quantity > 0
                ):
                    actions.append(ActionIntent(
                        "gather",
                        player.id,
                        parameters={"resource_node_id": node.id},
                    ))
            for target in engine.state.characters.values():
                if (
                    target.id != player.id
                    and target.alive
                    and target.active
                    and target.location_id == player.location_id
                    and "merchant" in target.tags
                ):
                    for item_id in target.inventory:
                        if player.coins >= engine.state.items[item_id].value:
                            actions.append(ActionIntent(
                                "trade",
                                player.id,
                                target_id=target.id,
                                parameters={"item_id": item_id},
                            ))
        active_hostiles = [
            character.id
            for character in engine.state.characters.values()
            if character.active and character.alive and "hostile" in character.tags
            and character.location_id == player.location_id
        ]
        if active_hostiles:
            actions.append(ActionIntent("attack", player.id, target_id=active_hostiles[0]))
        return rng.choice(actions)
