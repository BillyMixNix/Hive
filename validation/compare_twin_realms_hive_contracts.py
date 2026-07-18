from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


CONTRACT_RUNS = {
    "v1": "results/twin_realms_hive_learning_tier3_calibration_20.json",
    "v2": "results/twin_realms_hive_learning_tier3_calibration_v2_20.json",
    "v3": "results/twin_realms_hive_learning_tier3_contract_v3_20.json",
}
LEARNING_PROBE = "results/twin_realms_hive_learning_probe_v2_live.json"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def summarize_contract(path):
    report = load(path)
    checkpoint = load(report["checkpoint"])
    traces = checkpoint.get("cognition_state", {}).get("traces", [])
    phases = {}
    for phase in ("observe", "investigate", "plan", "act", "learn"):
        phase_traces = [
            trace for trace in traces if trace["phase"] == phase
        ]
        sources = Counter(trace["source"] for trace in phase_traces)
        phases[phase] = {
            "calls": len(phase_traces),
            "valid": sources.get("hive", 0),
            "fallbacks": sources.get("fallback", 0),
            "validity_rate": (
                sources.get("hive", 0) / len(phase_traces)
                if phase_traces else None
            ),
        }
    return {
        "world_events": report["world_events"],
        "accepted_events": report["accepted_events"],
        "invalid_reference_rejections": report["drift"][
            "invalid_reference_rejections"
        ],
        "proposal_validity": report["intent_proposals"]["validity_rate"],
        "transport_failures": report["clients"]["intent"]["failures"],
        "replay_consistent": report["replay_from_disk"],
        "phases": phases,
    }


def compare():
    learning = load(LEARNING_PROBE)
    return {
        "study": "twin_realms_hive_contract_calibration",
        "contracts": {
            version: summarize_contract(path)
            for version, path in CONTRACT_RUNS.items()
        },
        "learning_probe": {
            "lesson_count": learning["lesson_count"],
            "lesson_retrieved": learning[
                "lesson_retrieved_on_next_proposal"
            ],
            "next_action": learning["next_proposal"]["action"],
            "lesson_applied": learning["lessons"][0][
                "last_reuse_context"
            ]["lesson_applied"],
            "lesson_helped": learning["lessons"][0][
                "last_reuse_outcome"
            ],
            "phase_valid": learning["metrics"]["phase_valid"],
            "phase_fallbacks": learning["metrics"]["phase_fallbacks"],
            "replay_consistent": learning["replay_consistent"],
        },
        "findings": [
            "The action choice contract remained valid in all three versions.",
            "V1 observation and planning responses exceeded the small-model contract.",
            "V2 fixed planning but observation remained too broad.",
            "V3 separated compact observation from investigation and reached 100% phase validity.",
            "The learning probe created, retrieved, applied, and correctly attributed an insufficient-stamina lesson.",
        ],
    }


def main():
    report = compare()
    output = Path("results/twin_realms_hive_contract_comparison.json")
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
