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
