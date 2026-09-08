"""Check effects on actual arguments, with independent negative controls."""
import json
from pathlib import Path

import pytest

from analysis.public_contracts import InputPreservation, PublicContractGate
from hive_learning.ledger import digest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT/"examples/input-preservation-regression.json").read_text())


@pytest.mark.parametrize("item", FIXTURE["saved_bad_patches"], ids=lambda item: item["arm"])
def test_saved_patch_passes_public_tests_but_fails_input_contract(item):
    gate = PublicContractGate(FIXTURE["public_files"], [InputPreservation(**c) for c in FIXTURE["contracts"]])
    result = gate.evaluate(item["candidate"])
    assert result["candidate_sha256"] == item["candidate_sha256"]
    assert result["valid"] and result["public_test_exit_code"] == 0
    assert result["status"] == "FAILED" and result["accepted"] is False
    assert result["observed_calls"] == 1
    assert {v["argument"] for c in result["checks"] for v in c["violations"]} == {"values"}


def test_correct_reference_is_accepted():
    gate = PublicContractGate(FIXTURE["public_files"], [InputPreservation(**c) for c in FIXTURE["contracts"]])
    result = gate.evaluate(FIXTURE["reference"])
    assert result["accepted"] and result["status"] == "PASSED", result


@pytest.mark.parametrize("body", [
    "alias = values\n    alias[0]['items'].append(3)\n    values = []\n    return 7",
    "def mutate(target):\n        target[0]['items'].append(3)\n    mutate(values)\n    return 7",
    "values[0]['items'].append(3)\n    raise ValueError('expected')",
])
def test_alias_helper_and_exception_mutations_are_detected(body):
    assertion = "with pytest.raises(ValueError):\n        process([{'items': [1, 2]}])" if "raise " in body else "assert process([{'items': [1, 2]}]) == 7"
    files = {"sample.py": "def process(values):\n    " + body + "\n",
             "test_visible.py": "import pytest\nfrom sample import process\n\ndef test_public():\n    " + assertion + "\n"}
    result = PublicContractGate(files, [InputPreservation("sample.py", "process", ("values",))]).evaluate(files)
    assert result["valid"] and result["public_test_exit_code"] == 0, result
    assert result["accepted"] is False and result["checks"][0]["violations"]


def test_mutating_a_local_copy_and_rebinding_a_parameter_are_allowed():
    files = {"sample.py": "def process(values):\n    values = list(values)\n    values.append(3)\n    return values\n",
             "test_visible.py": "from sample import process\ndef test_public():\n    assert process([1, 2]) == [1, 2, 3]\n"}
    assert PublicContractGate(files, [InputPreservation("sample.py", "process", ("values",))]).evaluate(files)["accepted"]


def test_contract_on_method_argument_allows_separate_internal_state_changes():
    files = {"sample.py": "class Memo:\n    def fetch(self, *, values):\n        self.cached = list(values)\n        return self.cached\n",
             "test_visible.py": "from sample import Memo\ndef test_public():\n    m = Memo()\n    assert m.fetch(values=[1, 2]) == [1, 2]\n    assert m.cached == [1, 2]\n"}
    assert PublicContractGate(files, [InputPreservation("sample.py", "Memo.fetch", ("values",))]).evaluate(files)["accepted"]


@pytest.mark.parametrize("test", [
    "assert True",
    "assert process(iter([1, 2])) == 7",
])
def test_unobserved_or_unsupported_argument_never_passes(test):
    files = {"sample.py": "def process(values):\n    return 7\n",
             "test_visible.py": "from sample import process\ndef test_public():\n    " + test + "\n"}
    result = PublicContractGate(files, [InputPreservation("sample.py", "process", ("values",))]).evaluate(files)
    assert result["accepted"] is False and result["status"] == "ERROR", result


def test_checker_timeout_does_not_approve():
    files = {"sample.py": "def process(values):\n    while True:\n        pass\n",
             "test_visible.py": "from sample import process\ndef test_public():\n    process([1, 2])\n"}
    result = PublicContractGate(files, [InputPreservation("sample.py", "process", ("values",))], timeout=0.5).evaluate(files)
    assert result["accepted"] is False and result["error_code"] == "checker_timeout"


def test_test_changes_and_changed_policy_cannot_reuse_acceptance():
    gate = PublicContractGate(FIXTURE["public_files"], [InputPreservation(**c) for c in FIXTURE["contracts"]])
    changed = {**FIXTURE["reference"], "test_visible.py": "def test_public():\n    assert True\n"}
    assert gate.evaluate(changed)["error_code"] == "candidate_or_contract_invalid"
    public = gate.policy
    public["contracts"].clear()
    assert digest(gate.policy) == gate.policy_sha256
    gate.contracts = ()
    assert gate.evaluate(FIXTURE["reference"])["error_code"] == "public_contract_policy_changed"
