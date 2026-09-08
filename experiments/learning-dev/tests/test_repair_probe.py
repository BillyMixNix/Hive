"""Probe evaluator checks using scripted adapters, never model requests."""
from pathlib import Path

import pytest

from hive_learning.repair_probe import run_probe


@pytest.mark.parametrize("behavior,verdict", [("repair", "REPAIR_VERIFIED"),
    ("claim_only", "REPAIR_NOT_VERIFIED"), ("alter_tests", "INVALID")])
def test_probe_requires_an_actual_source_repair_and_unchanged_tests(tmp_path, behavior, verdict):
    class ScriptedFixture:
        def work(self, root, goal, lessons, calls):
            assert not lessons and calls == 36
            assert not (root / "test_protected.py").exists()
            if behavior == "repair":
                (root / "capacity.py").write_text("def admit(quantity, capacity):\n    return quantity <= capacity\n")
            elif behavior == "alter_tests":
                (root / "test_visible.py").write_text("def test_fake():\n    assert True\n")
            return {"calls": 1, "prompt_tokens": 0, "output_tokens": 0}, {"decision": "SATISFIED"}
        def observed_usage(self):
            return [{"calls": 1, "prompt_tokens": 0, "output_tokens": 0, "complete": True}]
    path = Path(__file__).resolve().parents[1] / "examples/repair-probe.json"
    report = run_probe(ScriptedFixture(), tmp_path / "work", path)
    assert report["before"]["valid"] and not report["before"]["passed"]
    assert report["verdict"] == verdict and report["promotion_eligible"] is False
    if behavior == "repair":
        assert report["after"]["passed"] and report["source_changed"]
