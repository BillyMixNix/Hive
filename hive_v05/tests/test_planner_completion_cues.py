import unittest
from unittest.mock import patch

from planner import PlannerAgent


class PlannerCompletionCueTests(unittest.TestCase):
    def setUp(self):
        self.agent = PlannerAgent()

    def test_accepts_code_like_completion_cues(self):
        child = {
            "completion_cues": [
                'parent_anchor.get("anchor_level", "file")',
                'child["target_symbol"] = anchored_symbol',
                'raise ValueError(f"Child task missing target_symbol: {child}")',
            ]
        }

        normalized = self.agent._normalize_completion_cues(child)

        self.assertEqual(normalized, child["completion_cues"])

    def test_normalize_completion_cues_only_trims_and_keeps_strings(self):
        child = {
            "completion_cues": [
                "keep_symbol",
                " consistent anchor handling ",
                "anchor preservation logic added",
            ]
        }

        normalized = self.agent._normalize_completion_cues(child)

        self.assertEqual(
            normalized,
            [
                "keep_symbol",
                "consistent anchor handling",
                "anchor preservation logic added",
            ],
        )

    def test_normalize_expected_operation_detects_comment_tasks(self):
        child = {
            "title": "Add anchor explanation comment",
            "description": "Insert a comment above the anchor_span branch to explain why span-based targeting is enforced.",
            "target_symbol": "select_edit_context",
            "change_intent": "modify_existing_logic",
        }

        normalized = self.agent._normalize_expected_operation(child)

        self.assertEqual(normalized, "insert_comment")

    def test_normalize_completion_cues_for_insert_comment(self):
        child = {
            "expected_operation": "insert_comment",
            "completion_cues": [],
        }

        normalized = self.agent._normalize_completion_cues(child)

        self.assertEqual(normalized, ["# ", "anchored_symbol", "anchor_span"])

    def test_validate_plan_rejects_non_concrete_completion_cues(self):
        plan = {
            "goal": "Keep child tasks anchored to exact symbols.",
            "task_type": "bugfix",
            "tasks": [
                {
                    "title": "Preserve child symbol anchor",
                    "description": "Update routing logic in route to preserve the symbol anchor on child tasks.",
                    "target_file": "main.py",
                    "target_symbol": "route",
                    "change_intent": "modify_existing_logic",
                    "expected_operation": "modify_logic",
                    "completion_cues": ["consistent anchor handling"],
                }
            ],
            "dependencies": ["main.py"],
            "risks": ["Overwriting child task anchors could break narrow patch routing."],
            "next_action": "Update route in main.py to keep the child symbol anchor attached to emitted tasks.",
            "status": "planned",
        }

        with self.assertRaisesRegex(ValueError, "concrete diff-visible code strings"):
            self.agent._validate_plan(plan, parent_task_id="p1")

    def test_plan_task_uses_narrow_fallback_on_invalid_planner_shape(self):
        task = {
            "id": "p-fallback",
            "note": "Insert a comment above the anchor_span branch in select_edit_context to explain strict span-based targeting.",
            "target_file": "coder_context.py",
            "target_symbol": "select_edit_context",
            "metadata": {
                "target_file": "coder_context.py",
                "target_symbol": "select_edit_context",
            },
        }

        with patch("planner.ask_model", return_value="not json at all"):
            plan = self.agent.plan_task(task)

        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["source"], "fallback_narrow_task")
        self.assertEqual(plan["metadata"]["planner_source"], "fallback_narrow_task")
        self.assertEqual(plan["metadata"]["planner_failure_code"], "invalid_llm_plan_shape")
        self.assertEqual(len(plan["tasks"]), 1)
        self.assertEqual(plan["tasks"][0]["target_file"], "coder_context.py")
        self.assertEqual(plan["tasks"][0]["target_symbol"], "select_edit_context")

    def test_plan_task_architectural_task_still_blocks_without_single_symbol_fallback(self):
        task = {
            "id": "p-blocked",
            "note": "Refactor planner and main.py routing architecture across multiple files.",
            "target_file": "main.py",
            "metadata": {
                "target_file": "main.py",
            },
        }

        with patch("planner.ask_model", return_value="not json at all"):
            plan = self.agent.plan_task(task)

        self.assertEqual(plan["status"], "blocked")
        self.assertEqual(plan["source"], "planner_error")
        self.assertEqual(plan["metadata"]["planner_failure_code"], "invalid_llm_plan_shape")

    def test_fallback_plan_preserves_anchored_file_and_symbol(self):
        task = {
            "id": "p-anchored",
            "note": "Update _normalize_completion_cues so empty non-string cues are ignored consistently.",
            "target_file": "planner.py",
            "target_symbol": "_normalize_completion_cues",
            "metadata": {
                "target_file": "planner.py",
                "target_symbol": "_normalize_completion_cues",
            },
        }

        with patch("planner.ask_model", return_value="{\"goal\": \"bad\", \"tasks\": []}"):
            plan = self.agent.plan_task(task)

        self.assertEqual(plan["source"], "fallback_narrow_task")
        child = plan["tasks"][0]
        self.assertEqual(child["target_file"], "planner.py")
        self.assertEqual(child["target_symbol"], "_normalize_completion_cues")


if __name__ == "__main__":
    unittest.main()
