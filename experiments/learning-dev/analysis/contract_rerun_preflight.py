"""Verify every original/reference case and public declaration without API use."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.contract_rerun import contracts, sources
from analysis.public_contracts import PublicContractGate
from analysis.verify_contract_repair import verify
from hive_learning.evaluate import grade, strict_json
from hive_learning.ledger import digest


def verify_study(study_path):
    raw = Path(study_path).read_bytes()
    study = strict_json(raw)
    references_raw = (ROOT/"examples/lesson-bank-v5-references.json").read_bytes()
    references = strict_json(references_raw)
    assert digest(references) == study["references_sha256"]
    rows = []
    for case in study["cases"]:
        reference = references[case["id"]]
        for path, content in case["files"].items():
            if path.startswith("test_"):
                assert reference[path] == content
        bad = grade(case["files"], case["protected_tests"])
        good = grade(reference, {**case["acceptance_tests"], **case["protected_tests"]})
        declarations = contracts(case)
        gate = PublicContractGate(case["files"], declarations) if declarations else None
        check = gate.evaluate(reference) if gate else None
        assert bad["valid"] and not bad["passed"], case["id"]
        assert good["valid"] and good["passed"], case["id"]
        assert check is None or check["valid"] and check["accepted"], case["id"]
        rows.append({"case_id": case["id"], "initial": bad, "reference": good,
                     "contract_policy": gate.policy if gate else None, "reference_contract": check})
    regression = verify()
    return {"schema": "hive.contract-rerun.preflight.v1", "verified": True,
            "study_sha256": hashlib.sha256(raw).hexdigest(), "runtime_sha256": digest(sources()),
            "new_model_requests": 0, "cases": rows,
            "saved_bad_patches_rejected": len(regression["saved_bad_patches"]),
            "reference_regression_accepted": regression["correct_reference"]["accepted"]}


if __name__ == "__main__":
    result = verify_study(ROOT/"examples/contract-rerun.json")
    with Path(sys.argv[1]).open("x") as f:
        f.write(json.dumps(result, indent=2)+"\n")
    print(json.dumps({"verified": True, "cases": len(result["cases"]),
                      "gated_cases": sum(c["contract_policy"] is not None for c in result["cases"]),
                      "new_model_requests": 0}))
