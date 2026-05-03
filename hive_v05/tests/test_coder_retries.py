import unittest

from coder import CoderAgent
from coder_prompting import build_preflight_intent, build_symbol_locked_prompt
from failure_intelligence import interpret_failure


class CoderRetryTests(unittest.TestCase):
    def setUp(self):
        self.agent = CoderAgent()
        self.task = {
            "id": "t1",
            "note": "Tighten retry behavior in generate_patch_with_revisions.",
            "target_file": "coder.py",
            "target_symbol": "generate_patch_with_revisions",
        }
        self.plan = {
            "goal": "Keep retries narrow and symbol-locked.",
            "tasks": [],
            "dependencies": ["coder.py"],
            "risks": [],
            "next_action": "Update retry prompt behavior.",
            "status": "planned",
        }
        self.context = {
            "mode": "exact_symbol_block",
            "target_name": "generate_patch_with_revisions",
            "context_text": "def generate_patch_with_revisions(self, task, plan, reflector, max_revisions=2):\n    pass",
        }

    def test_strip_markdown_fences_prefers_patch_block(self):
        raw_response = (
            "Here is the patch.\n\n"
            "```diff\n"
            "TARGET_FILE: coder.py\n"
            "CHANGE_TYPE: diff_patch\n"
            "RISK_LEVEL: low\n"
            "STATUS: proposed\n"
            "REASON: tighten retries\n"
            "PATCH:\n"
            "--- coder.py\n"
            "+++ coder.py\n"
            "@@\n"
            "-old\n"
            "+new\n"
            "```\n"
        )

        cleaned = self.agent._strip_markdown_fences_harder(
            raw_response,
            expect_patch_contract=True,
        )

        self.assertTrue(cleaned.startswith("TARGET_FILE: coder.py"))
        self.assertNotIn("```", cleaned)

    def test_symbol_locked_retry_prompt_stays_symbol_locked(self):
        prompt = self.agent._build_retry_prompt(
            self.task,
            self.plan,
            "coder.py",
            self.context["context_text"],
            "--- coder.py\n+++ coder.py\n@@\n-old\n+new",
            {
                "reflection": "Sandbox semantic failed: issue remains inside the target symbol.",
                "confidence": 0.8,
                "verdict": "revise",
            },
            "Keep the retry narrow.",
            self.context,
        )

        self.assertIn("Rewrite only the existing function generate_patch_with_revisions in coder.py.", prompt)
        self.assertIn("Previous patch excerpt:", prompt)
        self.assertIn("Prefer the smallest possible line edit", prompt)
        self.assertNotIn("Do not modify any other symbol.\n- Revise", prompt)

    def test_completion_cue_failure_stops_retry(self):
        interpretation = interpret_failure(
            stage="exception",
            error_text="Patch does not satisfy planner completion_cues; missing expected diff cues: ['return anchor'].",
            task=self.task,
        )

        self.assertTrue(self.agent._should_stop_retry(interpretation))

    def test_planner_validation_failure_stops_retry(self):
        interpretation = interpret_failure(
            stage="planner",
            error_text="Planner output failed validation: Planner produced task without target_symbol.",
            task=self.task,
            metadata={"planner_failure_code": "planner_missing_target_symbol"},
        )

        self.assertTrue(self.agent._should_stop_retry(interpretation))

    def test_symbol_anchor_drift_retry_profile_is_exact_and_no_new_methods(self):
        interpretation = interpret_failure(
            stage="exception",
            error_text="symbol_anchor_drift: patch modifies unrelated symbols ['helper']; only generate_patch_with_revisions may change.",
            task=self.task,
        )

        profile = self.agent._build_retry_profile(self.task, interpretation)
        formatted = self.agent._format_retry_profile(profile)

        self.assertEqual(profile["failure_code"], "symbol_anchor_drift")
        self.assertIn("exact symbol rewrite only", formatted)
        self.assertIn("no new methods", formatted)
        self.assertIn("same symbol", formatted)

    def test_missing_diff_headers_retry_profile_is_parser_contract_only(self):
        interpretation = interpret_failure(
            stage="exception",
            error_text="Patch is missing diff file headers.",
            task=self.task,
        )

        profile = self.agent._build_retry_profile(self.task, interpretation)
        formatted = self.agent._format_retry_profile(profile)

        self.assertEqual(profile["failure_code"], "missing_diff_headers")
        self.assertFalse(profile["prefer_smaller_retry"])
        self.assertTrue(profile["shape_reset_allowed"])
        self.assertIn("parser contract", formatted.lower())
        self.assertIn("---/+++ headers", formatted)

    def test_non_meaningful_patch_retry_profile_requires_substantive_change_or_block(self):
        interpretation = interpret_failure(
            stage="exception",
            error_text="Patch failed usefulness check: no meaningful code changes detected.",
            task=self.task,
        )

        profile = self.agent._build_retry_profile(self.task, interpretation)
        formatted = self.agent._format_retry_profile(profile)

        self.assertEqual(profile["failure_code"], "non_meaningful_patch")
        self.assertIn("substantive change or block", formatted.lower())
        self.assertIn("cosmetic-only patch", formatted)

    def test_preflight_intent_includes_symbol_span_operation_and_completion_cues(self):
        task = {
            "id": "t2",
            "note": "Copy context before returning it.",
            "target_file": "interface.py",
            "target_symbol": "_build_response",
            "expected_operation": "modify_logic",
            "completion_cues": ['"context": dict(context or {}),'],
            "metadata": {
                "anchor": {
                    "target_file": "interface.py",
                    "target_symbol": "_build_response",
                    "target_symbol_id": "interface.py::_build_response",
                    "lineno": 49,
                    "end_lineno": 55,
                }
            },
        }

        preflight = build_preflight_intent(task, "interface.py")

        self.assertIn("STRICT REQUIREMENTS:", preflight)
        self.assertIn("You MUST only modify: _build_response", preflight)
        self.assertIn("You MUST stay within lines: 49-55", preflight)
        self.assertIn("You MUST satisfy expected_operation: modify_logic", preflight)
        self.assertIn('"context": dict(context or {}),', preflight)
        self.assertIn("You MUST NOT modify any other functions", preflight)

    def test_symbol_locked_prompt_injects_preflight_intent(self):
        task = {
            "id": "t3",
            "note": "Copy context before returning it.",
            "target_file": "interface.py",
            "target_symbol": "_build_response",
            "expected_operation": "modify_logic",
            "completion_cues": ['"context": dict(context or {}),'],
            "metadata": {
                "anchor": {
                    "target_file": "interface.py",
                    "target_symbol": "_build_response",
                    "target_symbol_id": "interface.py::_build_response",
                    "lineno": 49,
                    "end_lineno": 55,
                }
            },
        }

        prompt = build_symbol_locked_prompt(
            task,
            "interface.py",
            "def _build_response(self, intent, text, context=None):\n    pass\n",
        )

        self.assertIn("Preflight intent:", prompt)
        self.assertIn("You MUST only modify: _build_response", prompt)
        self.assertIn("You MUST stay within lines: 49-55", prompt)
        self.assertIn("You MUST satisfy expected_operation: modify_logic", prompt)
        self.assertIn('"context": dict(context or {}),', prompt)


if __name__ == "__main__":
    unittest.main()
