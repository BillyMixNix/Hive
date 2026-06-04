"""Cross-case learning test for the shared-store sequence harness.

This is the test the original A/B benchmark could not express: it runs an
ordered [seed, reuse] sequence against ONE shared lesson store and checks that
a lesson recorded while handling the seed case is surfaced into the reuse
case's prompt and changes the coder's behaviour.

Two arms:
  - lessons ON : seed records a lesson -> reuse sees guidance -> good patch -> proposed
  - lessons OFF: empty store           -> reuse sees no guidance -> bad patch -> blocked

If the ON arm ever stops out-performing the OFF arm, either the refactor or the
lesson retrieval/injection path has regressed.
"""

import unittest

from benchmark_harness import ReliabilityBenchmarkHarness

TARGET_FILE = "coder_context.py"
TARGET_SYMBOL = "select_edit_context"
MARKER = "missing_diff_headers"  # failure_code; appears in the prompt only when a lesson is injected

_MALFORMED = (
    "TARGET_FILE: coder_context.py\n"
    "CHANGE_TYPE: diff_patch\nRISK_LEVEL: low\nSTATUS: proposed\n"
    "REASON: Attempt malformed diff.\nPATCH:\n"
    "@@ -1,0 +1,1 @@\n+        return revised_value\n"
)

_GOOD = (
    "TARGET_FILE: coder_context.py\n"
    "CHANGE_TYPE: diff_patch\nRISK_LEVEL: low\nSTATUS: proposed\n"
    "REASON: Add a narrow explanatory comment inside select_edit_context.\nPATCH:\n"
    "--- coder_context.py\n+++ coder_context.py\n"
    "@@ -971,6 +971,7 @@ def select_edit_context(task, plan, target_file, file_text, radius=0, padding_lines=40):\n"
    "         if anchor_span:\n"
    "+            # Enforce span-locked selection before building exact-symbol context.\n"
    "             selected_block = _find_block_by_anchor_span(all_blocks, anchor_span)\n"
    "             _validate_block_against_anchor_span(\n"
)

_PLAN = {
    "goal": "Insert a comment above the anchor_span lookup in select_edit_context.",
    "task_type": "bugfix",
    "tasks": [{
        "title": "Document anchor span lookup",
        "description": "Insert a comment above the anchor_span lookup in select_edit_context.",
        "target_file": TARGET_FILE,
        "target_symbol": TARGET_SYMBOL,
        "change_intent": "modify_existing_logic",
        "expected_operation": "insert_comment",
        "completion_cues": ["# Enforce span-locked selection before building exact-symbol context."],
    }],
    "dependencies": [], "risks": [], "next_action": "code", "status": "planned",
}


def _seed_case():
    return {
        "name": "seed_missing_diff_headers",
        "task_id": "seed-1",
        "band": "lesson_reuse",
        "task_note": "Insert a comment above the anchor_span lookup in select_edit_context.",
        "target_file": TARGET_FILE, "target_symbol": TARGET_SYMBOL,
        "change_intent": "modify_existing_logic", "expected_operation": "insert_comment",
        "completion_cues": ["# Enforce span-locked selection before building exact-symbol context."],
        "plan_response": _PLAN,
        "coder_side_effect": [_MALFORMED, _MALFORMED, _MALFORMED],  # always malformed -> records a lesson
        "expected_final_status": "blocked",
        "expected_failure_code": MARKER,
    }


def _reuse_case(observed):
    """Reuse case whose coder output reacts to whether lesson guidance is in the prompt."""
    def responder(prompt, *args, **kwargs):
        # Only the FIRST attempt is decisive: at that point the reuse case has not
        # failed yet in-case, so any MARKER in the prompt must have come from the
        # cross-case shared lesson store (i.e. the seed's lesson), not in-case retries.
        seen = MARKER in prompt
        observed.append(seen)
        return _GOOD if seen else _MALFORMED
    return {
        "name": "reuse_missing_diff_headers",
        "task_id": "reuse-1",
        "band": "lesson_reuse",
        "task_note": "Insert a comment above the anchor_span lookup in select_edit_context.",
        "target_file": TARGET_FILE, "target_symbol": TARGET_SYMBOL,
        "change_intent": "modify_existing_logic", "expected_operation": "insert_comment",
        "completion_cues": ["# Enforce span-locked selection before building exact-symbol context."],
        "plan_response": _PLAN,
        "coder_response": responder,  # callable -> guidance-sensitive
        "expected_final_status": "proposed",
        "expected_failure_code": None,
    }


class LessonReuseSequenceTests(unittest.TestCase):
    def test_lessons_on_surface_guidance_into_later_case(self):
        observed = []
        h = ReliabilityBenchmarkHarness()
        seed_res, reuse_res = h.run_sequence([_seed_case(), _reuse_case(observed)], lessons_enabled=True)
        self.assertEqual(seed_res["final_status"], "blocked")
        self.assertTrue(observed, "reuse coder was never invoked")
        self.assertTrue(observed[0], "reuse first attempt did not see the seeded lesson (cross-case injection failed)")
        self.assertEqual(reuse_res["final_status"], "proposed", "reuse should succeed first try once guidance is present")
        self.assertEqual(reuse_res["retry_count"], 0, "with the seeded lesson, reuse should need no retries")

    def test_lessons_reduce_retries_vs_off(self):
        """The headline signal: lessons ON solves the reuse case in fewer retries than OFF."""
        on_obs, off_obs = [], []
        on = ReliabilityBenchmarkHarness().run_sequence([_seed_case(), _reuse_case(on_obs)], lessons_enabled=True)[1]
        off = ReliabilityBenchmarkHarness().run_sequence([_seed_case(), _reuse_case(off_obs)], lessons_enabled=False)[1]
        self.assertLess(on["retry_count"], off["retry_count"],
                        "lessons ON did not reduce retries vs OFF — learning path regressed")

    def test_lessons_off_no_guidance(self):
        observed = []
        h = ReliabilityBenchmarkHarness()
        h.run_sequence([_seed_case(), _reuse_case(observed)], lessons_enabled=False)
        self.assertTrue(observed, "reuse coder was never invoked")
        self.assertFalse(observed[0], "reuse first attempt saw guidance even though lessons were OFF")


if __name__ == "__main__":
    unittest.main()
