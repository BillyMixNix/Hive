import unittest

from builder import BuilderAgent, build_pilot_context, format_pilot_brief, merge_pilot_context
from coder_prompting import build_prompt
from interface import Interface
from planner import PlannerAgent


class PilotIntentLoopTests(unittest.TestCase):
    def test_builder_persists_structured_pilot_context(self):
        agent = BuilderAgent()

        result = agent.build(
            {
                "intent": (
                    "Update router.py so pilot guidance can be revised mid-task. "
                    "Do not add a new subsystem."
                )
            }
        )

        self.assertEqual(result["pilot_intent"], result["pilot_context"]["current_intent"])
        self.assertIn("Do not add a new subsystem", result["pilot_context"]["constraints"])
        self.assertIn("pilot guidance can be revised", result["pilot_context"]["intent_summary"])

    def test_merge_pilot_context_keeps_recent_history(self):
        existing = build_pilot_context("Keep the patch narrow.")

        merged = merge_pilot_context(
            existing,
            "Also preserve the current planner flow without adding a new file.",
        )

        self.assertEqual(len(merged["history"]), 2)
        self.assertIn("Keep the patch narrow.", merged["history"])
        self.assertEqual(
            merged["current_intent"],
            "Also preserve the current planner flow without adding a new file.",
        )

    def test_interface_parses_pilot_task_guidance_command(self):
        message = Interface().process_input(
            "pilot task 14 preserve planner behavior and do not broaden scope"
        )

        self.assertEqual(message["intent"], "pilot_task_intent")
        self.assertEqual(message["context"]["task_id"], 14)
        self.assertEqual(
            message["context"]["pilot_input"],
            "preserve planner behavior and do not broaden scope",
        )

    def test_planner_prompt_includes_pilot_brief(self):
        task = {
            "id": 7,
            "note": "Update route to handle stale pilot plans safely.",
            "metadata": {
                "pilot_context": build_pilot_context(
                    "Update route to handle stale pilot plans safely. Do not add a new subsystem."
                )
            },
        }

        prompt = PlannerAgent()._build_prompt(task, hint="Keep the flow local.")

        self.assertIn("Pilot context:", prompt)
        self.assertIn("Do not add a new subsystem", prompt)

    def test_coder_prompt_includes_pilot_brief(self):
        task = {
            "id": 9,
            "note": "Update route to handle stale pilot plans safely.",
            "target_file": "router.py",
            "target_symbol": "route",
            "metadata": {
                "anchor": {
                    "target_file": "router.py",
                    "target_symbol": "route",
                    "lineno": 1,
                    "end_lineno": 20,
                },
                "pilot_context": build_pilot_context(
                    "Keep the patch inside route and preserve existing command handling."
                ),
            },
        }
        plan = {
            "goal": "Keep pilot intent aligned with execution.",
            "tasks": [{"title": "Update route", "description": "Tighten route behavior."}],
            "dependencies": ["router.py"],
            "risks": ["Routing regressions."],
            "next_action": "Update route in router.py.",
            "status": "planned",
        }

        prompt = build_prompt(task, plan, "router.py", "def route(self, user_input, message):\n    pass\n")

        self.assertIn("Pilot context:", prompt)
        self.assertIn("preserve existing command handling", prompt)
        self.assertIn(format_pilot_brief(task), prompt)


if __name__ == "__main__":
    unittest.main()
