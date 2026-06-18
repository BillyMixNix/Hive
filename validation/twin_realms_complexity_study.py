from __future__ import annotations

import argparse
import json
from pathlib import Path

from twin_realms import ComplexityStressRunner


def run_study(turns=1000):
    reports = []
    runner = ComplexityStressRunner()
    for tier in (0, 1, 2):
        engine, report = runner.run(tier, turns=turns)
        data = report.to_dict()
        data["state_digest"] = engine.simulator.state_digest(engine.state)
        data["player"] = {
            "level": engine.state.characters[engine.state.player_id].level,
            "experience": engine.state.characters[engine.state.player_id].experience,
            "equipment": engine.state.characters[engine.state.player_id].equipment,
            "skill_mastery": engine.state.characters[engine.state.player_id].skill_mastery,
            "jobs": engine.state.characters[engine.state.player_id].jobs,
        }
        reports.append(data)
    return {"turns_per_tier": turns, "reports": reports}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=1000)
    parser.add_argument(
        "--output",
        default="results/twin_realms_complexity_baseline.json",
    )
    args = parser.parse_args(argv)
    report = run_study(args.turns)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
