import shutil
import unittest
import uuid
from pathlib import Path

from HiveStateManager import HiveStateManager
from coder import CoderAgent
from coder_context import extract_code_blocks, select_edit_context
from coder_prompting import prepare_context_for_prompt
from failure_intelligence import interpret_failure
from repo_map import RepoMap


class Phase2ContextDisciplineTests(unittest.TestCase):
    def _make_temp_root(self):
        root = Path(__file__).resolve().parent / f"_tmp_phase2_{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

    def test_exact_symbol_context_includes_priority_and_high_confidence(self):
        file_path = Path(__file__).resolve().parents[1] / "coder_context.py"
        file_text = file_path.read_text(encoding="utf-8")
        blocks = extract_code_blocks(file_text, target_file="coder_context.py")
        target_block = next(block for block in blocks if block.get("name") == "select_edit_context")

        task = {
            "id": "phase2-1",
            "note": "Update select_edit_context narrowly.",
            "target_file": "coder_context.py",
            "target_symbol": "select_edit_context",
            "metadata": {
                "target_file": "coder_context.py",
                "target_symbol": "select_edit_context",
                "anchor": {
                    "target_file": "coder_context.py",
                    "target_symbol": "select_edit_context",
                    "target_symbol_id": target_block.get("symbol_id"),
                    "lineno": target_block.get("lineno"),
                    "end_lineno": target_block.get("end_lineno"),
                    "col_offset": target_block.get("col_offset"),
                    "end_col_offset": target_block.get("end_col_offset"),
                },
            },
        }
        plan = {
            "goal": "Keep exact symbol targeting stable.",
            "tasks": [],
            "dependencies": ["coder_context.py"],
            "risks": [],
            "next_action": "Edit only select_edit_context.",
            "status": "planned",
        }

        context = select_edit_context(task, plan, "coder_context.py", file_text)

        self.assertEqual(context["mode"], "exact_symbol_block")
        self.assertEqual(context["anchoring_confidence"], "high")
        self.assertFalse(context["under_anchored"])
        self.assertEqual(context["context_priority"][0], "exact_symbol_block")

    def test_repo_map_produces_deterministic_main_summary(self):
        repo_root = Path(__file__).resolve().parents[1]
        first = RepoMap(root=repo_root).build()
        second = RepoMap(root=repo_root).build()

        first_summary = first["file_summaries"]["main.py"]
        second_summary = second["file_summaries"]["main.py"]

        self.assertEqual(first_summary["route_branch_inventory"], second_summary["route_branch_inventory"])
        self.assertLessEqual(len(first_summary["route_branch_inventory"]), 12)
        self.assertIn("help", first_summary["route_branch_inventory"])
        self.assertLessEqual(len(first_summary["high_value_symbols"]), 8)

    def test_budget_drops_helper_and_import_blocks_before_summary(self):
        selected_block_text = "def target():\n    return important_value\n"
        context = {
            "mode": "block_window",
            "context_text": selected_block_text + ("# filler\n" * 1500),
            "selected_block": {
                "name": "target",
                "type": "function",
                "lineno": 10,
                "end_lineno": 12,
                "text": selected_block_text,
            },
            "neighbor_blocks": [
                {
                    "name": "target",
                    "type": "function",
                    "lineno": 10,
                    "end_lineno": 12,
                    "text": selected_block_text,
                }
            ],
            "helper_blocks": [{"name": "helper", "text": "def helper():\n    pass\n"}],
            "import_blocks": [{"name": "imports", "text": "import os\nimport sys\n"}],
            "context_priority": ["block_window", "line_window", "file_head_fallback"],
            "anchoring_confidence": "high",
        }

        prompt_text, metadata = prepare_context_for_prompt(
            target_file="sample.py",
            context=context,
            full_file_text=context["context_text"],
            prompt_kind="default",
            task={"id": "phase2-2", "note": "Update target narrowly.", "target_symbol": "target"},
            file_summary={"char_count": 20000, "symbol_count": 2},
        )

        self.assertEqual(metadata["budget_decision"], "trimmed_context_components")
        self.assertTrue(metadata["dropped_helper_blocks"])
        self.assertTrue(metadata["dropped_import_blocks"])
        self.assertFalse(metadata["summary_used"])
        self.assertIn("def target()", prompt_text)

    def test_large_file_summary_uses_structured_inventory(self):
        huge_selected_block = "def route():\n" + ("    branch = handler\n" * 1500)
        context = {
            "mode": "block_window",
            "context_text": huge_selected_block,
            "selected_block": {
                "name": "route",
                "type": "function",
                "lineno": 100,
                "end_lineno": 1600,
                "text": huge_selected_block,
            },
            "neighbor_blocks": [],
            "helper_blocks": [],
            "import_blocks": [],
            "context_priority": ["block_window", "line_window", "file_head_fallback"],
            "anchoring_confidence": "high",
        }

        prompt_text, metadata = prepare_context_for_prompt(
            target_file="main.py",
            context=context,
            full_file_text=huge_selected_block,
            prompt_kind="revision",
            task={"id": "phase2-3", "note": "Update route behavior.", "target_symbol": "route"},
            file_summary={
                "char_count": 50000,
                "symbol_count": 60,
                "symbol_inventory": [
                    {"type": "function", "symbol": "route", "lineno": 100, "end_lineno": 1600},
                    {"type": "function", "symbol": "apply_patch", "lineno": 1303, "end_lineno": 1420},
                ],
                "high_value_symbols": [
                    {"type": "function", "symbol": "route", "lineno": 100, "end_lineno": 1600},
                ],
                "route_branch_inventory": ["help", "show_patch", "apply_patch"],
            },
        )

        self.assertTrue(metadata["summary_used"])
        self.assertEqual(metadata["budget_decision"], "summary_used")
        self.assertIn("FILE SUMMARY: main.py", prompt_text)
        self.assertIn("Routes: help, show_patch, apply_patch", prompt_text)

    def test_under_anchored_large_file_context_sets_explicit_budget_signal(self):
        prompt_text, metadata = prepare_context_for_prompt(
            target_file="main.py",
            context={
                "mode": "file_head_fallback",
                "context_text": "line\n" * 300,
                "context_priority": ["file_head_fallback"],
                "anchoring_confidence": "low",
            },
            full_file_text="line\n" * 1000,
            prompt_kind="default",
            task={"id": "phase2-4", "note": "Update execution flow in main.py."},
            file_summary={"char_count": 50000, "symbol_count": 60, "route_branch_inventory": ["help"]},
        )

        self.assertTrue(metadata["under_anchored_after_trim"])
        self.assertEqual(metadata["budget_decision"], "under_anchored_after_trim")
        self.assertTrue(prompt_text)

    def test_coder_blocks_main_py_broad_task_early_with_explicit_reason(self):
        repo_root = Path(__file__).resolve().parents[1]
        temp_root = self._make_temp_root()
        state = HiveStateManager(snapshot_path=temp_root / "snapshot.json", repo_root=repo_root)
        state.rebuild_repo_map()
        coder = CoderAgent(state_manager=state)
        file_text = (repo_root / "main.py").read_text(encoding="utf-8")
        task = {
            "id": "phase2-5",
            "note": "Update execution flow in main.py without a narrower symbol anchor.",
            "target_file": "main.py",
            "metadata": {"target_file": "main.py"},
        }
        plan = {
            "goal": "Update execution flow in main.py.",
            "tasks": [],
            "dependencies": ["main.py"],
            "risks": [],
            "next_action": "Update main.py execution flow.",
            "status": "planned",
        }

        context = select_edit_context(task, plan, "main.py", file_text)

        with self.assertRaisesRegex(ValueError, "under-anchored after trim"):
            coder._apply_prompt_budget(
                task,
                plan,
                "main.py",
                context,
                file_text,
                prompt_kind="default",
            )

    def test_failure_intelligence_classifies_under_anchored_after_trim(self):
        result = interpret_failure(
            stage="context_budget",
            error_text="Context under-anchored after trim for main.py.",
            task={"id": "phase2-6", "target_file": "main.py"},
            metadata={"context_budget": {"under_anchored_after_trim": True, "budget_decision": "under_anchored_after_trim"}},
        )

        self.assertEqual(result.classification.failure_code, "under_anchored_after_trim")
        self.assertFalse(result.revision.retry_recommended)


if __name__ == "__main__":
    unittest.main()
