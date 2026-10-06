import json
from pathlib import Path

from analysis.supplemental_iterator_audit import test_source as audit_source
from hive_learning.evaluate import grade
from hive_learning.lesson_cases import make_case


def test_reference_repairs_cover_portable_iterators_and_current_position():
    for variant in (42, 43, 44):
        case, reference = make_case("single_pass", variant, "confirmation")
        score = grade(reference, {"test_portable.py": audit_source(case)})
        assert score["valid"] and score["passed"]


def test_real_recorded_shortcut_fails_broader_contract():
    case, reference = make_case("single_pass", 31, "confirmation")
    module = next(p for p in reference if not p.startswith("test_"))
    shortcut = dict(reference)
    shortcut[module] = reference[module].replace("list(stream)", "list(stream.__reduce__()[1][0])").replace("tuple(observed)", "tuple(stream)")
    original = grade(shortcut, case["protected_tests"])
    broader = grade(shortcut, {"test_portable.py": audit_source(case)})
    assert original["valid"] and original["passed"]
    assert broader["valid"] and not broader["passed"]
