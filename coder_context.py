from coder_prompting import get_plan_goal_text
import re
import ast
import textwrap



ARCHITECTURAL_FILES = {
    "planner.py",
    "coder.py",
    "router.py",
    "reflector.py",
    "main.py",
    "executor.py",
    "interface.py",
    "builder.py",
    "HiveMemoryAgent.py",
}

ARCHITECTURE_CUES = [
    "flow",
    "execution",
    "routing",
    "route",
    "planner",
    "coder",
    "executor",
    "reflector",
    "state",
    "plan state",
    "stored plan",
    "child task",
    "child-task",
    "grouped task",
    "grouped child",
    "progression",
    "dependency",
    "depends_on",
    "schema",
    "compatibility",
    "normalization",
    "shared logic",
    "shared flow",
    "underlying system",
    "main.py",
    "active",
    "complete",
    "completed",
    "proposed",
]

NARROW_ANCHOR_CUES = [
    "format",
    "formatting",
    "output",
    "display",
    "label",
    "string",
    "help",
    "rename",
    "adjust",
    "tweak",
]

MAIN_FLOW_ANCHORS = [
    'elif route == "code_task":',
    'elif route == "plan_task":',
    'elif route == "complete_task":',
    "def find_plan_for_task(",
    "def _get_first_ready_child_task(",
    "def _is_child_task_complete(",
    "def main():",
]


def _combined_text(task, plan):
    note = (task.get("note") or "").lower()
    goal = get_plan_goal_text(plan).lower()
    next_action = (plan.get("next_action") or "").lower()
    return f"{note} {goal} {next_action}"


def _normalized_combined_text(task, plan):
    """
    # Enforce strict span-based targeting when an exact anchor is present.
    Normalize combined task/plan text to avoid accidental substring matches
    like block name 'main' matching 'main.py'.
    """
    combined = _combined_text(task, plan)
    combined = re.sub(r"\bmain\.py\b", "main_file", combined)
    return combined


def _mentions_block_name(combined, block_name):
    """
    Match a block name as a standalone token-ish reference, not just as a raw
    substring inside another token.
    """
    pattern = rf"\b{re.escape(block_name.lower())}\b"
    return re.search(pattern, combined) is not None


def extract_code_blocks(file_text, target_file=None):
    """
    Extract class methods and top-level functions as editable blocks.

    AST-first for Python correctness.
    Falls back to a text parser if AST parsing fails.
    """
    try:
        tree = ast.parse(file_text)
        lines = file_text.splitlines()
        blocks = []

        file_prefix = f"{target_file}::" if target_file else ""

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = node.lineno - 1
                end = node.end_lineno
                block_text = "\n".join(lines[start:end])
                blocks.append({
                    "file": target_file,
                    "name": node.name,
                    "type": "function",
                    "start": start,
                    "end": end,
                    "lineno": node.lineno,
                    "end_lineno": node.end_lineno,
                    "col_offset": getattr(node, "col_offset", None),
                    "end_col_offset": getattr(node, "end_col_offset", None),
                    "symbol_id": f"{file_prefix}{node.name}",
                    "text": block_text,
                })

            elif isinstance(node, ast.ClassDef):
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        start = child.lineno - 1
                        end = child.end_lineno
                        block_text = "\n".join(lines[start:end])
                        blocks.append({
                            "file": target_file,
                            "name": child.name,
                            "type": "method",
                            "start": start,
                            "end": end,
                            "lineno": child.lineno,
                            "end_lineno": child.end_lineno,
                            "col_offset": getattr(child, "col_offset", None),
                            "end_col_offset": getattr(child, "end_col_offset", None),
                            "parent_name": node.name,
                            "symbol_id": f"{file_prefix}{node.name}.{child.name}",
                            "text": block_text,
                        })

        if blocks:
            return blocks

    except SyntaxError:
        pass

    # Fallback to text-based extraction if AST parsing fails
    lines = file_text.splitlines()
    blocks = []
    i = 0
    file_prefix = f"{target_file}::" if target_file else ""

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        is_top_level_function = stripped.startswith("def ") and indent == 0
        is_class_method = stripped.startswith("def ") and indent == 4

        if is_top_level_function or is_class_method:
            block_type = "function" if is_top_level_function else "method"
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
                next_is_top_level_function = next_stripped.startswith("def ") and next_indent == 0
                next_is_class_method = next_stripped.startswith("def ") and next_indent == 4

                if block_type == "function" and next_is_top_level_function:
                    break
                if block_type == "method" and next_is_class_method:
                    break

                i += 1

            end = i
            block_text = "\n".join(lines[start:end])
            blocks.append({
                "file": target_file,
                "name": name,
                "type": block_type,
                "start": start,
                "end": end,
                "lineno": start + 1,
                "end_lineno": end,
                "col_offset": None,
                "end_col_offset": None,
                "symbol_id": f"{file_prefix}{name}",
                "text": block_text,
            })
            continue

        i += 1

    return blocks


def _anchor_span_from_metadata(anchor):
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


def _find_block_by_anchor_span(blocks, anchor_span):
    if not blocks or not anchor_span:
        return None

    for block in blocks:
        if (
            block.get("lineno") == anchor_span.get("lineno")
            and block.get("end_lineno") == anchor_span.get("end_lineno")
        ):
            return block

    return None


def _validate_block_against_anchor_span(selected_block, anchor_span, anchored_symbol, target_file):
    if selected_block is None or not anchor_span:
        raise ValueError(
            f"CRITICAL: exact anchor span could not be resolved for {anchored_symbol or 'unknown symbol'} in {target_file}"
        )

    if anchored_symbol and selected_block.get("name") != anchored_symbol:
        raise ValueError(
            f"Anchor mismatch in {target_file}: expected symbol {anchored_symbol}, got {selected_block.get('name')}."
        )

    if selected_block.get("lineno") != anchor_span.get("lineno") or selected_block.get("end_lineno") != anchor_span.get("end_lineno"):
        raise ValueError(
            f"Anchor mismatch in {target_file}: expected lines {anchor_span.get('lineno')}-{anchor_span.get('end_lineno')}, "
            f"got {selected_block.get('lineno')}-{selected_block.get('end_lineno')}."
        )

    if anchor_span.get("col_offset") is not None and selected_block.get("col_offset") != anchor_span.get("col_offset"):
        raise ValueError(
            f"Anchor mismatch in {target_file}: expected col_offset {anchor_span.get('col_offset')}, got {selected_block.get('col_offset')}."
        )

    if anchor_span.get("end_col_offset") is not None and selected_block.get("end_col_offset") != anchor_span.get("end_col_offset"):
        raise ValueError(
            f"Anchor mismatch in {target_file}: expected end_col_offset {anchor_span.get('end_col_offset')}, got {selected_block.get('end_col_offset')}."
        )

    target_symbol_id = anchor_span.get("target_symbol_id")
    if target_symbol_id:
        block_symbol_id = selected_block.get("symbol_id")
        if block_symbol_id and block_symbol_id != target_symbol_id:
            raise ValueError(
                f"Anchor mismatch in {target_file}: expected symbol_id {target_symbol_id}, got {block_symbol_id}."
            )


def extract_route_blocks(file_text, target_file=None):
    """
    Extract route branches inside main() such as:

        if route == "..."
        elif route == "..."

    These behave like mini command handlers and should be editable
    blocks just like functions.
    """

    lines = file_text.splitlines()
    blocks = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        is_route = (
            indent >= 8 and (
                stripped.startswith('if route == "') or
                stripped.startswith('elif route == "')
            )
        )

        if not is_route:
            i += 1
            continue

        start = i

        try:
            route_name = stripped.split('"')[1]
        except Exception:
            i += 1
            continue

        i += 1

        while i < len(lines):
            next_line = lines[i]
            next_stripped = next_line.lstrip()
            next_indent = len(next_line) - len(next_stripped)

            next_is_route = (
                next_indent >= 8 and (
                    next_stripped.startswith('elif route == "') or
                    next_stripped.startswith('if route == "')
                )
            )

            if next_is_route:
                break

            i += 1

        end = i

        block_text = "\n".join(lines[start:end])

        blocks.append({
            "file": target_file,
            "name": f"route:{route_name}",
            "type": "route_branch",
            "start": start,
            "end": end,
            "lineno": start + 1,
            "end_lineno": end,
            "col_offset": None,
            "end_col_offset": None,
            "symbol_id": f"{target_file}::route:{route_name}" if target_file else f"route:{route_name}",
            "text": block_text,
        })

    return blocks


def extract_class_header(file_text):
    """
    Return the first class declaration block if present, otherwise empty string.
    Includes decorators and class line only.
    """
    lines = file_text.splitlines()

    for i, line in enumerate(lines):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        if stripped.startswith("class ") and indent == 0:
            start = i

            while start > 0:
                prev = lines[start - 1].strip()
                if prev.startswith("@"):
                    start -= 1
                else:
                    break

            return "\n".join(lines[start:i + 1])

    return ""


def extract_import_blocks(file_text):
    """
    Extract top-level import statements with their imported names.
    """
    try:
        tree = ast.parse(file_text)
        lines = file_text.splitlines()
        blocks = []

        for node in tree.body:
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue

            start = node.lineno - 1
            end = node.end_lineno
            imported_names = set()

            for alias in getattr(node, "names", []):
                if alias.asname:
                    imported_names.add(alias.asname)
                else:
                    imported_names.add(alias.name.split(".")[0])

            blocks.append({
                "type": "import",
                "start": start,
                "end": end,
                "text": "\n".join(lines[start:end]),
                "imported_names": imported_names,
            })

        return blocks

    except SyntaxError:
        return []


def extract_direct_references(block_text):
    """
    Extract direct function/helper references from a selected block.
    """
    try:
        tree = ast.parse(textwrap.dedent(block_text))
    except SyntaxError:
        return set()

    references = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                references.add(func.id)
            elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if func.value.id in {"self", "cls"}:
                    references.add(func.attr)

    return references


def select_referenced_helper_blocks(file_text, selected_block, max_helpers=3):
    """
    Include directly referenced local helper blocks without expanding to the whole file.
    """
    blocks = extract_code_blocks(file_text, target_file=selected_block.get("file"))
    if not blocks or selected_block is None:
        return []

    references = extract_direct_references(selected_block.get("text", ""))
    if not references:
        return []

    helper_blocks = []
    for block in blocks:
        if block["name"] == selected_block["name"]:
            continue
        if block["name"] not in references:
            continue
        helper_blocks.append(block)

    helper_blocks.sort(key=lambda block: block["start"])
    return helper_blocks[:max_helpers]


def select_relevant_import_blocks(file_text, selected_block, helper_blocks=None, max_imports=4):
    """
    Include only import blocks whose imported names are used in the selected/helper blocks.
    """
    helper_blocks = helper_blocks or []
    import_blocks = extract_import_blocks(file_text)
    if not import_blocks:
        return []

    references = set()
    references.update(extract_direct_references(selected_block.get("text", "")))

    for block in helper_blocks:
        references.update(extract_direct_references(block.get("text", "")))

    if not references:
        return []

    relevant = []
    for block in import_blocks:
        if block["imported_names"] & references:
            relevant.append(block)

    relevant.sort(key=lambda block: block["start"])
    return relevant[:max_imports]


def extract_mapping_blocks(file_text):
    """
    Extract top-level or class-level dict/list assignment blocks such as:

        EXACT_COMMANDS = { ... }
        PREFIX_COMMANDS = { ... }
        intent_routes = { ... }

    Returns block dicts compatible with selector logic.
    """
    lines = file_text.splitlines()
    blocks = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        is_assignment = "=" in stripped and not stripped.startswith("#")
        if not is_assignment:
            i += 1
            continue

        left, right = stripped.split("=", 1)
        name = left.strip()

        if not name.isidentifier():
            i += 1
            continue

        right = right.strip()
        starts_mapping = right.startswith("{") or right.startswith("[")
        if not starts_mapping:
            i += 1
            continue

        start = i
        open_char = right[0]
        close_char = "}" if open_char == "{" else "]"

        depth = right.count(open_char) - right.count(close_char)
        i += 1

        while i < len(lines) and depth > 0:
            current = lines[i]
            depth += current.count(open_char)
            depth -= current.count(close_char)
            i += 1

        end = i
        block_text = "\n".join(lines[start:end])

        blocks.append({
            "name": f"map:{name.lower()}",
            "type": "mapping_block",
            "start": start,
            "end": end,
            "text": block_text,
        })

    return blocks


def is_architectural_task(task, plan, target_file):
    combined = _combined_text(task, plan)

    if target_file in ARCHITECTURAL_FILES:
        if any(cue in combined for cue in ARCHITECTURE_CUES):
            return True

    return False


def is_narrow_anchor_task(task, plan, target_file):
    combined = _combined_text(task, plan)

    if is_architectural_task(task, plan, target_file):
        return False

    return any(cue in combined for cue in NARROW_ANCHOR_CUES)


def select_target_block(task, plan, target_file, file_text, anchored_symbol=None):
    """
    Select one likely edit block.

    Priority:
    1. explicit anchored symbol
    2. explicit method/function/route name mentions (token-aware)
    3. route branch preference for main.py command tasks
    4. architectural file preferred blocks
    5. file-specific default block
    6. first block fallback
    """
    blocks = extract_code_blocks(file_text, target_file=target_file)

    if target_file == "main.py":
        route_blocks = extract_route_blocks(file_text, target_file=target_file)
        blocks = route_blocks + blocks

    mapping_blocks = extract_mapping_blocks(file_text)
    blocks = mapping_blocks + blocks

    if not blocks:
        return None

    combined = _normalized_combined_text(task, plan)

    if anchored_symbol:
        for block in blocks:
            if block["name"] == anchored_symbol:
                return block
        return None

    preferred_by_file = {
        "planner.py": ["plan_task", "_fallback_plan", "_build_prompt"],
        "coder.py": ["generate_patch_with_revisions", "generate_patch", "_fallback_patch"],
        "router.py": ["map:intent_routes", "route"],
        "reflector.py": ["evaluate", "_build_prompt"],
        "main.py": [
            "route:show_plan",
            "route:show_task",
            "route:show_patch",
            "route:code_task",
            "route:apply_patch",
            "route:approve_patch",
            "route:complete_task",
            "route:help",
            "find_plan_for_task",
            "_get_first_ready_child_task",
            "_is_child_task_complete",
            "main",
        ],
        "executor.py": ["apply_patch", "verify_patch_context", "validate_patch_semantics"],
        "interface.py": ["map:exact_commands", "map:prefix_commands", "process_input"],
        "builder.py": ["build", "continue_task"],
        "HiveMemoryAgent.py": ["store", "get_task_by_id", "get_recent_notes", "update_task_status"],
    }

    for block in blocks:
        if _mentions_block_name(combined, block["name"]):
            return block

    helper_blocks = [
        block for block in blocks
        if block["name"].startswith("_")
    ]

    for block in helper_blocks:
        if block["name"].lower() in combined:
            return block

    if target_file == "main.py":
        route_terms = [
            ("show plan", "route:show_plan"),
            ("show_plan", "route:show_plan"),
            ("show task", "route:show_task"),
            ("show_task", "route:show_task"),
            ("show patch", "route:show_patch"),
            ("show_patch", "route:show_patch"),
            ("code task", "route:code_task"),
            ("code_task", "route:code_task"),
            ("apply patch", "route:apply_patch"),
            ("apply_patch", "route:apply_patch"),
            ("approve patch", "route:approve_patch"),
            ("approve_patch", "route:approve_patch"),
            ("complete task", "route:complete_task"),
            ("complete_task", "route:complete_task"),
            ("help", "route:help"),
        ]

        for term, route_name in route_terms:
            if term in combined:
                for block in blocks:
                    if block["name"] == route_name:
                        return block

    mapping_terms = [
        ("prefix_commands", "map:prefix_commands"),
        ("prefix commands", "map:prefix_commands"),
        ("exact_commands", "map:exact_commands"),
        ("exact commands", "map:exact_commands"),
        ("intent_routes", "map:intent_routes"),
        ("intent routes", "map:intent_routes"),
    ]

    for term, map_name in mapping_terms:
        if term in combined:
            for block in blocks:
                if block["name"] == map_name:
                    return block

    if target_file == "main.py" and is_architectural_task(task, plan, target_file):
        if any(term in combined for term in ["child task", "child-task", "depends_on", "dependency"]):
            for preferred_name in [
                "_get_first_ready_child_task",
                "_is_child_task_complete",
                "find_plan_for_task",
                "main",
            ]:
                for block in blocks:
                    if block["name"] == preferred_name:
                        return block

        if any(term in combined for term in ["stored plan", "plan state", "state", "active", "proposed", "completed"]):
            for preferred_name in [
                "find_plan_for_task",
                "_get_first_ready_child_task",
                "_is_child_task_complete",
                "main",
            ]:
                for block in blocks:
                    if block["name"] == preferred_name:
                        return block

        for preferred_name in [
            "find_plan_for_task",
            "_get_first_ready_child_task",
            "_is_child_task_complete",
            "main",
        ]:
            for block in blocks:
                if block["name"] == preferred_name:
                    return block

    preferred_names = preferred_by_file.get(target_file, [])
    for name in preferred_names:
        for block in blocks:
            if block["name"] == name:
                return block

    return None


def get_neighbor_blocks(blocks, selected_block, radius=0):
    """
    Return neighboring blocks around the selected block.
    """
    if not blocks or selected_block is None:
        return []

    selected_index = None
    for i, block in enumerate(blocks):
        if (
            block["name"] == selected_block["name"]
            and block["start"] == selected_block["start"]
            and block["end"] == selected_block["end"]
        ):
            selected_index = i
            break

    if selected_index is None:
        return [selected_block]

    start_index = max(0, selected_index - radius)
    end_index = min(len(blocks), selected_index + radius + 1)
    return blocks[start_index:end_index]


def build_line_window(file_text, center_start, center_end, padding_lines=40, target_name=None, selected_block=None):
    """
    Build a line-based context window around a selected range.
    """
    lines = file_text.splitlines()
    window_start = max(0, center_start - padding_lines)
    window_end = min(len(lines), center_end + padding_lines)

    return {
        "mode": "line_window",
        "target_name": target_name,
        "target_start": center_start,
        "target_end": center_end,
        "window_start": window_start,
        "window_end": window_end,
        "context_text": "\n".join(lines[window_start:window_end]),
        "full_file_text": file_text,
        "selected_block": selected_block,
        "neighbor_blocks": [selected_block] if selected_block else [],
        "helper_blocks": [],
        "import_blocks": [],
    }


def build_block_context_window(file_text, selected_block, radius=0, include_class_header=True):
    """
    Build a focused context window using the selected block and neighbors.
    """
    blocks = extract_code_blocks(file_text, target_file=selected_block.get("file"))
    if not blocks or selected_block is None:
        return None

    neighbor_blocks = get_neighbor_blocks(blocks, selected_block, radius=radius)
    if not neighbor_blocks:
        return None

    lines = file_text.splitlines()
    window_start = neighbor_blocks[0]["start"]
    window_end = neighbor_blocks[-1]["end"]
    helper_blocks = []
    import_blocks = []

    if selected_block.get("name"):
        helper_blocks = select_referenced_helper_blocks(file_text, selected_block)
        if helper_blocks:
            window_start = min(window_start, helper_blocks[0]["start"])
            window_end = max(window_end, helper_blocks[-1]["end"])

        import_blocks = select_relevant_import_blocks(
            file_text,
            selected_block,
            helper_blocks=helper_blocks,
        )
        if import_blocks:
            window_start = min(window_start, import_blocks[0]["start"])

    chunks = []

    if import_blocks:
        imports_text = "\n".join(block["text"] for block in import_blocks if block.get("text")).strip()
        if imports_text:
            chunks.append(imports_text)

    if include_class_header:
        class_header = extract_class_header(file_text)
        if class_header:
            chunks.append(class_header)

    main_context_text = "\n".join(lines[neighbor_blocks[0]["start"]:neighbor_blocks[-1]["end"]]).strip()
    if main_context_text:
        chunks.append(main_context_text)

    helper_chunks = []
    for block in helper_blocks:
        block_text = block.get("text", "").strip()
        if block_text:
            helper_chunks.append(block_text)

    if helper_chunks:
        chunks.append("\n\n".join(helper_chunks))

    context_text = "\n\n".join(chunk for chunk in chunks if chunk).strip()

    return {
        "mode": "block_window",
        "target_name": selected_block["name"],
        "target_start": selected_block["start"],
        "target_end": selected_block["end"],
        "window_start": window_start,
        "window_end": window_end,
        "context_text": context_text,
        "full_file_text": file_text,
        "selected_block": selected_block,
        "neighbor_blocks": neighbor_blocks,
        "helper_blocks": helper_blocks,
        "import_blocks": import_blocks,
    }


def build_exact_symbol_context(file_text, selected_block, padding_lines=8):
    """
    Build a symbol-locked context containing exactly the selected block plus a tiny
    surrounding line buffer.
    """
    lines = file_text.splitlines()
    window_start = max(0, selected_block["start"] - padding_lines)
    window_end = min(len(lines), selected_block["end"] + padding_lines)

    return {
        "mode": "exact_symbol_block",
        "target_name": selected_block["name"],
        "target_start": selected_block["start"],
        "target_end": selected_block["end"],
        "window_start": window_start,
        "window_end": window_end,
        "context_text": "\n".join(lines[window_start:window_end]),
        "full_file_text": file_text,
        "selected_block": selected_block,
        "neighbor_blocks": [selected_block],
        "helper_blocks": [],
        "import_blocks": [],
    }


def should_prefer_block_context(target_file):
    return target_file in ARCHITECTURAL_FILES


def find_anchor_line(lines, anchors):
    for anchor in anchors:
        anchor_lower = anchor.lower()
        for i, line in enumerate(lines):
            if anchor_lower in line.lower():
                return i, anchor
    return None, None


def infer_anchor_candidates(task, plan, target_file):
    combined = _combined_text(task, plan)
    anchors = []

    if "show patch" in combined:
        anchors.extend(['elif route == "show_patch":'])

    if "current task" in combined:
        anchors.extend(['elif route == "current_task":'])

    if "memory" in combined:
        anchors.extend(['elif route == "memory":'])

    if "help" in combined:
        anchors.extend([
            'elif route == "help":',
            "available commands:",
        ])

    if target_file == "main.py" and is_architectural_task(task, plan, target_file):
        anchors = MAIN_FLOW_ANCHORS + anchors

    return anchors


def build_anchor_context_window(file_text, anchor_line, anchor_text, padding_lines=20):
    lines = file_text.splitlines()
    window_start = max(0, anchor_line - padding_lines)
    window_end = min(len(lines), anchor_line + padding_lines + 1)

    return {
        "mode": "anchor_window",
        "target_name": anchor_text,
        "target_start": anchor_line,
        "target_end": anchor_line + 1,
        "window_start": window_start,
        "window_end": window_end,
        "context_text": "\n".join(lines[window_start:window_end]),
        "full_file_text": file_text,
        "anchor_text": anchor_text,
        "selected_block": None,
        "neighbor_blocks": [],
        "helper_blocks": [],
        "import_blocks": [],
    }


def _context_priority(selected_mode, *, has_selected_block=False, has_anchor_window=False):
    if selected_mode == "exact_symbol_block":
        return ["exact_symbol_block", "block_window", "line_window", "file_head_fallback"]
    if selected_mode == "block_window":
        return ["block_window", "line_window", "file_head_fallback"]
    if selected_mode == "anchor_window" or has_anchor_window:
        return ["anchor_window", "file_head_fallback"]
    if selected_mode == "line_window" and has_selected_block:
        return ["line_window", "file_head_fallback"]
    return ["file_head_fallback"]


def _is_concrete_route_anchor(anchor_text):
    lowered = (anchor_text or "").lower()
    return 'route ==' in lowered or 'elif route ==' in lowered or 'if route ==' in lowered


def _finalize_context(context, *, target_file, anchor=None):
    context = dict(context or {})
    anchor = dict(anchor or {})
    selected_block = context.get("selected_block") or {}
    mode = context.get("mode")
    anchor_text = context.get("anchor_text")

    if mode == "exact_symbol_block":
        anchoring_confidence = "high"
    elif mode in {"block_window", "line_window"} and selected_block:
        anchoring_confidence = "high"
    elif mode == "anchor_window" and _is_concrete_route_anchor(anchor_text):
        anchoring_confidence = "medium"
    elif mode == "anchor_window":
        anchoring_confidence = "low"
    else:
        anchoring_confidence = "low"

    under_anchored = anchoring_confidence == "low" and not selected_block

    context["target_file"] = target_file
    context["anchor_identity"] = {
        "target_file": target_file,
        "target_symbol": anchor.get("target_symbol") or context.get("target_name"),
        "target_symbol_id": anchor.get("target_symbol_id") or selected_block.get("symbol_id"),
        "anchor_text": anchor_text,
    }
    context["context_priority"] = _context_priority(
        mode,
        has_selected_block=bool(selected_block),
        has_anchor_window=mode == "anchor_window",
    )
    context["anchoring_confidence"] = anchoring_confidence
    context["under_anchored"] = under_anchored
    context["neighbor_blocks"] = list(context.get("neighbor_blocks") or [])
    context["helper_blocks"] = list(context.get("helper_blocks") or [])
    context["import_blocks"] = list(context.get("import_blocks") or [])
    return context


def select_edit_context(task, plan, target_file, file_text, radius=0, padding_lines=40):
    """
    Choose the best prompt context for patch generation.

    Current design phase:
    - block-first for architectural files/tasks
    - anchor-first only for genuinely narrow display/help/string edits
    - special preference for main.py execution-flow work
    """
    lines = file_text.splitlines()

    task_metadata = task.get("metadata") or {}
    anchor = task_metadata.get("anchor") or {}
    anchored_symbol = (
        task.get("target_symbol")
        or task_metadata.get("target_symbol")
        or anchor.get("target_symbol")
    )
    anchor_span = _anchor_span_from_metadata(anchor)
    change_intent = (
        task.get("change_intent")
        or task_metadata.get("change_intent")
        or "modify_existing_logic"
    )

    if anchored_symbol or anchor_span:
        all_blocks = extract_code_blocks(file_text, target_file=target_file)
        selected_block = None

        if anchor_span:
            selected_block = _find_block_by_anchor_span(all_blocks, anchor_span)
            _validate_block_against_anchor_span(
                selected_block,
                anchor_span,
                anchored_symbol,
                target_file,
            )
        else:
            selected_block = select_target_block(
                task,
                plan,
                target_file,
                file_text,
                anchored_symbol=anchored_symbol,
            )

        if selected_block is None:
            raise ValueError(
                f"CRITICAL: target_symbol '{anchored_symbol or anchor.get('target_symbol_id')}' not found in {target_file}"
            )

        if anchored_symbol and selected_block.get("name") != anchored_symbol:
            # Enforce strict symbol targeting when an exact anchor is present.
            raise ValueError(
                f"Explicit target symbol mismatch in {target_file}: expected {anchored_symbol}, got {selected_block.get('name')}."
            )

        return _finalize_context(
            build_exact_symbol_context(
                file_text,
                selected_block,
                padding_lines=min(padding_lines, 8),
            ),
            target_file=target_file,
            anchor=anchor,
        )

    if is_architectural_task(task, plan, target_file):
        selected_block = select_target_block(
            task,
            plan,
            target_file,
            file_text,
            anchored_symbol=None,
        )

        if should_prefer_block_context(target_file) and selected_block is not None:
            context = build_block_context_window(
                file_text,
                selected_block,
                radius=radius,
                include_class_header=True,
            )
            if context is not None:
                return _finalize_context(context, target_file=target_file, anchor=anchor)

        if selected_block is not None:
            return _finalize_context(
                build_line_window(
                    file_text,
                    selected_block["start"],
                    selected_block["end"],
                    padding_lines=padding_lines,
                    target_name=selected_block["name"],
                    selected_block=selected_block,
                ),
                target_file=target_file,
                anchor=anchor,
            )

    if is_narrow_anchor_task(task, plan, target_file):
        anchors = infer_anchor_candidates(task, plan, target_file)
        anchor_line, anchor_text = find_anchor_line(lines, anchors)
        if anchor_line is not None:
            return _finalize_context(
                build_anchor_context_window(
                    file_text,
                    anchor_line,
                    anchor_text,
                    padding_lines=20,
                ),
                target_file=target_file,
                anchor=anchor,
            )

    selected_block = select_target_block(
        task,
        plan,
        target_file,
        file_text,
        anchored_symbol=None,
    )

    if should_prefer_block_context(target_file) and selected_block is not None:
        context = build_block_context_window(
            file_text,
            selected_block,
            radius=radius,
            include_class_header=True,
        )
        if context is not None:
            return _finalize_context(context, target_file=target_file, anchor=anchor)

    if selected_block is not None:
        return _finalize_context(
            build_line_window(
                file_text,
                selected_block["start"],
                selected_block["end"],
                padding_lines=padding_lines,
                target_name=selected_block["name"],
                selected_block=selected_block,
            ),
            target_file=target_file,
            anchor=anchor,
        )

    fallback_end = min(len(lines), max(80, padding_lines * 2))
    return _finalize_context({
        "mode": "file_head_fallback",
        "target_name": None,
        "target_start": 0,
        "target_end": fallback_end,
        "window_start": 0,
        "window_end": fallback_end,
        "context_text": "\n".join(lines[:fallback_end]),
        "full_file_text": file_text,
    }, target_file=target_file, anchor=anchor)
