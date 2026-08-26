from kingdom.arena import ToolRequest
from kingdom.arena_tools import PytestTool


def test_pytest_tool_reports_pass_and_fail_without_shell_surface(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_pass.py").write_text("def test_ok():\n    assert 2 + 2 == 4\n", encoding="utf-8")
    (tests / "test_fail.py").write_text("def test_no():\n    assert 2 + 2 == 5\n", encoding="utf-8")
    tool = PytestTool(tmp_path, timeout=20)

    passed = tool.execute(
        ToolRequest("pytest", "run", {"selectors": ["tests/test_pass.py"]}, branch_id="b")
    )
    failed = tool.execute(
        ToolRequest("pytest", "run", {"selectors": ["tests/test_fail.py"]}, branch_id="b")
    )

    assert passed.status == "verified"
    assert "1 passed" in passed.detail
    assert failed.status == "failed"
    assert "1 failed" in failed.detail


def test_pytest_tool_rejects_flags_and_paths_outside_test_root(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / "not_a_test.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    tool = PytestTool(tmp_path)

    for selector in ("--collect-only", "../escape.py", "not_a_test.py"):
        try:
            tool.execute(
                ToolRequest("pytest", "run", {"selectors": [selector]}, branch_id="b")
            )
        except (ValueError, FileNotFoundError):
            pass
        else:
            raise AssertionError(f"unsafe selector was accepted: {selector}")
