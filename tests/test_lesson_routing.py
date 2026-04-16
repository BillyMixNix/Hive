import unittest
import uuid
from pathlib import Path

from HiveLessonMemory import LessonMemory


class LessonRoutingTests(unittest.TestCase):
    def _make_path(self):
        path = Path(__file__).resolve().parent / f"_tmp_lessons_{uuid.uuid4().hex}.jsonl"
        self.addCleanup(lambda: path.exists() and path.unlink())
        return path

    def test_retry_lessons_prioritize_exact_failure_symbol_and_context(self):
        path = self._make_path()
        memory = LessonMemory(path=str(path), max_entries=50)

        memory.add_lesson(
            file="coder_context.py",
            change_type="diff_patch",
            failure_reason="symbol_anchor_drift",
            failure_code="symbol_anchor_drift",
            retry_instruction="Exact symbol/context lesson",
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
            retry_instruction="Same failure but wrong symbol",
            target_symbol="other_symbol",
            context_mode="exact_symbol_block",
            times_used=3,
            success_after_use=2,
            failure_after_use=0,
            promotion_state="candidate",
        )
        memory.add_lesson(
            file="coder_context.py",
            change_type="diff_patch",
            failure_reason="non_meaningful_patch",
            failure_code="non_meaningful_patch",
            retry_instruction="Recent file-level fallback",
            target_symbol="select_edit_context",
            context_mode="block_window",
        )

        lessons = memory.get_retry_lessons(
            file="coder_context.py",
            change_type="diff_patch",
            failure_code="symbol_anchor_drift",
            target_symbol="select_edit_context",
            context_mode="exact_symbol_block",
            limit=3,
        )

        self.assertGreaterEqual(len(lessons), 2)
        self.assertEqual(lessons[0]["retry_instruction"], "Exact symbol/context lesson")
        self.assertEqual(lessons[0]["target_symbol"], "select_edit_context")
        self.assertEqual(lessons[0]["context_mode"], "exact_symbol_block")


if __name__ == "__main__":
    unittest.main()
