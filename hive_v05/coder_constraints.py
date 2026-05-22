from work_ontology import FILE_LEVEL_WORK_MODES, normalize_work_mode


def derive_patch_constraints(task, plan, target_file):
    note = (task.get("note") or "").lower()
    goal = str(plan.get("goal", "")).lower()
    next_action = (plan.get("next_action") or "").lower()
    metadata = task.get("metadata") or {}
    work_mode = normalize_work_mode(
        task.get("work_mode") or task.get("task_kind") or metadata.get("work_mode") or metadata.get("task_kind") or plan.get("work_mode") or plan.get("task_kind"),
        task_type=task.get("task_type") or metadata.get("task_type") or plan.get("task_type"),
        text=f"{note} {goal} {next_action}",
    )

    combined = f"{note} {goal} {next_action}"

    constraints = {
        "target_file": target_file,
        "max_files": 1,
        "max_new_methods": 1,
        "max_changed_regions": 1,
        "preferred_edit_style": "modify_existing_line",
        "allow_new_method": False,
        "allow_method_removal": False,
        "allow_class_scope_statements": False,
        "require_anchor_context": True,
        "notes": [],
    }

    if work_mode in FILE_LEVEL_WORK_MODES:
        constraints["preferred_edit_style"] = "file_level_localized"
        constraints["require_anchor_context"] = True
        constraints["notes"].append(
            f"Work mode {work_mode}: a file-level anchor is valid when the task creates, verifies, documents, observes, or configures an artifact."
        )

    if work_mode == "create":
        constraints["preferred_edit_style"] = "add_capability"
        constraints["allow_new_method"] = True
        constraints["max_new_methods"] = 1
        constraints["max_changed_regions"] = 2
        constraints["notes"].append(
            "Create-mode task: new symbols are allowed only when declared by creates_symbols or clearly required by the capability."
        )

    architectural_tokens = [
        "planner",
        "coder",
        "executor",
        "router",
        "reflector",
        "compatibility",
        "schema",
        "decomposition",
        "grouped",
        "normalization",
        "validation",
        "routing",
        "planner behavior",
        "one-file-first",
        "child task",
        "ordered child tasks",
    ]

    is_architectural = any(token in combined for token in architectural_tokens)

    if (
        not is_architectural
        and any(token in combined for token in ["add helper", "new helper", "extract helper"])
    ):
        constraints["preferred_edit_style"] = "add_helper"
        constraints["allow_new_method"] = True
        constraints["notes"].append(
            "Allow one new helper method if modification of existing code is not sufficient."
        )

    if any(token in combined for token in ["guard", "check", "lookup", "safe access", "null check"]):
        constraints["preferred_edit_style"] = "modify_existing_line"
        constraints["allow_new_method"] = False
        constraints["notes"].append("Prefer a local line edit over adding a new method.")

    if any(token in combined for token in ["refactor", "restructure", "rewrite"]):
        constraints["max_changed_regions"] = 2
        constraints["notes"].append("Task may require a slightly broader edit, but keep scope minimal.")

    if is_architectural:
        constraints["preferred_edit_style"] = "modify_existing_line"
        constraints["allow_new_method"] = False
        constraints["max_new_methods"] = 0
        constraints["max_changed_regions"] = 1
        constraints["notes"].append(
            "Architectural task detected: prefer modifying existing lines and shared flow."
        )
        constraints["notes"].append(
            "Do not add a new method unless absolutely required by the existing file structure."
        )
        constraints["notes"].append(
            "Prefer replacing or extending existing conditional, parsing, normalization, or validation logic over inserting a new def."
        )
        constraints["notes"].append(
            "Do not insert logic near return boundaries or inside a live method body."
        )

    if target_file in {"executor.py", "coder.py", "router.py", "reflector.py", "planner.py", "main.py"}:
        constraints["notes"].append("Preserve architecture and avoid introducing new subsystems.")

    return constraints


def format_patch_constraints(constraints):
    notes = constraints.get("notes", [])

    lines = [
        "PATCH CONSTRAINTS:",
        f"- target_file: {constraints['target_file']}",
        f"- max_files: {constraints['max_files']}",
        f"- max_new_methods: {constraints['max_new_methods']}",
        f"- max_changed_regions: {constraints['max_changed_regions']}",
        f"- preferred_edit_style: {constraints['preferred_edit_style']}",
        f"- allow_new_method: {constraints['allow_new_method']}",
        f"- allow_method_removal: {constraints['allow_method_removal']}",
        f"- allow_class_scope_statements: {constraints['allow_class_scope_statements']}",
        f"- require_anchor_context: {constraints['require_anchor_context']}",
    ]

    if notes:
        lines.append("- notes:")
        for note in notes:
            lines.append(f"  - {note}")

    return "\\n".join(lines)
