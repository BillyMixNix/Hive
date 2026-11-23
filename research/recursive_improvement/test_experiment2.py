import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.recursive_improvement.experiment2.structured import (
    compact_prompt, hive_plan, method_to_contract, validate_plan,
)
from research.recursive_improvement.experiment2.run import cost_report, StructuredTransport
from research.recursive_improvement.experiment2.regression_adapter import fixture_path_class
from validation.variant import apply_unified_diff


ORIGINAL = 'import json\nclass PlannerAgent:\n    def _extract_json_object(self, raw_response):\n        return raw_response\n    def other(self):\n        return 7\n'
PLAN = {"target_file": "planner.py", "target_symbol": "_extract_json_object",
        "objective": "extract_first_json_object", "approach": "Parse and extract the first JSON object from the response."}


class Experiment2Tests(unittest.TestCase):
    def test_off_goal_plan_is_rejected_before_coder(self):
        for change in ({"target_file": "main.py"}, {"objective": "new_feature"},
                       {"approach": "Add a new feature in main.py."}, {"approach": "Do something else completely."}):
            with self.assertRaises(ValueError):
                validate_plan(json.dumps({**PLAN, **change}))
        self.assertEqual(validate_plan(json.dumps(PLAN)), PLAN)
        self.assertEqual(json.loads(hive_plan(PLAN))["tasks"][0]["target_symbol"], "_extract_json_object")

    def test_structured_method_becomes_a_strict_single_method_diff(self):
        source = 'def _extract_json_object(self, raw_response):\n    return "{}"\n'
        result = method_to_contract(json.dumps({"method_source": source}), ORIGINAL)
        changed = apply_unified_diff(ORIGINAL, result.split("PATCH:\n", 1)[1])
        self.assertIn('        return "{}"', changed)
        self.assertIn('        return 7', changed)

    def test_method_cannot_add_code_change_signature_or_return_extra_fields(self):
        samples = [
            {"method_source": 'import os\ndef _extract_json_object(self, raw_response):\n    return "{}"'},
            {"method_source": 'def _extract_json_object(self, value):\n    return "{}"'},
            {"method_source": 'def _extract_json_object(self, raw_response):\n    return "{}"', "reason": "extra"},
        ]
        for sample in samples:
            with self.assertRaises((ValueError, PermissionError)):
                method_to_contract(json.dumps(sample), ORIGINAL)

    def test_coder_cannot_be_called_without_a_real_approved_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            transport = StructuredTransport({"generation": {"max_calls": 6}}, 1, ORIGINAL, [], Path(tmp), [])
            with patch("urllib.request.urlopen") as network:
                with self.assertRaises(RuntimeError):
                    transport("test", role="coder")
                network.assert_not_called()

    def test_only_legacy_fixture_paths_are_redirected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subject, scratch = root / "subject", root / "scratch"
            subject.mkdir(); scratch.mkdir()
            P = fixture_path_class(subject, scratch)
            self.assertEqual(P(subject) / "tests" / "_tmp_abc", scratch / "_tmp_abc")
            self.assertEqual(P(subject / "tests/_tmp_abc/file.json"), scratch / "_tmp_abc/file.json")
            self.assertEqual(P(subject) / "tests" / "test_gate.py", subject / "tests/test_gate.py")
            self.assertEqual(P(subject) / "planner.py", subject / "planner.py")
            self.assertFalse((subject / "tests").exists())

    def test_completed_usage_survives_downstream_rejection_but_disconnect_is_unknown(self):
        call = {"status": "ValueError", "done": True, "prompt_eval_count": 100, "eval_count": 25, "wall_ms": 50}
        self.assertEqual(cost_report([call])["prompt_tokens"], 100)
        self.assertEqual(cost_report([call])["output_tokens"], 25)
        self.assertIsNone(cost_report([call, {"status": "RemoteDisconnected", "wall_ms": 10}])["prompt_tokens"])

    def test_prompt_contains_only_public_cases(self):
        prompt = compact_prompt("planner", {"contract": "Extract the first JSON object."}, ORIGINAL,
                                [{"id": "public-marker", "input": "{}", "expected": {}}])
        self.assertIn("public-marker", prompt)
        self.assertNotIn("heldout", prompt)
        self.assertLess(len(prompt), 4000)


if __name__ == "__main__":
    unittest.main()
