from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from twin_realms import ComplexityStressRunner


def run_study(*, turns=1000, seed=20260611, output=None):
    engine, drift = ComplexityStressRunner().run(
        3,
        turns=turns,
        seed=seed,
    )
    player = engine.state.characters[engine.state.player_id]
    rejected = Counter(
        event.reason for event in engine.events if not event.accepted
    )
    report = {
        "study": "twin_realms_tier3_region",
        "seed": seed,
        "turns": turns,
        "drift": drift.to_dict(),
        "player": {
            "alive": player.alive,
            "level": player.level,
            "experience": player.experience,
            "realm": player.realm,
            "cultivation_stage": player.cultivation_stage,
            "cultivation_progress": player.cultivation_progress,
            "health": player.health,
            "stamina": player.stamina,
            "coins": player.coins,
            "location_id": player.location_id,
            "equipment": player.equipment,
            "skills": player.skill_mastery,
            "jobs": player.jobs,
            "reputation": player.reputation,
            "needs": player.needs,
        },
        "world": {
            "characters": len(engine.state.characters),
            "active_characters": sum(
                character.active and character.alive
                for character in engine.state.characters.values()
            ),
            "dead_characters": sorted(
                character.id
                for character in engine.state.characters.values()
                if not character.alive
            ),
            "locations": len(engine.state.locations),
            "items": len(engine.state.items),
            "factions": len(engine.state.factions),
            "resource_nodes": {
                node_id: node.quantity
                for node_id, node in sorted(engine.state.resource_nodes.items())
            },
            "world_pressures": engine.state.flags.get("world_pressures", {}),
            "alert_level": engine.state.flags.get("kingdom_alert_level"),
        },
        "event_audit": {
            "rejection_reasons": dict(rejected.most_common()),
            "resources_gathered": dict(Counter(
                event.facts["resource_kind"]
                for event in engine.events
                if event.event_type == "resource_gathered"
            )),
            "trades": [
                {
                    "turn": event.turn,
                    "item_id": event.facts["item_id"],
                    "price": event.facts["price"],
                }
                for event in engine.events
                if event.event_type == "item_traded"
            ],
            "kills": [
                {
                    "turn": event.turn,
                    "actor_id": event.actor_id,
                    "target_id": event.target_id,
                    "damage": event.facts["damage"],
                    "world_pressure_changes": event.facts.get(
                        "world_pressure_changes", {}
                    ),
                }
                for event in engine.events
                if (
                    event.event_type == "attack_resolved"
                    and event.facts.get("target_alive") is False
                )
            ],
        },
        "replay_consistent": engine.verify_replay(),
        "state_digest": engine.simulator.state_digest(engine.state),
    }
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260611)
    parser.add_argument(
        "--output",
        default="results/twin_realms_tier3_region_1000.json",
    )
    args = parser.parse_args(argv)
    print(json.dumps(run_study(
        turns=args.turns,
        seed=args.seed,
        output=args.output,
    ), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
