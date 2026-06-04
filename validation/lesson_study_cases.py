"""
Generalization seed->reuse pairs for the live lesson-efficacy study — ROUND 2.

Round 1 finding (preflight, n=4): comment/architectural/route tasks SATURATE
(off_solve=1.00) at budget=3 — no headroom — and the seeded `missing_diff_headers`
family did NOT match the failures qwen-7B actually makes. The model's real failure
on constrained edits was `symbol_anchor_drift` (it edits an adjacent function instead
of the requested one). The only pair with headroom was an anchor-constrained logic
edit (builder._normalize_text).

Round 2 therefore:
  - TASK RECIPE: a tiny logic guard on a small function that has an *adjacent sibling*
    function, which tempts the model into editing the wrong symbol -> produces real
    `symbol_anchor_drift` failures (headroom), instead of trivial one-shot successes.
  - LESSON FAMILY: seed lessons in `symbol_anchor_drift` (what the model actually
    fails), with instruction text that is genuinely relevant to that failure.
  - GENERALIZATION preserved: each lesson's origin_file differs from the reuse file,
    so a win requires cross-file transfer of a generalized lesson.

Still calibrate with --preflight: keep pairs whose off_solve is strictly between 0
and 1. Use a larger N (>=20) for the real run so the headroom pairs are trustworthy.
"""


def _reuse(name, band, target_file, target_symbol, task_note, cue):
    plan = {
        "goal": task_note,
        "task_type": "bugfix",
        "tasks": [{
            "title": name,
            "description": task_note,
            "target_file": target_file,
            "target_symbol": target_symbol,
            "change_intent": "modify_existing_logic",
            "expected_operation": "modify_logic",
            "completion_cues": [cue],
        }],
        "dependencies": [target_file], "risks": [], "next_action": "code", "status": "planned",
    }
    return {
        "name": name, "task_id": name, "band": band,
        "task_note": task_note,
        "target_file": target_file, "target_symbol": target_symbol,
        "change_intent": "modify_existing_logic", "expected_operation": "modify_logic",
        "completion_cues": [cue],
        "plan_response": plan,
        "expected_final_status": "proposed", "expected_failure_code": None,
    }


def _anchor_lesson(marker, origin_file):
    return {
        "origin_file": origin_file,
        # The model's anchor-drift is classified by interpret_failure into several
        # codes depending on HOW it drifts; seed the same guidance under all of them
        # so it matches whatever the model actually does. (Verified: single-code seeds
        # only injected on a subset of drift trials -> invalidated rounds 1-2.)
        "failure_code": "symbol_anchor_drift",
        "failure_codes": ["symbol_anchor_drift", "scope_alignment_mismatch", "new_method_not_allowed"],
        "retry_instruction": (
            f"{marker} Modify ONLY the requested target symbol. Do not add, remove, "
            f"or edit any other function. Keep the entire diff hunk inside the target "
            f"function's body, and include the requested symbol's def line as context."
        ),
        "trigger_pattern": "diff_patch::anchor_lock",
        "fix_strategy": "edit_only_target_symbol",
    }


def build_pairs():
    # Each reuse target is a small function that sits directly next to a sibling,
    # so an unanchored edit tends to drift into the neighbour -> symbol_anchor_drift.
    return [
        {
            "name": "anc_pair_1", "band": "anchor_logic",
            "lesson": _anchor_lesson("MKR_A1", "coder_context.py"),
            "reuse": _reuse("anc_pair_1", "anchor_logic", "builder.py", "_normalize_text",
                            "In _normalize_text only, return an empty string when value is None, "
                            "before the existing normalization. Do not modify any other function.",
                            "if value is None:"),
        },
        {
            "name": "anc_pair_2", "band": "anchor_logic",
            "lesson": _anchor_lesson("MKR_A2", "planner.py"),
            "reuse": _reuse("anc_pair_2", "anchor_logic", "builder.py", "_extract_sentences",
                            "In _extract_sentences only, return an empty list when text is falsy, "
                            "before any other logic. Do not touch neighbouring functions.",
                            "if not text:"),
        },
        {
            "name": "anc_pair_3", "band": "anchor_logic",
            "lesson": _anchor_lesson("MKR_A3", "coder.py"),
            "reuse": _reuse("anc_pair_3", "anchor_logic", "interface.py", "_parse_int_suffix",
                            "In _parse_int_suffix only, return None when clean does not start with "
                            "prefix, before parsing. Do not edit _parse_int_and_text_suffix.",
                            "return None"),
        },
        {
            "name": "anc_pair_4", "band": "anchor_logic",
            "lesson": _anchor_lesson("MKR_A4", "executor.py"),
            "reuse": _reuse("anc_pair_4", "anchor_logic", "work_ontology.py", "infer_work_mode",
                            "In infer_work_mode only, lowercase text once at the top and reuse it. "
                            "Do not modify infer_domain or infer_artifact.",
                            "lowered = (text or \"\").lower()"),
        },
        {
            "name": "anc_pair_6", "band": "anchor_logic",
            "lesson": _anchor_lesson("MKR_A6", "reflector.py"),
            "reuse": _reuse("anc_pair_6", "anchor_logic", "work_ontology.py", "normalize_work_mode",
                            "In normalize_work_mode only, return the default mode when mode is falsy, "
                            "before validation. Do not edit infer_work_mode.",
                            "return"),
        },
    ]
