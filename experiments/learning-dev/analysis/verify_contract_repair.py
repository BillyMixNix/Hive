"""Recheck known public input-mutation failures without any model access."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.checkpoint_followon import sources as frozen_sources
from analysis.public_contracts import InputPreservation, PublicContractGate
from hive_learning.ledger import digest

FIXTURE_SHA256 = "83072486f8db6eab4f1591a50fdba85f2ff0c6dcc9f5f6b917186b6493b8c64a"


def verify():
    path = ROOT/"examples/input-preservation-regression.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == FIXTURE_SHA256
    fixture = json.loads(path.read_text())
    gate = PublicContractGate(fixture["public_files"], [InputPreservation(**c) for c in fixture["contracts"]])
    rows = []
    for item in fixture["saved_bad_patches"]:
        assert digest(item["candidate"]) == item["candidate_sha256"]
        result = gate.evaluate(item["candidate"])
        assert result["valid"] and result["public_test_exit_code"] == 0
        assert result["status"] == "FAILED" and result["accepted"] is False
        assert {v["argument"] for c in result["checks"] for v in c["violations"]} == {"values"}
        rows.append({"arm": item["arm"], "original_controller_decision": item["original_controller_decision"],
                     "original_protected_checks_passed": item["original_protected_checks_passed"], "new_public_check": result})
    reference = gate.evaluate(fixture["reference"])
    assert reference["accepted"] and reference["valid"]
    frozen_sha = digest(frozen_sources())
    assert frozen_sha == "c6edd5410e93f4c57bd24519dec9deb475f261514093769f28bbdcec043e98c0"
    paths = ["analysis/public_contracts.py", "analysis/contract_checked_hive.py", "analysis/verify_contract_repair.py",
             "tests/test_public_contracts.py", "tests/test_contract_checked_hive.py", "examples/input-preservation-regression.json"]
    return {"verdict": "PUBLIC_INPUT_GATE_REGRESSION_VERIFIED", "scope": "Post-outcome engineering regression on public examples only.",
            "new_model_requests": 0, "new_api_charge_nano_usd": 0, "learning_gain_tested": False,
            "cumulative_prior_upper_nano_usd": 3469597600,
            "fixture_sha256": FIXTURE_SHA256, "original_workflow_url": fixture["workflow_url"],
            "frozen_runtime_unchanged": True, "frozen_runtime_sha256": frozen_sha,
            "source_hashes": {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
            "public_contract_policy": gate.policy, "public_contract_policy_sha256": gate.policy_sha256,
            "saved_bad_patches": rows, "distinct_bad_candidate_hashes": len({r["new_public_check"]["candidate_sha256"] for r in rows}),
            "correct_reference": reference,
            "limitations": ["Known regressions, not unseen tasks or a new learning comparison.",
                "Caller-declared final-value preservation on observed public-test calls only.",
                "Bounded built-in data; incomplete observations cannot approve.",
                "No general proof of correctness, object identity, thread behavior or adversarial containment."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pytest-report", type=Path)
    args = parser.parse_args()
    result = verify()
    if args.pytest_report:
        root = ET.parse(args.pytest_report).getroot()
        suites = list(root.iter("testsuite"))
        counts = {key: sum(int(s.attrib.get(key, 0)) for s in suites) for key in ("tests", "failures", "errors", "skipped")}
        assert counts["tests"] > 0 and counts["failures"] == counts["errors"] == 0
        result["offline_test_evidence"] = {**counts, "junit_sha256": hashlib.sha256(args.pytest_report.read_bytes()).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as f:
        f.write(json.dumps(result, indent=2)+"\n")
    print(json.dumps({"verdict": result["verdict"], "saved_bad_patches_rejected": len(result["saved_bad_patches"]),
                      "distinct_bad_candidates": result["distinct_bad_candidate_hashes"],
                      "correct_reference_accepted": result["correct_reference"]["accepted"],
                      "new_model_requests": 0, "output": str(args.output)}))


if __name__ == "__main__":
    main()
