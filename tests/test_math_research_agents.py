"""
Real tests for all five MathResearchAgent subclasses.
Uses actual CollatzExplorer, SymPy, and Z3 — no mocks.
"""
import sys
sys.path.insert(0, "/home/user/Hive")

import pytest
from math_domain import CollatzExplorer, Conjecture, MathProgressTracker
from HiveAgent import (
    ExploratoryAgent,
    AdversarialMathAgent,
    SymbolicMathAgent,
    FormalMathAgent,
    StrategicMathAgent,
)

try:
    import z3 as _z3
    _Z3_AVAILABLE = True
except ImportError:
    _Z3_AVAILABLE = False

REQUIRED_KEYS = {"role", "output", "confidence", "next_step"}


# ---------------------------------------------------------------------------
# ExploratoryAgent
# ---------------------------------------------------------------------------

class TestExploratoryAgent:

    def test_returns_required_keys(self):
        r = ExploratoryAgent().run({"n_range": (1, 100)})
        assert REQUIRED_KEYS.issubset(r.keys())

    def test_role_is_exploratory(self):
        r = ExploratoryAgent().run({"n_range": (1, 50)})
        assert r["role"] == "exploratory"

    def test_finds_longest_trajectory(self):
        r = ExploratoryAgent().run({"n_range": (1, 1000)})
        lt = r["output"]["longest_trajectory"]
        assert lt["n"] >= 1
        assert lt["stopping_time"] > 0

    def test_no_cycle_found_in_small_range(self):
        r = ExploratoryAgent().run({"n_range": (1, 500)})
        assert r["output"]["cycle_found"] is None
        assert r["confidence"] == 0.7

    def test_logs_entry(self):
        agent = ExploratoryAgent()
        agent.run({"n_range": (1, 50)})
        assert len(agent.session_log) == 1
        assert agent.session_log[0]["role"] == "exploratory"

    def test_accepts_prebuilt_explorer(self):
        explorer = CollatzExplorer()
        r = ExploratoryAgent().run({"explorer": explorer, "n_range": (1, 200)})
        assert r["output"]["range"] == [1, 200]


# ---------------------------------------------------------------------------
# AdversarialMathAgent
# ---------------------------------------------------------------------------

class TestAdversarialMathAgent:

    def test_returns_required_keys(self):
        r = AdversarialMathAgent().run({"n_range": (1, 100)})
        assert REQUIRED_KEYS.issubset(r.keys())

    def test_role_is_adversarial(self):
        r = AdversarialMathAgent().run({"n_range": (1, 100)})
        assert r["role"] == "adversarial"

    def test_no_counterexample_small_range(self):
        r = AdversarialMathAgent().run({"n_range": (1, 1000)})
        assert r["output"]["counterexample"] is None
        assert r["confidence"] == 0.6

    def test_updates_conjecture_on_survival(self):
        c = Conjecture(statement="All n reach 1")
        AdversarialMathAgent().run({"n_range": (1, 500), "conjecture": c})
        assert len(c.falsification_attempts) == 1
        assert "[SURVIVED]" in c.falsification_attempts[0]

    def test_conjecture_status_unchanged_when_survived(self):
        c = Conjecture(statement="All n reach 1")
        AdversarialMathAgent().run({"n_range": (1, 200), "conjecture": c})
        assert c.status == "unverified"


# ---------------------------------------------------------------------------
# SymbolicMathAgent
# ---------------------------------------------------------------------------

class TestSymbolicMathAgent:

    def test_returns_required_keys(self):
        r = SymbolicMathAgent().run({})
        assert REQUIRED_KEYS.issubset(r.keys())

    def test_role_is_symbolic(self):
        assert SymbolicMathAgent().run({})["role"] == "symbolic"

    def test_default_task_stopping_time_model(self):
        r = SymbolicMathAgent().run({})
        assert r["output"]["name"] == "stopping_time_model"
        assert "c_numerical" in r["output"]

    def test_gap_formula_task(self):
        r = SymbolicMathAgent().run({"task": "gap_formula"})
        assert r["output"]["name"] == "gap_formula"
        assert "gap_numerical" in r["output"]

    def test_verify_identity_true(self):
        r = SymbolicMathAgent().run({"task": "verify_identity", "lhs": "n + n", "rhs": "2*n"})
        assert r["output"]["identical"] is True

    def test_verify_identity_false(self):
        r = SymbolicMathAgent().run({"task": "verify_identity", "lhs": "n + 1", "rhs": "n"})
        assert r["output"]["identical"] is False

    def test_check_approximation_vanishes(self):
        r = SymbolicMathAgent().run({
            "task": "check_approximation",
            "exact": "log(3*n + 1)",
            "approx": "log(3*n)",
        })
        assert r["output"]["limit_as_n_inf"] == "0"

    def test_confidence_range(self):
        r = SymbolicMathAgent().run({})
        assert 0.0 <= r["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# FormalMathAgent
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _Z3_AVAILABLE, reason="z3-solver not installed")
class TestFormalMathAgent:

    def test_returns_required_keys(self):
        r = FormalMathAgent().run({})
        assert REQUIRED_KEYS.issubset(r.keys())

    def test_role_is_formal(self):
        assert FormalMathAgent().run({})["role"] == "formal"

    def test_run_all_proves_t1(self):
        r = FormalMathAgent().run({})
        assert r["output"]["T1"]["status"] == "PROVED"

    def test_run_all_proves_t2(self):
        r = FormalMathAgent().run({})
        assert r["output"]["T2"]["status"] == "PROVED"

    def test_even_after_odd_task(self):
        r = FormalMathAgent().run({"task": "even_after_odd"})
        assert r["output"]["status"] == "PROVED"
        assert r["confidence"] == 0.95

    def test_syracuse_growth_task(self):
        r = FormalMathAgent().run({"task": "syracuse_growth"})
        assert r["output"]["status"] == "PROVED"

    def test_v2_geq_k_task(self):
        r = FormalMathAgent().run({"task": "v2_geq_k", "k": 2})
        assert r["output"]["status"] == "PROVED"

    def test_geometric_distribution_task(self):
        r = FormalMathAgent().run({"task": "geometric_distribution", "max_k": 3})
        assert r["output"]["status"] in ("PROVED", "PARTIAL")

    def test_logs_entry(self):
        agent = FormalMathAgent()
        agent.run({"task": "even_after_odd"})
        assert len(agent.session_log) == 1


# ---------------------------------------------------------------------------
# StrategicMathAgent
# ---------------------------------------------------------------------------

class TestStrategicMathAgent:

    def test_returns_required_keys(self):
        c = Conjecture(statement="All n reach 1")
        r = StrategicMathAgent().run({"conjecture": c})
        assert REQUIRED_KEYS.issubset(r.keys())

    def test_role_is_strategic(self):
        c = Conjecture(statement="All n reach 1")
        assert StrategicMathAgent().run({"conjecture": c})["role"] == "strategic"

    def test_no_conjectures_returns_zero_confidence(self):
        r = StrategicMathAgent().run({})
        assert r["confidence"] == 0.0
        assert r["output"]["scores"] == []

    def test_scores_single_conjecture(self):
        c = Conjecture(statement="All n reach 1", evidence=["tested 10k values"])
        r = StrategicMathAgent().run({"conjecture": c})
        assert len(r["output"]["scores"]) == 1
        assert r["output"]["best_conjecture"] is not None

    def test_scores_multiple_conjectures(self):
        c1 = Conjecture(statement="All n reach 1")
        c2 = Conjecture(
            statement="E[T(n)] ≈ c * log(n)",
            evidence=["e1", "e2"],
            proof_sketch="Assume geometric distribution of v2. Let c = 3/log(4/3)."
        )
        r = StrategicMathAgent().run({"conjectures": [c1, c2]})
        assert len(r["output"]["scores"]) == 2
        # c2 should score higher (evidence + algebraic signal + proof sketch)
        assert r["output"]["scores"][0]["score"] >= r["output"]["scores"][1]["score"]

    def test_confidence_proportional_to_score(self):
        c = Conjecture(
            statement="E[T(n)] ≈ c * log(n)",
            evidence=["e1", "e2"],
            proof_sketch="Assume X. Let Y. Bounded by Z.",
            formal_fragment="Z3 proof",
        )
        r = StrategicMathAgent().run({"conjecture": c})
        assert r["confidence"] > 0.5

    def test_session_log_grows(self):
        agent = StrategicMathAgent()
        c = Conjecture(statement="All n reach 1")
        agent.run({"conjecture": c})
        agent.run({"conjecture": c})
        assert len(agent.session_log) == 2
