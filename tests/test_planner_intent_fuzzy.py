import unittest

from planner import PlannerAgent, ALLOWED_CHANGE_INTENTS, ALLOWED_EXPECTED_OPERATIONS


class PlannerIntentFuzzyTests(unittest.TestCase):
    def setUp(self):
        self.agent = PlannerAgent()

    def test_fuzzy_change_intent_novel_returns_canonical(self):
        result = self.agent._fuzzy_match_change_intent("add_performance_optimization")
        self.assertIn(result, ALLOWED_CHANGE_INTENTS)

    def test_fuzzy_change_intent_add_maps_to_add_new_capability(self):
        result = self.agent._fuzzy_match_change_intent("add_caching_capability")
        self.assertIn(result, {"add_new_capability", "add_method_or_function"})

    def test_fuzzy_change_intent_modify_maps_to_modify_existing_logic(self):
        result = self.agent._fuzzy_match_change_intent("modify_behavior")
        self.assertEqual(result, "modify_existing_logic")

    def test_fuzzy_change_intent_gibberish_returns_default(self):
        result = self.agent._fuzzy_match_change_intent("xyzzy_blorp_12")
        self.assertIn(result, ALLOWED_CHANGE_INTENTS)

    def test_fuzzy_expected_operation_novel_returns_canonical(self):
        result = self.agent._fuzzy_match_expected_operation("optimize_loop")
        self.assertIn(result, ALLOWED_EXPECTED_OPERATIONS)

    def test_fuzzy_expected_operation_replace_maps_to_canonical(self):
        result = self.agent._fuzzy_match_expected_operation("replace_existing_logic")
        self.assertIn(result, ALLOWED_EXPECTED_OPERATIONS)

    def test_validate_accepts_novel_change_intent_via_fuzzy(self):
        """_validate_plan_child_tasks should not raise on unknown intent — fuzzy-matches instead."""
        child = {
            "task_id": "task-1-1",
            "title": "Add caching",
            "description": "Cache results",
            "status": "planned",
            "depends_on": [],
            "target_file": "main.py",
            "target_symbol": "run",
            "change_intent": "add_caching_layer",
            "expected_operation": "modify_logic",
            "completion_cues": ["result_cache.get(key)"],
            "task_type": None,
            "task_kind": "modify",
            "work_mode": "modify",
            "creates_symbols": [],
            "wires_into_symbols": [],
        }
        plan = {
            "goal": "test",
            "next_action": "test",
            "task_kind": "modify",
            "work_mode": "modify",
            "task_type": None,
            "tasks": [child],
        }

        state = _SimpleState()
        self.agent.state_manager = state
        try:
            self.agent._validate_plan_child_tasks(plan)
        except ValueError as e:
            self.fail(f"_validate_plan_child_tasks raised ValueError on novel intent: {e}")
        self.assertIn(child["change_intent"], ALLOWED_CHANGE_INTENTS)

    def test_validate_accepts_novel_expected_operation_via_fuzzy(self):
        """_validate_plan_child_tasks should not raise on unknown expected_operation."""
        child = {
            "task_id": "task-1-1",
            "title": "Refactor loop",
            "description": "Refactor the loop body",
            "status": "planned",
            "depends_on": [],
            "target_file": "main.py",
            "target_symbol": "run",
            "change_intent": "refactor_local_block",
            "expected_operation": "optimize_loop_performance",
            "completion_cues": ["for item in items:"],
            "task_type": None,
            "task_kind": "modify",
            "work_mode": "modify",
            "creates_symbols": [],
            "wires_into_symbols": [],
        }
        plan = {
            "goal": "test",
            "next_action": "test",
            "task_kind": "modify",
            "work_mode": "modify",
            "task_type": None,
            "tasks": [child],
        }

        state = _SimpleState()
        self.agent.state_manager = state
        try:
            self.agent._validate_plan_child_tasks(plan)
        except ValueError as e:
            self.fail(f"_validate_plan_child_tasks raised ValueError on novel operation: {e}")
        self.assertIn(child["expected_operation"], ALLOWED_EXPECTED_OPERATIONS)


class _SimpleState:
    def get_known_files(self):
        return ["main.py", "planner.py"]

    def get_repo_map(self):
        return {"symbol_to_file": {}, "file_symbols": {"main.py": ["run"]}}

    def resolve_symbol_to_file(self, symbol):
        return None

    def get_symbol_span(self, target_file, target_symbol):
        return {"start": 1, "end": 10}

    def get_symbols_for_file(self, file_name):
        return ["run"]
