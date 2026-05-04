import unittest

from builder import BuilderAgent, build_pilot_context, format_pilot_brief, merge_pilot_context
from coder_prompting import build_prompt
from interface import Interface
from main import (
    _handle_pilot_task_intent,
    build_anchor_from_text,
    extract_required_completion_cues,
    merge_completion_cues,
)
from anchor_utils import merge_anchor_with_span
from planner import PlannerAgent


class FakeMemory:
    def __init__(self, task):
        self.task = task
        self.stored = []

    def get_task_by_id(self, task_id):
        if self.task.get("id") == task_id:
            return self.task
        return None

    def update_task_metadata(self, task_id, metadata):
        if self.task.get("id") == task_id:
            self.task["metadata"] = metadata

    def store(self, *args, **kwargs):
        self.stored.append({"args": args, "kwargs": kwargs})


class FakeState:
    def __init__(self):
        self.snapshot = None

    def get_known_files(self):
        return ["hive_gui.py", "main.py"]

    def get_repo_map(self):
        return {"symbol_to_file": {}, "file_symbols": {"hive_gui.py": []}}

    def resolve_symbol_to_file(self, symbol):
        return None

    def get_symbols_for_file(self, file_name):
        return []

    def get_symbol_span(self, target_file, target_symbol):
        return None


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

    def test_coder_prompt_includes_hive_builder_packet(self):
        task = {
            "id": 10,
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

        self.assertIn("# Hive Builder Packet", prompt)
        self.assertIn("## Output Requirement", prompt)
        self.assertIn("Return a unified diff only.", prompt)
        self.assertIn("File: router.py", prompt)

    def test_pilot_guidance_replaces_stale_file_anchor(self):
        task = {
            "id": 589,
            "note": "add a switch in the gui for a dark mode asthetic",
            "status": "planned",
            "metadata": {
                "target_file": "bazaar.py",
                "target_symbol": "switch",
                "target_symbol_id": "bazaar.py::Bazaar.switch",
                "lineno": 58,
                "end_lineno": 65,
                "anchor": {
                    "target_file": "bazaar.py",
                    "target_symbol": "switch",
                    "target_symbol_id": "bazaar.py::Bazaar.switch",
                    "anchor_source": "user_input",
                },
            },
        }
        memory = FakeMemory(task)
        state = FakeState()

        result = _handle_pilot_task_intent(
            589,
            "Target file is hive_gui.py. Do not use Bazaar.switch or any vendor/archive symbol.",
            memory,
            state,
            lambda: None,
            build_anchor_from_text,
            merge_pilot_context,
            extract_required_completion_cues,
            merge_completion_cues,
            merge_anchor_with_span,
            lambda *_args, **_kwargs: None,
            lambda *_args, **_kwargs: {"id": "plan-589"},
        )

        metadata = task["metadata"]
        self.assertIn("Re-run plan task 589", result)
        self.assertEqual(metadata["target_file"], "hive_gui.py")
        self.assertIsNone(metadata.get("target_symbol"))
        self.assertEqual(metadata["anchor"]["target_file"], "hive_gui.py")
        self.assertEqual(metadata["anchor"]["anchor_source"], "pilot_guidance")
        self.assertNotIn("target_symbol_id", metadata)
        self.assertNotIn("lineno", metadata)


if __name__ == "__main__":
    unittest.main()
