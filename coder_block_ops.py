from coder_constraints import derive_patch_constraints
from coder_context import select_target_block as select_context_target_block
from coder_prompting import get_plan_goal_text


def extract_method_blocks(file_text):
    lines = file_text.splitlines()
    blocks = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if stripped.startswith("def ") and indent == 4:
            name = stripped.split("def ", 1)[1].split("(", 1)[0].strip()
            start = i
            i += 1

            while i < len(lines):
                next_line = lines[i]
                next_stripped = next_line.lstrip()

                if not next_stripped:
                    i += 1
                    continue

                next_indent = len(next_line) - len(next_stripped)
                if next_stripped.startswith("def ") and next_indent == 4:
                    break

                i += 1

            end = i
            block_text = "\n".join(lines[start:end])
            blocks.append({
                "name": name,
                "start": start,
                "end": end,
                "text": block_text,
            })
            continue

        i += 1

    return blocks





def should_use_block_rewrite(task, plan, target_file):
    constraints = derive_patch_constraints(task, plan, target_file)
    if constraints.get("preferred_edit_style") != "modify_existing_line":
        return False

    task = task or {}
    metadata = task.get("metadata") or {}
    expected_operation = (
        task.get("expected_operation")
        or metadata.get("expected_operation")
        or "modify_logic"
    )
    change_intent = (
        task.get("change_intent")
        or metadata.get("change_intent")
        or "modify_existing_logic"
    )
    completion_cues = [
        str(cue).strip()
        for cue in (task.get("completion_cues") or metadata.get("completion_cues") or [])
        if str(cue).strip()
    ]
    combined = " ".join(
        part for part in [
            str(task.get("note") or ""),
            str((plan or {}).get("goal") or ""),
            str((plan or {}).get("next_action") or ""),
        ] if part
    ).lower()

    broad_operations = {
        "reorder_logic",
        "refactor_block",
        "update_state_flow",
        "update_contract",
    }
    broad_tokens = (
        "rewrite the method",
        "rewrite method",
        "rewrite block",
        "refactor block",
        "reorder logic",
        "state flow",
        "update contract",
    )
    narrow_tokens = (
        "instead of",
        "default value",
        "empty string",
        "or none",
        "guard",
        "safe access",
        "safely handle missing",
        "before lowercasing",
        "before merging",
    )

    if completion_cues:
        return False

    if expected_operation not in broad_operations:
        return False

    if change_intent in {"modify_existing_logic", "tighten_validation"} and any(token in combined for token in narrow_tokens):
        return False

    architectural_files = {"planner.py", "coder.py", "router.py", "reflector.py", "main.py", "executor.py"}
    if target_file not in architectural_files:
        return False

    return any(token in combined for token in broad_tokens)

def _find_shared_block_edges(original_lines, rewritten_lines):
    prefix_len = 0
    max_prefix = min(len(original_lines), len(rewritten_lines))
    while prefix_len < max_prefix and original_lines[prefix_len] == rewritten_lines[prefix_len]:
        prefix_len += 1

    suffix_len = 0
    max_suffix = min(len(original_lines) - prefix_len, len(rewritten_lines) - prefix_len)
    while (
        suffix_len < max_suffix
        and original_lines[len(original_lines) - 1 - suffix_len]
        == rewritten_lines[len(rewritten_lines) - 1 - suffix_len]
    ):
        suffix_len += 1

    return prefix_len, suffix_len


def _count_nonempty(lines):
    return sum(1 for line in lines if line.strip())


def validate_block_rewrite_minimality(original_block_text, rewritten_block_text, expected_operation=None):
    original_lines = original_block_text.splitlines()
    rewritten_lines = rewritten_block_text.splitlines()

    if len(original_lines) < 2 or len(rewritten_lines) < 2:
        raise ValueError("Block rewrite is too small to validate safely.")

    original_body = original_lines[1:]
    rewritten_body = rewritten_lines[1:]
    prefix_len, suffix_len = _find_shared_block_edges(original_body, rewritten_body)

    original_changed = original_body[prefix_len:len(original_body) - suffix_len if suffix_len else len(original_body)]
    rewritten_changed = rewritten_body[prefix_len:len(rewritten_body) - suffix_len if suffix_len else len(rewritten_body)]

    original_nonempty = _count_nonempty(original_body)
    changed_nonempty = max(_count_nonempty(original_changed), _count_nonempty(rewritten_changed))

    if changed_nonempty == 0:
        raise ValueError("Block rewrite produced no meaningful in-method change.")

    if original_nonempty >= 5 and prefix_len == 0 and suffix_len == 0:
        raise ValueError(
            "Block rewrite replaced the entire method body. Preserve surrounding in-method context and edit a narrower region."
        )

    if original_nonempty >= 8:
        changed_ratio = changed_nonempty / max(original_nonempty, 1)
        broad_operations = {"refactor_block", "reorder_logic", "update_state_flow", "update_contract"}
        ratio_limit = 0.85 if expected_operation in broad_operations else 0.65
        if changed_ratio > ratio_limit:
            raise ValueError(
                "Block rewrite is too broad for the selected method. Preserve more of the existing method body."
            )

    if expected_operation not in {"refactor_block", "reorder_logic"} and changed_nonempty > 40:
        raise ValueError(
            "Block rewrite changed too many lines for a narrow in-place edit."
        )

    return {
        "prefix_len": prefix_len,
        "suffix_len": suffix_len,
        "changed_nonempty": changed_nonempty,
        "original_nonempty": original_nonempty,
    }


def rewrite_block_to_diff(original_file_text, block, rewritten_block_text, target_file):
    old_lines = original_file_text.splitlines()
    original_block_lines = old_lines[block["start"]:block["end"]]
    rewritten_lines = rewritten_block_text.splitlines()

    prefix_len, suffix_len = _find_shared_block_edges(
        original_block_lines,
        rewritten_lines,
    )

    old_middle = original_block_lines[prefix_len:len(original_block_lines) - suffix_len if suffix_len else len(original_block_lines)]
    new_middle = rewritten_lines[prefix_len:len(rewritten_lines) - suffix_len if suffix_len else len(rewritten_lines)]

    if not old_middle and not new_middle:
        raise ValueError("Block rewrite produced no bounded diff content.")

    before_anchor = old_lines[block["start"] - 1] if block["start"] > 0 else None
    after_anchor = old_lines[block["end"]] if block["end"] < len(old_lines) else None

    hunk_lines = [f"--- {target_file}", f"+++ {target_file}"]

    old_count = len(original_block_lines)
    new_count = len(rewritten_lines)
    old_start = block["start"] + 1
    new_start = block["start"] + 1

    if before_anchor is not None:
        old_start -= 1
        new_start -= 1
        old_count += 1
        new_count += 1

    if after_anchor is not None:
        old_count += 1
        new_count += 1

    hunk_lines.append(f"@@ -{old_start},{old_count} +{new_start},{new_count} @@")

    if before_anchor is not None:
        hunk_lines.append(f" {before_anchor}")

    for line in original_block_lines[:prefix_len]:
        hunk_lines.append(f" {line}")

    for line in old_middle:
        hunk_lines.append(f"-{line}")

    for line in new_middle:
        hunk_lines.append(f"+{line}")

    if suffix_len:
        for line in original_block_lines[len(original_block_lines) - suffix_len:]:
            hunk_lines.append(f" {line}")

    if after_anchor is not None:
        hunk_lines.append(f" {after_anchor}")

    return "\n".join(hunk_lines).strip()
