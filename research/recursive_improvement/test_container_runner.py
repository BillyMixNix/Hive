import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.recursive_improvement.container_runner import ContainerRunner, Limits, SandboxUnavailable
from research.recursive_improvement.experiment1.run import restrict_method, score, stage_patch
from research.recursive_improvement.gate import Trial, evaluate_candidate


IMAGE = "sha256:" + "a" * 64


class BoundaryTests(unittest.TestCase):
    def test_command_enforces_boundary_and_never_exposes_oracle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            harness = root / "harness"
            harness.mkdir()
            command = ContainerRunner(IMAGE, harness).command(root, "test", "extract")
            for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--pids-limit",
                         "--memory", "--memory-swap", "--cpus", "--user=65534:65534",
                         "--security-opt=no-new-privileges:true", "--log-driver=none"):
                self.assertIn(flag, command)
            self.assertTrue(all(v.endswith(",readonly") for v in command if v.startswith("type=bind")))
            self.assertNotIn("--privileged", command)

    def test_no_mutable_images_or_invalid_limits(self):
        with self.assertRaises(ValueError):
            ContainerRunner("python:latest", Path("."))
        for value in (0, -1, float("nan"), True):
            with self.assertRaises(ValueError):
                Limits(memory_mb=value)

    def test_symlink_subject_is_rejected_before_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "escape").symlink_to("/etc/passwd")
            with self.assertRaises(ValueError):
                ContainerRunner(IMAGE, Path(__file__).parent).command(root, "x", "extract")

    def test_no_host_execution_fallback_on_daemon_failure(self):
        runner = ContainerRunner(IMAGE, Path(__file__).parent)
        with patch("research.recursive_improvement.container_runner._docker", side_effect=SandboxUnavailable("absent")):
            with self.assertRaises(SandboxUnavailable):
                runner.preflight()

    def test_subject_cannot_supply_scores_or_omit_cases(self):
        cases = [{"id": "a", "input": "{}", "expected": {}}]
        result = score(cases, [{"id": "a", "text": "{bad}", "correct": True}])
        self.assertFalse(result[0]["correct"])
        for responses in ([], [{"id": "wrong", "text": "{}"}],
                          [{"id": "a", "text": "{}", "error": "ValueError"}]):
            with self.assertRaises(ValueError):
                score(cases, responses)

    def test_json_types_invalid_returns_and_exceptions(self):
        cases = [{"id": "a", "input": "", "expected": {"x": True}}]
        self.assertFalse(score(cases, [{"id": "a", "text": '{"x":1}'}])[0]["correct"])
        self.assertFalse(score(cases, [{"id": "a", "text": '{"x":NaN}'}])[0]["correct"])
        cases = [{"id": "a", "input": "", "error": "ValueError"}]
        self.assertFalse(score(cases, [{"id": "a", "text": "invalid"}])[0]["correct"])
        self.assertTrue(score(cases, [{"id": "a", "error": "ValueError"}])[0]["correct"])

    def test_candidate_cannot_change_imports_signature_decorators_or_other_methods(self):
        original = "import json\nclass PlannerAgent:\n    def _extract_json_object(self, text):\n        return text\n    def other(self):\n        return 2\n"
        restrict_method(original, original.replace("return text", "return '{}'"))
        for candidate in (original.replace("import json", "import os"),
                          original.replace("return 2", "return 3"),
                          original.replace("self, text", "self, text, extra=None"),
                          original.replace("    def _extract", "    @property\n    def _extract")):
            with self.assertRaises(PermissionError):
                restrict_method(original, candidate)

    def test_protected_patch_rejected_without_creating_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(PermissionError):
                stage_patch(root, root / "variant", {"target_file": "tests/eval.py", "patch": "unused"})
            self.assertFalse((root / "variant").exists())

    def test_nonfinite_or_forged_trial_data_is_rejected(self):
        for value in (float("nan"), float("inf"), -1, True, "0"):
            for field in ("cost", "latency_ms"):
                with self.assertRaises(ValueError):
                    Trial("a", True, **{field: value, ("latency_ms" if field == "cost" else "cost"): 0})
        with self.assertRaises(ValueError):
            Trial("a", "true", 0, 0)
        for value in (float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                evaluate_candidate([], [], min_accuracy_gain=value)


if __name__ == "__main__":
    unittest.main()
