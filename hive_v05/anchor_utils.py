ANCHOR_SPAN_FIELDS = (
    "target_symbol_id",
    "lineno",
    "end_lineno",
    "col_offset",
    "end_col_offset",
)


def get_anchor_span_data(target_file, target_symbol, state_manager=None):
    if state_manager is None or not target_file or not target_symbol:
        return {}

    span = state_manager.get_symbol_span(target_file, target_symbol)
    if not isinstance(span, dict):
        return {}

    return {
        "target_symbol_id": span.get("symbol_id"),
        "lineno": span.get("lineno"),
        "end_lineno": span.get("end_lineno"),
        "col_offset": span.get("col_offset"),
        "end_col_offset": span.get("end_col_offset"),
    }


def merge_anchor_with_span(anchor, target_file, target_symbol, state_manager=None):
    merged = dict(anchor or {})

    for field in ANCHOR_SPAN_FIELDS:
        merged.pop(field, None)

    merged["target_file"] = target_file
    merged["target_symbol"] = target_symbol

    span_data = get_anchor_span_data(
        target_file,
        target_symbol,
        state_manager=state_manager,
    )
    for field, value in span_data.items():
        if value is not None:
            merged[field] = value

    return merged


def copy_anchor_fields(target, anchor):
    if not isinstance(target, dict) or not isinstance(anchor, dict):
        return target

    if anchor.get("target_symbol_id"):
        target["target_symbol_id"] = anchor.get("target_symbol_id")

    for field in ("lineno", "end_lineno", "col_offset", "end_col_offset"):
        if anchor.get(field) is not None:
            target[field] = anchor.get(field)

    return target


def canonicalize_task_anchor(
    task,
    *,
    target_file=None,
    target_symbol=None,
    state_manager=None,
    default_scope="single_file",
    default_anchor_level=None,
    default_anchor_source=None,
):
    if not isinstance(task, dict):
        return task

    metadata = dict(task.get("metadata") or {})
    existing_anchor = dict(metadata.get("anchor") or {})

    resolved_target_file = (
        target_file
        or task.get("target_file")
        or metadata.get("target_file")
        or existing_anchor.get("target_file")
    )
    resolved_target_symbol = (
        target_symbol
        or task.get("target_symbol")
        or metadata.get("target_symbol")
        or existing_anchor.get("target_symbol")
    )

    anchor_level = (
        default_anchor_level
        or existing_anchor.get("anchor_level")
        or ("symbol" if resolved_target_symbol else "file")
    )
    anchor_source = (
        default_anchor_source
        or existing_anchor.get("anchor_source")
        or "unknown"
    )

    anchor = merge_anchor_with_span(
        {
            **existing_anchor,
            "target_file": resolved_target_file,
            "target_symbol": resolved_target_symbol,
            "scope": existing_anchor.get("scope") or default_scope,
            "anchor_level": anchor_level,
            "anchor_source": anchor_source,
        },
        resolved_target_file,
        resolved_target_symbol,
        state_manager=state_manager,
    )

    metadata["target_file"] = resolved_target_file
    metadata["target_symbol"] = resolved_target_symbol
    metadata["anchor"] = anchor
    copy_anchor_fields(metadata, anchor)

    task["metadata"] = metadata
    task["target_file"] = resolved_target_file
    task["target_symbol"] = resolved_target_symbol
    copy_anchor_fields(task, anchor)
    return task
