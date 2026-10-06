"""Build and verify the prospective fixtures offline, before any paid request."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.checkpoint_cases import build_cases
from hive_learning.evaluate import grade, validate_files
from hive_learning.ledger import digest
from hive_learning.lesson_study import save_json


def main():
    cases, references = build_cases()
    bank = json.loads((ROOT/"results/bank-v4-phase-0/study-state.json").read_text())["lessons"]
    study = {"schema": "hive.lesson-bank.v5", "model": "gpt-5.6-luna", "calls_per_recipient": 36,
        "seed": 508917, "families": ["paired_sort", "single_pass", "versioned_cache"], "cases": cases,
        "lessons": bank, "bank_source": "results/bank-v4-phase-0/study-state.json",
        "references_sha256": digest(references), "policy": {
            "primary_endpoint": "model calls to independently verified repair; unsuccessful repairs receive 36",
            "minimum_reduction": 0.15, "alpha_one_sided": 0.00625,
            "all_18_lesson_repairs_required": True, "all_3_retention_repairs_required": True,
            "both_controls_required": True, "same_context_and_checkpoint_in_all_arms": True,
            "no_human_lesson_edits": True, "no_confirmation_updates": True,
            "no_replays_or_replacements": True, "one_frozen_attempt": True,
            "previous_studies_retained": True, "model_weights_unchanged": True}}
    report = {"verified": False, "scope": "offline fixture validation, not model evidence",
              "cases_sha256": digest(cases), "references_sha256": digest(references), "cases": []}
    for case in cases:
        for key in ("files", "acceptance_tests", "protected_tests"):
            validate_files(case[key])
        before = grade(case["files"], case["protected_tests"])
        after = grade(references[case["id"]], {**case["acceptance_tests"], **case["protected_tests"]})
        assert before["valid"] and not before["passed"] and after["valid"] and after["passed"], (case["id"], before, after)
        report["cases"].append({"case_id": case["id"], "before": before, "reference": after})
        print(case["id"], "verified", flush=True)
    report["verified"] = True
    save_json(ROOT/"examples/lesson-bank-v5.json", study)
    save_json(ROOT/"examples/lesson-bank-v5-references.json", references)
    save_json(ROOT/"results/lesson-v5-preflight.json", report)
    print(json.dumps({"cases": len(cases), "bank_sha256": digest(bank), "verified": True}))


if __name__ == "__main__":
    main()
