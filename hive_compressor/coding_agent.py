"""Coding-agent history adapter for Hive Compressor.

The adapter follows the product law:

    Human language is preserved. Machine state is compressed. Source remains recoverable.

It never rewrites a human message into shorter prose. Instead it preserves the
exact source, accepts or derives structured operational records, compresses only
those records, and falls back to source evidence whenever interpretation is not
safe enough to discard from model context.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

from .adapter import SourceEvidence, build_adapter_packet, preserve_source
from .compressor import CompressionError, compress_records


KNOWN_EVENT_KINDS = {
    "human_message",
    "tool_call",
    "tool_result",
    "file_change",
    "test_run",
    "plan",
    "decision",
    "failure",
    "status",
}


DEFAULT_MIN_CONFIDENCE = 0.90


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _event_ref(event: dict[str, Any], index: int) -> str:
    raw = event.get("id") or event.get("ref")
    if raw is None:
        return f"event-{index + 1}"
    if not isinstance(raw, str) or not raw.strip():
        raise CompressionError(f"event {index} id/ref must be a non-empty string")
    return raw.strip()


def _effective_time(event: dict[str, Any], index: int) -> Any:
    if "effective_t" in event:
        return event["effective_t"]
    if "timestamp" in event:
        return event["timestamp"]
    return index + 1


def _source_for_event(event: dict[str, Any], event_ref: str) -> SourceEvidence:
    kind = event.get("kind")
    if kind == "human_message":
        text = event.get("text")
        if not isinstance(text, str):
            raise CompressionError(f"human event {event_ref} requires string text")
        return preserve_source(f"source:{event_ref}", text, source_type="human")

    # For machine events, keep a canonical evidence copy so every derived state
    # remains recoverable without embedding raw logs in the compressed record.
    return preserve_source(
        f"source:{event_ref}",
        _canonical_json(event),
        source_type="machine_event",
    )


def _record(
    event_ref: str,
    ordinal: int,
    effective_t: Any,
    *,
    kind: str,
    authority: str,
    status: str,
    requires: list[str] | None = None,
    effects: Any,
) -> dict[str, Any]:
    return {
        "ref": f"state:{event_ref}:{ordinal}",
        "effective_t": effective_t,
        "kind": kind,
        "authority": authority,
        "status": status,
        "requires": list(requires or []),
        "effects": effects,
    }


def _directive_records(
    event: dict[str, Any],
    event_ref: str,
    effective_t: Any,
    min_confidence: float,
) -> tuple[list[dict[str, Any]], bool]:
    """Convert explicit human-message directives to machine state.

    The adapter deliberately does not infer semantics from human prose by regex.
    A coding-agent integration may attach structured `directives` after its own
    interpretation step. Low-confidence directives do not become machine state.
    """
    directives = event.get("directives")
    if directives is None:
        return [], False
    if not isinstance(directives, list):
        raise CompressionError(f"human event {event_ref}.directives must be a list")

    records: list[dict[str, Any]] = []
    all_safe = True
    for ordinal, directive in enumerate(directives, start=1):
        if not isinstance(directive, dict):
            raise CompressionError(f"human event {event_ref} directive {ordinal} must be an object")

        confidence = directive.get("confidence", 1.0)
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise CompressionError(
                f"human event {event_ref} directive {ordinal} confidence must be between 0 and 1"
            )
        if confidence < min_confidence:
            all_safe = False
            continue

        state_kind = str(directive.get("kind") or "instruction").strip()
        status = str(directive.get("status") or "active").strip()
        effects = directive.get("effects")
        if effects is None:
            raise CompressionError(
                f"human event {event_ref} directive {ordinal} requires effects"
            )
        requires = directive.get("requires") or []
        if not isinstance(requires, list) or not all(isinstance(x, str) for x in requires):
            raise CompressionError(
                f"human event {event_ref} directive {ordinal}.requires must be a string list"
            )

        records.append(
            _record(
                event_ref,
                ordinal,
                effective_t,
                kind=state_kind,
                authority="user_instruction",
                status=status,
                requires=requires,
                effects=effects,
            )
        )

    # A human source is safe to omit from repeated model context only when the
    # integration supplied at least one directive and every directive cleared the gate.
    fully_interpreted = bool(directives) and all_safe and len(records) == len(directives)
    return records, fully_interpreted


def _machine_records(
    event: dict[str, Any],
    event_ref: str,
    effective_t: Any,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    kind = event.get("kind")
    state_effects = event.get("state_effects")
    requires = event.get("requires") or []
    if not isinstance(requires, list) or not all(isinstance(x, str) for x in requires):
        raise CompressionError(f"event {event_ref}.requires must be a string list")

    def one(state_kind: str, authority: str, status: str, effects: Any) -> tuple[list[dict[str, Any]], bool, None]:
        return [
            _record(
                event_ref,
                1,
                effective_t,
                kind=state_kind,
                authority=authority,
                status=status,
                requires=requires,
                effects=effects,
            )
        ], True, None

    if kind == "tool_call":
        tool = event.get("tool")
        if not isinstance(tool, str) or not tool:
            return [], False, "tool_call_missing_tool"
        effects = state_effects if state_effects is not None else {
            "op": "tool_call",
            "tool": tool,
            "target": event.get("target"),
        }
        return one("action", "agent_action", "historical", effects)

    if kind == "tool_result":
        tool = event.get("tool")
        if not isinstance(tool, str) or not tool:
            return [], False, "tool_result_missing_tool"
        effects = state_effects if state_effects is not None else {
            "op": "tool_result",
            "tool": tool,
            "ok": bool(event.get("ok", True)),
        }
        return one("observation", "tool_result", "historical", effects)

    if kind == "file_change":
        path = event.get("path")
        if not isinstance(path, str) or not path:
            return [], False, "file_change_missing_path"
        effects = state_effects if state_effects is not None else {
            "op": "file_change",
            "path": path,
            "change": event.get("change", "modified"),
        }
        return one("change", "tool_result", "active", effects)

    if kind == "test_run":
        suite = event.get("suite") or event.get("command")
        if not isinstance(suite, str) or not suite:
            return [], False, "test_run_missing_suite"
        effects = state_effects if state_effects is not None else {
            "op": "test_status",
            "suite": suite,
            "passed": int(event.get("passed", 0) or 0),
            "failed": int(event.get("failed", 0) or 0),
            "skipped": int(event.get("skipped", 0) or 0),
        }
        return one("test", "tool_result", "active", effects)

    if kind == "plan":
        if state_effects is None:
            label = event.get("label")
            if not isinstance(label, str) or not label:
                return [], False, "plan_missing_state_effects"
            state_effects = {"op": "plan", "label": label}
        return one("plan", "agent", "planned", state_effects)

    if kind == "decision":
        if state_effects is None:
            decision = event.get("decision")
            if not isinstance(decision, str) or not decision:
                return [], False, "decision_missing_state_effects"
            state_effects = {"op": "decision", "value": decision}
        return one("decision", "agent", "active", state_effects)

    if kind == "failure":
        if state_effects is None:
            code = event.get("code") or event.get("failure")
            if not isinstance(code, str) or not code:
                return [], False, "failure_missing_state_effects"
            state_effects = {"op": "failure", "code": code}
        return one("failure", "tool_result", "active", state_effects)

    if kind == "status":
        if state_effects is None:
            name = event.get("name")
            value = event.get("value")
            if not isinstance(name, str) or not name:
                return [], False, "status_missing_name"
            state_effects = {"op": "set", "path": name, "value": value}
        return one("state", "system", "active", state_effects)

    return [], False, "unknown_event_kind"


def adapt_coding_session(
    events: Iterable[dict[str, Any]],
    *,
    mode: str = "c1",
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> dict[str, Any]:
    """Turn coding-agent history into source-linked compressible machine state.

    Safe behavior is intentionally conservative:
    - exact human text is preserved as source evidence;
    - un-interpreted or low-confidence human messages remain verbatim in model context;
    - unknown/malformed machine events remain verbatim fallback evidence;
    - only structured records enter `compress_records`.
    """
    if not isinstance(min_confidence, (int, float)) or not 0 <= min_confidence <= 1:
        raise CompressionError("min_confidence must be between 0 and 1")

    event_list = list(events)
    sources: list[SourceEvidence] = []
    linked_records: list[dict[str, Any]] = []
    fallback_refs: list[str] = []
    fallback_reasons: dict[str, str] = {}
    human_refs: list[str] = []

    seen_event_refs: set[str] = set()

    for index, event in enumerate(event_list):
        if not isinstance(event, dict):
            raise CompressionError(f"event {index} must be an object")

        event_ref = _event_ref(event, index)
        if event_ref in seen_event_refs:
            raise CompressionError(f"duplicate event ref: {event_ref}")
        seen_event_refs.add(event_ref)

        kind = event.get("kind")
        if not isinstance(kind, str) or not kind:
            raise CompressionError(f"event {event_ref} requires a string kind")

        source = _source_for_event(event, event_ref)
        sources.append(source)
        source_ref = source.ref
        effective_t = _effective_time(event, index)

        if kind == "human_message":
            human_refs.append(source_ref)
            records, fully_interpreted = _directive_records(
                event, event_ref, effective_t, float(min_confidence)
            )
            for record in records:
                linked_records.append({"record": record, "source_refs": [source_ref]})
            if not fully_interpreted:
                fallback_refs.append(source_ref)
                fallback_reasons[source_ref] = "human_source_not_fully_interpreted"
            continue

        if kind not in KNOWN_EVENT_KINDS:
            fallback_refs.append(source_ref)
            fallback_reasons[source_ref] = "unknown_event_kind"
            continue

        records, safe, reason = _machine_records(event, event_ref, effective_t)
        for record in records:
            linked_records.append({"record": record, "source_refs": [source_ref]})
        if not safe:
            fallback_refs.append(source_ref)
            fallback_reasons[source_ref] = reason or "machine_event_not_safely_interpreted"

    packet = build_adapter_packet(sources, linked_records)
    compression = compress_records(packet["compression_records"], mode=mode)

    source_by_ref = {entry["ref"]: entry for entry in packet["source_evidence"]}

    # The newest human message is always supplied verbatim to the next model call,
    # even when its operational meaning was safely extracted.
    model_refs: list[str] = []
    if human_refs:
        model_refs.append(human_refs[-1])
    for ref in fallback_refs:
        if ref not in model_refs:
            model_refs.append(ref)

    verbatim_sources = [source_by_ref[ref] for ref in model_refs]

    raw_history = _canonical_json(event_list)
    model_ready = {
        "verbatim_sources": verbatim_sources,
        "compressed_state": compression["records"],
        "lineage": packet["lineage"],
    }
    hive_context = _canonical_json(model_ready)

    raw_bytes = len(raw_history.encode("utf-8"))
    hive_bytes = len(hive_context.encode("utf-8"))
    saved = max(0, raw_bytes - hive_bytes)

    return {
        "schema": "hive.coding-agent-adapter.v1",
        "source_evidence": packet["source_evidence"],
        "lineage": packet["lineage"],
        "compression": compression,
        "model_context": model_ready,
        "fallback": {
            "required": bool(fallback_refs),
            "source_refs": fallback_refs,
            "reasons": fallback_reasons,
        },
        "shadow": {
            "raw_history_bytes": raw_bytes,
            "hive_model_context_bytes": hive_bytes,
            "bytes_saved": saved,
            "reduction_percent": round((saved / raw_bytes * 100.0) if raw_bytes else 0.0, 2),
            "quality_status": "not_measured",
            "note": "size-only shadow comparison; no task-quality claim",
        },
    }
