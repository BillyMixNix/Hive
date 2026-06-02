import unittest

from planner import PlannerAgent


class FakeStateManager:
    def __init__(self):
        self.repo_map = {
            "symbol_to_file": {
                "route": "main.py",
            }
        }
        self.spans = {
            ("main.py", "route"): {
                "symbol_id": "main.py::route",
                "lineno": 100,
                "end_lineno": 220,
                "col_offset": 0,
                "end_col_offset": 4,
            }
        }

    def get_known_files(self):
        return ["main.py", "planner.py"]

    def get_repo_map(self):
        return self.repo_map

    def resolve_symbol_to_file(self, symbol):
        return self.repo_map["symbol_to_file"].get(symbol)

    def get_symbol_span(self, target_file, target_symbol):
        return self.spans.get((target_file, target_symbol))

    def get_symbols_for_file(self, target_file):
        return [sym for sym, f in self.repo_map["symbol_to_file"].items() if f == target_file]


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


if __name__ == "__main__":
    unittest.main()
