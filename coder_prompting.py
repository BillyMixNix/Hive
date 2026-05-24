from coder_prompt import (
    CODER_PROMPT_TEMPLATE,
    CODER_REVISION_PROMPT_TEMPLATE,
    BLOCK_REWRITE_PROMPT_TEMPLATE,
    SYMBOL_LOCKED_PATCH_PROMPT_TEMPLATE,
)
from builder import format_pilot_brief
from coder_constraints import derive_patch_constraints, format_patch_constraints
from work_ontology import FILE_LEVEL_WORK_MODES, normalize_work_mode

DEFAULT_CONTEXT_BUDGET_CHARS = 6000
REVISION_CONTEXT_BUDGET_CHARS = 6800
SYMBOL_LOCKED_CONTEXT_BUDGET_CHARS = 5200
BLOCK_REWRITE_CONTEXT_BUDGET_CHARS = 4500
LARGE_FILE_CHAR_THRESHOLD = 16000
LARGE_FILE_SYMBOL_THRESHOLD = 30


def get_plan_goal_text(plan):
    return str(plan.get("goal", "")).strip()


def get_plan_task_lines(plan):
    tasks = plan.get("tasks", [])
    lines = []

    if not isinstance(tasks, list):
        return lines

    for item in tasks:
        if not isinstance(item, dict):
            continue

        title = str(item.get("title", "")).strip()
        description = str(item.get("description", "")).strip()

        if title and description:
            lines.append(f"- {title}: {description}")
        elif title:
            lines.append(f"- {title}")
        elif description:
            lines.append(f"- {description}")

    return lines


def _format_completion_cues(task):
    metadata = task.get("metadata") or {}
    cues = task.get("completion_cues") or metadata.get("completion_cues") or []
    normalized = []
    for cue in cues:
        if cue is None:
            continue
        text = str(cue).strip()
        if text:
            normalized.append(text)
    return normalized


def _get_pilot_guardrail_text(task):
    metadata = task.get("metadata") or {}
    text = str(metadata.get("pilot_guardrails_text") or "").strip()
    return text or "No relevant pilot guardrails."


def build_preflight_intent(task, target_file):
    task = dict(task or {})
    metadata = task.get("metadata") or {}
    anchor = metadata.get("anchor") or {}
    target_symbol = task.get("target_symbol") or metadata.get("target_symbol") or anchor.get("target_symbol") or ""
    target_symbol_id = task.get("target_symbol_id") or metadata.get("target_symbol_id") or anchor.get("target_symbol_id")
    expected_operation = task.get("expected_operation") or metadata.get("expected_operation") or "modify_logic"
    completion_cues = _format_completion_cues(task)
    work_mode = normalize_work_mode(
        task.get("work_mode") or task.get("task_kind") or metadata.get("work_mode") or metadata.get("task_kind"),
        task_type=task.get("task_type") or metadata.get("task_type"),
        text=task.get("note") or task.get("description") or "",
    )
    creates_symbols = task.get("creates_symbols") or metadata.get("creates_symbols") or []
    wires_into_symbols = task.get("wires_into_symbols") or metadata.get("wires_into_symbols") or []
    insertion_region = task.get("insertion_region") or metadata.get("insertion_region") or ""

    span_start = anchor.get("lineno")
    span_end = anchor.get("end_lineno")
    if span_start is not None and span_end is not None:
        span_text = f"{span_start}-{span_end}"
    else:
        span_text = "UNSPECIFIED"

    lines = ["STRICT REQUIREMENTS:"]
    lines.append(f"- Work mode: {work_mode}")
    lines.append(f"- You MUST stay within file: {target_file}")
    if target_symbol:
        lines.append(f"- You MUST only modify: {target_symbol}")
        lines.append(f"- You MUST stay within lines: {span_text}")
        if target_symbol_id:
            lines.append(f"- You MUST match symbol_id: {target_symbol_id}")
        lines.append("- You MUST NOT modify any other functions, methods, classes, or file regions")
    elif work_mode in FILE_LEVEL_WORK_MODES:
        lines.append("- You are allowed to use a file-level anchor because this work mode may create or verify artifacts.")
        if creates_symbols:
            lines.append("- New symbols allowed by plan:")
            lines.extend(f"  - {symbol}" for symbol in creates_symbols)
        if wires_into_symbols:
            lines.append("- Existing symbols that may be wired into:")
            lines.extend(f"  - {symbol}" for symbol in wires_into_symbols)
        if insertion_region:
            lines.append(f"- Preferred insertion region: {insertion_region}")
        lines.append("- Keep the patch localized and do not create unrelated capabilities.")
    else:
        lines.append("- You MUST stay inside the explicitly selected file-level region.")
    lines.append(f"- You MUST satisfy expected_operation: {expected_operation}")
    if completion_cues:
        lines.append("- You MUST include completion cues:")
        lines.extend(f"  - {cue}" for cue in completion_cues)
    else:
        lines.append("- You MUST include completion cues: none explicitly provided")
    lines.append("- If you cannot satisfy every strict requirement exactly, return STATUS: blocked")
    return "\n".join(lines)


def _context_budget_for_kind(prompt_kind):
    if prompt_kind == "revision":
        return REVISION_CONTEXT_BUDGET_CHARS
    if prompt_kind == "symbol_locked":
        return SYMBOL_LOCKED_CONTEXT_BUDGET_CHARS
    if prompt_kind == "block_rewrite":
        return BLOCK_REWRITE_CONTEXT_BUDGET_CHARS
    return DEFAULT_CONTEXT_BUDGET_CHARS


def _build_file_summary(target_file, full_file_text, selected_block=None, file_summary=None, max_symbols=12):
    lines = [f"FILE SUMMARY: {target_file}"]

    if selected_block:
        lines.append(
            f"Selected symbol: {selected_block.get('name')} ({selected_block.get('lineno')}-{selected_block.get('end_lineno')})"
        )

    file_summary = dict(file_summary or {})
    symbol_inventory = list(file_summary.get("symbol_inventory") or [])
    high_value_symbols = list(file_summary.get("high_value_symbols") or [])
    import_summary = list(file_summary.get("import_summary") or [])
    route_inventory = list(file_summary.get("route_branch_inventory") or [])

    if not symbol_inventory and full_file_text:
        from coder_context import extract_code_blocks

        try:
            blocks = extract_code_blocks(full_file_text, target_file=target_file)
        except Exception:
            blocks = []
        symbol_inventory = [
            {
                "type": block.get("type"),
                "symbol": block.get("name"),
                "lineno": block.get("lineno"),
                "end_lineno": block.get("end_lineno"),
            }
            for block in blocks[:max_symbols]
        ]

    if high_value_symbols:
        lines.append("High-value symbols:")
        for symbol in high_value_symbols[:8]:
            lines.append(
                f"- {symbol.get('type')} {symbol.get('symbol')} [{symbol.get('lineno')}-{symbol.get('end_lineno')}]"
            )

    if symbol_inventory:
        lines.append("File inventory:")
        for symbol in symbol_inventory[:max_symbols]:
            lines.append(
                f"- {symbol.get('type')} {symbol.get('symbol')} [{symbol.get('lineno')}-{symbol.get('end_lineno')}]"
            )
    else:
        lines.append("No symbol inventory available.")

    if import_summary:
        lines.append("Imports: " + ", ".join(import_summary[:10]))

    if route_inventory:
        lines.append("Routes: " + ", ".join(route_inventory[:10]))

    return "\n".join(lines)


def _hard_trim_text(text, budget_chars):
    if len(text) <= budget_chars:
        return text

    if budget_chars <= 80:
        return text[:budget_chars]

    head = max(0, budget_chars - 48)
    return f"{text[:head].rstrip()}\n...\n# context trimmed to budget\n"


def _is_large_file(file_summary, full_file_text):
    summary = dict(file_summary or {})
    char_count = int(summary.get("char_count") or len(full_file_text or ""))
    symbol_count = int(summary.get("symbol_count") or 0)
    return char_count >= LARGE_FILE_CHAR_THRESHOLD or symbol_count >= LARGE_FILE_SYMBOL_THRESHOLD


def _is_route_anchor(anchor_text):
    lowered = (anchor_text or "").lower()
    return 'route ==' in lowered or 'elif route ==' in lowered or 'if route ==' in lowered


def _task_is_file_head_compatible(task):
    note = str((task or {}).get("note") or "").lower()
    tokens = (
        "top of file",
        "module docstring",
        "module-level",
        "module level",
        "imports",
        "file header",
    )
    return any(token in note for token in tokens)


def _task_has_explicit_symbol(task):
    task = task or {}
    metadata = task.get("metadata") or {}
    return bool(task.get("target_symbol") or metadata.get("target_symbol"))


def _task_allows_file_level_context(task):
    task = task or {}
    metadata = task.get("metadata") or {}
    mode = normalize_work_mode(
        task.get("work_mode") or task.get("task_kind") or metadata.get("work_mode") or metadata.get("task_kind"),
        task_type=task.get("task_type") or metadata.get("task_type"),
        text=task.get("note") or task.get("description") or "",
    )
    return mode in FILE_LEVEL_WORK_MODES


def _build_neighbor_text(context):
    selected_block = context.get("selected_block") or {}
    neighbor_blocks = list(context.get("neighbor_blocks") or [])
    if not neighbor_blocks:
        if selected_block.get("text"):
            return str(selected_block.get("text")).strip()
        return ""
    chunks = []
    for block in neighbor_blocks:
        block_text = str((block or {}).get("text") or "").strip()
        if block_text:
            chunks.append(block_text)
    return "\n\n".join(chunks).strip()


def _build_selected_block_summary(selected_block):
    if not selected_block:
        return ""
    return "\n".join([
        "SELECTED BLOCK SUMMARY:",
        f"- name: {selected_block.get('name')}",
        f"- type: {selected_block.get('type')}",
        f"- lines: {selected_block.get('lineno')}-{selected_block.get('end_lineno')}",
    ])


def prepare_context_for_prompt(
    *,
    target_file,
    context,
    full_file_text,
    related_context_text="",
    prompt_kind="default",
    task=None,
    plan=None,
    file_summary=None,
):
    context = dict(context or {})
    selected_block = context.get("selected_block") or {}
    base_context_text = str(context.get("context_text") or full_file_text or "")
    related_context_text = str(related_context_text or "")
    budget_chars = _context_budget_for_kind(prompt_kind)
    file_summary = dict(file_summary or {})
    large_file = _is_large_file(file_summary, full_file_text)

    raw_context_text = base_context_text
    if related_context_text:
        raw_context_text = f"{base_context_text}\n{related_context_text}".strip()

    metadata = {
        "selected_mode": context.get("mode"),
        "raw_context_length": len(raw_context_text),
        "trimmed_context_length": len(raw_context_text),
        "trimmed": False,
        "summary_used": False,
        "full_file_omitted": True,
        "budget_chars": budget_chars,
        "budget_decision": "full_context_used",
        "dropped_related_context": False,
        "dropped_helper_blocks": False,
        "dropped_import_blocks": False,
        "large_file_policy_applied": large_file,
        "under_anchored_after_trim": False,
        "context_priority": list(context.get("context_priority") or []),
        "anchoring_confidence": context.get("anchoring_confidence"),
    }

    if target_file == "main.py":
        if context.get("mode") == "file_head_fallback":
            metadata["under_anchored_after_trim"] = True
            metadata["budget_decision"] = "under_anchored_after_trim"
        elif context.get("mode") == "anchor_window" and not _is_route_anchor(context.get("anchor_text")):
            metadata["under_anchored_after_trim"] = True
            metadata["budget_decision"] = "under_anchored_after_trim"
        elif context.get("mode") in {"block_window", "line_window"} and not _task_has_explicit_symbol(task):
            metadata["under_anchored_after_trim"] = True
            metadata["budget_decision"] = "under_anchored_after_trim"

    if (
        context.get("mode") == "file_head_fallback"
        and not _task_is_file_head_compatible(task)
        and not _task_allows_file_level_context(task)
    ):
        metadata["under_anchored_after_trim"] = True
        metadata["budget_decision"] = "under_anchored_after_trim"

    if len(raw_context_text) <= budget_chars and not metadata["under_anchored_after_trim"]:
        return raw_context_text, metadata

    prompt_text = base_context_text
    metadata["trimmed"] = True
    metadata["budget_decision"] = "trimmed"
    if related_context_text:
        metadata["dropped_related_context"] = True

    if len(prompt_text) <= budget_chars and not metadata["under_anchored_after_trim"]:
        metadata["trimmed_context_length"] = len(prompt_text)
        metadata["budget_decision"] = "trimmed_related_context"
        return prompt_text, metadata

    reduced_context_text = _build_neighbor_text(context)
    if reduced_context_text:
        dropped_helper = bool(context.get("helper_blocks"))
        dropped_imports = bool(context.get("import_blocks"))
        prompt_text = reduced_context_text
        metadata["dropped_helper_blocks"] = dropped_helper
        metadata["dropped_import_blocks"] = dropped_imports
        if len(prompt_text) <= budget_chars and not metadata["under_anchored_after_trim"]:
            metadata["trimmed_context_length"] = len(prompt_text)
            metadata["budget_decision"] = "trimmed_context_components"
            return prompt_text, metadata

    selected_block_text = str(selected_block.get("text") or "").strip()
    if selected_block_text and not metadata["under_anchored_after_trim"]:
        block_fits = len(selected_block_text) <= budget_chars
        # For exact_symbol_block mode the selected block IS the minimum viable
        # context — a summary cannot substitute. Serve it up to 20k chars
        # (≈500 lines) regardless of the normal budget ceiling.
        exact_symbol_override = (
            context.get("mode") == "exact_symbol_block"
            and len(selected_block_text) <= 20000
        )
        if block_fits or exact_symbol_override:
            metadata["trimmed_context_length"] = len(selected_block_text)
            metadata["budget_decision"] = "trimmed_to_selected_block"
            return selected_block_text, metadata

    summary_text = _build_file_summary(
        target_file,
        full_file_text,
        selected_block=selected_block,
        file_summary=file_summary,
    )
    block_summary = _build_selected_block_summary(selected_block)
    if selected_block_text:
        combined_summary = f"{block_summary}\n\n{summary_text}".strip()
        if len(combined_summary) <= budget_chars:
            metadata["trimmed_context_length"] = len(combined_summary)
            metadata["summary_used"] = True
            metadata["budget_decision"] = "summary_used"
            if not metadata["under_anchored_after_trim"]:
                return combined_summary, metadata

    summary_only = _hard_trim_text(summary_text, budget_chars)
    metadata["trimmed_context_length"] = len(summary_only)
    metadata["summary_used"] = True
    if metadata["under_anchored_after_trim"]:
        metadata["budget_decision"] = "under_anchored_after_trim"
    else:
        metadata["budget_decision"] = "summary_used"
    return summary_only, metadata


def prepare_block_rewrite_input(*, target_file, block, file_summary=None):
    block = dict(block or {})
    block_text = str(block.get("text") or "")
    budget_chars = _context_budget_for_kind("block_rewrite")
    metadata = {
        "budget_chars": budget_chars,
        "trimmed": False,
        "summary_used": False,
        "budget_decision": "full_context_used",
        "under_anchored_after_trim": False,
        "large_file_policy_applied": _is_large_file(file_summary or {}, block_text),
    }

    if len(block_text) <= budget_chars:
        return block_text, metadata

    summary_text = "\n\n".join([
        _build_selected_block_summary(block),
        _build_file_summary(target_file, "", selected_block=block, file_summary=file_summary),
    ]).strip()
    summary_text = _hard_trim_text(summary_text, budget_chars)
    metadata["trimmed"] = True
    metadata["summary_used"] = True
    metadata["budget_decision"] = "block_summary_used"
    return summary_text, metadata


def build_prompt(task, plan, target_file, file_text, lesson_text=""):
    constraints = derive_patch_constraints(task, plan, target_file)
    constraint_text = format_patch_constraints(constraints)
    preflight_intent = build_preflight_intent(task, target_file)
    pilot_brief = format_pilot_brief(task)

    return CODER_PROMPT_TEMPLATE.format(
        task_id=task["id"],
        task_note=task["note"],
        pilot_brief=pilot_brief,
        pilot_guardrails=_get_pilot_guardrail_text(task),
        plan_goal=get_plan_goal_text(plan),
        plan_steps=get_plan_task_lines(plan),
        plan_dependencies=plan.get("dependencies", []),
        plan_risks=plan.get("risks", []),
        plan_next_action=plan.get("next_action", ""),
        plan_status=plan.get("status", ""),
        target_file=target_file,
        file_text=file_text,
        lesson_text=lesson_text,
        preflight_intent=preflight_intent,
        patch_constraints=constraint_text,
    )


def build_revision_prompt(task, plan, target_file, file_text, previous_patch, reflection, lesson_text=""):
    trimmed_previous_patch = previous_patch[:1500] if previous_patch else ""
    lesson_text = lesson_text or "No relevant recent failure lessons."
    constraints = derive_patch_constraints(task, plan, target_file)
    constraint_text = format_patch_constraints(constraints)
    preflight_intent = build_preflight_intent(task, target_file)
    pilot_brief = format_pilot_brief(task)

    return CODER_REVISION_PROMPT_TEMPLATE.format(
        task_id=task["id"],
        task_note=task["note"],
        pilot_brief=pilot_brief,
        pilot_guardrails=_get_pilot_guardrail_text(task),
        plan_goal=get_plan_goal_text(plan),
        plan_steps=get_plan_task_lines(plan),
        plan_dependencies=plan.get("dependencies", []),
        plan_risks=plan.get("risks", []),
        plan_next_action=plan.get("next_action", ""),
        plan_status=plan.get("status", ""),
        target_file=target_file,
        file_text=file_text,
        previous_patch_excerpt=trimmed_previous_patch,
        reflection=reflection,
        lesson_text=lesson_text,
        preflight_intent=preflight_intent,
        patch_constraints=constraint_text,
    )


def build_block_rewrite_prompt(task, plan, target_file, block, lesson_text=""):
    return BLOCK_REWRITE_PROMPT_TEMPLATE.format(
        task_id=task["id"],
        task_note=task["note"],
        pilot_brief=format_pilot_brief(task),
        pilot_guardrails=_get_pilot_guardrail_text(task),
        plan_goal=get_plan_goal_text(plan),
        plan_steps=get_plan_task_lines(plan),
        plan_dependencies=plan.get("dependencies", []),
        plan_risks=plan.get("risks", []),
        plan_next_action=plan.get("next_action", ""),
        plan_status=plan.get("status", ""),
        target_file=target_file,
        lesson_text=lesson_text or "No relevant recent failure lessons.",
        block_name=block["name"],
        block_text=block["text"],
    )


def build_symbol_locked_prompt(task, target_file, file_text, lesson_text=""):
    task_metadata = task.get("metadata") or {}
    target_symbol = task.get("target_symbol") or task_metadata.get("target_symbol") or ""
    preflight_intent = build_preflight_intent(task, target_file)

    return SYMBOL_LOCKED_PATCH_PROMPT_TEMPLATE.format(
        task_id=task["id"],
        task_note=task["note"],
        pilot_brief=format_pilot_brief(task),
        pilot_guardrails=_get_pilot_guardrail_text(task),
        target_file=target_file,
        target_symbol=target_symbol,
        file_text=file_text,
        lesson_text=lesson_text or "No relevant recent failure lessons.",
        preflight_intent=preflight_intent,
    )
