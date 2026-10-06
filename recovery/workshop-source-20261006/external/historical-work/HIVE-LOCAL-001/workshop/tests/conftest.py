import pytest

from workshop import hive_verifier


@pytest.fixture(autouse=True)
def deterministic_verifier_for_non_isolation_unit_tests(request, monkeypatch):
    """Keep legacy orchestration tests independent of a local Docker daemon.

    The dedicated isolation tests exercise the real fail-closed adapter and
    inspect its complete container command. No production bypass exists.
    """
    if request.node.path.name == "test_hive_isolated_verifier.py":
        return
    passed = {"passed": True, "checks": [{"name": "isolated_fixture", "passed": True, "detail": "unit fixture"}],
              "isolation": {"backend": "test-fixture", "available": True}}
    monkeypatch.setattr(hive_verifier, "verify_tree_isolated", lambda tree, *args, **kwargs: passed)
    monkeypatch.setattr(hive_verifier, "targeted_verify_isolated", lambda tree, files, *args, **kwargs: passed)
