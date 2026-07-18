from __future__ import annotations

import json
from pathlib import Path

from twin_realms import TwinRealmsEngine
from twin_realms.behavior import analyze_agent_behavior


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def summarize(report):
    engine = TwinRealmsEngine.load(report["checkpoint"])
    behavior = analyze_agent_behavior(engine)
    return {
        "agent_loop": report["agent_loop"],
        "invalid_references": behavior["invalid_reference_rejections"],
        "pre_death_accepted_rate": behavior["pre_death_accepted_rate"],
        "survival_turns": behavior["survival_turns"],
        "progression": behavior["progression"],
        "hostile_present_action_mix": behavior[
            "hostile_present_action_mix"
        ],
        "terminal_state_rejections": behavior[
            "terminal_state_rejections"
        ],
        "replay_consistent": behavior["replay_consistent"],
        "final_player": behavior["final_player"],
        "threat_onset": behavior["threat_onset"],
        "proposal_validity": {
            "player": report["intent_proposals"]["validity_rate"],
            "npc": report["npc_proposals"]["validity_rate"],
        },
        "narration_guard_violations": report[
            "narration_guard_violations"
        ],
    }


def compare(
    grounded_path="results/twin_realms_live_tier2_grounded_1000.json",
    awareness_path=(
        "results/twin_realms_live_tier2_grounded_awareness_1000.json"
    ),
):
    grounded = summarize(load_json(grounded_path))
    awareness = summarize(load_json(awareness_path))
    return {
        "comparison_basis": {
            "complexity_tier": 2,
            "player_turns": 1000,
            "control": "grounded_agent",
            "treatment": "grounded_agent + situational_awareness_packet",
            "all_other_agent_policy_and_world_settings_held_constant": True,
        },
        "grounded_agent": grounded,
        "grounded_agent_with_situational_awareness": awareness,
        "delta_awareness_minus_grounded": {
            "invalid_references": (
                awareness["invalid_references"]
                - grounded["invalid_references"]
            ),
            "pre_death_accepted_rate": (
                awareness["pre_death_accepted_rate"]
                - grounded["pre_death_accepted_rate"]
            ),
            "survival_player_turns": (
                awareness["survival_turns"]["player_turns"]
                - grounded["survival_turns"]["player_turns"]
            ),
            "survival_world_turns": (
                awareness["survival_turns"]["world_turns"]
                - grounded["survival_turns"]["world_turns"]
            ),
            "progression_events_before_threat": (
                awareness["progression"]["before_threat"][
                    "accepted_events"
                ]
                - grounded["progression"]["before_threat"][
                    "accepted_events"
                ]
            ),
            "progression_events_after_threat": (
                awareness["progression"]["after_threat"]["accepted_events"]
                - grounded["progression"]["after_threat"]["accepted_events"]
            ),
            "experience_before_threat": (
                awareness["progression"]["before_threat"][
                    "experience_gained"
                ]
                - grounded["progression"]["before_threat"][
                    "experience_gained"
                ]
            ),
            "experience_after_threat": (
                awareness["progression"]["after_threat"][
                    "experience_gained"
                ]
                - grounded["progression"]["after_threat"][
                    "experience_gained"
                ]
            ),
            "terminal_state_rejections": (
                awareness["terminal_state_rejections"]
                - grounded["terminal_state_rejections"]
            ),
        },
    }


def main():
    report = compare()
    output = Path("results/twin_realms_awareness_comparison.json")
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
