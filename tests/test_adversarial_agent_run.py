"""
Real tests for AdversarialTestAgent.run() — the orchestrating dispatcher.
No mocks: uses actual callables and verifies routing + hypothesis mutation.
"""
import sys
import dataclasses
sys.path.insert(0, "/home/user/Hive")

from code_domain import AdversarialTestAgent, CodeConjecture


def _conjecture(hypothesis_type="correctness", statement="f(x) always returns an int"):
    return CodeConjecture(statement=statement, hypothesis_type=hypothesis_type)


agent = AdversarialTestAgent()


class TestRunDispatching:

    # ------------------------------------------------------------------
    # skipped / missing args
    # ------------------------------------------------------------------
    def test_architecture_skipped_without_forbidden_edge(self):
        h = _conjecture("architecture")
        r = agent.run(h)
        assert r["status"] == "skipped"
        assert r["falsified"] is False

    def test_performance_skipped_without_fn(self):
        h = _conjecture("performance")
        r = agent.run(h)
        assert r["status"] == "skipped"

    def test_correctness_skipped_without_fn(self):
        h = _conjecture("correctness")
        r = agent.run(h)
        assert r["status"] == "skipped"

    # ------------------------------------------------------------------
    # correctness → boundary_probe
    # ------------------------------------------------------------------
    def test_correctness_runs_boundary_probe(self):
        h = _conjecture("correctness", "abs(x) always returns a non-negative int")
        r = agent.run(h, fn=abs)
        assert r["hypothesis_type"] == "correctness"
        assert r["status"] in ("survived", "falsified")
        assert "detail" in r
        assert "results" in r["detail"]   # boundary_probe output shape

    def test_correctness_infers_str_type_hint(self):
        h = _conjecture("correctness", "len(str) always returns a non-negative int")
        r = agent.run(h, fn=len)
        assert r["detail"].get("type_hint") == "str"

    def test_correctness_infers_list_type_hint(self):
        h = _conjecture("correctness", "sorted(list) always returns a list")
        r = agent.run(h, fn=sorted)
        assert r["detail"].get("type_hint") == "list"

    # ------------------------------------------------------------------
    # security → boundary_probe with str
    # ------------------------------------------------------------------
    def test_security_uses_str_boundary_probe(self):
        h = _conjecture("security", "no user input reaches eval")
        r = agent.run(h, fn=len)
        assert r["hypothesis_type"] == "security"
        assert r["detail"].get("type_hint") == "str"

    # ------------------------------------------------------------------
    # architecture → architecture_trace
    # ------------------------------------------------------------------
    def test_architecture_runs_trace(self, tmp_path):
        # Write a tiny module that does NOT call the forbidden function
        (tmp_path / "planner.py").write_text("def plan(): return 42\n")
        h = _conjecture("architecture", "planner never calls ask_model directly")
        r = agent.run(
            h,
            source_dir=str(tmp_path),
            forbidden_edge=("planner", "ask_model"),
        )
        assert r["hypothesis_type"] == "architecture"
        assert r["falsified"] is False
        assert r["verdict"] == "clean"

    def test_architecture_detects_violation(self, tmp_path):
        (tmp_path / "planner.py").write_text("def plan(): return ask_model('hi')\n")
        h = _conjecture("architecture")
        r = agent.run(
            h,
            source_dir=str(tmp_path),
            forbidden_edge=("planner", "ask_model"),
        )
        assert r["falsified"] is True
        assert len(r["detail"]["violations"]) > 0

    # ------------------------------------------------------------------
    # performance → scaling_probe
    # ------------------------------------------------------------------
    def test_performance_runs_scaling_probe(self):
        h = _conjecture("performance", "sorted() scales acceptably")
        r = agent.run(
            h,
            fn=sorted,
            size_fn=lambda n: list(range(n, 0, -1)),
            sizes=[10, 50, 100],
        )
        assert r["hypothesis_type"] == "performance"
        assert "sizes" in r["detail"]

    # ------------------------------------------------------------------
    # hypothesis mutation
    # ------------------------------------------------------------------
    def test_run_records_falsification_attempt(self):
        h = _conjecture("correctness")
        assert len(h.falsification_attempts) == 0
        agent.run(h, fn=abs)
        assert len(h.falsification_attempts) == 1

    def test_run_marks_hypothesis_falsified_when_fn_raises(self):
        def always_raises(x):
            raise ValueError("boom")

        h = _conjecture("correctness")
        r = agent.run(h, fn=always_raises)
        assert r["falsified"] is True
        assert h.status == "falsified"

    def test_survived_does_not_change_hypothesis_status(self):
        h = _conjecture("correctness")
        agent.run(h, fn=abs)
        assert h.status == "unverified"   # abs won't raise on boundary ints

    # ------------------------------------------------------------------
    # return shape
    # ------------------------------------------------------------------
    def test_run_always_returns_required_keys(self):
        required = {"hypothesis_type", "status", "falsified", "verdict", "counterexample", "detail"}
        for h_type in ("correctness", "architecture", "performance", "security"):
            h = _conjecture(h_type)
            r = agent.run(h)
            assert required.issubset(r.keys()), f"Missing keys for {h_type}: {required - r.keys()}"
