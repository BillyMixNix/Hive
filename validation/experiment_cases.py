"""Deterministic seed/reuse cases for validating Hive's learning experiment path.

These cases do not claim that a live model has improved. They prove that the
same Hive worker path behaves differently when a scoped lesson from an earlier
failure is available to a later task. Live-model evidence uses the broader
reliability pack through ``validation.ab_run --live``.
"""

from __future__ import annotations


TARGET_FILE = "coder_context.py"
TARGET_SYMBOL = "select_edit_context"
LESSON_MARKER = "missing_diff_headers"

_MALFORMED = (
    "TARGET_FILE: coder_context.py\n"
    "CHANGE_TYPE: diff_patch\n"
    "RISK_LEVEL: low\n"
    "STATUS: proposed\n"
    "REASON: Attempt malformed diff.\n"
    "PATCH:\n"
    "@@ -1,0 +1,1 @@\n"
    "+        return revised_value\n"
)

_GOOD = (
    "TARGET_FILE: coder_context.py\n"
    "CHANGE_TYPE: diff_patch\n"
    "RISK_LEVEL: low\n"
    "STATUS: proposed\n"
    "REASON: Add a narrow explanatory comment inside select_edit_context.\n"
    "PATCH:\n"
    "--- coder_context.py\n"
    "+++ coder_context.py\n"
    "@@ -971,6 +971,7 @@ def select_edit_context(task, plan, target_file, file_text, radius=0, padding_lines=40):\n"
    "         if anchor_span:\n"
    "+            # Enforce span-locked selection before building exact-symbol context.\n"
    "             selected_block = _find_block_by_anchor_span(all_blocks, anchor_span)\n"
    "             _validate_block_against_anchor_span(\n"
)

_PLAN = {
    "goal": "Insert a comment above the anchor_span lookup in select_edit_context.",
    "task_type": "docs",
    "tasks": [
        {
            "title": "Document anchor span lookup",
            "description": "Insert a comment above the anchor_span lookup in select_edit_context.",
            "target_file": TARGET_FILE,
            "target_symbol": TARGET_SYMBOL,
            "change_intent": "modify_existing_logic",
            "expected_operation": "insert_comment",
            "completion_cues": [
                "# Enforce span-locked selection before building exact-symbol context."
            ],
            "task_type": "docs",
            "task_id": "lesson-reuse-child",
        }
    ],
    "dependencies": [TARGET_FILE],
    "risks": [],
    "next_action": "Insert the explanatory comment in select_edit_context.",
    "status": "planned",
}


def _reuse_responder(observations: list[bool]):
    def responder(prompt, *args, **kwargs):
        saw_seed_lesson = LESSON_MARKER in prompt
        observations.append(saw_seed_lesson)
        return _GOOD if saw_seed_lesson else _MALFORMED

    return responder


def build_lesson_reuse_experiment_pack(observations: list[bool] | None = None) -> list[dict]:
    """Return an ordered failure seed followed by a guidance-sensitive reuse case."""

    observations = observations if observations is not None else []
    common = {
        "band": "lesson_reuse_experiment",
        "task_note": "Insert a comment above the anchor_span lookup in select_edit_context.",
        "target_file": TARGET_FILE,
        "target_symbol": TARGET_SYMBOL,
        "change_intent": "modify_existing_logic",
        "expected_operation": "insert_comment",
        "completion_cues": [
            "# Enforce span-locked selection before building exact-symbol context."
        ],
        "task_type": "docs",
        "plan_response": _PLAN,
    }
    return [
        {
            **common,
            "name": "seed_missing_diff_headers",
            "task_id": "lesson-seed-1",
            "coder_side_effect": [_MALFORMED, _MALFORMED, _MALFORMED],
            "expected_final_status": "blocked",
            "expected_failure_code": LESSON_MARKER,
        },
        {
            **common,
            "name": "reuse_missing_diff_headers",
            "task_id": "lesson-reuse-1",
            "coder_response": _reuse_responder(observations),
            "expected_final_status": "proposed",
            "expected_failure_code": None,
        },
    ]
