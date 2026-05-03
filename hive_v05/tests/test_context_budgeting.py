import unittest

from coder_prompting import (
    DEFAULT_CONTEXT_BUDGET_CHARS,
    prepare_context_for_prompt,
)


class ContextBudgetingTests(unittest.TestCase):
    def test_exact_symbol_context_stays_untrimmed_under_budget(self):
        context = {
            "mode": "exact_symbol_block",
            "context_text": "def target():\n    return 1\n",
            "selected_block": {
                "name": "target",
                "lineno": 1,
                "end_lineno": 2,
                "text": "def target():\n    return 1\n",
            },
        }

        prompt_text, metadata = prepare_context_for_prompt(
            target_file="sample.py",
            context=context,
            full_file_text=context["context_text"],
            prompt_kind="symbol_locked",
        )

        self.assertEqual(prompt_text, context["context_text"])
        self.assertFalse(metadata["trimmed"])
        self.assertFalse(metadata["summary_used"])
        self.assertEqual(metadata["selected_mode"], "exact_symbol_block")

    def test_large_context_drops_related_text_before_selected_block(self):
        selected_block_text = "def target():\n    return important_value\n"
        base_context = selected_block_text + ("# padding\n" * 1200)
        related_context = "# Related files from repo graph:\n" + ("helper = 1\n" * 1200)
        context = {
            "mode": "block_window",
            "context_text": base_context,
            "selected_block": {
                "name": "target",
                "lineno": 10,
                "end_lineno": 12,
                "text": selected_block_text,
            },
        }

        prompt_text, metadata = prepare_context_for_prompt(
            target_file="sample.py",
            context=context,
            full_file_text=base_context,
            related_context_text=related_context,
            prompt_kind="default",
        )

        self.assertTrue(metadata["trimmed"])
        self.assertEqual(metadata["budget_decision"], "trimmed_context_components")
        self.assertIn("def target()", prompt_text)
        self.assertNotIn("helper = 1", prompt_text)
        self.assertLessEqual(metadata["trimmed_context_length"], DEFAULT_CONTEXT_BUDGET_CHARS)

    def test_budget_metadata_reports_summary_use_when_needed(self):
        huge_summary_context = "top\n" * 4000
        huge_selected_block = "def target():\n" + ("    line = 1\n" * 2000)
        context = {
            "mode": "block_window",
            "context_text": huge_summary_context,
            "selected_block": {
                "name": "target",
                "lineno": 1,
                "end_lineno": 2001,
                "text": huge_selected_block,
            },
        }

        prompt_text, metadata = prepare_context_for_prompt(
            target_file="planner.py",
            context=context,
            full_file_text=huge_summary_context,
            related_context_text="helper\n" * 3000,
            prompt_kind="default",
        )

        self.assertTrue(metadata["trimmed"])
        self.assertTrue(metadata["summary_used"])
        self.assertEqual(metadata["budget_decision"], "summary_used")
        self.assertIn("FILE SUMMARY: planner.py", prompt_text)
        self.assertLessEqual(metadata["trimmed_context_length"], DEFAULT_CONTEXT_BUDGET_CHARS)


if __name__ == "__main__":
    unittest.main()
