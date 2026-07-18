import json

import pytest

from regression_gate import RegressionDefinitionError, RegressionGate, load_regression_cases


def _write_case(directory, name, payload):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def test_gate_runs_behavior_and_aliasing_checks(tmp_path):
    module_path = tmp_path / "sample.py"
    module_path.write_text(
        """
class Normalizer:
    def normalize(self, value):
        return str(value or \"\").strip().lower()


def build_response(context):
    return {\"context\": dict(context)}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    cases_dir = tmp_path / "cases"
    _write_case(
        cases_dir,
        "normalization.json",
        [
            {
                "id": "normalizes-none",
                "target_file": "sample.py",
                "callable": "Normalizer.normalize",
                "construct": {"mode": "new"},
                "args": [None],
                "expected": "",
            },
            {
                "id": "response-detaches-context",
                "target_file": "sample.py",
                "callable": "build_response",
                "args": [{"mode": "safe"}],
                "expected": {"context": {"mode": "safe"}},
                "post_mutations": [
                    {"path": ["context", "mode"], "value": "changed"}
                ],
                "preserve_inputs": True,
            },
        ],
    )

    report = RegressionGate(cases_dir).run_for_file(
        module_path,
        target_file="sample.py",
    )

    assert report["passed"] is True
    assert report["passed_count"] == 2
    assert report["failed_case_ids"] == []


def test_gate_reports_behavior_failure(tmp_path):
    module_path = tmp_path / "sample.py"
    module_path.write_text("def normalize(value):\n    return value\n", encoding="utf-8")
    cases_dir = tmp_path / "cases"
    _write_case(
        cases_dir,
        "failure.json",
        {
            "id": "lowercases-value",
            "target_file": "sample.py",
            "callable": "normalize",
            "args": [" ADMIN "],
            "expected": "admin",
        },
    )

    report = RegressionGate(cases_dir).run_for_file(module_path, target_file="sample.py")

    assert report["passed"] is False
    assert report["failed_case_ids"] == ["lowercases-value"]
    assert "expected 'admin'" in report["cases"][0]["details"][0]


def test_gate_supports_expected_exceptions(tmp_path):
    module_path = tmp_path / "sample.py"
    module_path.write_text(
        "def require_list(value):\n    if not isinstance(value, list):\n        raise TypeError('list required')\n    return value\n",
        encoding="utf-8",
    )
    cases_dir = tmp_path / "cases"
    _write_case(
        cases_dir,
        "exception.json",
        {
            "id": "rejects-non-list",
            "target_file": "sample.py",
            "callable": "require_list",
            "args": [None],
            "expected_exception": "TypeError",
        },
    )

    report = RegressionGate(cases_dir).run_for_file(module_path, target_file="sample.py")

    assert report["passed"] is True


def test_duplicate_case_ids_are_rejected(tmp_path):
    cases_dir = tmp_path / "cases"
    payload = {
        "id": "duplicate",
        "target_file": "sample.py",
        "callable": "normalize",
        "args": ["x"],
        "expected": "x",
    }
    _write_case(cases_dir, "one.json", payload)
    _write_case(cases_dir, "two.json", payload)

    with pytest.raises(RegressionDefinitionError, match="duplicate case id"):
        load_regression_cases(cases_dir)
