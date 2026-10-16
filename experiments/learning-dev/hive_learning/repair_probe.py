"""One frozen visible-failure integration check; no learning or promotion gate."""
import copy
import hashlib
import json
from pathlib import Path

from .evaluate import candidate_snapshot, grade, strict_json, validate_files, write_files
from .ledger import digest
from .loop import implementation_hashes


PROBE_SHA256 = "c6676e972b10de0ac475d0b8ae435877cf67dfca6f7053b906013e58cbe54a81"
# This controller-side contract check is distinct from the protected final grid.
# Every tested value is outside that grid. Only the boolean result reaches Hive;
# test source and the independent final evaluation never enter worker prompts.
ACCEPTANCE_TESTS = {"test_acceptance.py": """from capacity import admit

def test_contract_boundaries():
    for cap in (-100, 100, 1000000):
        assert admit(cap - 1, cap) is True
        assert admit(cap, cap) is True
        assert admit(cap + 1, cap) is False
"""}


def read_probe(path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != PROBE_SHA256:
        raise ValueError("repair probe bytes do not match commitment")
    case = strict_json(raw)
    if (set(case) != {"schema", "id", "goal", "files", "protected_tests"}
            or case["schema"] != "hive.development.repair-probe.v1"):
        raise ValueError("invalid repair probe")
    validate_files(case["files"])
    validate_files(case["protected_tests"])
    if set(case["files"]) & set(case["protected_tests"]):
        raise ValueError("repair probe tests overlap public files")
    return case


def run_probe(adapter, root, path):
    """Give the unchanged controller a real public failure, then grade a copy.

    The model receives no lesson and cannot access the protected test file via
    its brokered tools. All source, controller output and traces are preserved.
    The fixture is authored development material, not an unseen capability test.
    """
    case = read_probe(path)
    original = copy.deepcopy(case["files"])
    implementation = implementation_hashes()
    report = {"scope": "development_real_model", "kind": "visible_failure_repair_probe",
              "probe_sha256": PROBE_SHA256, "case_id": case["id"],
              "acceptance_check_sha256": digest(ACCEPTANCE_TESTS), "acceptance_checks": [],
              "promotion_eligible": False, "lessons_supplied": [],
              "verdict": "INVALID", "probe_integrity_verified": False}
    root.mkdir(parents=True, exist_ok=False)
    write_files(root, original)
    try:
        # A verified failure before model work is an essential negative control.
        baseline = grade(original, case["protected_tests"])
        report["before"] = baseline
        if not baseline["valid"] or baseline["passed"]:
            raise ValueError("repair probe has no valid initial failure")
        def acceptance_oracle(workspace):
            snapshot = candidate_snapshot(workspace, original)
            checked = grade(snapshot, ACCEPTANCE_TESTS)
            report["acceptance_checks"].append({"candidate_sha256": digest(snapshot), **checked})
            return checked["valid"] and checked["passed"]
        # Verify that the required checker itself rejects the broken revision.
        if acceptance_oracle(root):
            raise ValueError("acceptance checker accepted the broken revision")
        usage, result = adapter.work(root, case["goal"], [], 36, acceptance_oracle=acceptance_oracle)
        report.update({"usage": usage, "controller": result})
        candidate = candidate_snapshot(root, original)
        report["candidate"] = candidate
        report["candidate_sha256"] = digest(candidate)
        report["source_changed"] = candidate != original
        (root.parent / "candidate.json").write_text(json.dumps(candidate, indent=2) + "\n")
        after = grade(candidate, case["protected_tests"])
        report["after"] = after
        if read_probe(path) != case or implementation_hashes() != implementation:
            raise ValueError("repair probe inputs changed during execution")
        report["probe_integrity_verified"] = True
        passed = (after["valid"] and after["passed"] and report["source_changed"]
                  and result["decision"] == "SATISFIED")
        report["verdict"] = "REPAIR_VERIFIED" if passed else "REPAIR_NOT_VERIFIED"
    except Exception as exc:
        # Transport failure details use fixed codes in observed_usage; arbitrary
        # exception text is not copied from a controller or provider boundary.
        report["reason"] = "repair probe stopped: " + type(exc).__name__
    report["transport_usage"] = adapter.observed_usage()
    return report
