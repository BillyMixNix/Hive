import unittest

from coder_validation import task_allows_comment_only_change, validate_patch_data


class CommentOnlyTaskTests(unittest.TestCase):
    def test_comment_task_allows_comment_only_patch(self):
        task = {
            "id": 516,
            "note": "Insert a comment above the exact_symbol_block branch in the select_edit_context function to explain that it enforces strict span-based targeting.",
            "target_file": "coder_context.py",
            "target_symbol": "select_edit_context",
        }
        patch_data = {
            "target_file": "coder_context.py",
            "change_type": "diff_patch",
            "risk_level": "low",
            "status": "proposed",
            "patch": (
                "--- coder_context.py\n"
                "+++ coder_context.py\n"
                "@@ -105,6 +105,7 @@ def select_edit_context(task, plan, target_file, file_text, radius=0, padding_lines=40):\n"
                "     if anchored_symbol or anchor_span:\n"
                "         all_blocks = extract_code_blocks(file_text, target_file=target_file)\n"
                "         selected_block = None\n"
                "+        # Enforces strict span-based targeting.\n"
                "         if anchor_span:\n"
            ),
        }

        self.assertTrue(task_allows_comment_only_change(task))
        validate_patch_data(patch_data, task=task)

    def test_non_comment_task_still_rejects_comment_only_patch(self):
        task = {
            "id": 1,
            "note": "Fix the routing bug in route.",
            "target_file": "router.py",
            "target_symbol": "route",
        }
        patch_data = {
            "target_file": "router.py",
            "change_type": "diff_patch",
            "risk_level": "low",
            "status": "proposed",
            "patch": (
                "--- router.py\n"
                "+++ router.py\n"
                "@@ -10,6 +10,7 @@ def route(self, user_input, message):\n"
                "     intent = message.get(\"intent\")\n"
                "+    # Route user input by detected intent.\n"
                "     text = user_input.lower().strip()\n"
            ),
        }

        self.assertFalse(task_allows_comment_only_change(task))
        with self.assertRaisesRegex(ValueError, "Patch change too small or non-functional."):
            validate_patch_data(patch_data, task=task)


if __name__ == "__main__":
    unittest.main()
