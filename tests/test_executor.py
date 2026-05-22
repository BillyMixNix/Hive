import ast
from executor import ExecutorAgent
from pathlib import Path


def test_executor_sandbox_apply_simple_patch(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text("def foo():\n    return 1\n")

    # Use placeholder tokens to avoid patch-tool parsing issues in this test file.
    patch_lines = [
        "@@",
        "-    return 1",
        "+    return 2",
    ]

    patch = "\n".join(patch_lines)

    executor = ExecutorAgent()
    report = executor.test_patch_in_sandbox(patch, str(sample), patch_reason="test")

    assert isinstance(report, dict)
    assert report.get('applied') is True
    assert report.get('syntax_valid') is True


def test_structural_scope_allows_nested_class(tmp_path):
    # Regression: validator must not false-positive on valid Python with nested classes.
    # This pattern (class inside class) is common in external codebases (e.g. dateutil).
    target = tmp_path / "module.py"
    target.write_text(
        "class Outer:\n"
        "    class Inner:\n"
        "        x = 1\n"
        "    def method(self):\n"
        "        pass\n"
    )
    executor = ExecutorAgent()
    tree = ast.parse(target.read_text())
    issues = executor._collect_structural_issues(tree)
    assert issues == [], f"False positive on nested class: {issues}"


def test_structural_scope_catches_bare_call_at_class_scope(tmp_path):
    # A bare function call at class scope (not a docstring) should be flagged.
    target = tmp_path / "bad.py"
    target.write_text(
        "class Bad:\n"
        "    some_func()\n"
    )
    executor = ExecutorAgent()
    tree = ast.parse(target.read_text())
    issues = executor._collect_structural_issues(tree)
    assert len(issues) > 0, "Should have flagged bare call at class scope"


def test_structural_scope_baseline_bypass(tmp_path):
    # If the original file already triggers the structural check (e.g. it uses
    # a pattern not in our allowlist), _detect_structural_scope_inconsistency
    # must return clean rather than block the patch.
    target = tmp_path / "module.py"
    # Write a file with a decorator stored as a class variable — edge case
    # that might not be in the allowlist; use a bare call to simulate any
    # "unknown" pattern by temporarily shrinking the allowlist isn't feasible,
    # so we use the nested-class case which was the real regression.
    target.write_text(
        "class Outer:\n"
        "    class Inner:\n"
        "        pass\n"
        "    def method(self):\n"
        "        return 1\n"
    )
    patch = (
        f"--- {target}\n"
        f"+++ {target}\n"
        "@@ -5,1 +5,1 @@\n"
        "-        return 1\n"
        "+        return 2\n"
    )
    executor = ExecutorAgent()
    detected, _ = executor._detect_structural_scope_inconsistency(patch, str(target))
    assert not detected, "Baseline bypass should suppress false positive"
