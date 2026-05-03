import unittest

from coder import CoderAgent
from coder_block_ops import validate_block_rewrite_minimality


class BlockRewriteMinimalityTests(unittest.TestCase):
    def test_rejects_full_body_replacement_for_narrow_edit(self):
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

    def test_prepare_rewritten_block_accepts_localized_edit(self):
        agent = CoderAgent()
        original = (
            "    def target(self):\n"
            "        line_a = 1\n"
            "        line_b = 2\n"
            "        line_c = line_a + line_b\n"
            "        return line_c\n"
        )
        rewritten = (
            "    def target(self):\n"
            "        line_a = 1\n"
            "        line_b = 2\n"
            "        line_c = (line_a + line_b) * 2\n"
            "        return line_c\n"
        )

        prepared = agent._prepare_rewritten_block(
            rewritten,
            original,
            "target",
            expected_operation="modify_logic",
        )

        self.assertIn("line_c = (line_a + line_b) * 2", prepared)


if __name__ == "__main__":
    unittest.main()
