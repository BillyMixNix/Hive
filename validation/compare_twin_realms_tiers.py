from __future__ import annotations

import json
from pathlib import Path

from twin_realms import TwinRealmsEngine


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compare(
    baseline_path="results/twin_realms_complexity_baseline.json",
    tier1_path="results/twin_realms_live_tier1_1000.json",
    tier2_path="results/twin_realms_live_tier2_1000.json",
):
    baseline = load_json(baseline_path)
    baselines = {
        report["complexity_tier"]: report
        for report in baseline["reports"]
    }
    rows = []
    for tier, path in ((1, tier1_path), (2, tier2_path)):
        live = load_json(path)
        base = baselines[tier]
        engine = TwinRealmsEngine.load(live["checkpoint"])
        player = engine.state.characters[engine.state.player_id]
        rows.append({
            "tier": tier,
            "baseline": {
                "world_events": base["world_turns"],
                "rejection_rate": base["rejection_rate"],
                "invalid_reference_rejections": base["invalid_reference_rejections"],
                "action_diversity": base["action_diversity"],
                "replay_consistent": base["replay_consistent"],
                "drift_detected": base["drift_detected"],
                "player_level": base["player"]["level"],
                "player_experience": base["player"]["experience"],
                "equipment": base["player"]["equipment"],
                "skills": base["player"]["skill_mastery"],
                "jobs": base["player"]["jobs"],
            },
            "live": {
                "world_events": live["world_events"],
                "rejection_rate": live["drift"]["rejection_rate"],
                "invalid_reference_rejections": live["drift"]["invalid_reference_rejections"],
                "action_diversity": live["drift"]["action_diversity"],
                "replay_consistent": live["replay_from_disk"],
                "drift_detected": live["drift"]["drift_detected"],
                "intent_validity": live["intent_proposals"]["validity_rate"],
                "npc_validity": live["npc_proposals"]["validity_rate"],
                "player_level": player.level,
                "player_experience": player.experience,
                "equipment": player.equipment,
                "skills": player.skill_mastery,
                "jobs": player.jobs,
            },
            "delta": {
                "world_events": live["world_events"] - base["world_turns"],
                "rejection_rate_points": (
                    live["drift"]["rejection_rate"] - base["rejection_rate"]
                ),
                "invalid_reference_rejections": (
                    live["drift"]["invalid_reference_rejections"]
                    - base["invalid_reference_rejections"]
                ),
                "action_diversity": (
                    live["drift"]["action_diversity"] - base["action_diversity"]
                ),
                "player_levels": player.level - base["player"]["level"],
            },
        })
    return {
        "comparison_basis": {
            "player_turns": 1000,
            "baseline_control": "deterministic",
            "live_control": "qwen2.5:3b assisted",
            "live_npc_count": 1,
        },
        "tiers": rows,
        "findings": [
            "Replay consistency remained perfect in deterministic and live runs.",
            "Live proposal schema validity was 100% for player intent and NPC actions.",
            "Live rejection rate rose to 66.38% in both tiers.",
            "The dominant live failure was repeated targeting across different locations.",
            "Tier 2 progression mechanics were not exercised by the live workload.",
        ],
    }


def main():
    report = compare()
    output = Path("results/twin_realms_tier_live_vs_baseline.json")
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
