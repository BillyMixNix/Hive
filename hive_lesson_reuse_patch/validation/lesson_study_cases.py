"""
Generalization seed->reuse pairs for the live lesson-efficacy study.

Each pair:
  - lesson : a crafted GENERALIZED lesson in some failure family, whose `origin_file`
             DIFFERS from the reuse task's file (so transfer != memorization).
             retry_instruction begins with a unique MARKER token so injection can be
             verified deterministically (_injection_fires in lesson_study.py).
  - reuse  : a real, low-risk editing task against a real repo symbol, run live.

Bands mirror the reliability pack: comment_docstring, narrow_logic_edits,
architectural_in_place_rewrites, route_flow_state.

IMPORTANT — calibration: difficulty was authored without access to the live model.
Run `--preflight` and check each pair's OFF-arm solve rate is strictly between 0 and 1.
Pairs at 0.0 or 1.0 have no headroom; raise/lower difficulty (see LESSON_STUDY.md).
"""


def _reuse(name, band, target_file, target_symbol, task_note, cue,
           change_intent="modify_existing_logic", expected_operation="insert_comment"):
    plan = {
        "goal": task_note,
        "task_type": "bugfix",
        "tasks": [{
            "title": name,
            "description": task_note,
            "target_file": target_file,
            "target_symbol": target_symbol,
            "change_intent": change_intent,
            "expected_operation": expected_operation,
            "completion_cues": [cue],
        }],
        "dependencies": [target_file], "risks": [], "next_action": "code", "status": "planned",
    }
    return {
        "name": name, "task_id": name, "band": band,
        "task_note": task_note,
        "target_file": target_file, "target_symbol": target_symbol,
        "change_intent": change_intent, "expected_operation": expected_operation,
        "completion_cues": [cue],
        "plan_response": plan,
        "expected_final_status": "proposed", "expected_failure_code": None,
    }


def _lesson(marker, failure_code, origin_file, instruction, trigger=None, fix=None):
    return {
        "origin_file": origin_file,
        "failure_code": failure_code,
        "retry_instruction": f"{marker} {instruction}",
        "trigger_pattern": trigger or "diff_patch::modify_existing_logic",
        "fix_strategy": fix or "emit_valid_unified_diff",
    }


def build_pairs():
    return [
        # ---- comment_docstring ----
        {
            "name": "cd_pair_1", "band": "comment_docstring",
            "lesson": _lesson("MKR_CD1", "missing_diff_headers", "coder_context.py",
                              "Always emit ---/+++ file headers and an @@ hunk in the unified diff."),
            "reuse": _reuse("cd_pair_1", "comment_docstring", "interface.py", "_build_response",
                            "Add a one-line comment above the return in _build_response explaining the response shape.",
                            "# Build the normalized response payload."),
        },
        {
            "name": "cd_pair_2", "band": "comment_docstring",
            "lesson": _lesson("MKR_CD2", "missing_diff_headers", "planner.py",
                              "A unified diff must start with ---/+++ headers before any @@ hunk."),
            "reuse": _reuse("cd_pair_2", "comment_docstring", "work_ontology.py", "infer_work_mode",
                            "Add a comment at the top of infer_work_mode describing what it returns.",
                            "# Infer the work mode from free text."),
        },
        # ---- narrow_logic_edits ----
        {
            "name": "nl_pair_1", "band": "narrow_logic_edits",
            "lesson": _lesson("MKR_NL1", "missing_diff_headers", "coder.py",
                              "Emit a unified diff with ---/+++ headers and an @@ hunk; no prose outside PATCH:."),
            "reuse": _reuse("nl_pair_1", "narrow_logic_edits", "builder.py", "_normalize_text",
                            "In _normalize_text, guard against a None input by returning an empty string.",
                            "if value is None:", change_intent="modify_existing_logic",
                            expected_operation="modify_logic"),
        },
        {
            "name": "nl_pair_2", "band": "narrow_logic_edits",
            "lesson": _lesson("MKR_NL2", "missing_diff_headers", "reflector.py",
                              "Emit only a clean unified diff with ---/+++ headers; no commentary."),
            "reuse": _reuse("nl_pair_2", "narrow_logic_edits", "interface.py", "_parse_int_suffix",
                            "In _parse_int_suffix, return None when the suffix is not a digit string.",
                            "return None", change_intent="modify_existing_logic",
                            expected_operation="modify_logic"),
        },
        # ---- architectural_in_place_rewrites ----
        {
            "name": "ar_pair_1", "band": "architectural_in_place_rewrites",
            "lesson": _lesson("MKR_AR1", "missing_diff_headers", "router.py",
                              "Produce a valid unified diff with ---/+++ headers; keep it within one scope.",
                              trigger="diff_patch::architectural", fix="emit_valid_unified_diff"),
            "reuse": _reuse("ar_pair_1", "architectural_in_place_rewrites", "coder_constraints.py",
                            "derive_patch_constraints",
                            "Add an inline comment inside derive_patch_constraints documenting the constraint order.",
                            "# Constraints are applied in priority order."),
        },
        {
            "name": "ar_pair_2", "band": "architectural_in_place_rewrites",
            "lesson": _lesson("MKR_AR2", "missing_diff_headers", "executor.py",
                              "Emit a unified diff with ---/+++ headers for one function body.",
                              trigger="diff_patch::architectural", fix="emit_valid_unified_diff"),
            "reuse": _reuse("ar_pair_2", "architectural_in_place_rewrites", "repo_map.py", "_compact_symbol_record",
                            "Add a comment above the return in _compact_symbol_record explaining the compaction.",
                            "# Compact the symbol record for the repo map."),
        },
        # ---- route_flow_state ----
        {
            "name": "rf_pair_1", "band": "route_flow_state",
            "lesson": _lesson("MKR_RF1", "missing_diff_headers", "main.py",
                              "Anchor to the named symbol and emit a valid unified diff with ---/+++ headers.",
                              trigger="diff_patch::route_flow", fix="emit_valid_unified_diff"),
            "reuse": _reuse("rf_pair_1", "route_flow_state", "work_ontology.py", "normalize_work_mode",
                            "Add a guard at the top of normalize_work_mode returning the default when mode is falsy.",
                            "return", change_intent="modify_existing_logic", expected_operation="modify_logic"),
        },
        {
            "name": "rf_pair_2", "band": "route_flow_state",
            "lesson": _lesson("MKR_RF2", "missing_diff_headers", "router.py",
                              "Keep the hunk aligned to the anchor and emit valid ---/+++ diff headers.",
                              trigger="diff_patch::route_flow", fix="emit_valid_unified_diff"),
            "reuse": _reuse("rf_pair_2", "route_flow_state", "builder.py", "merge_pilot_context",
                            "Add a comment in merge_pilot_context describing the merge precedence.",
                            "# New input takes precedence over existing context."),
        },
    ]
