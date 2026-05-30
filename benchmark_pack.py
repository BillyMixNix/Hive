import json

# Frozen at 1.0 — never change this value during an evolution run.
# If the task set changes, scores from different runs are not comparable.
BENCHMARK_PACK_VERSION = "1.0"


def _base_plan(*, goal, task_type, title, description, target_file, target_symbol, change_intent, expected_operation, completion_cues, next_action, risks=None):
    return {
        "goal": goal,
        "task_type": task_type,
        "tasks": [
            {
                "title": title,
                "description": description,
                "target_file": target_file,
                "target_symbol": target_symbol,
                "change_intent": change_intent,
                "expected_operation": expected_operation,
                "completion_cues": list(completion_cues or []),
            }
        ],
        "dependencies": [target_file],
        "risks": list(risks or []),
        "next_action": next_action,
        "status": "planned",
    }


def _success_comment_case(index):
    target_file = "coder_context.py"
    target_symbol = "select_edit_context"
    completion_cues = [
        "# Enforce span-locked selection before building exact-symbol context.",
    ]
    description = "Insert a comment above the anchor_span lookup in select_edit_context to explain the strict span lock."
    return {
        "name": f"docs_comment_{index:02d}",
        "band": "comment_docstring",
        "task_id": f"bench-doc-{index:02d}",
        "task_note": description,
        "target_file": target_file,
        "target_symbol": target_symbol,
        "change_intent": "modify_existing_logic",
        "expected_operation": "insert_comment",
        "completion_cues": completion_cues,
        "expected_failure_sensitivities": ["symbol_anchor_drift", "non_meaningful_patch"],
        "plan_response": _base_plan(
            goal="Clarify strict span-locked context selection in select_edit_context.",
            task_type="docs",
            title="Document anchor span lookup",
            description=description,
            target_file=target_file,
            target_symbol=target_symbol,
            change_intent="modify_existing_logic",
            expected_operation="insert_comment",
            completion_cues=completion_cues,
            next_action="Insert the explanatory comment in select_edit_context.",
            risks=["Misplaced comment could drift outside the target symbol."],
        ),
        "coder_response": (
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
        ),
        "expected_final_status": "proposed",
        "expected_failure_code": None,
    }


def _success_logic_case(index):
    if index % 2 == 0:
        target_file = "interface.py"
        target_symbol = "_build_response"
        completion_cues = ['"context": dict(context or {}),']
        description = "Update _build_response to copy the provided context mapping before returning it."
        coder_response = (
            "TARGET_FILE: interface.py\n"
            "CHANGE_TYPE: diff_patch\n"
            "RISK_LEVEL: low\n"
            "STATUS: proposed\n"
            "REASON: Copy the optional context mapping before storing it in the response.\n"
            "PATCH:\n"
            "--- interface.py\n"
            "+++ interface.py\n"
            "@@ -44,7 +44,7 @@ class Interface:\n"
            "     def _build_response(self, intent, text, context=None):\n"
            "         return {\n"
            "             \"intent\": intent,\n"
            "-            \"context\": context or {},\n"
            "+            \"context\": dict(context or {}),\n"
            "             \"raw_text\": text,\n"
            "         }\n"
        )
        goal = "Keep Interface responses from sharing mutable context objects."
        title = "Copy response context"
        next_action = "Modify _build_response in Interface."
    else:
        target_file = "router.py"
        target_symbol = "normalize_command"
        completion_cues = ['return str(command or "").lower().strip()']
        description = "Update normalize_command to handle missing command values safely before lowercasing."
        coder_response = (
            "    def normalize_command(self, command):\n"
            "        return str(command or \"\").lower().strip()\n"
        )
        goal = "Keep command normalization safe for missing values."
        title = "Guard normalize_command input"
        next_action = "Patch normalize_command in Router."

    return {
        "name": f"logic_narrow_{index:02d}",
        "band": "narrow_logic_edits",
        "task_id": f"bench-logic-{index:02d}",
        "task_note": description,
        "target_file": target_file,
        "target_symbol": target_symbol,
        "change_intent": "modify_existing_logic",
        "expected_operation": "modify_logic",
        "completion_cues": completion_cues,
        "expected_failure_sensitivities": ["symbol_anchor_drift", "missing_context_block", "mixed_scope_patch"],
        "plan_response": _base_plan(
            goal=goal,
            task_type="bugfix",
            title=title,
            description=description,
            target_file=target_file,
            target_symbol=target_symbol,
            change_intent="modify_existing_logic",
            expected_operation="modify_logic",
            completion_cues=completion_cues,
            next_action=next_action,
            risks=["Changing response construction could drift outside the target method."],
        ),
        "coder_response": coder_response,
        "expected_final_status": "proposed",
        "expected_failure_code": None,
    }


def _malformed_patch_response(target_file, failure_code):
    if failure_code == "missing_diff_headers":
        return (
            f"TARGET_FILE: {target_file}\n"
            "CHANGE_TYPE: diff_patch\n"
            "RISK_LEVEL: low\n"
            "STATUS: proposed\n"
            "REASON: Attempt malformed diff.\n"
            "PATCH:\n"
            "@@ -1,0 +1,1 @@\n"
            "+        return revised_value\n"
        )
    if failure_code == "missing_patch_section":
        return (
            f"TARGET_FILE: {target_file}\n"
            "CHANGE_TYPE: diff_patch\n"
            "RISK_LEVEL: low\n"
            "STATUS: proposed\n"
            "REASON: Attempt malformed response.\n"
            f"--- {target_file}\n"
            f"+++ {target_file}\n"
            "@@ -1,0 +1,1 @@\n"
            "+        return revised_value\n"
        )
    if failure_code == "non_diff_commentary":
        return (
            f"TARGET_FILE: {target_file}\n"
            "CHANGE_TYPE: diff_patch\n"
            "RISK_LEVEL: low\n"
            "STATUS: proposed\n"
            "REASON: Attempt malformed response.\n"
            "PATCH:\n"
            "Here is the fix.\n"
            f"--- {target_file}\n"
            f"+++ {target_file}\n"
            "@@ -1,0 +1,1 @@\n"
            "+        return revised_value\n"
        )
    raise ValueError(f"Unsupported malformed failure_code: {failure_code}")


def _missing_context_patch(target_file):
    return (
        f"TARGET_FILE: {target_file}\n"
        "CHANGE_TYPE: diff_patch\n"
        "RISK_LEVEL: low\n"
        "STATUS: proposed\n"
        "REASON: Attempt with missing real context block.\n"
        "PATCH:\n"
        f"--- {target_file}\n"
        f"+++ {target_file}\n"
        "@@ -1,0 +1,1 @@\n"
        "+        if not isinstance(cue, str): continue\n"
    )


def _planner_mixed_scope_patch():
    return (
        "TARGET_FILE: planner.py\n"
        "CHANGE_TYPE: diff_patch\n"
        "RISK_LEVEL: low\n"
        "STATUS: proposed\n"
        "REASON: Bad mixed-scope planner patch for benchmark coverage.\n"
        "PATCH:\n"
        "--- planner.py\n"
        "+++ planner.py\n"
        "@@ -190,7 +190,9 @@ class PlannerAgent:\n"
        "     def _normalize_completion_cues(self, child):\n"
        "+helper_context = {}\n"
        "+        child = dict(child)\n"
        "         cues = child.get(\"completion_cues\") or []\n"
    )


def _main_mixed_scope_patch():
    return (
        "TARGET_FILE: main.py\n"
        "CHANGE_TYPE: diff_patch\n"
        "RISK_LEVEL: low\n"
        "STATUS: proposed\n"
        "REASON: Bad mixed-scope main patch for benchmark coverage.\n"
        "PATCH:\n"
        "--- main.py\n"
        "+++ main.py\n"
        "@@ -418,7 +418,9 @@ def update_current_snapshot(state, task=None, plan=None, child=None, status=None):\n"
        " def update_current_snapshot(state, task=None, plan=None, child=None, status=None):\n"
        "+status_map = {}\n"
        "+    task_metadata = (task or {}).get(\"metadata\") or {}\n"
        "     if state is None:\n"
    )


def _architecture_failure_case(index):
    variants = [
        ("missing_diff_headers", "missing_diff_headers", "coder.py", "_build_retry_prompt"),
        ("missing_patch_section", "missing_patch_section", "planner.py", "_normalize_completion_cues"),
        ("non_diff_commentary", "non_diff_commentary", "executor.py", "validate_patch_semantics"),
        ("missing_context_block", "scope_alignment_mismatch", "planner.py", "_normalize_completion_cues"),
        ("mixed_scope_patch", "mixed_scope_patch", "planner.py", "_normalize_completion_cues"),
    ]
    failure_code, expected_failure_code, target_file, target_symbol = variants[(index - 1) % len(variants)]
    description = f"Harden {target_symbol} with a narrow in-place architecture edit."
    if failure_code == "mixed_scope_patch":
        coder_side_effect = [_planner_mixed_scope_patch()] * 3
    elif failure_code == "missing_context_block":
        coder_side_effect = [_missing_context_patch(target_file)] * 3
    else:
        coder_side_effect = [_malformed_patch_response(target_file, failure_code)] * 3

    return {
        "name": f"architecture_{failure_code}_{index:02d}",
        "band": "architectural_in_place_rewrites",
        "task_id": f"bench-arch-{index:02d}",
        "task_note": description,
        "target_file": target_file,
        "target_symbol": target_symbol,
        "change_intent": "modify_existing_logic",
        "expected_operation": "modify_logic",
        "completion_cues": ["return revised_value"],
        "expected_failure_sensitivities": [failure_code],
        "plan_response": _base_plan(
            goal=f"Keep {target_symbol} constrained and architecture-safe.",
            task_type="bugfix",
            title=f"Update {target_symbol} in place",
            description=description,
            target_file=target_file,
            target_symbol=target_symbol,
            change_intent="modify_existing_logic",
            expected_operation="modify_logic",
            completion_cues=["return revised_value"],
            next_action=f"Patch {target_symbol} in {target_file}.",
            risks=["A broad patch could drift outside the target architectural method."],
        ),
        "coder_side_effect": coder_side_effect,
        "expected_final_status": "blocked",
        "expected_failure_code": expected_failure_code,
    }


def _route_failure_case(index):
    variants = [
        ("missing_diff_headers", "missing_diff_headers", "update_current_snapshot"),
        ("missing_patch_section", "missing_patch_section", "_get_first_ready_child_task"),
        ("non_diff_commentary", "non_diff_commentary", "update_last_patch_snapshot"),
        ("missing_context_block", "scope_alignment_mismatch", "record_failure_observability"),
        ("mixed_scope_patch", "mixed_scope_patch", "update_current_snapshot"),
    ]
    failure_code, expected_failure_code, target_symbol = variants[(index - 1) % len(variants)]
    target_file = "main.py"
    description = f"Tighten {target_symbol} for route/state flow consistency."
    if failure_code == "mixed_scope_patch":
        coder_side_effect = [_main_mixed_scope_patch()] * 3
    elif failure_code == "missing_context_block":
        coder_side_effect = [_missing_context_patch(target_file)] * 3
    else:
        coder_side_effect = [_malformed_patch_response(target_file, failure_code)] * 3

    return {
        "name": f"route_flow_{failure_code}_{index:02d}",
        "band": "route_flow_state",
        "task_id": f"bench-route-{index:02d}",
        "task_note": description,
        "target_file": target_file,
        "target_symbol": target_symbol,
        "change_intent": "modify_existing_logic",
        "expected_operation": "modify_logic",
        "completion_cues": ["return revised_value"],
        "expected_failure_sensitivities": [failure_code],
        "plan_response": _base_plan(
            goal=f"Keep main.py route/state flow stable inside {target_symbol}.",
            task_type="bugfix",
            title=f"Update {target_symbol} state flow",
            description=description,
            target_file=target_file,
            target_symbol=target_symbol,
            change_intent="modify_existing_logic",
            expected_operation="modify_logic",
            completion_cues=["return revised_value"],
            next_action=f"Patch {target_symbol} in main.py.",
            risks=["A malformed route/state patch can break anchored flow handling."],
        ),
        "coder_side_effect": coder_side_effect,
        "expected_final_status": "blocked",
        "expected_failure_code": expected_failure_code,
    }


def build_reliability_benchmark_pack():
    cases = []
    for index in range(1, 11):
        cases.append(_success_comment_case(index))
    for index in range(1, 11):
        cases.append(_success_logic_case(index))
    for index in range(1, 11):
        cases.append(_architecture_failure_case(index))
    for index in range(1, 11):
        cases.append(_route_failure_case(index))
    return cases


def _unreachable_code_case(index):
    """
    Cases that exploit a confirmed gap in _detect_unreachable_code_after_return:
    the check inspects existing file lines before the anchor but does NOT scan
    the additions block itself for a return followed by more executable code.

    All variants produce expected_final_status="blocked" but the current pipeline
    returns "proposed" — giving baseline < 1.0 on this pack.

    A patch to executor._detect_unreachable_code_after_return that also scans
    within the additions would fix these and raise the score.

    Empirically verified: all variants fail with current pipeline (proposed when
    expected blocked), confirmed via benchmark_harness.run_case().
    """
    variants = [
        (
            "router.py", "normalize_command",
            "Guard normalize_command against missing command values safely before lowercasing.",
            (
                "TARGET_FILE: router.py\n"
                "CHANGE_TYPE: diff_patch\n"
                "RISK_LEVEL: low\n"
                "STATUS: proposed\n"
                "REASON: Guard normalize_command against missing command values.\n"
                "PATCH:\n"
                "--- router.py\n"
                "+++ router.py\n"
                "@@ -32,5 +32,6 @@ class Router:\n"
                "     def normalize_command(self, command):\n"
                "-        return command.lower().strip()\n"
                "+        return str(command or \"\").lower().strip()\n"
                "+        dead_code = True\n"
            ),
            ['return str(command or "").lower().strip()'],
        ),
        (
            "router.py", "normalize_command",
            "Guard normalize_command against missing command values safely before lowercasing.",
            (
                "TARGET_FILE: router.py\n"
                "CHANGE_TYPE: diff_patch\n"
                "RISK_LEVEL: low\n"
                "STATUS: proposed\n"
                "REASON: Guard normalize_command against missing command values.\n"
                "PATCH:\n"
                "--- router.py\n"
                "+++ router.py\n"
                "@@ -32,5 +32,9 @@ class Router:\n"
                "     def normalize_command(self, command):\n"
                "-        return command.lower().strip()\n"
                "+        if command:\n"
                "+            return command.lower().strip()\n"
                "+        return str(command or \"\").lower().strip()\n"
                "+        result = \"unreachable\"  # dead code after return\n"
            ),
            ['return str(command or "").lower().strip()'],
        ),
        (
            "router.py", "normalize_command",
            "Guard normalize_command against missing command values safely before lowercasing.",
            (
                "TARGET_FILE: router.py\n"
                "CHANGE_TYPE: diff_patch\n"
                "RISK_LEVEL: low\n"
                "STATUS: proposed\n"
                "REASON: Guard normalize_command against missing command values.\n"
                "PATCH:\n"
                "--- router.py\n"
                "+++ router.py\n"
                "@@ -32,5 +32,9 @@ class Router:\n"
                "     def normalize_command(self, command):\n"
                "-        return command.lower().strip()\n"
                "+        if command is None:\n"
                "+            return \"\"\n"
                "+        elif not command:\n"
                "+            return \"\"\n"
                "+        return str(command).lower().strip()\n"
                "+        fallback = \"dead\"\n"
            ),
            ['return str(command).lower().strip()'],
        ),
        (
            "router.py", "validate_command_context",
            "Harden validate_command_context to check context key presence before returning.",
            (
                "TARGET_FILE: router.py\n"
                "CHANGE_TYPE: diff_patch\n"
                "RISK_LEVEL: low\n"
                "STATUS: proposed\n"
                "REASON: Harden validate_command_context to check context key presence.\n"
                "PATCH:\n"
                "--- router.py\n"
                "+++ router.py\n"
                "@@ -72,3 +72,5 @@ class Router:\n"
                "     def validate_command_context(self, message):\n"
                "-        return \"context\" in message\n"
                "+        return bool(message) and \"context\" in message\n"
                "+        stale = True  # unreachable after return\n"
            ),
            ['return bool(message) and "context" in message'],
        ),
        (
            "router.py", "normalize_context",
            "Tighten normalize_context to safely coerce non-dict context values.",
            (
                "TARGET_FILE: router.py\n"
                "CHANGE_TYPE: diff_patch\n"
                "RISK_LEVEL: low\n"
                "STATUS: proposed\n"
                "REASON: Tighten normalize_context to safely coerce non-dict context values.\n"
                "PATCH:\n"
                "--- router.py\n"
                "+++ router.py\n"
                "@@ -75,3 +75,5 @@ class Router:\n"
                "     def normalize_context(self, context):\n"
                "-        return context if isinstance(context, dict) else {}\n"
                "+        return dict(context) if isinstance(context, dict) else {}\n"
                "+        fallback = None  # unreachable after return\n"
            ),
            ['return dict(context) if isinstance(context, dict) else {}'],
        ),
    ]
    target_file, target_symbol, description, coder_response, completion_cues = variants[
        (index - 1) % len(variants)
    ]
    return {
        "name": f"challenge_unreachable_{index:02d}",
        "band": "challenge_unreachable_detection",
        "task_id": f"bench-ch-unreachable-{index:02d}",
        "task_note": description,
        "target_file": target_file,
        "target_symbol": target_symbol,
        "change_intent": "modify_existing_logic",
        "expected_operation": "modify_logic",
        "completion_cues": completion_cues,
        "expected_failure_sensitivities": ["unreachable_code_after_return"],
        "plan_response": _base_plan(
            goal=f"Patch {target_symbol} in {target_file}.",
            task_type="bugfix",
            title=f"Update {target_symbol}",
            description=description,
            target_file=target_file,
            target_symbol=target_symbol,
            change_intent="modify_existing_logic",
            expected_operation="modify_logic",
            completion_cues=completion_cues,
            next_action=f"Apply the patch to {target_symbol} in {target_file}.",
            risks=["Patch may insert unreachable code after a return statement."],
        ),
        "coder_response": coder_response,
        "expected_final_status": "blocked",
        "expected_failure_code": "scope_alignment_mismatch",
    }


def build_challenge_pack():
    """
    Cases where the current pipeline gets the WRONG answer, giving baseline
    0.0 on this pack (all cases fail) and leaving full headroom for improvement.

    The gap: _detect_unreachable_code_after_return in executor.py only scans
    existing file lines before the anchor for a terminal statement.  It does
    NOT check the additions block itself, so patches that add a return and then
    add more executable code afterwards all slip through as "proposed" when they
    should be "blocked".

    All 5 cases here were empirically confirmed to produce final_status="proposed"
    with the current pipeline (confirmed via benchmark_harness.run_case()).

    To make this pack score above 0.0, fix _detect_unreachable_code_after_return
    to also scan for terminal statements within the additions list, not just in
    the existing file.  A correct fix should raise this pack's score to 1.0
    (from 0.0), giving delta=+1.0 — a clear acceptance signal for the gate.

    Baseline: 0.0  (all 5 cases fail: pipeline says proposed, expected blocked)
    Target:   1.0  (after fix to unreachable detection in additions)
    """
    cases = []
    for index in range(1, 6):
        cases.append(_unreachable_code_case(index))
    return cases


def benchmark_pack_as_json():
    return json.dumps(build_reliability_benchmark_pack(), indent=2)
