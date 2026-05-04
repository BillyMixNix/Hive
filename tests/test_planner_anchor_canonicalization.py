import unittest
from pathlib import Path

from planner import PlannerAgent
from repo_map import RepoMap
from main import build_anchor_from_text, enrich_task_anchor_for_planning


class FakeStateManager:
    def __init__(self):
        self.repo_map = {
            "symbol_to_file": {
                "route": "main.py",
                "switch": "bazaar.py",
                "_build_ui": "hive_gui.py",
            }
        }
        self.spans = {
            ("main.py", "route"): {
                "symbol_id": "main.py::route",
                "lineno": 100,
                "end_lineno": 220,
                "col_offset": 0,
                "end_col_offset": 4,
            },
            ("bazaar.py", "switch"): {
                "symbol_id": "bazaar.py::Bazaar.switch",
                "lineno": 58,
                "end_lineno": 65,
                "col_offset": 4,
                "end_col_offset": 63,
            },
            ("hive_gui.py", "_build_ui"): {
                "symbol_id": "hive_gui.py::HiveGui._build_ui",
                "lineno": 40,
                "end_lineno": 150,
                "col_offset": 4,
                "end_col_offset": 20,
            }
        }

    def get_known_files(self):
        return ["main.py", "planner.py", "hive_gui.py", "bazaar.py"]

    def get_repo_map(self):
        return self.repo_map

    def resolve_symbol_to_file(self, symbol):
        return self.repo_map["symbol_to_file"].get(symbol)

    def get_symbol_span(self, target_file, target_symbol):
        return self.spans.get((target_file, target_symbol))

    def get_symbols_for_file(self, file_name):
        return {
            "main.py": ["route"],
            "hive_gui.py": ["HiveGui", "_build_ui"],
            "bazaar.py": ["Bazaar", "switch"],
        }.get(file_name, [])


class PlannerAnchorCanonicalizationTests(unittest.TestCase):
    def setUp(self):
        self.state_manager = FakeStateManager()
        self.agent = PlannerAgent(state_manager=self.state_manager)

    def test_validate_plan_canonicalizes_child_and_plan_anchors(self):
        plan = {
            "goal": "Update route in main.py to preserve exact child anchor spans.",
            "task_type": "bugfix",
            "tasks": [
                {
                    "title": "Keep child route anchor canonical",
                    "description": "Update route to preserve child task anchor span metadata.",
                    "change_intent": "modify_existing_logic",
                    "expected_operation": "modify_logic",
                    "completion_cues": [
                        'child["metadata"]["anchor"]["target_symbol_id"] = "main.py::route"',
                    ],
                }
            ],
            "dependencies": ["main.py"],
            "risks": ["Missing span metadata can break strict symbol context selection."],
            "next_action": "Patch route so child tasks retain exact symbol span metadata.",
            "status": "planned",
        }

        task = {
            "id": "500",
            "note": "Fix route in main.py so child task anchors stay canonical.",
            "metadata": {
                "anchor": {
                    "target_file": "main.py",
                    "target_symbol": "route",
                    "scope": "single_file",
                    "anchor_source": "user_input",
                }
            },
        }

        validated = self.agent._validate_plan(
            plan,
            parent_task_id="500",
            default_target_file="main.py",
            task=task,
        )

        child = validated["tasks"][0]
        child_anchor = child["metadata"]["anchor"]
        plan_anchor = validated["metadata"]["anchor"]

        for anchor in (child_anchor, plan_anchor):
            self.assertEqual(anchor["target_file"], "main.py")
            self.assertEqual(anchor["target_symbol"], "route")
            self.assertEqual(anchor["target_symbol_id"], "main.py::route")
            self.assertEqual(anchor["lineno"], 100)
            self.assertEqual(anchor["end_lineno"], 220)
            self.assertEqual(anchor["col_offset"], 0)
            self.assertEqual(anchor["end_col_offset"], 4)

        self.assertEqual(child["target_file"], "main.py")
        self.assertEqual(child["target_symbol"], "route")
        self.assertEqual(child["target_symbol_id"], "main.py::route")
        self.assertEqual(child["lineno"], 100)
        self.assertEqual(child["end_lineno"], 220)
        self.assertEqual(child["col_offset"], 0)
        self.assertEqual(child["end_col_offset"], 4)

    def test_gui_language_prefers_gui_file_over_unrelated_switch_symbol(self):
        task = {
            "id": "589",
            "note": "add a switch in the gui for a dark mode asthetic",
            "metadata": {},
        }

        anchor = self.agent._build_anchor_from_task(task)

        self.assertEqual(anchor["target_file"], "hive_gui.py")
        self.assertNotEqual(anchor.get("target_file"), "bazaar.py")
        self.assertNotEqual(anchor.get("target_symbol"), "switch")

    def test_task_backlog_create_request_targets_task_management_file_level(self):
        task = {
            "id": "597",
            "note": "create a way of clearing older tasks that no longer need to be completed",
            "metadata": {},
        }

        anchor = self.agent._build_anchor_from_task(task)
        text_anchor = build_anchor_from_text(task["note"], state_manager=self.state_manager, task=task)

        self.assertEqual(anchor["target_file"], "main.py")
        self.assertIsNone(anchor.get("target_symbol"))
        self.assertEqual(text_anchor["target_file"], "main.py")
        self.assertIsNone(text_anchor.get("target_symbol"))

    def test_stale_vendor_anchor_is_rederived_from_gui_language(self):
        task = {
            "id": "589",
            "note": "add a switch in the gui for a dark mode asthetic",
            "metadata": {
                "target_file": "missing_vendor.py",
                "target_symbol": "switch",
                "target_symbol_id": "missing_vendor.py::Vendor.switch",
                "lineno": 58,
                "anchor": {
                    "target_file": "missing_vendor.py",
                    "target_symbol": "switch",
                    "anchor_source": "user_input",
                },
            },
        }

        anchor = self.agent._build_anchor_from_task(task)

        self.assertEqual(anchor["target_file"], "hive_gui.py")
        self.assertNotEqual(anchor.get("target_symbol"), "switch")

    def test_task_enrichment_discards_stale_vendor_anchor(self):
        task = {
            "id": 589,
            "note": "add a switch in the gui for a dark mode asthetic",
            "metadata": {
                "target_file": "missing_vendor.py",
                "target_symbol": "switch",
                "anchor": {
                    "target_file": "missing_vendor.py",
                    "target_symbol": "switch",
                    "anchor_source": "user_input",
                },
            },
        }

        enriched = enrich_task_anchor_for_planning(task, state_manager=self.state_manager)

        self.assertEqual(enriched["metadata"]["target_file"], "hive_gui.py")
        self.assertNotEqual(enriched["metadata"].get("target_symbol"), "switch")
        self.assertNotIn("target_symbol_id", enriched["metadata"])
        self.assertNotIn("lineno", enriched["metadata"])

    def test_gui_file_level_request_does_not_infer_create_and_plan_symbol(self):
        task = {
            "id": 589,
            "note": "add a switch in the gui for a dark mode asthetic | next: Inspect the most relevant implementation area",
            "metadata": {
                "target_file": "hive_gui.py",
                "target_symbol": None,
                "anchor": {
                    "target_file": "hive_gui.py",
                    "target_symbol": None,
                    "anchor_source": "pilot_guidance",
                },
            },
        }

        anchor = self.agent._build_anchor_from_task(task)
        enriched = enrich_task_anchor_for_planning(task, state_manager=self.state_manager)

        self.assertEqual(anchor["target_file"], "hive_gui.py")
        self.assertIsNone(anchor.get("target_symbol"))
        self.assertEqual(enriched["metadata"]["target_file"], "hive_gui.py")
        self.assertIsNone(enriched["metadata"].get("target_symbol"))

    def test_gui_file_level_request_clears_previous_inferred_symbol(self):
        task = {
            "id": 589,
            "note": "add a switch in the gui for a dark mode asthetic | next: Inspect the most relevant implementation area",
            "metadata": {
                "target_file": "hive_gui.py",
                "target_symbol": "_create_and_plan_task",
                "target_symbol_id": "hive_gui.py::HiveGui._create_and_plan_task",
                "lineno": 286,
                "anchor": {
                    "target_file": "hive_gui.py",
                    "target_symbol": "_create_and_plan_task",
                    "target_symbol_id": "hive_gui.py::HiveGui._create_and_plan_task",
                    "anchor_source": "file_level_inference",
                },
            },
        }

        anchor = self.agent._build_anchor_from_task(task)
        enriched = enrich_task_anchor_for_planning(task, state_manager=self.state_manager)

        self.assertEqual(anchor["target_file"], "hive_gui.py")
        self.assertIsNone(anchor.get("target_symbol"))
        self.assertEqual(enriched["metadata"]["target_file"], "hive_gui.py")
        self.assertIsNone(enriched["metadata"].get("target_symbol"))
        self.assertNotIn("target_symbol_id", enriched["metadata"])
        self.assertNotIn("lineno", enriched["metadata"])


class RepoMapScopeTests(unittest.TestCase):
    def test_repo_map_ignores_virtualenv_and_nested_archives(self):
        repo_map = RepoMap(root=Path.cwd()).build()

        self.assertIn("hive_gui.py", repo_map["known_files"])
        self.assertNotIn("bazaar.py", repo_map["known_files"])
        self.assertNotIn("switch", repo_map["symbol_to_file"])


if __name__ == "__main__":
    unittest.main()
