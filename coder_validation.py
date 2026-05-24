import re

KNOWN_FILES = {
    "main.py",
    "router.py",
    "interface.py",
    "hive_gui.py",
    "hive_cockpit.py",
    "planner.py",
    "planner_prompt.py",
    "work_ontology.py",
    "coder.py",
    "coder_prompt.py",
    "builder.py",
    "executor.py",
    "reflector.py",
    "reflector_prompt.py",
    "HiveMemoryAgent.py",
    "HiveLessonMemory.py",
    "HiveStateManager.py",
    "HiveAgent.py",
    "HiveBridge.py",
    "hive_llm.py",
    "coder_context.py",
    "coder_validation.py",
    "repo_map.py",
    "coder_block_ops.py",
    "coder_constraints.py",
    "coder_failures.py",
    "coder_prompting.py",

}


def has_unfinished_block_before_added_def(diff_lines):
    bracket_balance = 0

    for i, line in enumerate(diff_lines):
        if not line:
            continue

        content = line[1:] if line[0] in "+- " else line
        stripped = content.rstrip()

        if line.startswith("+") and stripped.lstrip().startswith("def "):
            if bracket_balance > 0:
                return True

            j = i - 1
            while j >= 0:
                prev_line = diff_lines[j]

                if not prev_line:
                    j -= 1
                    continue

                prev_content = prev_line[1:] if prev_line[0] in "+- " else prev_line
                prev_stripped = prev_content.rstrip()

                if not prev_stripped.strip():
                    j -= 1
                    continue

                bad_endings = ("(", "[", "{", ",", "\\")
                if prev_stripped.strip().endswith(bad_endings):
                    return True

                if prev_stripped.strip().startswith(("if ", "for ", "while ")) and not prev_stripped.strip().endswith(":"):
                    return True

                break

        bracket_balance += stripped.count("(") - stripped.count(")")
        bracket_balance += stripped.count("[") - stripped.count("]")
        bracket_balance += stripped.count("{") - stripped.count("}")

    return False


def has_bad_method_indent(diff_lines):
    for line in diff_lines:
        if not line.startswith("+"):
            continue

        content = line[1:]
        stripped = content.lstrip()

        if not stripped.startswith("def "):
            continue

        indent = len(content) - len(stripped)
        # Nested functions inside method bodies have indent > 4 — allow them.
        if indent > 4:
            continue
        if indent != 4:
            return True

    return False


def preflight_patch_contract(raw_response, constraints=None):
    text = (raw_response or "").strip()
    if not text:
        raise ValueError("Empty model response.")

    patch_marker_count = text.count("PATCH:")
    if patch_marker_count == 0:
        raise ValueError("No PATCH: section found in model response.")
    if patch_marker_count > 1:
        raise ValueError("Model response contains multiple PATCH: sections.")

    patch_body = text.partition("PATCH:")[2].strip()
    if not patch_body:
        raise ValueError("PATCH section is empty.")

    if "--- " not in patch_body or "+++ " not in patch_body:
        raise ValueError("Patch is missing diff file headers.")

    patch_lines = patch_body.splitlines()
    valid_prefixes = ("---", "+++", "@@", "+", "-", " ", "\\")

    for line in patch_lines:
        if not line:
            continue
        if not line.startswith(valid_prefixes):
            raise ValueError(f"Patch contains non-diff commentary: {line[:80]}")

    nonempty_diff_lines = [line for line in patch_lines if line.strip()]
    if len(nonempty_diff_lines) > 80:
        raise ValueError("Patch is too large for first-pass review.")

    target_headers = [line for line in patch_lines if line.startswith("+++ ")]
    if len(target_headers) != 1:
        raise ValueError("Patch must target exactly one file.")

    added_method_names = []
    for line in patch_lines:
        if not line.startswith("+"):
            continue
        content = line[1:]  # strip leading +
        if not content.lstrip().startswith("def "):
            continue
        # Only count class-level methods (4 spaces indent), not nested functions (8+ spaces)
        indent = len(content) - len(content.lstrip())
        if indent <= 4:
            name = content.split("def ", 1)[1].split("(", 1)[0].strip()
            added_method_names.append(name)

    if len(set(added_method_names)) != len(added_method_names):
        raise ValueError("Patch adds duplicate method definitions.")

    if len(added_method_names) > 1:
        raise ValueError("Patch is too broad: more than one new method added.")

    if constraints is not None:
        allow_new_method = constraints.get("allow_new_method", True)
        max_new_methods = constraints.get("max_new_methods", 1)

        if not allow_new_method and added_method_names:
            raise ValueError("Patch violates constraints: new methods are not allowed for this task.")

        if len(added_method_names) > max_new_methods:
            raise ValueError(f"Patch violates constraints: max_new_methods={max_new_methods}.")

    return True

def has_meaningful_change(diff_lines):
    meaningful = []

    for line in diff_lines:
        if not (line.startswith("+") or line.startswith("-")):
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue

        content = line[1:].strip()

        if not content:
            continue

        if content.startswith("#"):
            continue

        if content in {"(", ")", ",", ":", "]", "[", "{", "}"}:
            continue

        meaningful.append(content)

    return len(meaningful) > 0


def task_allows_comment_only_change(task):
    if not isinstance(task, dict):
        return False

    task_note = (task.get("note") or "").strip().lower()
    task_type = (task.get("task_type") or "").strip().lower()
    metadata = task.get("metadata") or {}
    expected_operation = (task.get("expected_operation") or metadata.get("expected_operation") or "").strip().lower()

    if task_type == "docs":
        return True

    if expected_operation in {"insert_comment", "insert_docstring", "update_help_text"}:
        return True

    comment_tokens = (
        "comment",
        "docstring",
        "explain",
        "explanation",
        "clarify",
        "document",
        "documentation",
        "annotate",
        "annotation",
    )
    return any(token in task_note for token in comment_tokens)

def extract_simple_replace_intent(task_note):
    text = (task_note or "").strip()

    patterns = [
        r"replace\s+`([^`]+)`\s+with\s+`([^`]+)`",
        r'replace\s+"([^"]+)"\s+with\s+"([^"]+)"',
        r"replace\s+'([^']+)'\s+with\s+'([^']+)'",
        r"replace\s+([A-Za-z_][A-Za-z0-9_\.]*)\s+with\s+([A-Za-z_][A-Za-z0-9_\.]*)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            old_token = match.group(1).strip()
            new_token = match.group(2).strip()
            if old_token and new_token and old_token != new_token:
                return old_token, new_token

    return None


def patch_satisfies_simple_replace_intent(diff_lines, old_token, new_token):
    removed_mentions_old = False
    added_mentions_new = False

    for line in diff_lines:
        if line.startswith("---") or line.startswith("+++"):
            continue

        if line.startswith("-") and old_token in line[1:]:
            removed_mentions_old = True

        if line.startswith("+") and new_token in line[1:]:
            added_mentions_new = True

    return removed_mentions_old and added_mentions_new


def get_task_change_intent(task):
    return (
        task.get("change_intent")
        or ((task.get("metadata") or {}).get("change_intent"))
        or "modify_existing_logic"
    )


def get_task_expected_operation(task):
    return (
        task.get("expected_operation")
        or ((task.get("metadata") or {}).get("expected_operation"))
    )


def get_task_type(task):
    return (
        task.get("task_type")
        or ((task.get("metadata") or {}).get("task_type"))
        or ""
    )


def get_task_completion_cues(task):
    cues = (
        task.get("completion_cues")
        or ((task.get("metadata") or {}).get("completion_cues"))
        or []
    )

    if not isinstance(cues, list):
        return []

    return [cue.strip() for cue in cues if isinstance(cue, str) and cue.strip()]


def get_patch_change_summary(patch_text):
    diff_lines = patch_text.splitlines()
    meaningful_added = []
    meaningful_removed = []
    context_lines = []
    added_defs = []
    removed_defs = []
    hunk_count = 0

    for line in diff_lines:
        if line.startswith("@@"):
            hunk_count += 1
            continue

        if line.startswith("+++ ") or line.startswith("--- "):
            continue

        if line.startswith(" "):
            context_lines.append(line[1:])
            continue

        if line.startswith("+"):
            content = line[1:]
            stripped = content.strip()
            if stripped:
                meaningful_added.append(content)
                if stripped.startswith("def "):
                    added_defs.append(stripped.split("def ", 1)[1].split("(", 1)[0].strip())
            continue

        if line.startswith("-"):
            content = line[1:]
            stripped = content.strip()
            if stripped:
                meaningful_removed.append(content)
                if stripped.startswith("def "):
                    removed_defs.append(stripped.split("def ", 1)[1].split("(", 1)[0].strip())

    return {
        "diff_lines": diff_lines,
        "meaningful_added": meaningful_added,
        "meaningful_removed": meaningful_removed,
        "context_lines": context_lines,
        "added_defs": added_defs,
        "removed_defs": removed_defs,
        "hunk_count": hunk_count,
        "changed_lines": meaningful_added + meaningful_removed,
    }


def extract_changed_def_names(patch_text):
    changed_defs = set()

    for line in patch_text.splitlines():
        if not line or line.startswith(("+++", "---", "@@")):
            continue
        if not line.startswith(("+", "-", " ")):
            continue

        content = line[1:] if line[0] in "+- " else line
        stripped = content.strip()
        if not stripped.startswith("def "):
            continue

        name = stripped.split("def ", 1)[1].split("(", 1)[0].strip()
        if name:
            changed_defs.add(name)

    return changed_defs


def _get_anchor_span(anchor):
    if not isinstance(anchor, dict):
        return None

    lineno = anchor.get("lineno")
    end_lineno = anchor.get("end_lineno")
    if lineno is None or end_lineno is None:
        return None

    return {
        "target_symbol_id": anchor.get("target_symbol_id"),
        "lineno": lineno,
        "end_lineno": end_lineno,
        "col_offset": anchor.get("col_offset"),
        "end_col_offset": anchor.get("end_col_offset"),
    }


def _validate_selected_block_against_anchor(selected_block, anchor, target_symbol):
    anchor_span = _get_anchor_span(anchor)
    target_symbol_id = (anchor or {}).get("target_symbol_id")

    if selected_block is None:
        if anchor_span or target_symbol_id or target_symbol:
            raise ValueError(
                f"symbol_anchor_drift: selected block missing for anchored symbol {target_symbol or target_symbol_id}."
            )
        return True

    if target_symbol and selected_block.get("name") != target_symbol:
        raise ValueError(
            f"symbol_anchor_drift: selected block expected {target_symbol}, got {selected_block.get('name')}."
        )

    if target_symbol_id and selected_block.get("symbol_id") != target_symbol_id:
        raise ValueError(
            f"symbol_anchor_drift: selected block symbol_id expected {target_symbol_id}, got {selected_block.get('symbol_id')}."
        )

    if not anchor_span:
        return True

    if selected_block.get("lineno") != anchor_span.get("lineno") or selected_block.get("end_lineno") != anchor_span.get("end_lineno"):
        raise ValueError(
            f"symbol_anchor_drift: selected block lines expected {anchor_span.get('lineno')}-{anchor_span.get('end_lineno')}, "
            f"got {selected_block.get('lineno')}-{selected_block.get('end_lineno')}."
        )

    if anchor_span.get("col_offset") is not None and selected_block.get("col_offset") != anchor_span.get("col_offset"):
        raise ValueError(
            f"symbol_anchor_drift: selected block col_offset expected {anchor_span.get('col_offset')}, got {selected_block.get('col_offset')}."
        )

    if anchor_span.get("end_col_offset") is not None and selected_block.get("end_col_offset") != anchor_span.get("end_col_offset"):
        raise ValueError(
            f"symbol_anchor_drift: selected block end_col_offset expected {anchor_span.get('end_col_offset')}, got {selected_block.get('end_col_offset')}."
        )

    return True


def validate_symbol_locked_patch(patch_data, task, selected_block=None):
    task_metadata = task.get("metadata") or {}
    target_symbol = task.get("target_symbol") or task_metadata.get("target_symbol")
    if not target_symbol:
        return True

    anchor = task_metadata.get("anchor") or {}
    target_file = (
        task.get("target_file")
        or task_metadata.get("target_file")
        or anchor.get("target_file")
    )
    target_symbol_id = (
        task.get("target_symbol_id")
        or task_metadata.get("target_symbol_id")
        or anchor.get("target_symbol_id")
    )
    context_target = patch_data.get("context_target")
    context_mode = patch_data.get("context_mode")
    context_symbol_id = patch_data.get("context_symbol_id")
    context_span = patch_data.get("context_span") or {}
    patch_text = patch_data.get("patch", "")
    changed_defs = extract_changed_def_names(patch_text)
    anchor_span = _get_anchor_span(anchor)

    if patch_data.get("target_file") != target_file:
        raise ValueError(
            f"symbol_anchor_drift: patch target file expected {target_file}, got {patch_data.get('target_file')}."
        )

    required_anchor_fields = {
        "target_file": target_file,
        "target_symbol": target_symbol,
        "target_symbol_id": target_symbol_id,
        "lineno": anchor_span.get("lineno") if anchor_span else None,
        "end_lineno": anchor_span.get("end_lineno") if anchor_span else None,
    }
    missing_anchor_fields = [name for name, value in required_anchor_fields.items() if value is None]
    if missing_anchor_fields:
        raise ValueError(
            "symbol_anchor_drift: anchored task is missing required anchor proof fields "
            f"{missing_anchor_fields} for {target_symbol}."
        )

    if context_mode != "exact_symbol_block":
        raise ValueError(
            f"symbol_anchor_drift: exact_symbol_block context required for anchored symbol {target_symbol}, got {context_mode}."
        )

    if context_target != target_symbol:
        raise ValueError(
            f"symbol_anchor_drift: exact symbol context expected {target_symbol}, got {context_target}."
        )

    _validate_selected_block_against_anchor(selected_block, anchor, target_symbol)

    if not context_symbol_id:
        raise ValueError(
            f"symbol_anchor_drift: patch context is missing symbol_id proof for {target_symbol}."
        )

    if context_symbol_id != target_symbol_id:
        raise ValueError(
            f"symbol_anchor_drift: patch context symbol_id expected {target_symbol_id}, got {context_symbol_id}."
        )

    if not context_span:
        raise ValueError(
            f"symbol_anchor_drift: patch context is missing span proof for {target_symbol}."
        )

    if (
        context_span.get("lineno") != anchor_span.get("lineno")
        or context_span.get("end_lineno") != anchor_span.get("end_lineno")
    ):
        raise ValueError(
            f"symbol_anchor_drift: exact context span expected {anchor_span.get('lineno')}-{anchor_span.get('end_lineno')}, "
            f"got {context_span.get('lineno')}-{context_span.get('end_lineno')}."
        )

    if anchor_span.get("col_offset") is not None and context_span.get("col_offset") != anchor_span.get("col_offset"):
        raise ValueError(
            f"symbol_anchor_drift: exact context col_offset expected {anchor_span.get('col_offset')}, got {context_span.get('col_offset')}."
        )

    if anchor_span.get("end_col_offset") is not None and context_span.get("end_col_offset") != anchor_span.get("end_col_offset"):
        raise ValueError(
            f"symbol_anchor_drift: exact context end_col_offset expected {anchor_span.get('end_col_offset')}, got {context_span.get('end_col_offset')}."
        )

    if changed_defs:
        if target_symbol not in changed_defs:
            raise ValueError(
                f"symbol_anchor_drift: patch does not modify requested symbol {target_symbol}."
            )

        unrelated_defs = sorted(name for name in changed_defs if name != target_symbol)
        if unrelated_defs:
            raise ValueError(
                f"symbol_anchor_drift: patch modifies unrelated symbols {unrelated_defs}; only {target_symbol} may change."
            )

    return True


def extract_simple_rename_intent(task_note):
    text = (task_note or "").strip()

    patterns = [
        r"rename\s+`([^`]+)`\s+to\s+`([^`]+)`",
        r'rename\s+"([^"]+)"\s+to\s+"([^"]+)"',
        r"rename\s+'([^']+)'\s+to\s+'([^']+)'",
        r"rename\s+([A-Za-z_][A-Za-z0-9_\.]*)\s+to\s+([A-Za-z_][A-Za-z0-9_\.]*)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            old_token = match.group(1).strip()
            new_token = match.group(2).strip()
            if old_token and new_token and old_token != new_token:
                return old_token, new_token

    return None


def extract_insert_after_anchor_intent(task_note):
    text = (task_note or "").strip()

    patterns = [
        r"(?:insert|add)\s+`([^`]+)`\s+(?:immediately\s+)?after\s+`([^`]+)`",
        r'(?:insert|add)\s+"([^"]+)"\s+(?:immediately\s+)?after\s+"([^"]+)"',
        r"(?:insert|add)\s+'([^']+)'\s+(?:immediately\s+)?after\s+'([^']+)'",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            inserted = match.group(1).strip()
            anchor = match.group(2).strip()
            if inserted and anchor:
                return inserted, anchor

    anchor_only_patterns = [
        r"(?:insert|add).+?(?:immediately\s+)?after\s+`([^`]+)`",
        r'(?:insert|add).+?(?:immediately\s+)?after\s+"([^"]+)"',
        r"(?:insert|add).+?(?:immediately\s+)?after\s+'([^']+)'",
    ]

    for pattern in anchor_only_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return None, match.group(1).strip()

    return None


def extract_quoted_task_tokens(task_note):
    text = task_note or ""
    tokens = []
    patterns = [
        r"`([^`]+)`",
        r'"([^"]+)"',
        r"'([^']+)'",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = match.group(1).strip()
            if value and value not in tokens:
                tokens.append(value)

    return tokens


def extract_meaningful_keywords(text):
    stop_words = {
        "the", "and", "for", "with", "from", "into", "after", "before", "line",
        "lines", "file", "task", "patch", "code", "change", "changes", "update",
        "modify", "existing", "logic", "intent", "match", "make", "ensure",
        "expand", "reject", "partial", "scope", "drift", "common", "pattern",
        "patterns", "replace", "rename", "insert", "add", "tighten", "validation",
        "prompt", "contract", "routing", "route", "state", "handling", "local",
        "block", "adjust", "single", "this", "that", "task", "note", "patches",
        "python", "file", "files", "method", "methods", "function", "functions",
    }

    keywords = set()
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", (text or "").lower()):
        if token in stop_words:
            continue
        if token.endswith(".py"):
            continue
        keywords.add(token)
        if "_" in token:
            for piece in token.split("_"):
                if len(piece) >= 3 and piece not in stop_words:
                    keywords.add(piece)

    return keywords


def validate_scope_alignment(summary, task_note, change_intent, explicit_tokens=None):
    explicit_tokens = [token for token in (explicit_tokens or []) if token]
    task_keywords = extract_meaningful_keywords(task_note)
    diff_keywords = extract_meaningful_keywords("\n".join(summary["changed_lines"]))
    overlap = task_keywords & diff_keywords

    if len(task_keywords) >= 2 and not overlap and not explicit_tokens:
        raise ValueError(
            f"scope_alignment_mismatch: Patch appears misaligned with task scope for change_intent={change_intent}: no meaningful keyword overlap with task note."
        )

    if explicit_tokens:
        unrelated_lines = []
        for line in summary["changed_lines"]:
            if any(token in line for token in explicit_tokens):
                continue
            unrelated_lines.append(line.strip())

        if len(unrelated_lines) > 3:
            raise ValueError(
                f"scope_alignment_mismatch: Patch appears broader than the explicit task intent; too many changed lines do not relate to {explicit_tokens}."
            )


def validate_structural_patch_shape(summary):
    executable_indents = set()

    for line in summary["diff_lines"]:
        if not (line.startswith("+") or line.startswith("-")):
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue

        content = line[1:]
        stripped = content.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue

        indent = len(content) - len(content.lstrip(" "))
        executable_indents.add(indent)

    if 0 in executable_indents and any(indent > 0 for indent in executable_indents):
        raise ValueError(
            "mixed_scope_patch: Patch mixes top-level and nested-scope executable lines in the same diff."
        )


def validate_replace_like_intent(summary, old_token, new_token):
    if not patch_satisfies_simple_replace_intent(summary["diff_lines"], old_token, new_token):
        raise ValueError(
            f"Patch does not satisfy explicit replace intent: expected replacement of {old_token} with {new_token}."
        )

    if any(old_token in line for line in summary["meaningful_added"]):
        raise ValueError(
            f"Patch appears partial or inconsistent: added lines still contain replaced token {old_token}."
        )

    if any(new_token in line for line in summary["meaningful_removed"]):
        raise ValueError(
            f"Patch appears partial or inconsistent: removed lines still contain replacement token {new_token}."
        )


def validate_insert_after_anchor_intent(summary, task_note):
    parsed = extract_insert_after_anchor_intent(task_note)
    inserted_token = None
    anchor_token = None

    if parsed:
        inserted_token, anchor_token = parsed

    if summary["meaningful_removed"]:
        raise ValueError("Patch violates insert_line_after_anchor intent: insertion task should not remove existing code.")

    if not summary["meaningful_added"]:
        raise ValueError("Patch violates insert_line_after_anchor intent: no inserted lines found.")

    if summary["added_defs"]:
        raise ValueError("Patch violates insert_line_after_anchor intent: unexpected new method definition.")

    if summary["hunk_count"] > 1:
        raise ValueError("Patch violates insert_line_after_anchor intent: edit spans multiple hunks and appears broader than a local insertion.")

    if anchor_token:
        searchable_lines = summary["context_lines"] + summary["changed_lines"]
        if not any(anchor_token in line for line in searchable_lines):
            raise ValueError(
                f"Patch violates insert_line_after_anchor intent: anchor {anchor_token!r} not present in patch context."
            )

    if inserted_token and not any(inserted_token in line for line in summary["meaningful_added"]):
        raise ValueError(
            f"Patch violates insert_line_after_anchor intent: expected inserted content {inserted_token!r} not found in added lines."
        )


def validate_tighten_validation_intent(summary):
    if summary["added_defs"]:
        raise ValueError("Patch violates tighten_validation intent: validation tightening should update existing logic, not add a new method.")

    if not summary["meaningful_added"]:
        raise ValueError("Patch violates tighten_validation intent: no new validation logic detected.")

    validation_signals = (
        "if ", "raise ", "return False", "ValueError", "TypeError",
        " is None", " not in ", ".get(", "invalid", "blocked", "reject"
    )

    if not any(any(signal in line for signal in validation_signals) for line in summary["meaningful_added"]):
        raise ValueError(
            "Patch violates tighten_validation intent: added lines do not look like guard or rejection logic."
        )

    if summary["hunk_count"] > 2:
        raise ValueError("Patch violates tighten_validation intent: patch is too broad for a localized validation change.")


def validate_update_prompt_contract_intent(summary, task_note):
    if summary["added_defs"]:
        raise ValueError("Patch violates update_prompt_contract intent: prompt contract updates should not add new methods.")

    contract_signals = (
        '"', "'", "PATCH:", "TARGET_FILE:", "CHANGE_TYPE:", "STATUS:",
        "RISK_LEVEL:", "REASON:", "json", "schema", "response", "prompt", "task_type"
    )
    changed_blob = "\n".join(summary["changed_lines"])
    quoted_tokens = extract_quoted_task_tokens(task_note)

    if not any(signal in changed_blob for signal in contract_signals):
        raise ValueError(
            "Patch violates update_prompt_contract intent: changed lines do not appear to edit prompt or response-contract content."
        )

    if quoted_tokens and not any(token in changed_blob for token in quoted_tokens):
        raise ValueError(
            "Patch appears scope-drifted for update_prompt_contract intent: quoted task tokens are absent from the diff."
        )

    if summary["hunk_count"] > 2:
        raise ValueError("Patch violates update_prompt_contract intent: patch is broader than a localized contract update.")


def validate_adjust_routing_order_intent(summary):
    if summary["added_defs"]:
        raise ValueError("Patch violates adjust_routing_order intent: routing order changes should modify existing flow, not add methods.")

    if not summary["meaningful_added"] or not summary["meaningful_removed"]:
        raise ValueError("Patch violates adjust_routing_order intent: expected reordered existing routing logic, not a one-sided edit.")

    routing_signals = ("route", "intent", "if ", "elif ", "return", "priority", "before", "after")
    changed_blob = "\n".join(summary["changed_lines"]).lower()
    if not any(signal in changed_blob for signal in routing_signals):
        raise ValueError(
            "Patch violates adjust_routing_order intent: changed lines do not look like routing or priority logic."
        )

    if summary["hunk_count"] > 2:
        raise ValueError("Patch violates adjust_routing_order intent: patch is too broad for a local routing-order change.")


def validate_update_state_handling_intent(summary):
    state_signals = (
        "state", "snapshot", "save", "load", "persist", "record",
        "restore", "backup", "memory", "metadata"
    )
    changed_blob = "\n".join(summary["changed_lines"]).lower()

    if not any(signal in changed_blob for signal in state_signals):
        raise ValueError(
            "Patch violates update_state_handling intent: changed lines do not appear to touch state or persistence behavior."
        )

    if summary["hunk_count"] > 2:
        raise ValueError("Patch violates update_state_handling intent: patch is too broad for a localized state-handling change.")


def validate_refactor_local_block_intent(summary):
    if not summary["meaningful_added"] or not summary["meaningful_removed"]:
        raise ValueError("Patch violates refactor_local_block intent: local refactor should rewrite an existing block, not only add or delete lines.")

    if summary["hunk_count"] > 2:
        raise ValueError("Patch violates refactor_local_block intent: patch spans too many regions for a local block refactor.")


def validate_insert_docstring_operation(summary):
    if summary["added_defs"]:
        raise ValueError("Patch violates expected_operation=insert_docstring: docstring insertion should not add a new method.")

    if not summary["meaningful_added"]:
        raise ValueError("Patch violates expected_operation=insert_docstring: no inserted docstring lines found.")

    changed_blob = "\n".join(summary["changed_lines"])
    if '"""' not in changed_blob and "'''" not in changed_blob:
        raise ValueError("Patch violates expected_operation=insert_docstring: changed lines do not look like a docstring insertion.")

    if summary["hunk_count"] > 2:
        raise ValueError("Patch violates expected_operation=insert_docstring: patch is broader than a localized docstring edit.")


def validate_insert_comment_operation(summary):
    if summary["added_defs"]:
        raise ValueError("Patch violates expected_operation=insert_comment: comment insertion should not add a new method.")

    changed_blob = "\n".join(summary["changed_lines"])
    if "#" not in changed_blob:
        raise ValueError("Patch violates expected_operation=insert_comment: changed lines do not look like a comment insertion.")

    non_comment_additions = [
        line for line in summary["meaningful_added"]
        if not line.lstrip().startswith("#")
    ]
    if non_comment_additions:
        raise ValueError("Patch violates expected_operation=insert_comment: patch adds non-comment code.")

    if summary["hunk_count"] > 2:
        raise ValueError("Patch violates expected_operation=insert_comment: patch is broader than a localized comment edit.")


def validate_update_help_text_operation(summary):
    if summary["added_defs"]:
        raise ValueError("Patch violates expected_operation=update_help_text: help-text updates should not add a new method.")

    if not summary["meaningful_added"] and not summary["meaningful_removed"]:
        raise ValueError("Patch violates expected_operation=update_help_text: no text changes found.")

    changed_blob = "\n".join(summary["changed_lines"]).lower()
    text_signals = (
        "help",
        "usage",
        "description",
        "error",
        "warning",
        '"',
        "'",
    )
    if not any(signal in changed_blob for signal in text_signals):
        raise ValueError("Patch violates expected_operation=update_help_text: changed lines do not look like help or user-facing text.")

    if summary["hunk_count"] > 2:
        raise ValueError("Patch violates expected_operation=update_help_text: patch is broader than a localized text update.")


def validate_expected_operation(summary, expected_operation, task_note):
    changed_blob = "\n".join(summary["changed_lines"])
    lowered_changed = changed_blob.lower()

    if expected_operation == "replace":
        replace_intent = extract_simple_replace_intent(task_note)
        if not replace_intent:
            raise ValueError("Task expected_operation=replace but the task note does not specify a concrete replacement.")
        validate_replace_like_intent(summary, replace_intent[0], replace_intent[1])
        return

    if expected_operation == "rename":
        rename_intent = extract_simple_rename_intent(task_note)
        if not rename_intent:
            raise ValueError("Task expected_operation=rename but the task note does not specify a concrete rename.")
        validate_replace_like_intent(summary, rename_intent[0], rename_intent[1])
        return

    if expected_operation == "insert_after_anchor":
        validate_insert_after_anchor_intent(summary, task_note)
        return

    if expected_operation == "insert_docstring":
        validate_insert_docstring_operation(summary)
        return

    if expected_operation == "insert_comment":
        validate_insert_comment_operation(summary)
        return

    if expected_operation == "update_help_text":
        validate_update_help_text_operation(summary)
        return

    if expected_operation == "tighten_guard":
        validate_tighten_validation_intent(summary)
        return

    if expected_operation == "update_contract":
        validate_update_prompt_contract_intent(summary, task_note)
        return

    if expected_operation == "reorder_logic":
        validate_adjust_routing_order_intent(summary)
        return

    if expected_operation == "update_state_flow":
        validate_update_state_handling_intent(summary)
        return

    if expected_operation == "refactor_block":
        validate_refactor_local_block_intent(summary)
        return

    if expected_operation == "modify_logic":
        if not summary["meaningful_added"] and not summary["meaningful_removed"]:
            raise ValueError("Patch violates expected_operation=modify_logic: no meaningful code changes found.")

        if summary["hunk_count"] > 2:
            raise ValueError("Patch violates expected_operation=modify_logic: patch is broader than a localized logic edit.")

        if not lowered_changed.strip():
            raise ValueError("Patch violates expected_operation=modify_logic: empty diff body.")


def evaluate_completion_cues(summary, completion_cues):
    result = {
        "provided_cues": completion_cues or [],
        "matched_cues": [],
        "missing_cues": [],
        "all_matched": True,
    }

    if not completion_cues:
        return result

    changed_blob = "\n".join(summary["changed_lines"])

    for cue in completion_cues:
        if cue in changed_blob:
            result["matched_cues"].append(cue)
        else:
            result["missing_cues"].append(cue)

    if result["missing_cues"]:
        result["all_matched"] = False

    return result


def get_completion_cue_policy(task):
    task_type = get_task_type(task).strip().lower()
    expected_operation = (get_task_expected_operation(task) or "").strip().lower()

    if expected_operation in {"replace", "rename", "update_help_text"}:
        return "exact_required"

    if task_type == "docs":
        return "advisory"

    if expected_operation in {
        "modify_logic",
        "tighten_guard",
        "reorder_logic",
        "update_state_flow",
        "refactor_block",
        "insert_after_anchor",
        "insert_comment",
        "insert_docstring",
        "update_contract",
    }:
        return "advisory"

    return "advisory"


def apply_completion_cue_policy(task, cue_result):
    policy = get_completion_cue_policy(task)

    if policy == "exact_required" and not cue_result["all_matched"]:
        raise ValueError(
            f"Patch missed required completion cues: {cue_result['missing_cues']}"
        )

    return cue_result


def validate_patch_matches_task_intent(patch_data, task):
    task_note = (task.get("note") or "").strip()
    change_intent = get_task_change_intent(task)
    expected_operation = get_task_expected_operation(task)
    completion_cues = get_task_completion_cues(task)
    summary = get_patch_change_summary(patch_data["patch"])
    validate_structural_patch_shape(summary)

    replace_intent = extract_simple_replace_intent(task_note) or extract_simple_rename_intent(task_note)
    if replace_intent:
        old_token, new_token = replace_intent
        validate_replace_like_intent(summary, old_token, new_token)

    if expected_operation:
        validate_expected_operation(summary, expected_operation, task_note)

    if change_intent == "insert_line_after_anchor":
        validate_insert_after_anchor_intent(summary, task_note)
    elif change_intent == "tighten_validation":
        validate_tighten_validation_intent(summary)
    elif change_intent == "update_prompt_contract":
        validate_update_prompt_contract_intent(summary, task_note)
    elif change_intent == "adjust_routing_order":
        validate_adjust_routing_order_intent(summary)
    elif change_intent == "update_state_handling":
        validate_update_state_handling_intent(summary)
    elif change_intent == "refactor_local_block":
        validate_refactor_local_block_intent(summary)

    if change_intent in {
        "modify_existing_logic",
        "tighten_validation",
        "update_prompt_contract",
        "adjust_routing_order",
        "update_state_handling",
        "refactor_local_block",
    }:
        validate_scope_alignment(
            summary,
            task_note,
            change_intent,
            explicit_tokens=[replace_intent[0], replace_intent[1]] if replace_intent else None,
        )

    cue_result = evaluate_completion_cues(summary, completion_cues)
    patch_data["completion_cue_result"] = apply_completion_cue_policy(task, cue_result)

    return True


def validate_patch_data(patch_data, task=None):
    if patch_data["target_file"] not in KNOWN_FILES:
        raise ValueError(f"Unknown target file: {patch_data['target_file']}")

    if patch_data["change_type"] != "diff_patch":
        raise ValueError("Only diff_patch is currently supported.")

    patch_text = patch_data["patch"]
    if "--- " not in patch_text or "+++ " not in patch_text:
        raise ValueError("Patch is missing diff file headers.")

    diff_lines = patch_text.splitlines()
    valid_prefixes = ("---", "+++", "@@", "+", "-", " ", "\\")

    for line in diff_lines:
        if not line:
            continue
        if not line.startswith(valid_prefixes):
            raise ValueError(f"Patch contains non-diff commentary: {line[:80]}")

    added_method_names = []
    for line in diff_lines:
        if line.startswith("+") and line.lstrip("+").strip().startswith("def "):
            name = line.split("def ", 1)[1].split("(", 1)[0].strip()
            added_method_names.append(name)

    for name in set(added_method_names):
        if patch_text.count(f"def {name}(") > 1:
            raise ValueError(f"Patch contains duplicate method definition for: {name}")

    if len(added_method_names) != len(set(added_method_names)):
        raise ValueError("Patch adds duplicate method definitions.")

    if len(added_method_names) > 1:
        raise ValueError("First patch is too broad: more than one new method added.")

    removed_method_names = []
    for line in diff_lines:
        if line.startswith("-") and line.lstrip("-").strip().startswith("def "):
            name = line.split("def ", 1)[1].split("(", 1)[0].strip()
            removed_method_names.append(name)

    if removed_method_names:
        raise ValueError(f"Patch removes existing methods: {removed_method_names}")

    for i, line in enumerate(diff_lines[1:], start=1):
        if line.startswith("+") and line.lstrip("+").strip().startswith("def "):
            prev = diff_lines[i - 1].strip()
            if prev.startswith("return "):
                raise ValueError("Patch appears to insert a method immediately after a return line.")

    has_anchor = any(line.startswith(" ") or line.startswith("-") for line in diff_lines)
    if not has_anchor:
        if not (patch_data["risk_level"] == "high" and patch_data["status"] == "blocked"):
            raise ValueError("Patch has no anchor context or removal lines.")

    if has_bad_method_indent(diff_lines):
        raise ValueError("Patch adds a method with invalid indentation level.")

    if has_unfinished_block_before_added_def(diff_lines):
        raise ValueError("Patch inserts a method into an unfinished block.")
    
    if (
        patch_data.get("status") != "blocked"
        and not has_meaningful_change(diff_lines)
        and not task_allows_comment_only_change(task)
    ):
        raise ValueError("Patch change too small or non-functional.")

def validate_patch_against_anchor(patch_data, anchor):
    if not anchor:
        return True

    anchored_file = anchor.get("target_file")
    anchored_symbol = anchor.get("target_symbol")
    anchored_symbol_id = anchor.get("target_symbol_id")
    scope = anchor.get("scope") or "single_file"

    if scope == "single_file" and anchored_file:
        if patch_data.get("target_file") != anchored_file:
            raise ValueError(
                f"Patch target {patch_data.get('target_file')} does not match explicit task file {anchored_file}."
            )

    if anchored_symbol:
        if patch_data.get("context_target") != anchored_symbol:
            raise ValueError(
                f"Selected context target {patch_data.get('context_target')} does not match explicit task method {anchored_symbol}."
            )

    if anchored_symbol_id and patch_data.get("context_symbol_id"):
        if patch_data.get("context_symbol_id") != anchored_symbol_id:
            raise ValueError(
                f"Selected context symbol_id {patch_data.get('context_symbol_id')} does not match explicit task symbol_id {anchored_symbol_id}."
            )

    anchor_span = _get_anchor_span(anchor)
    context_span = patch_data.get("context_span") or {}
    if anchor_span and context_span:
        if context_span.get("lineno") != anchor_span.get("lineno") or context_span.get("end_lineno") != anchor_span.get("end_lineno"):
            raise ValueError(
                f"Selected context span {context_span.get('lineno')}-{context_span.get('end_lineno')} does not match explicit task span {anchor_span.get('lineno')}-{anchor_span.get('end_lineno')}."
            )

        if anchor_span.get("col_offset") is not None and context_span.get("col_offset") != anchor_span.get("col_offset"):
            raise ValueError(
                f"Selected context col_offset {context_span.get('col_offset')} does not match explicit task col_offset {anchor_span.get('col_offset')}."
            )

        if anchor_span.get("end_col_offset") is not None and context_span.get("end_col_offset") != anchor_span.get("end_col_offset"):
            raise ValueError(
                f"Selected context end_col_offset {context_span.get('end_col_offset')} does not match explicit task end_col_offset {anchor_span.get('end_col_offset')}."
            )

    return True
