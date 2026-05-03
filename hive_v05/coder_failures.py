UNKNOWN_FAILURE_CODE = "unknown_failure"

FAILURE_FAMILIES = (
    "targeting",
    "formatting",
    "placement",
    "structure",
    "semantics",
    "reflection",
    "doctrine",
    "orchestration",
    "unknown",
)

FAILURE_CLASSES = (
    "parser_contract",
    "planner_contract",
    "explicit_target",
    "scope_boundary",
    "anchor_placement",
    "class_scope",
    "semantic_safety",
    "reflection_verdict",
    "retry_budget",
    "sandbox_environment",
    "context_budget",
    "policy",
    "unknown",
)


def _taxonomy_entry(family, failure_class, instruction, constraints=None, strategy_code=None):
    return {
        "family": family,
        "class": failure_class,
        "instruction": instruction,
        "constraints": list(constraints or []),
        "strategy_code": strategy_code or failure_class,
    }


FAILURE_TAXONOMY = {
    "missing_patch_section": _taxonomy_entry(
        "formatting",
        "parser_contract",
        "Return ONLY the required fields followed by exactly one PATCH: section and a unified diff.",
        [
            "Output exactly one PATCH: marker.",
            "Do not return prose, markdown fences, or analysis before the diff fields.",
        ],
    ),
    "empty_patch": _taxonomy_entry(
        "formatting",
        "parser_contract",
        "Do not leave PATCH empty; provide a minimal anchored diff or return a blocked patch header with a clear reason.",
        [
            "If no safe edit is possible, return STATUS: blocked with a clear REASON.",
            "Do not emit an empty diff body.",
        ],
    ),
    "non_diff_commentary": _taxonomy_entry(
        "formatting",
        "parser_contract",
        "Output diff lines only after PATCH:. Do not include doctrine text, summaries, or commentary.",
        [
            "After PATCH:, output only unified diff lines.",
            "Do not include markdown fences or explanatory sentences anywhere in the response.",
        ],
    ),
    "multiple_patch_sections": _taxonomy_entry(
        "formatting",
        "parser_contract",
        "Return exactly one PATCH: section.",
        [
            "Emit the PATCH: line once.",
            "Do not include alternate patches or fallback diffs in the same response.",
        ],
    ),
    "missing_diff_headers": _taxonomy_entry(
        "formatting",
        "parser_contract",
        "Return a unified diff with both --- and +++ file headers.",
        [
            "Include exactly one --- header and one matching +++ header.",
            "Do not omit diff file headers.",
        ],
    ),
    "empty_model_response": _taxonomy_entry(
        "formatting",
        "parser_contract",
        "Return the required fields and a minimal unified diff patch.",
        [
            "Do not return an empty response.",
            "Emit the required patch fields in the required format.",
        ],
    ),
    "stagnant_retry_patch": _taxonomy_entry(
        "orchestration",
        "retry_budget",
        "Do not repeat the previous failed patch. Apply one narrow corrective rule and return a materially different diff inside the same anchored symbol.",
        [
            "Do not resubmit the same patch text after a failure.",
            "Keep the retry inside the same anchored symbol and change only the failing lines.",
        ],
        strategy_code="retry_with_new_patch_shape",
    ),
    "non_meaningful_patch": _taxonomy_entry(
        "doctrine",
        "policy",
        "Return a patch that changes actual requested behavior or documentation content instead of punctuation-only or whitespace-only edits.",
        [
            "Do not return punctuation-only, bracket-only, or whitespace-only changes.",
            "If the task is documentation-only, keep the change narrow but still include the requested explanatory text.",
        ],
        strategy_code="require_meaningful_change",
    ),
    "planner_invalid_json": _taxonomy_entry(
        "orchestration",
        "planner_contract",
        "Planner output was malformed. Use the narrow fallback plan or regenerate valid planner JSON before coding.",
        [
            "Do not retry coder generation until planner output is valid or fallback planning is selected.",
            "Preserve the anchored target file and symbol if narrow fallback is available.",
        ],
        strategy_code="planner_recover_invalid_json",
    ),
    "planner_validation_failure": _taxonomy_entry(
        "orchestration",
        "planner_contract",
        "Planner output failed validation. Use a conservative single-symbol fallback plan or fix the invalid planner fields first.",
        [
            "Do not pass an invalid planner child task to coder.",
            "Keep fallback planning narrow and single-symbol only.",
        ],
        strategy_code="planner_recover_validation",
    ),
    "planner_fallback_used": _taxonomy_entry(
        "orchestration",
        "planner_contract",
        "Planner fallback was used. Keep the task narrow and avoid broad decomposition until planner output is stable.",
        [
            "Stay on the anchored file and symbol only.",
            "Do not infer multi-file work from a fallback plan.",
        ],
        strategy_code="planner_fallback_narrow",
    ),
    "multiple_target_files": _taxonomy_entry(
        "targeting",
        "explicit_target",
        "Modify exactly one file in this patch.",
        [
            "Use one target file only.",
            "Do not include diff headers for any second file.",
        ],
    ),
    "explicit_file_mismatch": _taxonomy_entry(
        "targeting",
        "explicit_target",
        "Keep the patch on the explicitly named file from the task note. Do not drift to a dependency or default file.",
        [
            "Use the exact anchored file only.",
            "Do not redirect the patch to a fallback dependency.",
        ],
    ),
    "explicit_method_mismatch": _taxonomy_entry(
        "targeting",
        "explicit_target",
        "Target the explicitly named method from the task note. Do not rewrite a broader default block.",
        [
            "Keep the edit inside the anchored method or symbol.",
            "Do not substitute a neighboring or default block.",
        ],
    ),
    "symbol_anchor_drift": _taxonomy_entry(
        "targeting",
        "explicit_target",
        "Rewrite only the requested existing symbol. Do not modify unrelated symbols, do not rename the target, and do not add new functions.",
        [
            "Modify the exact anchored symbol only.",
            "Do not touch neighboring functions or blocks.",
            "Return only a unified diff for the anchored file.",
        ],
        strategy_code="rewrite_target_symbol_only",
    ),
    "scope_alignment_mismatch": _taxonomy_entry(
        "targeting",
        "explicit_target",
        "Keep the patch aligned to the exact requested task scope and intent. Do not broaden the edit beyond the named symbol and requested change.",
        [
            "Edit only lines that directly satisfy the task note or explicit replace tokens.",
            "Do not add unrelated logic just because it appears nearby in the same file.",
        ],
        strategy_code="realign_to_task_scope",
    ),
    "bad_method_insertion_point": _taxonomy_entry(
        "placement",
        "anchor_placement",
        "Do not insert a new method immediately after a return line. Insert only after the previous method has fully ended.",
        [
            "Do not place a new def directly after a return statement.",
            "Keep class-level definitions at clean boundaries only.",
        ],
    ),
    "missing_anchor_context": _taxonomy_entry(
        "placement",
        "anchor_placement",
        "Use real anchor context lines from the file. Include unchanged context lines before and after the edit.",
        [
            "Include unchanged surrounding lines from the real file.",
            "Do not emit additions-only placement guesses.",
        ],
    ),
    "missing_context_block": _taxonomy_entry(
        "placement",
        "anchor_placement",
        "Include a real contiguous context block or removal lines from the target file before retrying.",
        [
            "Do not submit additions-only diffs without surrounding real file context.",
            "Use unchanged anchor lines from the current on-disk file.",
        ],
        strategy_code="restore_real_context_block",
    ),
    "mixed_scope_patch": _taxonomy_entry(
        "placement",
        "scope_boundary",
        "Keep the patch inside one indentation and scope boundary. Do not mix top-level additions with nested function-body additions in the same patch hunk.",
        [
            "Edit one scope boundary only.",
            "Do not combine module-scope and nested-scope additions in one localized patch.",
        ],
        strategy_code="stay_within_one_scope_boundary",
    ),
    "inserted_after_terminal_statement": _taxonomy_entry(
        "placement",
        "scope_boundary",
        "Move the inserted lines above the return/raise boundary.",
        [
            "Do not insert executable code after return, raise, break, or continue.",
            "Place new executable lines before the terminal statement in the same block.",
        ],
        strategy_code="move_above_terminal_boundary",
    ),
    "new_method_not_allowed": _taxonomy_entry(
        "doctrine",
        "policy",
        "Do not add helper methods. Rewrite the existing target method in place.",
        [
            "Do not add any new def line.",
            "Modify existing lines inside the selected target block instead of inserting helpers.",
        ],
    ),
    "duplicate_method_definition": _taxonomy_entry(
        "structure",
        "class_scope",
        "Do not define a method that already exists in the patch. Add or modify only one method definition.",
        [
            "Do not emit the same def name twice.",
            "Prefer revising one existing method body instead of re-declaring methods.",
        ],
    ),
    "too_many_new_methods": _taxonomy_entry(
        "structure",
        "class_scope",
        "Reduce scope to one localized change. Prefer revising one existing shared method in place instead of adding new methods.",
        [
            "Touch one localized region only.",
            "Keep at most one method definition change in the patch.",
        ],
    ),
    "removes_existing_methods": _taxonomy_entry(
        "structure",
        "class_scope",
        "Preserve all existing methods. Do not remove or replace unrelated method definitions.",
        [
            "Do not delete any existing def line.",
            "Revise method bodies in place instead of removing methods.",
        ],
    ),
    "unfinished_block_insertion": _taxonomy_entry(
        "structure",
        "class_scope",
        "Do not insert a new method until the previous structure has fully closed. Place new methods only at clean class-level boundaries.",
        [
            "Do not place a def inside an open block.",
            "Keep parentheses/brackets/braces structurally balanced around the insertion point.",
        ],
    ),
    "bad_method_indent": _taxonomy_entry(
        "structure",
        "class_scope",
        "Add new methods only at class-method indentation level with exactly 4 leading spaces.",
        [
            "If adding a method, indent it exactly to class scope.",
            "Do not nest class methods inside another method body.",
        ],
    ),
    "duplicate_docstring_instead_of_edit": _taxonomy_entry(
        "structure",
        "class_scope",
        "Edit the existing docstring block instead of adding a second docstring.",
        [
            "Do not add a second standalone string expression.",
            "Revise the existing docstring in place.",
        ],
        strategy_code="edit_existing_docstring",
    ),
    "comment_task_rejected_as_nonfunctional": _taxonomy_entry(
        "doctrine",
        "policy",
        "Allow the localized comment/docstring/help-text edit for this documentation-style task instead of forcing a logic change.",
        [
            "Keep the patch narrowly scoped to the requested explanatory text.",
            "Do not broaden a documentation task into unrelated logic edits.",
        ],
        strategy_code="allow_documentation_only_patch",
    ),
    "structural_scope_invalid": _taxonomy_entry(
        "structure",
        "class_scope",
        "Revise the patch so the resulting file keeps valid executable structure at class and module scope.",
        [
            "Do not introduce stray executable nodes at class scope.",
            "Keep structure parsable and aligned with the surrounding scope.",
        ],
        strategy_code="repair_scope_structure",
    ),
    "block_rewrite_wrong_method": _taxonomy_entry(
        "targeting",
        "explicit_target",
        "Block rewrite must return the exact anchored method only. Do not rewrite or rename any other method.",
        [
            "Return the same target method name and the same target method only.",
            "Do not substitute a neighboring method or emit helper methods.",
        ],
        strategy_code="rewrite_exact_block_only",
    ),
    "block_rewrite_contract_failure": _taxonomy_entry(
        "structure",
        "parser_contract",
        "Block rewrite output must satisfy the exact rewrite contract for the selected method.",
        [
            "Return a non-empty rewrite of the selected method only.",
            "Preserve the original def line and method signature exactly.",
            "Make a meaningful in-method change instead of echoing the original block.",
        ],
        strategy_code="repair_block_rewrite_contract",
    ),
    "sandbox_apply_failed": _taxonomy_entry(
        "placement",
        "anchor_placement",
        "Revise the patch so it can be applied cleanly in sandbox without anchor or placement errors.",
        [
            "Keep the patch anchored to exact existing file lines.",
            "Do not change placement strategy unless needed to match real context.",
        ],
    ),
    "sandbox_syntax_failed": _taxonomy_entry(
        "structure",
        "class_scope",
        "Revise the patch so the resulting sandboxed file is valid Python syntax.",
        [
            "Return syntactically valid Python only.",
            "Do not leave unclosed blocks, broken indentation, or malformed defs.",
        ],
    ),
    "sandbox_semantic_failed": _taxonomy_entry(
        "semantics",
        "semantic_safety",
        "Revise the patch so it passes semantic safety checks in sandbox.",
        [
            "Do not introduce undefined helpers, unreachable code, or invalid scope references.",
            "Prefer a smaller in-place change over structural expansion.",
        ],
    ),
    "local_assignment_at_module_scope": _taxonomy_entry(
        "semantics",
        "scope_boundary",
        "Insert the assignment inside the target function body near existing local setup lines.",
        [
            "Do not place local setup variables at module scope.",
            "Keep the assignment inside the intended function body.",
        ],
        strategy_code="move_assignment_inside_function",
    ),
    "sandbox_unavailable": _taxonomy_entry(
        "orchestration",
        "retry_budget",
        "Sandbox testing is unavailable. Keep the patch minimal and structurally conservative.",
        [
            "Prefer the smallest safe edit.",
            "Avoid risky structural rewrites when sandbox confirmation is unavailable.",
        ],
    ),
    "workspace_sandbox_permission_issue": _taxonomy_entry(
        "orchestration",
        "sandbox_environment",
        "Sandbox setup hit a workspace permission issue. Use a writable workspace-local sandbox path or escalate the environment issue instead of retrying the same patch.",
        [
            "Do not treat filesystem permission failures as patch-quality failures.",
            "Switch sandbox location or escalate the environment issue before retrying.",
        ],
        strategy_code="sandbox_permission_recover",
    ),
    "under_anchored_after_trim": _taxonomy_entry(
        "doctrine",
        "context_budget",
        "Prompt trimming removed too much anchor confidence. Block early and require a narrower symbol or stronger anchor before coding.",
        [
            "Do not continue with file-head or weak anchor context on a large file.",
            "Prefer an exact symbol or selected block anchor before retrying.",
        ],
        strategy_code="block_under_anchored_trimmed_context",
    ),
    "reflector_reject": _taxonomy_entry(
        "reflection",
        "reflection_verdict",
        "Keep the same goal and target file, but reduce scope and fix only the issue identified by reflection.",
        [
            "Do not broaden the patch beyond the rejected region.",
            "Replace the rejected approach instead of layering extra logic on top of it.",
        ],
        strategy_code="replace_rejected_approach",
    ),
    "reflector_revision": _taxonomy_entry(
        "reflection",
        "reflection_verdict",
        "Revise the previous patch narrowly instead of expanding it.",
        [
            "Keep the same target file and patch shape.",
            "Change only the lines needed to address the reflection.",
        ],
    ),
    "completion_cue_mismatch": _taxonomy_entry(
        "doctrine",
        "policy",
        "Do not broaden the patch just to satisfy stale completion cues. Stop and surface the mismatch.",
        [
            "Do not expand scope only to force expected cue strings into the diff.",
            "Prefer reporting the cue mismatch over retrying with a broader rewrite.",
        ],
        strategy_code="stop_on_completion_cue_mismatch",
    ),
    "patch_too_large": _taxonomy_entry(
        "doctrine",
        "policy",
        "Reduce scope. Keep the patch smaller and more localized.",
        [
            "Touch one bounded region only.",
            "Prefer modifying an existing block instead of rewriting multiple regions.",
        ],
    ),
    "oversized_context_trimmed": _taxonomy_entry(
        "doctrine",
        "context_budget",
        "Prompt context exceeded budget and was trimmed. Keep the anchored symbol block and summary; do not re-expand to a full-file prompt.",
        [
            "Prefer the exact selected symbol block over broad file windows.",
            "Use summary scaffolding instead of reintroducing raw large-file context.",
        ],
        strategy_code="keep_trimmed_context",
    ),
    "sandbox_retry_exhausted": _taxonomy_entry(
        "orchestration",
        "retry_budget",
        "Stop repeating the same patch shape. Escalate or substantially change the approach before retrying.",
        [
            "Do not immediately resubmit the same failure pattern.",
            "Escalate or change strategy after repeated identical failures.",
        ],
        strategy_code="stop_repeating_failed_retry_shape",
    ),
    UNKNOWN_FAILURE_CODE: _taxonomy_entry(
        "unknown",
        "unknown",
        "Keep the patch minimal, anchored, structurally valid, and avoid repeating the previous failure.",
        [
            "Prefer a smaller localized diff.",
            "Do not repeat the same failed patch shape unchanged.",
        ],
    ),
}

RETRY_TEMPLATE_MAP = {
    code: {
        "instruction": entry["instruction"],
        "constraints": list(entry.get("constraints") or []),
        "strategy_code": entry.get("strategy_code"),
    }
    for code, entry in FAILURE_TAXONOMY.items()
}

FAILURE_RULES = RETRY_TEMPLATE_MAP


def _classify_format_failure(text):
    """Classify formatting / parser-contract failures."""
    if "no patch:" in text:
        return "missing_patch_section"
    if "patch section is empty" in text:
        return "empty_patch"
    if "non-diff commentary" in text:
        return "non_diff_commentary"
    if "multiple patch: sections" in text:
        return "multiple_patch_sections"
    if "patch is missing diff file headers" in text or "missing diff file headers" in text:
        return "missing_diff_headers"
    if "empty model response" in text:
        return "empty_model_response"
    if "patch change too small or non-functional" in text:
        return "comment_task_rejected_as_nonfunctional"
    if "non_meaningful_patch" in text:
        return "non_meaningful_patch"
    return None


def _classify_sandbox_failure(text):
    """Classify sandbox environment failures."""
    if "sandbox apply failed" in text:
        return "sandbox_apply_failed"
    if "sandbox syntax failed" in text:
        return "sandbox_syntax_failed"
    if "sandbox semantic failed" in text:
        return "sandbox_semantic_failed"
    if "sandbox unavailable" in text:
        return "sandbox_unavailable"
    if "access is denied" in text or "permission denied" in text or "winerror 5" in text:
        return "workspace_sandbox_permission_issue"
    return None


def _classify_planner_failure(text):
    """Classify planner contract failures."""
    if "planner output was malformed" in text or "no json object found" in text:
        return "planner_invalid_json"
    if "planner output failed validation" in text:
        return "planner_validation_failure"
    if "planner fallback was used" in text:
        return "planner_fallback_used"
    return None


def _classify_scope_failure(text):
    """Classify scope boundary and method structure failures."""
    if "new methods are not allowed" in text:
        return "new_method_not_allowed"
    if "violates constraints" in text and ("new method" in text or "new methods" in text):
        return "new_method_not_allowed"
    if "duplicate method definition" in text or "duplicate method definitions" in text:
        return "duplicate_method_definition"
    if "more than one new method" in text:
        return "too_many_new_methods"
    if "removes existing methods" in text:
        return "removes_existing_methods"
    if "immediately after a return line" in text:
        return "bad_method_insertion_point"
    if "invalid indentation level" in text:
        return "bad_method_indent"
    if "unfinished block" in text:
        return "unfinished_block_insertion"
    if (
        "mixed_scope_detected': true" in text
        or '"mixed_scope_detected": true' in text
        or "mixed scope detected" in text
        or "mixed_scope_patch" in text
    ):
        return "mixed_scope_patch"
    if "local_assignment_at_module_scope" in text:
        return "local_assignment_at_module_scope"
    return None


def _classify_anchor_failure(text):
    """Classify anchor and context block failures."""
    if "no anchor context or removal lines" in text:
        return "missing_context_block"
    if "no anchor context" in text:
        return "missing_anchor_context"
    if (
        "anchor_found': false" in text
        or '"anchor_found": false' in text
        or "context_block_found': false" in text
        or '"context_block_found": false' in text
    ):
        return "missing_context_block"
    if "under-anchored after trim" in text:
        return "under_anchored_after_trim"
    if "context exceeded budget" in text or "context was trimmed" in text:
        return "oversized_context_trimmed"
    if "does not satisfy planner completion_cues" in text or "missing expected diff cues" in text:
        return "completion_cue_mismatch"
    return None


def _classify_target_failure(text):
    """Classify explicit target and scope alignment failures."""
    if "must target exactly one file" in text:
        return "multiple_target_files"
    if "does not match explicit task file" in text:
        return "explicit_file_mismatch"
    if "does not match explicit task method" in text:
        return "explicit_method_mismatch"
    if "symbol_anchor_drift" in text:
        return "symbol_anchor_drift"
    if (
        "patch appears misaligned with task scope" in text
        or "patch appears broader than the explicit task intent" in text
    ):
        return "scope_alignment_mismatch"
    if "too large for first-pass review" in text:
        return "patch_too_large"
    return None


def _classify_reflection_failure(text):
    """Classify reflector verdict failures."""
    if "reflector rejected patch" in text:
        return "reflector_reject"
    if "reflector requested revision" in text:
        return "reflector_revision"
    return None


def _classify_block_rewrite_failure(text):
    """Classify block rewrite contract failures."""
    if "block rewrite returned incorrect method" in text:
        return "block_rewrite_wrong_method"
    if (
        "block_rewrite_contract_failure" in text
        or "block rewrite returned an empty block" in text
        or "block rewrite changed the target method signature" in text
        or "block rewrite produced no meaningful change" in text
    ):
        return "block_rewrite_contract_failure"
    return None


def classify_failure(error_text):
    """
    Classify a failure string into a structured failure code.

    Delegates to grouped helper classifiers in priority order.
    Returns UNKNOWN_FAILURE_CODE if no group matches.
    """
    text = str(error_text).lower()

    return (
        _classify_format_failure(text)
        or _classify_sandbox_failure(text)
        or _classify_planner_failure(text)
        or _classify_scope_failure(text)
        or _classify_anchor_failure(text)
        or _classify_target_failure(text)
        or _classify_reflection_failure(text)
        or _classify_block_rewrite_failure(text)
        or UNKNOWN_FAILURE_CODE
    )


def build_retry_instruction(error_text):
    category = classify_failure(error_text)
    rule = RETRY_TEMPLATE_MAP.get(category) or RETRY_TEMPLATE_MAP[UNKNOWN_FAILURE_CODE]
    return rule["instruction"]


def build_symbol_drift_retry(task, target_file):
    task_metadata = task.get("metadata") or {}
    target_symbol = task.get("target_symbol") or task_metadata.get("target_symbol")
    if not target_symbol:
        return None

    return (
        f"Rewrite only the existing function {target_symbol} in {target_file}.\n"
        f"Do not modify any symbol other than {target_symbol}.\n"
        "Do not add new functions.\n"
        f"Return only a unified diff for {target_file}."
    )


def build_retry_guidance(error_text, recent_lessons=None, rejected_patches=None):
    category = classify_failure(error_text)
    rule = RETRY_TEMPLATE_MAP.get(category) or RETRY_TEMPLATE_MAP[UNKNOWN_FAILURE_CODE]

    lines = [
        "RETRY CONSTRAINTS:",
        f"- Failure category: {category}",
        f"- Primary instruction: {rule['instruction']}",
    ]

    for constraint in rule.get("constraints", [])[:3]:
        lines.append(f"- Constraint: {constraint}")

    recent_lessons = recent_lessons or []
    matching_lessons = [
        lesson for lesson in recent_lessons
        if isinstance(lesson, dict)
        and (
            lesson.get("failure_code") == category
            or lesson.get("failure_reason") == category
        )
    ][:2]

    if matching_lessons:
        lines.append("- Matching recent lesson patterns:")
        for lesson in matching_lessons:
            pattern = lesson.get("failure_pattern") or lesson.get("retry_instruction")
            if pattern:
                lines.append(f"- Avoid repeating: {str(pattern)[:160]}")

        lines.append("- Constraint: Change the patch shape materially instead of resubmitting a near-identical diff.")

    rejected_patches = rejected_patches or []
    normalized_rejections = [str(item).strip() for item in rejected_patches if str(item).strip()][:2]
    if normalized_rejections:
        lines.append("- Recent rejected patch notes:")
        for entry in normalized_rejections:
            lines.append(f"- Avoid rejected pattern: {entry[:160]}")

    return "\n".join(lines)
