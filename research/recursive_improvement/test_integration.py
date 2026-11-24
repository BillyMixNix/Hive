import tempfile
import unittest
from pathlib import Path

from research.recursive_improvement.integration import (
    CandidatePolicy,
    evaluate_proposal,
    propose_candidate,
)
from validation.archive import read_events


BASE_SOURCE = "def adjust(x):\n    return x\n"
PATCH = (
    "--- target.py\n"
    "+++ target.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def adjust(x):\n"
    "-    return x\n"
    "+    return x + 1\n"
)


class FakePlanner:
    def __init__(self, result=None):
        self.result = result or {"source": "test_planner", "tasks": []}
        self.calls = []

    def plan_task(self, task):
        self.calls.append(task)
        return self.result


class FakeCoder:
    def __init__(self, patch_data=None):
        self.patch_data = patch_data or {
            "target_file": "target.py",
            "patch": PATCH,
            "status": "proposed",
            "source": "test_coder",
        }
        self.calls = []

    def generate_patch(self, task, plan):
        self.calls.append((task, plan))
        return self.patch_data


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    (repo / "target.py").write_text(BASE_SOURCE, encoding="utf-8")
    regressions = repo / "validation" / "regressions"
    regressions.mkdir(parents=True)
    return repo


def behavioral_score(repo: Path) -> float:
    return 1.0 if "return x + 1" in (repo / "target.py").read_text(encoding="utf-8") else 0.0


class RecursiveImprovementIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.policy = CandidatePolicy(editable_targets=frozenset({"target.py"}))
        self.task = {"id": "ri-1", "note": "Make adjust add one."}

    def test_existing_planner_and_coder_contracts_produce_a_proposal(self):
        planner = FakePlanner()
        coder = FakeCoder()

        proposal = propose_candidate(
            self.task,
            planner=planner,
            coder=coder,
            policy=self.policy,
        )

        self.assertEqual(proposal.target_file, "target.py")
        self.assertEqual(proposal.plan["source"], "test_planner")
        self.assertEqual(len(planner.calls), 1)
        self.assertEqual(len(coder.calls), 1)

    def test_candidate_cannot_target_tests_or_evaluator_directories(self):
        protected = CandidatePolicy(editable_targets=frozenset({"tests/new_test.py"}))
        patch_data = {
            "target_file": "tests/new_test.py",
            "patch": "--- /dev/null\n+++ tests/new_test.py\n@@ -0,0 +1,1 @@\n+pass\n",
            "status": "proposed",
        }

        with self.assertRaises(PermissionError):
            protected.validate_patch_data(patch_data)

    def test_candidate_cannot_escape_repository_with_path_traversal(self):
        with self.assertRaises(ValueError):
            self.policy.assert_editable("../target.py")
        with self.assertRaises(ValueError):
            self.policy.assert_editable("C:\\target.py")

    def test_declared_target_must_match_diff_target(self):
        policy = CandidatePolicy(editable_targets=frozenset({"target.py", "other.py"}))
        patch_data = {
            "target_file": "target.py",
            "patch": PATCH.replace("target.py", "other.py"),
            "status": "proposed",
        }

        with self.assertRaises(ValueError):
            policy.validate_patch_data(patch_data)

    def test_planner_block_stops_before_coder(self):
        planner = FakePlanner({"status": "blocked", "llm_error": "offline"})
        coder = FakeCoder()

        with self.assertRaises(RuntimeError):
            propose_candidate(
                self.task,
                planner=planner,
                coder=coder,
                policy=self.policy,
            )
        self.assertEqual(coder.calls, [])

    def test_isolated_evaluation_returns_candidate_without_promotion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            proposal = propose_candidate(
                self.task,
                planner=FakePlanner(),
                coder=FakeCoder(),
                policy=self.policy,
            )

            record = evaluate_proposal(
                proposal,
                repo_root=repo,
                scorer=behavioral_score,
                regression_runner=lambda _repo: {
                    "passed": True,
                    "passed_count": 2,
                    "case_count": 2,
                    "failed_case_ids": [],
                },
                archive_path=root / "evidence.jsonl",
                policy=self.policy,
                n=2,
            )

            self.assertEqual(record["decision"], "candidate")
            self.assertFalse(record["promotion_allowed"])
            self.assertFalse(record["recursive_self_improvement_proven"])
            self.assertEqual(record["prototype_status"], "candidate_evaluation_only")
            self.assertEqual(record["regression_report"]["passed_count"], 2)
            self.assertEqual((repo / "target.py").read_text(encoding="utf-8"), BASE_SOURCE)
            events = read_events(root / "evidence.jsonl")
            self.assertEqual(events[-1]["event_type"], "recursive_improvement_candidate_evaluation")
            self.assertFalse(events[-1]["promotion_allowed"])
            self.assertFalse(events[-1]["recursive_self_improvement_proven"])

    def test_regression_failure_rejects_before_empirical_scoring(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            proposal = propose_candidate(
                self.task,
                planner=FakePlanner(),
                coder=FakeCoder(),
                policy=self.policy,
            )
            score_calls = []

            def scorer(candidate_repo):
                score_calls.append(candidate_repo)
                return behavioral_score(candidate_repo)

            record = evaluate_proposal(
                proposal,
                repo_root=repo,
                scorer=scorer,
                regression_runner=lambda _repo: {
                    "passed": False,
                    "passed_count": 1,
                    "case_count": 2,
                    "failed_case_ids": ["known-regression"],
                },
                archive_path=root / "evidence.jsonl",
                policy=self.policy,
                n=2,
            )

            self.assertEqual(record["decision"], "reject")
            self.assertIn("self_verification_failed", record["reason"])
            self.assertEqual(score_calls, [])
            self.assertEqual((repo / "target.py").read_text(encoding="utf-8"), BASE_SOURCE)


if __name__ == "__main__":
    unittest.main()
