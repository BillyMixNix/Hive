import json

from regression_gate import load_regression_cases


def write_case(path, case_id, target):
    path.write_text(json.dumps({
        "id": case_id,
        "target_file": target,
        "callable": "compute",
        "args": [2],
        "expected": 4,
    }), encoding="utf-8")


def test_path_qualified_regression_target_does_not_alias_same_basename(tmp_path):
    cases = tmp_path / "cases"
    cases.mkdir()
    write_case(cases / "a.json", "a-router", "pkg_a/router.py")
    write_case(cases / "b.json", "b-router", "pkg_b/router.py")

    selected = load_regression_cases(cases, target_file="pkg_a/router.py")
    assert [case.case_id for case in selected] == ["a-router"]


def test_basename_only_target_retains_compatibility(tmp_path):
    cases = tmp_path / "cases"
    cases.mkdir()
    write_case(cases / "a.json", "a-router", "pkg_a/router.py")
    write_case(cases / "b.json", "b-router", "pkg_b/router.py")

    selected = load_regression_cases(cases, target_file="router.py")
    assert [case.case_id for case in selected] == ["a-router", "b-router"]
