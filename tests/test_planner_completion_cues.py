import unittest
from unittest.mock import patch

from planner import PlannerAgent


class FileFallbackState:
    def get_known_files(self):
        return ["hive_gui.py", "main.py", "planner.py"]

    def get_repo_map(self):
        return {"symbol_to_file": {}, "file_symbols": {"hive_gui.py": []}}

    def resolve_symbol_to_file(self, symbol):
        return None

    def get_symbol_span(self, target_file, target_symbol):
        return None

    def get_symbols_for_file(self, file_name):
        return []


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

    def test_plan_task_uses_file_fallback_for_single_file_gui_feature(self):
        agent = PlannerAgent(state_manager=FileFallbackState())
        task = {
            "id": 589,
            "note": "add a switch in the gui for a dark mode asthetic",
            "target_file": "hive_gui.py",
            "metadata": {
                "target_file": "hive_gui.py",
                "anchor": {
                    "target_file": "hive_gui.py",
                    "target_symbol": None,
                    "scope": "single_file",
                    "anchor_level": "file",
                    "anchor_source": "pilot_guidance",
                },
            },
        }
        bad_plan = {
            "goal": "Add dark mode toggle to the GUI.",
            "task_type": "feature",
            "tasks": [
                {
                    "title": "Add dark mode switch",
                    "description": "Add a switch to toggle the GUI dark mode aesthetic.",
                    "target_file": "hive_gui.py",
                    "change_intent": "modify_existing_logic",
                    "expected_operation": "modify_logic",
                    "completion_cues": ["dark mode switch works"],
                }
            ],
            "dependencies": ["hive_gui.py"],
            "risks": ["Theme regressions."],
            "next_action": "Patch hive_gui.py.",
            "status": "planned",
        }

        with patch("planner.ask_model", return_value=str(bad_plan).replace("'", '"')):
            plan = agent.plan_task(task)

        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["source"], "fallback_file_task")
        self.assertEqual(plan["target_file"], "hive_gui.py")
        self.assertEqual(plan["tasks"][0]["target_file"], "hive_gui.py")
        self.assertIsNone(plan["tasks"][0].get("target_symbol"))

    def test_plan_task_uses_file_fallback_for_task_backlog_feature(self):
        agent = PlannerAgent(state_manager=FileFallbackState())
        task = {
            "id": 597,
            "note": "create a way of clearing older tasks that no longer need to be completed",
            "target_file": "main.py",
            "metadata": {
                "target_file": "main.py",
                "work_mode": "create",
                "domain": "code",
                "artifact": "task backlog",
                "anchor": {
                    "target_file": "main.py",
                    "target_symbol": None,
                    "scope": "single_file",
                    "anchor_level": "file",
                    "anchor_source": "file_level_inference",
                },
            },
        }
        bad_plan = {
            "goal": "Create a stale-task clearing command.",
            "task_type": "feature",
            "tasks": [
                {
                    "title": "Add stale task clearing",
                    "description": "Create a command that clears older tasks that no longer need completion.",
                    "target_file": "main.py",
                    "change_intent": "modify_existing_logic",
                    "expected_operation": "modify_logic",
                    "completion_cues": ["old tasks are clearable"],
                }
            ],
            "dependencies": ["main.py"],
            "risks": ["Task history could be removed too broadly."],
            "next_action": "Patch main.py.",
            "status": "planned",
        }

        with patch("planner.ask_model", return_value=str(bad_plan).replace("'", '"')):
            plan = agent.plan_task(task)

        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["source"], "fallback_file_task")
        self.assertEqual(plan["target_file"], "main.py")
        self.assertEqual(plan["work_mode"], "create")
        self.assertEqual(plan["tasks"][0]["target_file"], "main.py")
        self.assertIsNone(plan["tasks"][0].get("target_symbol"))

    def test_insert_method_change_intent_normalizes_for_gui_file_plan(self):
        agent = PlannerAgent(state_manager=FileFallbackState())
        task = {
            "id": 589,
            "note": "add a switch in the gui for a dark mode asthetic",
            "target_file": "hive_gui.py",
            "metadata": {
                "target_file": "hive_gui.py",
                "anchor": {
                    "target_file": "hive_gui.py",
                    "target_symbol": None,
                    "scope": "single_file",
                    "anchor_level": "file",
                    "anchor_source": "pilot_guidance",
                },
            },
        }
        plan_payload = {
            "goal": "Add dark mode toggle to the GUI.",
            "task_type": "feature",
            "tasks": [
                {
                    "title": "Add dark mode switch",
                    "description": "Add a switch to toggle the GUI dark mode aesthetic.",
                    "target_file": "hive_gui.py",
                    "target_symbol": None,
                    "change_intent": "insert_method",
                    "expected_operation": "modify_logic",
                    "completion_cues": [],
                }
            ],
            "dependencies": ["hive_gui.py"],
            "risks": ["Theme regressions."],
            "next_action": "Patch hive_gui.py.",
            "status": "planned",
        }

        with patch("planner.ask_model", return_value=str(plan_payload).replace("'", '"').replace("None", "null")):
            plan = agent.plan_task(task)

        self.assertEqual(plan["status"], "planned")
        self.assertEqual(plan["dependencies"], ["hive_gui.py"])
        self.assertEqual(plan["tasks"][0]["change_intent"], "add_method_or_function")
        self.assertIsNone(plan["tasks"][0].get("target_symbol"))

    def test_create_mode_moves_new_symbol_out_of_target_symbol(self):
        agent = PlannerAgent(state_manager=FileFallbackState())
        task = {
            "id": 589,
            "note": "add a switch in the gui for a dark mode asthetic",
            "target_file": "hive_gui.py",
            "metadata": {
                "target_file": "hive_gui.py",
                "anchor": {
                    "target_file": "hive_gui.py",
                    "target_symbol": None,
                    "scope": "single_file",
                    "anchor_level": "file",
                    "anchor_source": "pilot_guidance",
                },
            },
        }
        plan_payload = {
            "goal": "Add dark mode toggle to the GUI.",
            "work_mode": "create",
            "domain": "code",
            "artifact": "GUI capability",
            "operation": "add control and wire state",
            "validation": "AST parse and GUI launch smoke test",
            "task_type": "feature",
            "tasks": [
                {
                    "title": "Add dark mode switch",
                    "description": "Add a switch to toggle the GUI dark mode aesthetic.",
                    "work_mode": "create",
                    "domain": "code",
                    "artifact": "GUI capability",
                    "operation": "add control and wire state",
                    "validation": "AST parse and GUI launch smoke test",
                    "target_file": "hive_gui.py",
                    "target_symbol": "GUIApp",
                    "change_intent": "add_new_capability",
                    "expected_operation": "add_capability",
                    "completion_cues": [],
                }
            ],
            "dependencies": ["hive_gui.py"],
            "risks": ["Theme regressions."],
            "next_action": "Add the dark mode control in hive_gui.py.",
            "status": "planned",
        }

        with patch("planner.ask_model", return_value=str(plan_payload).replace("'", '"')):
            plan = agent.plan_task(task)

        child = plan["tasks"][0]
        self.assertEqual(plan["work_mode"], "create")
        self.assertEqual(plan["domain"], "code")
        self.assertEqual(child["work_mode"], "create")
        self.assertIsNone(child.get("target_symbol"))
        self.assertIn("GUIApp", child["creates_symbols"])
        self.assertEqual(child["expected_operation"], "add_capability")

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
