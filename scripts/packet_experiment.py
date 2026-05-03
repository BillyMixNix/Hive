"""
packet_experiment.py

Run a packetized vs legacy prompt experiment for a representative Hive task.

Usage:
    python scripts/packet_experiment.py

Outputs a JSON file `experiment_result.json` in the repo root with runs and simple metrics.

This script tolerates missing LLM endpoints and records errors for later inspection.
"""
import json
from pathlib import Path
from time import sleep

from coder_prompting import build_hive_builder_packet, build_prompt
from hive_llm import ask_model


def run_experiment(task, plan, file_text, runs=3, lesson_text="No recent lessons."):
    target = task.get("target_file")
    builder_packet = build_hive_builder_packet(task, plan, target, lesson_text=lesson_text)
    full_prompt = build_prompt(task, plan, target, file_text, lesson_text=lesson_text)
    legacy_prompt = full_prompt.replace(builder_packet, "")

    def trial(prompt, trials):
        outs = []
        for i in range(trials):
            try:
                out = ask_model(prompt, timeout=60)
            except Exception as e:
                out = f"__ERROR__ {e}"
            outs.append(out)
            sleep(0.4)
        return outs

    packet_outs = trial(full_prompt, runs)
    legacy_outs = trial(legacy_prompt, runs)

    def eval_list(lst, cue):
        res = []
        for o in lst:
            res.append({
                "length": len(o) if o else 0,
                "has_diff": ("PATCH:" in o) or ("--- " in o and "+++ " in o),
                "has_headers": ("---" in o and "+++" in o),
                "contains_cue": cue in o,
                "snippet": (o or "")[:800],
            })
        return res

    cue = (task.get("completion_cues") or [""])[0]
    result = {
        "task": {"id": task.get("id"), "target_file": target},
        "builder_packet_len": len(builder_packet),
        "full_prompt_len": len(full_prompt),
        "legacy_prompt_len": len(legacy_prompt),
        "packet_runs": eval_list(packet_outs, cue),
        "legacy_runs": eval_list(legacy_outs, cue),
    }

    return result


def main():
    repo_root = Path(__file__).resolve().parents[1]
    # Representative task (insert completion cue)
    task = {
        "id": 102,
        "note": "Insert the exact line `if not isinstance(cue, str): continue` into _normalize_completion_cues.",
        "target_file": "planner.py",
        "target_symbol": "_normalize_completion_cues",
        "completion_cues": ["if not isinstance(cue, str): continue"],
        "metadata": {"anchor": {"target_file": "planner.py", "target_symbol": "_normalize_completion_cues", "lineno": 70, "end_lineno": 110}},
    }
    plan = {
        "goal": "Ignore non-string completion cues",
        "tasks": [{"title": "Patch normalizer", "description": "Add type guard for cues."}],
        "dependencies": ["planner.py"],
        "risks": ["Minor behavioral change if mis-inserted."],
        "next_action": "Patch _normalize_completion_cues in planner.py.",
        "status": "planned",
    }
    file_text = "def _normalize_completion_cues(self, child):\n    cues = child.get(\"completion_cues\") or []\n    ...\n"

    print("Running experiment (3 trials each). This will call your configured LLM endpoint.")
    out = run_experiment(task, plan, file_text, runs=3)
    out_path = repo_root / "experiment_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(f"Wrote results to {out_path}")


if __name__ == "__main__":
    main()
