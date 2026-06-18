from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from twin_realms import TwinRealmsEngine


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def live_summary(report, engine):
    player = engine.state.characters[engine.state.player_id]
    return {
        "world_events": report["world_events"],
        "accepted_events": report["accepted_events"],
        "rejected_events": report["rejected_events"],
        "rejection_rate": report["drift"]["rejection_rate"],
        "invalid_reference_rejections": report["drift"][
            "invalid_reference_rejections"
        ],
        "unavailable_actor_rejections": report["drift"][
            "unavailable_actor_rejections"
        ],
        "action_diversity": report["drift"]["action_diversity"],
        "replay_consistent": report["replay_from_disk"],
        "narration_guard_violations": report["narration_guard_violations"],
        "intent_validity": report["intent_proposals"]["validity_rate"],
        "npc_validity": report["npc_proposals"]["validity_rate"],
        "event_counts": report["event_counts"],
        "player": {
            "alive": player.alive,
            "health": player.health,
            "level": player.level,
            "experience": player.experience,
            "equipment": player.equipment,
            "skills": player.skill_mastery,
            "jobs": player.jobs,
        },
    }


def pre_death_summary(engine):
    death = next(
        (
            event
            for event in engine.events
            if event.target_id == engine.state.player_id
            and event.facts.get("target_alive") is False
        ),
        None,
    )
    if death is None:
        return None
    events = [event for event in engine.events if event.turn <= death.turn]
    rejected = [event for event in events if not event.accepted]
    return {
        "terminal_turn": death.turn,
        "terminal_actor": death.actor_id,
        "terminal_event": death.event_type,
        "terminal_damage": death.facts.get("damage"),
        "events": len(events),
        "accepted_events": len(events) - len(rejected),
        "rejected_events": len(rejected),
        "rejection_rate": len(rejected) / len(events),
        "invalid_reference_rejections": sum(
            event.reason
            and any(
                term in event.reason
                for term in ("target", "reference", "location", "item")
            )
            for event in rejected
        ),
        "unavailable_actor_rejections": sum(
            event.reason == "actor is unavailable" for event in rejected
        ),
        "event_counts": dict(sorted(Counter(
            event.event_type for event in events
        ).items())),
    }


def compare(
    baseline_path="results/twin_realms_complexity_baseline.json",
    stateless_path="results/twin_realms_live_tier2_1000.json",
    grounded_path="results/twin_realms_live_tier2_grounded_1000.json",
):
    baseline_report = next(
        report
        for report in load_json(baseline_path)["reports"]
        if report["complexity_tier"] == 2
    )
    stateless_report = load_json(stateless_path)
    grounded_report = load_json(grounded_path)
    stateless_engine = TwinRealmsEngine.load(stateless_report["checkpoint"])
    grounded_engine = TwinRealmsEngine.load(grounded_report["checkpoint"])
    stateless = live_summary(stateless_report, stateless_engine)
    grounded = live_summary(grounded_report, grounded_engine)
    return {
        "comparison_basis": {
            "complexity_tier": 2,
            "player_turns": 1000,
            "model": grounded_report["model"],
            "live_npc_count": 1,
            "stateless_agent_loop": stateless_report.get(
                "agent_loop", "stateless"
            ),
            "grounded_agent_loop": grounded_report["agent_loop"],
        },
        "deterministic_baseline": baseline_report,
        "stateless_live": stateless,
        "grounded_live": grounded,
        "grounded_pre_death": pre_death_summary(grounded_engine),
        "grounded_vs_stateless": {
            "invalid_reference_rejections": (
                grounded["invalid_reference_rejections"]
                - stateless["invalid_reference_rejections"]
            ),
            "unavailable_actor_rejections": (
                grounded["unavailable_actor_rejections"]
                - stateless["unavailable_actor_rejections"]
            ),
            "rejection_rate_points": (
                grounded["rejection_rate"] - stateless["rejection_rate"]
            ),
            "action_diversity": (
                grounded["action_diversity"] - stateless["action_diversity"]
            ),
            "player_levels": (
                grounded["player"]["level"] - stateless["player"]["level"]
            ),
            "player_experience": (
                grounded["player"]["experience"]
                - stateless["player"]["experience"]
            ),
        },
        "findings": [
            "Replay remained exact in deterministic, stateless, and grounded runs.",
            "Grounding eliminated all 1,111 invalid-reference rejections.",
            "Before death, the grounded run accepted 61 of 63 events and used equipment, jobs, movement, rest, and combat.",
            "The grounded player reached level 3 with 66 experience, while the stateless player remained level 1 with zero experience.",
            "The grounded player died on event 63 because stamina recovery consumed combat turns; 944 later player actions were rejected as unavailable.",
            "The next bottleneck is terminal-state and survival planning, not world-state grounding or replay coherence.",
        ],
    }


def main():
    report = compare()
    output = Path("results/twin_realms_agent_loop_comparison.json")
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
