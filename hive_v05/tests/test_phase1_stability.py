import shutil
import unittest
import uuid
from pathlib import Path

from HiveLessonMemory import LessonMemory
from HiveStateManager import HiveStateManager
from coder_context import extract_code_blocks, select_edit_context
from coder_validation import validate_patch_data, validate_patch_matches_task_intent
from coder_block_ops import validate_block_rewrite_minimality
from failure_intelligence import interpret_failure
from planner import PlannerAgent


class Phase1StabilityTests(unittest.TestCase):
    def _make_temp_root(self):
        root = Path(__file__).resolve().parent / f"_tmp_phase1_{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        return root

    def test_exact_symbol_context_selection_stays_symbol_locked(self):
        file_path = Path(__file__).resolve().parents[1] / "coder_context.py"
        file_text = file_path.read_text(encoding="utf-8")
        blocks = extract_code_blocks(file_text, target_file="coder_context.py")
        target_block = next(block for block in blocks if block.get("name") == "select_edit_context")

        task = {
            "id": "phase1-1",
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
        self.assertEqual(context["target_name"], "select_edit_context")
        self.assertEqual((context.get("selected_block") or {}).get("symbol_id"), target_block.get("symbol_id"))

    def test_comment_task_normalizes_to_insert_comment(self):
        agent = PlannerAgent()
        child = {
            "title": "Add exact-symbol explanation comment",
            "description": "Insert a comment above the exact_symbol_block branch to explain strict span-based targeting.",
            "target_symbol": "select_edit_context",
            "change_intent": "modify_existing_logic",
        }

        self.assertEqual(agent._normalize_expected_operation(child), "insert_comment")

    def test_comment_only_patch_is_valid_for_comment_task(self):
        task = {
            "id": "phase1-2",
            "note": "Insert a comment above the exact_symbol_block branch in select_edit_context.",
            "target_file": "coder_context.py",
            "target_symbol": "select_edit_context",
            "expected_operation": "insert_comment",
            "metadata": {"expected_operation": "insert_comment"},
        }
        patch_data = {
            "target_file": "coder_context.py",
            "change_type": "diff_patch",
            "risk_level": "low",
            "status": "proposed",
            "patch": (
                "--- coder_context.py\n"
                "+++ coder_context.py\n"
                "@@ -971,6 +971,7 @@ def select_edit_context(task, plan, target_file, file_text, radius=0, padding_lines=40):\n"
                "     if anchored_symbol and selected_block.get(\"name\") != anchored_symbol:\n"
                "+        # Enforces strict span-based targeting to keep context selection exact.\n"
                "         raise ValueError(\n"
            ),
        }

        validate_patch_data(patch_data, task=task)

    def test_block_rewrite_rejects_broad_full_body_replacement(self):
        original = (
            "    def target(self):\n"
            "        line_a = 1\n"
            "        line_b = 2\n"
            "        line_c = 3\n"
            "        line_d = 4\n"
            "        return line_a + line_b + line_c + line_d\n"
        )
        rewritten = (
            "    def target(self):\n"
            "        start = compute_start()\n"
            "        middle = compute_middle(start)\n"
            "        end = compute_end(middle)\n"
            "        audit(start, middle, end)\n"
            "        return finalize(end)\n"
        )

        with self.assertRaisesRegex(ValueError, "entire method body"):
            validate_block_rewrite_minimality(
                original,
                rewritten,
                expected_operation="modify_logic",
            )

    def test_mixed_scope_shape_wins_before_scope_alignment(self):
        task = {
            "id": "phase1-2b",
            "note": "Update _build_response so it copies the provided context mapping before returning it.",
            "target_file": "interface.py",
            "target_symbol": "_build_response",
            "change_intent": "modify_existing_logic",
            "completion_cues": ['"context": dict(context or {}),'],
        }
        patch_data = {
            "target_file": "interface.py",
            "change_type": "diff_patch",
            "risk_level": "low",
            "status": "proposed",
            "patch": (
                "--- interface.py\n"
                "+++ interface.py\n"
                "@@ -44,7 +44,9 @@ class Interface:\n"
                "     def _build_response(self, intent, text, context=None):\n"
                "+status_map = {}\n"
                "+        context = dict(context or {})\n"
                "         return {\n"
                "             \"intent\": intent,\n"
                "             \"context\": context or {},\n"
            ),
        }

        with self.assertRaisesRegex(ValueError, "mixed_scope_patch"):
            validate_patch_matches_task_intent(patch_data, task)

    def test_retry_lessons_prioritize_exact_failure_symbol_and_context(self):
        temp_root = self._make_temp_root()
        path = temp_root / "lessons.jsonl"
        memory = LessonMemory(path=str(path), max_entries=20)

        memory.add_lesson(
            file="coder_context.py",
            change_type="diff_patch",
            failure_reason="symbol_anchor_drift",
            failure_code="symbol_anchor_drift",
            retry_instruction="Exact lesson",
            target_symbol="select_edit_context",
            context_mode="exact_symbol_block",
            times_used=3,
            success_after_use=3,
            failure_after_use=0,
            promotion_state="trusted",
        )
        memory.add_lesson(
            file="coder_context.py",
            change_type="diff_patch",
            failure_reason="symbol_anchor_drift",
            failure_code="symbol_anchor_drift",
            retry_instruction="Wrong symbol lesson",
            target_symbol="other_symbol",
            context_mode="exact_symbol_block",
        )
        memory.add_lesson(
            file="coder_context.py",
            change_type="diff_patch",
            failure_reason="unknown_failure",
            failure_code="unknown_failure",
            retry_instruction="Broad fallback lesson",
        )

        lessons = memory.get_retry_lessons(
            file="coder_context.py",
            change_type="diff_patch",
            failure_code="symbol_anchor_drift",
            target_symbol="select_edit_context",
            context_mode="exact_symbol_block",
            limit=3,
        )

        self.assertEqual(lessons[0]["retry_instruction"], "Exact lesson")

    def test_failure_intelligence_classifies_comment_guard_failure(self):
        result = interpret_failure(
            stage="exception",
            error_text="Patch change too small or non-functional.",
            task={
                "id": "phase1-3",
                "target_file": "coder_context.py",
                "expected_operation": "insert_comment",
                "metadata": {"expected_operation": "insert_comment"},
            },
        )

        self.assertEqual(result.classification.failure_code, "comment_task_rejected_as_nonfunctional")

    def test_state_manager_refreshes_stale_cached_text(self):
        temp_root = self._make_temp_root()
        target = temp_root / "sample.py"
        target.write_text("print('disk')\n", encoding="utf-8")

        state = HiveStateManager(
            snapshot_path=temp_root / "snapshot.json",
            repo_root=temp_root,
        )
        state.set_file_text("sample.py", "print('cached')\n", source="applied_patch")

        content = state.get_effective_file_text("sample.py")

        self.assertEqual(content, "print('disk')\n")
        self.assertEqual(state.get_file_text("sample.py"), "print('disk')\n")


if __name__ == "__main__":
    unittest.main()
