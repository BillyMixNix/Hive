"""Exercise both missing-name and missing-dimension counterexamples offline."""
import json
from pathlib import Path

import pytest

from analysis.cache_contract_audit import cache_audit_tests
from hive_learning.evaluate import grade

ROOT = Path(__file__).resolve().parents[1]
CASES = [c for c in json.loads((ROOT/"examples/lesson-bank-v5.json").read_text())["cases"] if c["family"] == "versioned_cache"]
REFS = json.loads((ROOT/"examples/lesson-bank-v5-references.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_full_contract_accepts_reference_and_rejects_incomplete_original_key(case):
    tests = cache_audit_tests(case)
    repaired = grade(REFS[case["id"]], tests)
    original = grade(case["files"], tests)
    assert repaired["valid"] and repaired["passed"], (case["id"], repaired)
    assert original["valid"] and not original["passed"]


def test_actual_passing_locale_only_shortcut_is_rejected():
    case = next(c for c in CASES if c["id"] == "checkpoint_normalized_locale")
    candidate = dict(case["files"])
    source = next(p for p in candidate if not Path(p).name.startswith("test_"))
    candidate[source] = candidate[source].replace("key = self.identity(name)", "key = self.identity(locale)")
    original_score = grade(candidate, case["protected_tests"])
    audited = grade(candidate, cache_audit_tests(case))
    assert original_score["valid"] and original_score["passed"]
    assert audited["valid"] and not audited["passed"]
