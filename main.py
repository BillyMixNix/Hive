from pathlib import Path
import re

import torch

from anchor_utils import copy_anchor_fields, merge_anchor_with_span
from builder import merge_pilot_context
from router import Router
from interface import Interface
from reflector import Reflector

from HiveMemoryAgent import HiveMemoryAgent
from HiveLessonMemory import LessonMemory
from HiveStateManager import HiveStateManager
from failure_intelligence import interpret_failure
from repo_map import RepoMap


def make_dummy_vector():
    return torch.randn(256).to("cpu")


def extract_file_anchor(text, state_manager=None):
    lowered = (text or "").lower()

    known_files = []
    if state_manager is not None:
        known_files = state_manager.get_known_files()

    for f in known_files:
        if f.lower() in lowered:
            return f

    gui_terms = (
        "gui",
        "ui",
        "window",
        "desktop",
        "button",
        "toggle",
        "dark mode",
        "theme",
        "aesthetic",
        "asthetic",
    )
    if any(term in lowered for term in gui_terms):
        known_file_set = set(known_files)
        for candidate in ("hive_gui.py", "interface.py"):
            if candidate in known_file_set:
                return candidate

    return None


def _get_known_symbols(state_manager=None):
    if state_manager is None:
        return []

    repo_map = state_manager.get_repo_map() or {}
    symbol_to_file = repo_map.get("symbol_to_file") or {}
    return list(symbol_to_file.keys())


def _normalize_anchor_token(token):
    token = (token or "").strip().lower()
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _tokenize_anchor_text(value):
    raw_tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", (value or "").lower())
    normalized = []

    for raw in raw_tokens:
        for part in raw.split("_"):
            normalized_part = _normalize_anchor_token(part)
            if len(normalized_part) >= 3:
                normalized.append(normalized_part)

    return normalized


def _collect_symbol_identifier_matches(raw_text, lowered, symbols):
    matches = []

    for symbol in symbols:
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(symbol.lower())}(?![A-Za-z0-9_])"
        for match in re.finditer(pattern, lowered):
            trailing = lowered[match.end():match.end() + 3]
            if trailing == ".py":
                continue
            matches.append(symbol)
            break

    return matches


def extract_symbol_anchor(text, state_manager=None, target_file=None):
    raw_text = text or ""
    lowered = raw_text.lower()
    scoring_text = raw_text
    scoring_lowered = lowered

    symbols = []
    if state_manager is not None and target_file:
        symbols = state_manager.get_symbols_for_file(target_file) or []
    if not symbols:
        symbols = _get_known_symbols(state_manager=state_manager)
    if not symbols:
        return None

    known_files = state_manager.get_known_files() if state_manager is not None else []
    for file_name in known_files or []:
        scoring_text = re.sub(re.escape(file_name), " ", scoring_text, flags=re.IGNORECASE)
        scoring_lowered = re.sub(re.escape(file_name.lower()), " ", scoring_lowered)

    quoted_matches = []
    for symbol in symbols:
        patterns = [
            rf"`{re.escape(symbol)}`",
            rf'"{re.escape(symbol)}"',
            rf"'{re.escape(symbol)}'",
        ]
        if any(re.search(pattern, raw_text, flags=re.IGNORECASE) for pattern in patterns):
            quoted_matches.append(symbol)

    if quoted_matches:
        return sorted(quoted_matches, key=len, reverse=True)[0]

    exact_matches = _collect_symbol_identifier_matches(
        scoring_text,
        scoring_lowered,
        symbols,
    )

    if exact_matches:
        return sorted(exact_matches, key=len, reverse=True)[0]

    text_tokens = _tokenize_anchor_text(scoring_text)
    if not text_tokens:
        return None

    text_token_set = set(text_tokens)
    scored = []

    for symbol in symbols:
        symbol_tokens = _tokenize_anchor_text(symbol)
        if not symbol_tokens:
            continue

        symbol_token_set = set(symbol_tokens)
        overlap = text_token_set & symbol_token_set
        if not overlap:
            continue

        overlap_score = len(overlap)
        token_hits = sum(text_tokens.count(token) for token in overlap)
        coverage = overlap_score / max(len(symbol_token_set), 1)
        scored.append({
            "symbol": symbol,
            "score": (overlap_score * 10) + token_hits + coverage,
            "overlap": overlap_score,
            "coverage": coverage,
        })

    if not scored:
        return None

    scored.sort(
        key=lambda entry: (
            entry["score"],
            entry["overlap"],
            entry["coverage"],
            len(entry["symbol"]),
        ),
        reverse=True,
    )

    best = scored[0]
    runner_up = scored[1] if len(scored) > 1 else None

    if best["overlap"] < 2 and best["coverage"] < 0.6:
        strong_unique_hint = (
            best["overlap"] >= 1
            and (
                runner_up is None
                or runner_up["overlap"] == 0
                or (best["score"] - runner_up["score"] >= 2.5)
            )
        )
        if not strong_unique_hint:
            return None

    if runner_up is not None:
        if best["score"] - runner_up["score"] < 2 and best["overlap"] == runner_up["overlap"]:
            return None

    return best["symbol"]


def extract_required_completion_cues(text):
    raw_text = text or ""
    cues = []

    for marker in (
        "required code in the final patch:",
        "required code in final patch:",
        "completion cue:",
        "completion cues:",
    ):
        match = re.search(re.escape(marker) + r"\s*(.+)", raw_text, flags=re.IGNORECASE)
        if not match:
            continue

        payload = match.group(1).strip().rstrip(".")
        if any(marker in payload for marker in ("(", ")", "{", "}", "=", ":", ".")):
            cues.append(payload)

        for quoted in re.findall(r'"([^"]+)"|\'([^\']+)\'|`([^`]+)`', payload):
            cue = next((part for part in quoted if part), "").strip()
            if cue:
                cues.append(cue)

        if not cues and payload:
            parts = [part.strip() for part in re.split(r"\s*\|\s*|\s*;\s*", payload) if part.strip()]
            for part in parts:
                cues.append(part.rstrip("."))
        break

    deduped = []
    seen = set()
    for cue in cues:
        normalized = cue.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)

    return deduped[:3]


def merge_completion_cues(existing_cues, new_cues):
    merged = []
    seen = set()

    for cue in list(existing_cues or []) + list(new_cues or []):
        normalized = str(cue or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)

    return merged[:3]


def build_anchor_from_text(text, state_manager=None):
    target_file = extract_file_anchor(text, state_manager=state_manager)
    target_symbol = extract_symbol_anchor(
        text,
        state_manager=state_manager,
        target_file=target_file,
    )

    if not target_file and target_symbol and state_manager is not None:
        target_file = state_manager.resolve_symbol_to_file(target_symbol)
    elif target_file and not target_symbol and state_manager is not None:
        target_symbol = infer_symbol_from_task_note(
            text,
            target_file,
            state_manager=state_manager,
        )

    return merge_anchor_with_span({
        "target_file": target_file,
        "target_symbol": target_symbol,
        "scope": "single_file",
        "anchor_level": "symbol" if target_symbol else "file",
        "anchor_source": "user_input",
    }, target_file, target_symbol, state_manager=state_manager)


def _normalize_token(token):
    """Stem a token for fuzzy symbol matching."""
    token = (token or "").strip().lower()
    if len(token) > 5 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _tokenize_for_symbol_scoring(value):
    """Tokenize and normalize text for symbol overlap scoring."""
    raw_tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", (value or "").lower())
    parts = []
    for raw in raw_tokens:
        for piece in raw.split("_"):
            norm = _normalize_token(piece)
            if len(norm) >= 3:
                parts.append(norm)
    return parts


def _score_symbols_for_text(text, symbols, target_file):
    """
    Core symbol inference algorithm shared by infer_symbol_from_task_note
    and planner._infer_symbol_from_text_for_file.

    Tries three strategies in priority order:
    1. Quoted exact match (backtick, double-quote, single-quote)
    2. Word-boundary exact match
    3. Token overlap scoring with method/error hints

    Returns the best matching symbol name or None.
    """
    scoring_text = re.sub(re.escape(target_file), " ", text or "", flags=re.IGNORECASE)
    lowered = scoring_text.lower()
    prefers_method = any(t in lowered for t in ("method", "function", "helper"))
    error_language = any(t in lowered for t in ("invalid", "error", "fail"))

    # Strategy 1: quoted match
    quoted = []
    for symbol in symbols:
        patterns = [rf"`{re.escape(symbol)}`", rf'"{re.escape(symbol)}"', rf"'{re.escape(symbol)}'"]
        if any(re.search(p, scoring_text, flags=re.IGNORECASE) for p in patterns):
            quoted.append(symbol)
    if quoted:
        return sorted(quoted, key=len, reverse=True)[0]

    # Strategy 2: exact word-boundary match
    exact = []
    for symbol in symbols:
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(symbol.lower())}(?![A-Za-z0-9_])"
        for match in re.finditer(pattern, lowered):
            if lowered[match.end():match.end() + 3] == ".py":
                continue
            exact.append(symbol)
            break
    if exact:
        return sorted(exact, key=len, reverse=True)[0]

    # Strategy 3: token overlap scoring
    text_tokens = _tokenize_for_symbol_scoring(scoring_text)
    if not text_tokens:
        return None
    text_token_set = set(text_tokens)
    scored = []

    for symbol in symbols:
        symbol_tokens = _tokenize_for_symbol_scoring(symbol)
        if not symbol_tokens:
            continue
        symbol_token_set = set(symbol_tokens)
        overlap = text_token_set & symbol_token_set
        if not overlap:
            continue
        overlap_score = len(overlap)
        token_hits = sum(text_tokens.count(t) for t in overlap)
        coverage = overlap_score / max(len(symbol_token_set), 1)
        score = (overlap_score * 10) + token_hits + coverage

        if prefers_method:
            if symbol.startswith("_") or symbol[:1].islower():
                score += 2
            if symbol[:1].isupper():
                score -= 3
        if not error_language and {"invalid", "error", "fail"} & symbol_token_set:
            score -= 3

        scored.append({"symbol": symbol, "score": score,
                        "overlap": overlap_score, "coverage": coverage})

    if not scored:
        return None

    scored.sort(key=lambda e: (e["score"], e["overlap"], e["coverage"], len(e["symbol"])),
                reverse=True)
    best = scored[0]
    runner_up = scored[1] if len(scored) > 1 else None

    if best["overlap"] < 2 and best["coverage"] < 0.6:
        strong = (best["overlap"] >= 1 and (
            runner_up is None
            or runner_up["overlap"] == 0
            or (best["score"] - runner_up["score"] >= 2.5)
        ))
        if not strong:
            return None

    if runner_up is not None:
        if best["score"] - runner_up["score"] < 2 and best["overlap"] == runner_up["overlap"]:
            return None

    return best["symbol"]


def infer_symbol_from_task_note(text, target_file, state_manager=None):
    """Infer the most relevant symbol in target_file from task note text."""
    if state_manager is None or not target_file:
        return None
    symbols = state_manager.get_symbols_for_file(target_file)
    if not symbols:
        return None
    return _score_symbols_for_text(text, symbols, target_file)


def _is_gui_file_level_request(text, target_file):
    lowered = (text or "").lower()
    if target_file not in {"hive_gui.py", "interface.py"}:
        return False
    return any(term in lowered for term in (
        "gui",
        "ui",
        "window",
        "desktop",
        "button",
        "toggle",
        "dark mode",
        "theme",
        "aesthetic",
        "asthetic",
    ))


def _text_explicitly_mentions_symbol(text, symbol):
    if not symbol:
        return False
    raw_text = text or ""
    patterns = [
        rf"`{re.escape(symbol)}`",
        rf'"{re.escape(symbol)}"',
        rf"'{re.escape(symbol)}'",
    ]
    return any(re.search(pattern, raw_text, flags=re.IGNORECASE) for pattern in patterns)


def enrich_task_anchor_for_planning(task, memory=None, state_manager=None):
    if not isinstance(task, dict):
        return task

    metadata = dict(task.get("metadata") or {})
    anchor = dict(metadata.get("anchor") or {})

    target_file = (
        task.get("target_file")
        or metadata.get("target_file")
        or anchor.get("target_file")
        or extract_file_anchor(task.get("note"), state_manager=state_manager)
    )
    target_symbol = (
        task.get("target_symbol")
        or metadata.get("target_symbol")
        or anchor.get("target_symbol")
    )

    note_text = task.get("note") or ""
    note_lower = note_text.lower()
    known_files = set(state_manager.get_known_files()) if state_manager is not None else set()

    if target_file and known_files and target_file not in known_files:
        target_file = extract_file_anchor(note_text, state_manager=state_manager)
        target_symbol = None
        anchor = {}

    if target_symbol and state_manager is not None and not target_file:
        resolved_file = state_manager.resolve_symbol_to_file(target_symbol)
        if resolved_file in known_files:
            target_file = resolved_file
        else:
            target_symbol = None

    completion_cues = (
        task.get("completion_cues")
        or metadata.get("completion_cues")
        or extract_required_completion_cues(note_text)
    )

    anchor_source = str(anchor.get("anchor_source") or "").lower()
    if (
        target_symbol
        and _is_gui_file_level_request(note_text, target_file)
        and anchor_source in {"pilot_guidance", "file_level_inference", "repo_symbol_inference", "planner_normalized", "user_input"}
        and not _text_explicitly_mentions_symbol(note_text, target_symbol)
    ):
        target_symbol = None
        for key in ("target_symbol", "target_symbol_id", "lineno", "end_lineno", "col_offset", "end_col_offset"):
            metadata.pop(key, None)
            task.pop(key, None)
        anchor = {
            "target_file": target_file,
            "target_symbol": None,
            "scope": anchor.get("scope") or "single_file",
            "anchor_level": "file",
            "anchor_source": "file_level_inference",
        }

    should_reinfer_symbol = False
    if target_file:
        anchor_source = str(anchor.get("anchor_source") or "").lower()
        preserve_file_level_anchor = (
            not target_symbol
            and anchor_source in {"pilot_guidance", "file_level_inference", "user_input"}
            and _is_gui_file_level_request(note_text, target_file)
        )
        if preserve_file_level_anchor:
            should_reinfer_symbol = False
        elif not target_symbol:
            should_reinfer_symbol = True
        elif anchor_source in {"user_input", "task_note", "file_level_inference"}:
            prefers_method = any(token in note_lower for token in ("method", "function", "helper"))
            symbol_looks_broad = bool(target_symbol[:1].isupper())
            if prefers_method or symbol_looks_broad:
                should_reinfer_symbol = True

    inferred_symbol = None
    if target_file and should_reinfer_symbol:
        inferred_symbol = infer_symbol_from_task_note(
            note_text,
            target_file,
            state_manager=state_manager,
        )

    if inferred_symbol:
        target_symbol = inferred_symbol
        anchor_source = "repo_symbol_inference"
        anchor_level = "symbol"
    else:
        anchor_source = anchor.get("anchor_source") or "file_level_inference"
        anchor_level = "symbol" if target_symbol else "file"

    anchor = merge_anchor_with_span({
        **anchor,
        "target_file": target_file,
        "target_symbol": target_symbol,
        "scope": anchor.get("scope") or "single_file",
        "anchor_level": anchor_level,
        "anchor_source": anchor_source,
    }, target_file, target_symbol, state_manager=state_manager)

    metadata["target_file"] = target_file
    metadata["target_symbol"] = target_symbol
    metadata["completion_cues"] = completion_cues
    metadata["anchor"] = anchor
    copy_anchor_fields(metadata, anchor)
    for key in ("target_symbol_id", "lineno", "end_lineno", "col_offset", "end_col_offset"):
        if key not in anchor:
            metadata.pop(key, None)
            task.pop(key, None)

    task["metadata"] = metadata
    task["target_file"] = target_file
    task["target_symbol"] = target_symbol
    copy_anchor_fields(task, anchor)

    if memory is not None and task.get("id") is not None:
        memory.update_task_metadata(task["id"], metadata)

    return task

def find_plan_for_task(memory, task_id, limit=100):
    recent_notes = memory.get_recent_notes(limit)

    for entry in reversed(recent_notes):
        if entry.get("tag") != "plan":
            continue

        meta = entry.get("metadata") or {}
        if meta.get("task_id") == task_id:
            return meta.get("plan")

    return None


def find_patch_entry(memory, patch_id):
    patch_entry = memory.get_task_by_id(patch_id)

    if not patch_entry:
        return None, f"Patch {patch_id} not found."

    if patch_entry.get("tag") != "patch":
        return None, f"Task {patch_id} is not a patch entry."

    return patch_entry, None


def require_patch_metadata(patch_entry, patch_id):
    metadata = patch_entry.get("metadata")
    if not metadata:
        return None, f"Patch {patch_id} has no metadata."
    return metadata, None


def update_patch_entry(memory, patch_id, *, metadata=None, status=None):
    if metadata is not None:
        memory.update_task_metadata(patch_id, metadata)
    if status is not None:
        memory.update_task_status(patch_id, status)
    return memory.get_task_by_id(patch_id)


def _summarize_patch_stats(patch_text):
    lines = str(patch_text or "").splitlines()
    additions = 0
    deletions = 0
    hunks = 0

    for line in lines:
        if line.startswith("@@"):
            hunks += 1
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

    return {
        "hunks": hunks,
        "additions": additions,
        "deletions": deletions,
    }


def build_pilot_review_packet(patch_id, patch_metadata):
    meta = dict(patch_metadata or {})
    reflection = dict(meta.get("reflection") or {})
    stats = _summarize_patch_stats(meta.get("patch", ""))
    excerpt_lines = str(meta.get("patch") or "").splitlines()[:20]
    excerpt = "\n".join(excerpt_lines).strip()

    return {
        "patch_id": patch_id,
        "task_id": meta.get("task_id"),
        "plan_id": meta.get("plan_id"),
        "task_note": meta.get("task_note"),
        "child_task_id": meta.get("child_task_id"),
        "child_task_title": meta.get("child_task_title"),
        "child_task_description": meta.get("child_task_description"),
        "target_file": meta.get("target_file"),
        "target_symbol": meta.get("child_target_symbol") or meta.get("target_symbol") or meta.get("context_target"),
        "coder_reason": meta.get("reason"),
        "reflector_verdict": reflection.get("verdict"),
        "reflector_reflection": reflection.get("reflection"),
        "reflector_next_step": reflection.get("next_step"),
        "patch_stats": stats,
        "patch_excerpt": excerpt,
        "review_questions": [
            "Is this the right place to patch?",
            "Does this solve the active child step rather than adjacent behavior?",
            "Does this solve the planned task without intent drift?",
        ],
    }


def format_pilot_review_packet(packet):
    packet = dict(packet or {})
    stats = dict(packet.get("patch_stats") or {})
    questions = packet.get("review_questions") or []

    lines = [
        f"Pilot Review Packet: Patch {packet.get('patch_id') or 'none'}",
        f"Source Task: {packet.get('task_id') or 'none'}",
        f"Plan ID: {packet.get('plan_id') or 'none'}",
        f"Task Note: {packet.get('task_note') or 'none'}",
        f"Child Task: {packet.get('child_task_title') or packet.get('child_task_description') or 'none'}",
        f"Child Task ID: {packet.get('child_task_id') or 'none'}",
        f"Target File: {packet.get('target_file') or 'none'}",
        f"Target Symbol: {packet.get('target_symbol') or 'none'}",
        f"Coder Reason: {packet.get('coder_reason') or 'none'}",
        f"Reflector Verdict: {packet.get('reflector_verdict') or 'none'}",
        f"Reflector Notes: {packet.get('reflector_reflection') or 'none'}",
        f"Patch Stats: hunks={stats.get('hunks', 0)} additions={stats.get('additions', 0)} deletions={stats.get('deletions', 0)}",
        "Pilot Checks:",
    ]
    for question in questions:
        lines.append(f"- {question}")
    if packet.get("patch_excerpt"):
        lines.append("")
        lines.append("Patch Excerpt:")
        lines.append(packet["patch_excerpt"])
    return "\n".join(lines)


def _infer_pilot_guidance_category(*, location_correct=None, task_alignment=None, plan_step_alignment=None, pilot_reason="", pilot_guidance=""):
    text = f"{pilot_reason} {pilot_guidance}".lower()
    if location_correct is False:
        if "symbol" in text:
            return "wrong_symbol"
        return "wrong_location"
    if plan_step_alignment is False:
        if "broader" in text or "adjacent" in text:
            return "solves_task_but_not_step"
        return "wrong_step"
    if task_alignment is False:
        if "broad" in text:
            return "over_broad_fix"
        return "intent_drift"
    if "broad" in text:
        return "over_broad_fix"
    return "intent_drift"


def record_pilot_guardrail(lesson_memory, patch_metadata, *, pilot_verdict, pilot_reason="", pilot_guidance="", location_correct=None, task_alignment=None, plan_step_alignment=None):
    if lesson_memory is None:
        return None

    meta = dict(patch_metadata or {})
    guidance_category = _infer_pilot_guidance_category(
        location_correct=location_correct,
        task_alignment=task_alignment,
        plan_step_alignment=plan_step_alignment,
        pilot_reason=pilot_reason,
        pilot_guidance=pilot_guidance,
    )
    guardrail_text = (pilot_guidance or pilot_reason or "Stay aligned with the pilot-reviewed patch intent.").strip()
    lesson_memory.add_lesson(
        file=meta.get("target_file"),
        change_type=meta.get("child_task_type") or meta.get("task_type") or "patch_review",
        failure_reason=pilot_reason or pilot_verdict,
        retry_instruction=guardrail_text,
        task_id=meta.get("task_id"),
        plan_id=meta.get("plan_id"),
        patch_id=meta.get("patch_id"),
        source="pilot",
        severity="high" if pilot_verdict == "reject" else "medium",
        lesson_family="pilot_guardrail",
        guidance_category=guidance_category,
        guardrail_text=guardrail_text,
        preferred_recovery_action="retry_patch" if guidance_category in {"wrong_location", "wrong_symbol"} else "replan_task",
        applies_to_step_level=guidance_category in {"wrong_step", "solves_task_but_not_step"},
        applies_to_task_level=guidance_category in {"intent_drift", "over_broad_fix"},
        target_symbol=meta.get("child_target_symbol") or meta.get("target_symbol"),
        change_intent=meta.get("child_change_intent") or meta.get("change_intent"),
        planner_source=meta.get("planner_source"),
        context_mode=meta.get("context_mode"),
        lesson_level="generalized" if pilot_verdict in {"reject", "revise"} else "exact",
        location_correct=location_correct,
        task_alignment=task_alignment,
        plan_step_alignment=plan_step_alignment,
        pilot_verdict=pilot_verdict,
    )
    return guardrail_text


def list_pending_pilot_review_patches(memory, limit=25):
    entries = []
    for entry in reversed(memory.get_recent_notes(limit)):
        if entry.get("tag") != "patch":
            continue
        if entry.get("status") != "pending_pilot_review":
            continue
        entries.append(entry)
    return entries


def _guidance_suggests_local_fix(text):
    lowered = str(text or "").lower()
    local_markers = (
        "wrong symbol",
        "wrong place",
        "wrong file",
        "use ",
        "target ",
        "same step",
        "tighten",
        "narrow",
        "current child step",
    )
    return any(marker in lowered for marker in local_markers)


def _guidance_suggests_replan(text):
    lowered = str(text or "").lower()
    replan_markers = (
        "wrong step",
        "wrong task",
        "wrong scope",
        "intent drift",
        "broader",
        "adjacent behavior",
        "not this step",
        "different step",
        "replan",
    )
    return any(marker in lowered for marker in replan_markers)


def decide_recovery_action(patch_metadata, pilot_guidance, state_manager=None):
    meta = dict(patch_metadata or {})
    guidance = str(pilot_guidance or "").strip()
    location_correct = meta.get("location_correct")
    task_alignment = meta.get("task_alignment")
    plan_step_alignment = meta.get("plan_step_alignment")

    guidance_anchor = build_anchor_from_text(guidance, state_manager=state_manager) if guidance else {}
    named_target = bool(guidance_anchor.get("target_file") or guidance_anchor.get("target_symbol"))

    if location_correct is True and task_alignment is False and plan_step_alignment is False:
        return "replan_task"
    if location_correct is True and task_alignment is True and plan_step_alignment is False:
        return "replan_task"
    if location_correct is False:
        return "retry_patch" if named_target or _guidance_suggests_local_fix(guidance) else "replan_task"

    if _guidance_suggests_replan(guidance):
        return "replan_task"
    if _guidance_suggests_local_fix(guidance):
        return "retry_patch"
    return "stop_and_wait"


def _summarize_reflection(meta):
    reflection = dict(meta.get("reflection") or {})
    return {
        "verdict": reflection.get("verdict"),
        "reflection": reflection.get("reflection"),
        "next_step": reflection.get("next_step"),
    }


def build_recovery_payload(patch_metadata, recovery_action, pilot_guidance, state_manager=None):
    meta = dict(patch_metadata or {})
    guidance = str(pilot_guidance or "").strip()
    guidance_anchor = build_anchor_from_text(guidance, state_manager=state_manager) if guidance else {}

    payload = {
        "recovery_action": recovery_action,
        "recovery_reason": guidance or meta.get("pilot_reason") or "Pilot correction requested.",
        "recovery_source_patch_id": meta.get("patch_id"),
        "recovery_attempt_count": int((meta.get("recovery_attempt_count") or 0)) + 1,
        "pilot_guidance": guidance,
        "pilot_guardrail_text": guidance or meta.get("pilot_reason"),
        "reflector_summary": _summarize_reflection(meta),
        "rejected_patch_excerpt": "\n".join(str(meta.get("patch") or "").splitlines()[:20]),
        "target_file": guidance_anchor.get("target_file") or meta.get("target_file"),
        "target_symbol": guidance_anchor.get("target_symbol") or meta.get("child_target_symbol") or meta.get("target_symbol"),
        "child_task_id": meta.get("child_task_id"),
        "child_task_description": meta.get("child_task_description"),
    }
    if recovery_action == "retry_patch":
        payload["recovery_status"] = "retry_ready"
        payload["retry_source"] = "pilot_revision"
    elif recovery_action == "replan_task":
        payload["recovery_status"] = "replan_ready"
        payload["planner_source"] = "pilot_replan"
    else:
        payload["recovery_status"] = "blocked"
    return payload


def list_pending_recoveries(memory, limit=50):
    entries = []
    seen_task_ids = set()
    for entry in reversed(memory.get_recent_notes(limit)):
        metadata = entry.get("metadata") or {}
        task_id = metadata.get("task_id") or entry.get("id")
        if metadata.get("recovery_status") in {"retry_ready", "replan_ready", "blocked"} and task_id not in seen_task_ids:
            seen_task_ids.add(task_id)
            entries.append(entry)
    return entries


def format_recovery_payload(task_id, recovery):
    recovery = dict(recovery or {})
    return "\n".join([
        f"Recovery State: task {task_id}",
        f"Action: {recovery.get('recovery_action') or 'none'}",
        f"Status: {recovery.get('recovery_status') or 'none'}",
        f"Reason: {recovery.get('recovery_reason') or 'none'}",
        f"Source Patch: {recovery.get('recovery_source_patch_id') or 'none'}",
        f"Attempts: {recovery.get('recovery_attempt_count') if recovery.get('recovery_attempt_count') is not None else 'none'}",
        f"Target File: {recovery.get('target_file') or 'none'}",
        f"Target Symbol: {recovery.get('target_symbol') or 'none'}",
        f"Pilot Guidance: {recovery.get('pilot_guidance') or 'none'}",
    ])


def payload_task_id(payload):
    if isinstance(payload, dict):
        return payload.get("task_id")
    return None


def payload_patch_id(payload):
    if isinstance(payload, dict):
        return payload.get("patch_id")
    return None


def find_backup_for_patch(memory, patch_id, limit=50):
    recent_notes = memory.get_recent_notes(limit)

    for entry in reversed(recent_notes):
        if entry.get("tag") != "patch_apply":
            continue

        metadata = entry.get("metadata") or {}
        if metadata.get("patch_id") == patch_id:
            return metadata.get("backup_path")

    return None

def _is_child_task_complete(plan, child_task_id):
    for child in plan.get("tasks", []):
        if child.get("task_id") == child_task_id:
            return child.get("status") in ("complete", "completed")
    return False

def _initialize_child_task_statuses(plan):
    tasks = plan.get("tasks", [])
    if not isinstance(tasks, list):
        return plan

    plan["active_child_task_id"] = None
    plan["active_child_task_title"] = None
    plan["active_child_target_file"] = None

    found_current = False

    for child in tasks:
        status = child.get("status")
        if status == "complete":
            continue

        if not found_current:
            child["status"] = "current"
            plan["active_child_task_id"] = child.get("task_id")
            plan["active_child_task_title"] = child.get("title")
            plan["active_child_target_file"] = child.get("target_file")
            found_current = True
        else:
            child["status"] = "next"

    plan["tasks"] = tasks
    return plan


def _complete_child_task(plan, child_task_id):
    tasks = plan.get("tasks", [])
    if not isinstance(tasks, list):
        return plan

    completed = False

    plan["active_child_task_id"] = None
    plan["active_child_task_title"] = None
    plan["active_child_target_file"] = None

    for child in tasks:
        if child.get("task_id") == child_task_id:
            child["status"] = "complete"
            completed = True
            break

    if completed:
        for child in tasks:
            if child.get("status") != "next":
                continue

            deps = child.get("depends_on", [])
            if all(_is_child_task_complete(plan, dep) for dep in deps):
                child["status"] = "current"
                plan["active_child_task_id"] = child.get("task_id")
                plan["active_child_task_title"] = child.get("title")
                plan["active_child_target_file"] = child.get("target_file")
                break

    plan["tasks"] = tasks
    return plan


def _get_first_ready_child_task(plan):
    tasks = plan.get("tasks", [])
    if not isinstance(tasks, list):
        return None

    active_child_task_id = plan.get("active_child_task_id")

    # First, prefer the stored active child pointer if it is still valid
    if active_child_task_id is not None:
        for child in tasks:
            if child.get("task_id") != active_child_task_id:
                continue

            deps = child.get("depends_on", [])
            if all(_is_child_task_complete(plan, dep) for dep in deps):
                child["status"] = "current"
                plan["active_child_task_title"] = child.get("title")
                plan["active_child_target_file"] = child.get("target_file")
                plan["tasks"] = tasks
                return child
            break

    # Next, prefer an existing current task if its dependencies are met
    for child in tasks:
        if child.get("status") != "current":
            continue

        deps = child.get("depends_on", [])
        if all(_is_child_task_complete(plan, dep) for dep in deps):
            plan["active_child_task_id"] = child.get("task_id")
            plan["active_child_task_title"] = child.get("title")
            plan["active_child_target_file"] = child.get("target_file")
            plan["tasks"] = tasks
            return child

    # Otherwise promote the first eligible next task
    for child in tasks:
        if child.get("status") != "next":
            continue

        deps = child.get("depends_on", [])
        if all(_is_child_task_complete(plan, dep) for dep in deps):
            child["status"] = "current"
            plan["active_child_task_id"] = child.get("task_id")
            plan["active_child_task_title"] = child.get("title")
            plan["active_child_target_file"] = child.get("target_file")
            plan["tasks"] = tasks
            return child

    plan["active_child_task_id"] = None
    plan["active_child_task_title"] = None
    plan["active_child_target_file"] = None
    plan["tasks"] = tasks
    return None


def update_current_snapshot(state, task=None, plan=None, child=None, status=None):
    if state is None:
        return None

    task_metadata = (task or {}).get("metadata") or {}
    current_data = {
        "active_goal": (task or {}).get("note"),
        "active_task_id": (task or {}).get("id"),
        "active_plan_id": f"plan-{task['id']}" if task and task.get("id") is not None else None,
        "active_child_task_id": (child or {}).get("task_id") or (plan or {}).get("active_child_task_id"),
        "current_child_task_title": (child or {}).get("title") or (plan or {}).get("active_child_task_title"),
        "task_status": status or (child or {}).get("status") or (task or {}).get("status") or (plan or {}).get("status"),
        "target_file": (
            (child or {}).get("target_file")
            or (task or {}).get("target_file")
            or task_metadata.get("target_file")
            or (plan or {}).get("active_child_target_file")
        ),
        "target_symbol": (
            (child or {}).get("target_symbol")
            or (task or {}).get("target_symbol")
            or task_metadata.get("target_symbol")
        ),
        "change_intent": (
            (child or {}).get("change_intent")
            or (task or {}).get("change_intent")
            or task_metadata.get("change_intent")
        ),
        "expected_operation": (
            (child or {}).get("expected_operation")
            or (task or {}).get("expected_operation")
            or task_metadata.get("expected_operation")
        ),
        "completion_cues": (
            (child or {}).get("completion_cues")
            or (task or {}).get("completion_cues")
            or task_metadata.get("completion_cues")
            or []
        ),
        "pilot_intent": task_metadata.get("pilot_intent"),
        "recovery_action": task_metadata.get("recovery_action"),
        "recovery_status": task_metadata.get("recovery_status"),
        "recovery_reason": task_metadata.get("recovery_reason"),
    }

    state.set_current_work(current_data)
    state.save_snapshot()
    return current_data


def format_current_snapshot(snapshot):
    current = (snapshot or {}).get("current") or {}

    if not any(
        current.get(key)
        for key in [
            "active_goal",
            "active_task_id",
            "current_child_task_title",
            "target_file",
            "target_symbol",
        ]
    ):
        return "No current observability state recorded."

    cues = current.get("completion_cues") or []
    cues_text = ", ".join(cues) if cues else "none"

    lines = [
        "Current Work",
        f"Goal: {current.get('active_goal') or 'none'}",
        f"Task ID: {current.get('active_task_id') or 'none'}",
        f"Plan ID: {current.get('active_plan_id') or 'none'}",
        f"Child Task: {current.get('current_child_task_title') or 'none'}",
        f"Child Task ID: {current.get('active_child_task_id') or 'none'}",
        f"Status: {current.get('task_status') or 'none'}",
        f"Target File: {current.get('target_file') or 'none'}",
        f"Target Symbol: {current.get('target_symbol') or 'none'}",
        f"Change Intent: {current.get('change_intent') or 'none'}",
        f"Expected Operation: {current.get('expected_operation') or 'none'}",
        f"Completion Cues: {cues_text}",
        f"Pilot Intent: {current.get('pilot_intent') or 'none'}",
        f"Recovery Action: {current.get('recovery_action') or 'none'}",
        f"Recovery Status: {current.get('recovery_status') or 'none'}",
    ]
    if current.get("recovery_reason"):
        lines.append(f"Recovery Reason: {current.get('recovery_reason')}")

    updated_at = current.get("updated_at")
    if updated_at:
        lines.append(f"Updated: {updated_at}")

    return "\n".join(lines)


def update_last_patch_snapshot(state, patch_data=None, **overrides):
    if state is None:
        return None

    patch_data = patch_data or {}
    reflection = patch_data.get("reflection") or {}
    sandbox_report = patch_data.get("sandbox_report") or {}

    base = {
        "patch_id": patch_data.get("patch_id"),
        "task_id": patch_data.get("task_id"),
        "plan_id": patch_data.get("plan_id"),
        "target_file": patch_data.get("target_file"),
        "target_symbol": (
            patch_data.get("target_symbol")
            or patch_data.get("child_target_symbol")
            or patch_data.get("context_target")
        ),
        "change_intent": (
            patch_data.get("change_intent")
            or patch_data.get("child_change_intent")
        ),
        "expected_operation": (
            patch_data.get("expected_operation")
            or patch_data.get("child_expected_operation")
        ),
        "patch_status": patch_data.get("status"),
        "validation_outcome": (
            "passed"
            if sandbox_report
            and sandbox_report.get("applied") is True
            and sandbox_report.get("syntax_valid") is True
            and sandbox_report.get("semantic_valid") is True
            else patch_data.get("validation_outcome")
        ),
        "rejection_reason": (
            patch_data.get("llm_error")
            or patch_data.get("rejection_reason")
            or patch_data.get("failure_reason")
        ),
        "reflection_verdict": reflection.get("verdict"),
        "confidence": reflection.get("confidence"),
        "pilot_verdict": patch_data.get("pilot_verdict"),
        "pilot_reason": patch_data.get("pilot_reason"),
        "pilot_guidance": patch_data.get("pilot_guidance"),
        "recovery_action": patch_data.get("recovery_action"),
        "recovery_status": patch_data.get("recovery_status"),
    }

    base.update(overrides)
    state.set_last_patch(base)
    state.save_snapshot()
    return base


def format_last_patch_snapshot(snapshot):
    last_patch = (snapshot or {}).get("last_patch") or {}

    if not any(
        last_patch.get(key)
        for key in [
            "patch_id",
            "target_file",
            "target_symbol",
            "patch_status",
            "validation_outcome",
        ]
    ):
        return "No last patch observability state recorded."

    lines = [
        "Last Patch",
        f"Patch ID: {last_patch.get('patch_id') or 'none'}",
        f"Task ID: {last_patch.get('task_id') or 'none'}",
        f"Plan ID: {last_patch.get('plan_id') or 'none'}",
        f"Target File: {last_patch.get('target_file') or 'none'}",
        f"Target Symbol: {last_patch.get('target_symbol') or 'none'}",
        f"Change Intent: {last_patch.get('change_intent') or 'none'}",
        f"Expected Operation: {last_patch.get('expected_operation') or 'none'}",
        f"Status: {last_patch.get('patch_status') or 'none'}",
        f"Validation Result: {last_patch.get('validation_outcome') or 'none'}",
        f"Reflection Verdict: {last_patch.get('reflection_verdict') or 'none'}",
        f"Pilot Verdict: {last_patch.get('pilot_verdict') or 'none'}",
        f"Recovery Action: {last_patch.get('recovery_action') or 'none'}",
        f"Recovery Status: {last_patch.get('recovery_status') or 'none'}",
        f"Confidence: {last_patch.get('confidence') if last_patch.get('confidence') is not None else 'none'}",
    ]

    if last_patch.get("rejection_reason"):
        lines.append(f"Reason: {last_patch.get('rejection_reason')}")
    if last_patch.get("pilot_reason"):
        lines.append(f"Pilot Reason: {last_patch.get('pilot_reason')}")
    if last_patch.get("pilot_guidance"):
        lines.append(f"Pilot Guidance: {last_patch.get('pilot_guidance')}")

    timestamp = last_patch.get("timestamp") or last_patch.get("updated_at")
    if timestamp:
        lines.append(f"Updated: {timestamp}")

    return "\n".join(lines)


def record_failure_observability(state, error_text, task=None, patch_data=None, **overrides):
    if state is None:
        return None

    task = task or {}
    patch_data = patch_data or {}
    reason = str(error_text or "").strip()
    interpretation = interpret_failure(
        stage=overrides.get("stage") or "observability",
        error_text=reason,
        task=task,
        patch_data=patch_data,
        sandbox_report=patch_data.get("sandbox_report") if isinstance(patch_data, dict) else None,
        reflection=patch_data.get("reflection") if isinstance(patch_data, dict) else None,
        source=overrides.get("source") or "observability",
        metadata={"plan_id": patch_data.get("plan_id") if isinstance(patch_data, dict) else None},
    )
    failure_data = dict(interpretation.observability)

    failure_data.update(overrides)
    state.record_failure(failure_data)
    state.save_snapshot()
    return failure_data


def format_failures_snapshot(snapshot):
    failures = (snapshot or {}).get("failures") or {}
    recent = failures.get("recent") or []

    if not recent:
        return "No failure observability state recorded."

    lines = ["Recent Failures"]

    for index, entry in enumerate(recent, start=1):
        lines.append(
            f"{index}. "
            f"[{entry.get('failure_family') or 'unknown'} / "
            f"{entry.get('failure_class') or 'unknown'} / "
            f"{entry.get('failure_code') or entry.get('failure_category') or 'unknown_failure'}] "
            f"file={entry.get('target_file') or 'none'} "
            f"symbol={entry.get('target_symbol') or 'none'} "
            f"change_intent={entry.get('change_intent') or 'none'} "
            f"expected_operation={entry.get('expected_operation') or 'none'}"
        )
        lines.append(f"   reason: {entry.get('reason') or 'none'}")
        if entry.get("retry_instruction"):
            lines.append(f"   retry: {entry.get('retry_instruction')}")

    counts = failures.get("counts_by_category") or {}
    if counts:
        summary = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        lines.append(f"Counts: {summary}")

    updated_at = failures.get("updated_at")
    if updated_at:
        lines.append(f"Updated: {updated_at}")

    return "\n".join(lines)


def sync_lessons_observability(state, lesson_memory, limit=5):
    if state is None or lesson_memory is None:
        return None

    recent_lessons = lesson_memory.get_recent_lessons(limit=limit)
    normalized = []

    for lesson in reversed(recent_lessons):
        summary = (
            lesson.get("retry_instruction")
            or lesson.get("failure_pattern")
            or lesson.get("failure_reason")
            or "No summary."
        )
        last_outcome = lesson.get("last_outcome")
        last_outcome_note = lesson.get("last_outcome_note")
        success_after_use = lesson.get("success_after_use")
        if success_after_use is None:
            success_after_use = 1 if (
                last_outcome == "success"
                or last_outcome_note == "retry_success"
            ) else 0
        failure_after_use = lesson.get("failure_after_use")
        if failure_after_use is None:
            failure_after_use = 1 if (
                last_outcome == "failure"
                or last_outcome_note == "failed_again"
            ) else 0
        normalized.append({
            "tag": lesson.get("failure_code") or lesson.get("failure_reason") or lesson.get("source") or "lesson",
            "summary": summary,
            "source": lesson.get("source"),
            "target_file": lesson.get("file"),
            "target_symbol": lesson.get("target_symbol"),
            "lesson_id": lesson.get("lesson_id"),
            "lesson_level": lesson.get("lesson_level", "exact"),
            "trigger_pattern": lesson.get("trigger_pattern"),
            "fix_strategy": lesson.get("fix_strategy"),
            "times_used": lesson.get("times_used", 0),
            "success_after_use": success_after_use,
            "failure_after_use": failure_after_use,
            "promotion_state": lesson.get("promotion_state", "raw"),
            "last_used_at": lesson.get("last_used_at"),
            "last_match_reasons": list(lesson.get("last_match_reasons") or []),
            "last_guidance_changed": lesson.get("last_guidance_changed"),
            "last_reuse_outcome": lesson.get("last_reuse_outcome"),
            "timestamp": lesson.get("timestamp"),
        })

    state.set_lessons(normalized)
    state.save_snapshot()
    return normalized


def format_lessons_snapshot(snapshot):
    lessons_section = (snapshot or {}).get("lessons") or {}
    recent = lessons_section.get("recent") or []

    if not recent:
        return "No lesson observability state recorded."

    lines = ["Recent Lessons"]

    for index, lesson in enumerate(recent, start=1):
        lines.append(
            f"{index}. [{lesson.get('source') or 'unknown'}] "
            f"tag={lesson.get('tag') or 'lesson'} "
            f"level={lesson.get('lesson_level') or 'exact'}"
        )
        lines.append(f"   summary: {lesson.get('summary') or 'none'}")
        lines.append(
            f"   effectiveness: times_used={lesson.get('times_used', 0)} "
            f"success_after_use={lesson.get('success_after_use', 0)} "
            f"failure_after_use={lesson.get('failure_after_use', 0)} "
            f"promotion_state={lesson.get('promotion_state') or 'raw'}"
        )
        if lesson.get("lesson_id"):
            lines.append(f"   lesson_id: {lesson.get('lesson_id')}")
        if lesson.get("trigger_pattern") or lesson.get("fix_strategy"):
            lines.append(
                f"   match: trigger_pattern={lesson.get('trigger_pattern') or 'none'} "
                f"fix_strategy={lesson.get('fix_strategy') or 'none'}"
            )
        if lesson.get("last_match_reasons"):
            lines.append(
                "   last_match_reasons: "
                + ", ".join(str(reason) for reason in lesson.get("last_match_reasons") or [])
            )
        if lesson.get("last_guidance_changed") is not None or lesson.get("last_reuse_outcome") is not None:
            lines.append(
                f"   reuse: guidance_changed={lesson.get('last_guidance_changed')} "
                f"outcome={lesson.get('last_reuse_outcome') or 'unknown'}"
            )
        if lesson.get("last_used_at"):
            lines.append(f"   last_used_at: {lesson.get('last_used_at')}")
        if lesson.get("target_file") or lesson.get("target_symbol"):
            lines.append(
                f"   target: file={lesson.get('target_file') or 'none'} "
                f"symbol={lesson.get('target_symbol') or 'none'}"
            )

    updated_at = lessons_section.get("updated_at")
    if updated_at:
        lines.append(f"Updated: {updated_at}")

    return "\n".join(lines)


def format_system_snapshot(snapshot):
    system = (snapshot or {}).get("system") or {}

    lines = [
        "System",
        f"Repo Loaded: {system.get('repo_loaded') if system.get('repo_loaded') is not None else 'none'}",
        f"Known Files: {system.get('known_files_count') if system.get('known_files_count') is not None else 'none'}",
        f"Known Symbols: {system.get('known_symbols_count') if system.get('known_symbols_count') is not None else 'none'}",
        f"Active Route: {system.get('active_route') or 'none'}",
        f"Active Mode: {system.get('active_mode') or 'none'}",
    ]

    updated_at = system.get("updated_at")
    if updated_at:
        lines.append(f"Updated: {updated_at}")

    return "\n".join(lines)


def format_cockpit_snapshot(snapshot):
    sections = [
        format_current_snapshot(snapshot),
        format_last_patch_snapshot(snapshot),
        format_failures_snapshot(snapshot),
        format_lessons_snapshot(snapshot),
        format_system_snapshot(snapshot),
    ]
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Domain Route Handlers
# Extracted from main() to reduce cyclomatic complexity.
# Each handler receives (route, payload, memory, state) and returns a result string.
# ---------------------------------------------------------------------------

def _handle_math_route(route, payload, memory, state):
    """Handle all math research routes. Returns result string."""

    if route == "math_explore":
        from math_domain import CollatzExplorer, get_known_results
        explorer = CollatzExplorer()
        raw_input = (payload.get("input") or "").strip()
        parts = raw_input.split()
        try:
            start = int(parts[0]) if len(parts) >= 1 else 1
            end = int(parts[1]) if len(parts) >= 2 else min(start + 999, 10000)
        except ValueError:
            start, end = 1, 1000

        stopping_times = explorer.stopping_times(start, end)
        max_vals = explorer.max_values(start, end)
        longest_n, longest_t = explorer.find_longest_trajectory(start, end)
        cycle_hit = explorer.search_for_cycle(start, end)
        parity = explorer.parity_patterns(start, min(start + 49, end), prefix_length=6)

        lines = [
            f"[MATH EXPLORE] Collatz n ∈ [{start}, {end}]",
            f"Longest trajectory: n={longest_n} → {longest_t} steps",
            f"Peak value in range: n={max(max_vals, key=max_vals.get)} → {max(max_vals.values())}",
            f"Counterexample found: {'YES — n=' + str(cycle_hit) + ' DOES NOT REACH 1' if cycle_hit else 'None (all reach 1)'}",
            f"Parity prefix groups ({min(len(parity), 5)} of {len(parity)} shown):",
        ]
        for sig, ns in list(parity.items())[:5]:
            lines.append(f"  {sig}: {ns[:6]}{'...' if len(ns) > 6 else ''}")

        memory.store(
            make_dummy_vector(),
            tag="math_explore",
            note=f"Collatz exploration [{start},{end}] | longest={longest_n}:{longest_t}steps",
            status="complete",
            metadata={
                "range": [start, end],
                "longest_n": longest_n,
                "longest_stopping_time": longest_t,
                "counterexample": cycle_hit,
                "known_results": get_known_results(),
            },
        )
        return "\n".join(lines)

    if route == "math_conjecture":
        from math_domain import Conjecture, CollatzExplorer, MathLessonRecorder
        statement = (payload.get("input") or "").strip()
        if not statement:
            return "A conjecture requires a statement. Usage: conjecture <precise mathematical claim>"
        conj = Conjecture(statement=statement, domain="collatz", status="unverified", confidence=0.0)
        explorer = CollatzExplorer()
        counterexample = explorer.search_for_cycle(1, 10000)
        if counterexample:
            conj.record_falsification_attempt("search n∈[1,10000]", succeeded=True)
            status_line = f"FALSIFIED by counterexample n={counterexample}"
        else:
            conj.add_evidence("Survived adversarial search over n∈[1,10000]: all reach 1")
            conj.elevate("supported", 0.3)
            status_line = "Survived initial adversarial testing. Status: supported (confidence: 0.30)"
        memory.store(
            make_dummy_vector(),
            tag="math_conjecture",
            note=f"Conjecture: {statement[:80]} | {status_line}",
            status=conj.status,
            metadata=conj.to_dict(),
        )
        return f"[CONJECTURE REGISTERED]\n{statement}\n\nAdversarial result: {status_line}\nEvidence: {conj.evidence}\nNext: submit to symbolic agent or request formal fragment."

    if route == "math_falsify":
        from math_domain import CollatzExplorer, MathLessonRecorder
        statement = (payload.get("input") or "").strip()
        explorer = CollatzExplorer()
        ranges = [(1, 10000), (10001, 100000), (100001, 500000)]
        found = None
        searched_up_to = 0
        for r_start, r_end in ranges:
            hit = explorer.search_for_cycle(r_start, r_end)
            searched_up_to = r_end
            if hit:
                found = hit
                break
        recorder = MathLessonRecorder()
        if found:
            recorder.record(
                conjecture_statement=statement,
                strategy="adversarial_counterexample_search",
                failure_point=f"n={found} does not reach 1",
                insight=f"Counterexample exists at n={found}. Conjecture is FALSE.",
                agent="adversarial",
            )
            return f"[FALSIFIED] Counterexample found: n={found}\nConjecture: {statement}\nSearch range: n∈[1,{searched_up_to}]"
        recorder.record(
            conjecture_statement=statement,
            strategy="adversarial_counterexample_search",
            failure_point="no counterexample found",
            insight=f"No counterexample in n∈[1,{searched_up_to}]. Conjecture survived this adversarial pass.",
            agent="adversarial",
        )
        return (
            f"[SURVIVED] No counterexample found in n∈[1,{searched_up_to}]\n"
            f"Conjecture: {statement}\n"
            f"This does not prove the conjecture — absence of evidence is not proof.\n"
            f"Next: symbolic agent, stopping time bound, or formal fragment."
        )

    if route == "show_conjectures":
        entries = memory.search_by_tag("math_conjecture")
        if not entries:
            return "No conjectures recorded yet. Use: conjecture <statement>"
        lines = [f"[CONJECTURES] {len(entries)} recorded:"]
        for e in entries[-10:]:
            meta = e.get("metadata") or {}
            lines.append(
                f"  [{meta.get('status','?')} | conf={meta.get('confidence',0):.2f}] "
                f"{meta.get('statement','(no statement)')[:80]}"
            )
        return "\n".join(lines)

    if route == "show_math_lessons":
        from math_domain import MathLessonRecorder
        recorder = MathLessonRecorder()
        lessons = recorder.load_lessons()
        if not lessons:
            return "No math lessons recorded yet. Failed proof attempts will be stored here."
        lines = [f"[MATH LESSONS] {len(lessons)} recorded:"]
        for lesson in lessons[-8:]:
            lines.append(
                f"  [{lesson.get('agent','?')}] Strategy: {lesson.get('strategy','?')}\n"
                f"    Failure: {lesson.get('failure_point','?')}\n"
                f"    Insight: {lesson.get('insight','?')}"
            )
        return "\n".join(lines)

    if route == "math_status":
        from math_domain import get_known_results
        conjectures = memory.search_by_tag("math_conjecture")
        explorations = memory.search_by_tag("math_explore")
        known = get_known_results()
        lines = [
            "=== HIVE MATH STATUS ===",
            "Domain: Collatz Conjecture",
            "Mission: Generate, test, formalize, and refine mathematical knowledge",
            "",
            f"Explorations run:    {len(explorations)}",
            f"Conjectures filed:   {len(conjectures)}",
            "",
            f"Known grounding results ({len(known)}):",
        ]
        for r in known:
            lines.append(f"  [{r['type']}] {r['result'][:80]}")
        lines += [
            "",
            "Commands: explore collatz <start> <end> | conjecture <statement>",
            "          falsify <statement> | show conjectures | show math lessons",
        ]
        return "\n".join(lines)

    return None  # route not handled here


def _handle_code_route(route, payload, memory, state):
    """Handle all code research routes. Returns result string."""

    if route == "code_hypothesize":
        from code_domain import (
            CodeConjecture, CodeExplorer, CodeProgressTracker,
            AdversarialTestAgent
        )
        raw = (payload.get("input") or "").strip()
        if not raw:
            return "Usage: hypothesize <falsifiable claim about code behavior>"
        h_type = "correctness"
        statement = raw
        for t in ("correctness", "performance", "architecture",
                  "security", "invariant", "regression"):
            if raw.lower().startswith(f"{t}:"):
                h_type = t
                statement = raw[len(t)+1:].strip()
                break
        hyp = CodeConjecture(statement=statement, hypothesis_type=h_type)
        explorer = CodeExplorer()
        tracker = CodeProgressTracker()
        evidence_lines = []
        for py_file in sorted(Path(".").glob("*.py")):
            if py_file.name in ("math_domain.py", "code_domain.py"):
                continue
            nested = explorer.detect_nested_loops(str(py_file))
            dangerous = explorer.find_eval_exec_calls(str(py_file))
            if nested and h_type == "performance":
                evidence_lines.append(f"  {py_file.name}: {len(nested)} nested loop(s) detected")
                hyp.add_evidence(f"{py_file.name}: {len(nested)} nested loops")
            if dangerous and h_type == "security":
                evidence_lines.append(
                    f"  {py_file.name}: {len(dangerous)} dangerous call(s): "
                    f"{[d['name'] for d in dangerous]}"
                )
                hyp.add_evidence(f"{py_file.name}: dangerous calls {[d['name'] for d in dangerous]}")
        score = tracker.score(hyp)
        memory.store(
            make_dummy_vector(),
            tag="code_hypothesis",
            note=f"[{h_type}] {statement[:80]}",
            status=hyp.status,
            metadata=hyp.to_dict(),
        )
        lines = [
            f"[HYPOTHESIS REGISTERED — {h_type.upper()}]",
            statement, "",
            "Initial evidence scan:",
        ] + (evidence_lines or ["  No automatic evidence found — run benchmark or probe to gather data."])
        lines += ["", f"Progress: {score['score']}/6 — {score['level_name']}", f"Next:     {score['next_action']}"]
        return "\n".join(lines)

    if route == "code_scan":
        from code_domain import CodeExplorer, AdversarialTestAgent
        target = (payload.get("input") or "").strip() or "."
        explorer = CodeExplorer()
        lines = [f"[CODE SCAN] {target}"]
        py_files = sorted(Path(target if Path(target).is_dir() else ".").glob("*.py"))
        total_nested = 0
        total_dangerous = 0
        high_complexity = []
        for py_file in py_files:
            if py_file.name.startswith("_"):
                continue
            metrics = explorer.get_source_metrics(str(py_file))
            total_nested   += metrics.get("nested_loops", 0)
            total_dangerous += metrics.get("dangerous_calls", 0)
            fns = explorer.get_functions(str(py_file))
            for fn in fns:
                c = explorer.count_complexity(str(py_file), fn["name"])
                if isinstance(c, dict) and c.get("rating") in ("medium", "high"):
                    high_complexity.append(
                        f"  {py_file.name}:{fn['name']} — complexity {c['complexity']} ({c['rating']})"
                    )
        lines += [
            f"Files scanned: {len(py_files)}",
            f"Total nested loops: {total_nested}",
            f"Total dangerous calls (eval/exec): {total_dangerous}",
            f"High/medium complexity functions ({len(high_complexity)}):",
        ] + (high_complexity[:10] or ["  None detected"])
        return "\n".join(lines)

    if route == "code_benchmark":
        return (
            "[BENCHMARK] To benchmark a function, import it in a script and use:\n"
            "  from code_domain import CodeExplorer\n"
            "  explorer = CodeExplorer()\n"
            "  explorer.benchmark(fn, [((arg1,),{}), ((arg2,),{})])\n"
            "Or use: adversarial test <hypothesis_id> to run scaling probes."
        )

    if route == "code_probe":
        from code_domain import CodeExplorer
        target = (payload.get("input") or "").strip()
        explorer = CodeExplorer()
        if target.endswith(".py") and Path(target).exists():
            metrics = explorer.get_source_metrics(target)
            fns = explorer.get_functions(target)
            nested = explorer.detect_nested_loops(target)
            lines = [
                f"[PROBE] {target}",
                f"Lines: {metrics['total_lines']} | Functions: {metrics['functions']} | Classes: {metrics['classes']}",
                f"Nested loops: {len(nested)} | Dangerous calls: {metrics['dangerous_calls']}",
                "Functions:",
            ]
            for fn in fns:
                c = explorer.count_complexity(target, fn["name"])
                rating = c.get("rating","?") if isinstance(c, dict) else "?"
                lines.append(f"  {fn['name']}() — {fn['body_lines']} lines, complexity {c.get('complexity','?')} ({rating})")
            return "\n".join(lines)
        return "[PROBE] Usage: probe <filename.py> — specify a Python file to inspect."

    if route == "code_arch_trace":
        from code_domain import AdversarialTestAgent
        agent = AdversarialTestAgent()
        raw = (payload.get("input") or "").strip()
        parts = [p.strip() for p in raw.replace("→", " ").replace("->", " ").split()]
        if len(parts) >= 2:
            caller, callee = parts[0], parts[1]
            arch_result = agent.architecture_trace(".", (caller, callee))
            lines = [
                f"[ARCHITECTURE TRACE] {arch_result['forbidden_edge']}",
                f"Verdict: {arch_result['verdict']}",
            ]
            if arch_result["violations"]:
                lines.append(f"Violations ({len(arch_result['violations'])}):")
                for v in arch_result["violations"]:
                    lines.append(f"  {v['file']} line {v['lineno']}")
            return "\n".join(lines)
        return "[ARCH TRACE] Usage: trace arch <caller> <callee_function>"

    if route == "code_adversarial":
        from code_domain import CodeLessonRecorder
        raw = (payload.get("input") or "").strip()
        recorder = CodeLessonRecorder()
        return (
            f"[ADVERSARIAL] Hypothesis targeted: {raw}\n"
            f"To run boundary probe: import AdversarialTestAgent from code_domain\n"
            f"and call agent.boundary_probe(fn, type_hint)\n"
            f"Code lessons recorded: {len(recorder.load_lessons())}"
        )

    if route == "show_hypotheses":
        entries = memory.search_by_tag("code_hypothesis")
        if not entries:
            return "No hypotheses registered yet. Use: hypothesize <claim>"
        from code_domain import CODE_PROGRESS_LEVELS
        lines = [f"[HYPOTHESES] {len(entries)} registered:"]
        for e in entries[-10:]:
            meta = e.get("metadata") or {}
            lines.append(
                f"  [{meta.get('status','?')} | {meta.get('hypothesis_type','?')} | "
                f"conf={meta.get('confidence',0):.2f}] "
                f"{meta.get('statement','(no statement)')[:70]}"
            )
        return "\n".join(lines)

    if route == "show_code_lessons":
        from code_domain import CodeLessonRecorder
        recorder = CodeLessonRecorder()
        lessons = recorder.load_lessons()
        if not lessons:
            return "No code lessons recorded yet. Failed strategies will be stored here."
        lines = [f"[CODE LESSONS] {len(lessons)} recorded:"]
        for lesson in lessons[-8:]:
            lines.append(
                f"  [{lesson.get('agent','?')}] {lesson.get('strategy','?')}\n"
                f"    Failed: {lesson.get('failure_point','?')}\n"
                f"    Insight: {lesson.get('insight','?')}"
            )
        return "\n".join(lines)

    if route == "code_status":
        from code_domain import CodeExplorer
        hypotheses = memory.search_by_tag("code_hypothesis")
        explorer = CodeExplorer()
        py_files = list(Path(".").glob("*.py"))
        total_nested = sum(
            len(explorer.detect_nested_loops(str(f)))
            for f in py_files if not f.name.startswith("_")
        )
        lines = [
            "=== HIVE CODE STATUS ===",
            "Domain: Python / Hive codebase",
            "Mission: Form, test, and verify hypotheses about code behavior",
            "",
            f"Project files:       {len(py_files)}",
            f"Nested loops found:  {total_nested}",
            f"Hypotheses filed:    {len(hypotheses)}",
            "",
            "Commands: hypothesize <claim> | scan | probe <file.py>",
            "          trace arch <caller> <callee> | show hypotheses | show code lessons",
        ]
        return "\n".join(lines)

    return None  # route not handled here


def _handle_display_route(route, payload, memory, state, lesson_memory,
                          payload_task_id, payload_patch_id,
                          find_patch_entry, require_patch_metadata,
                          list_pending_pilot_review_patches, list_pending_recoveries,
                          build_pilot_review_packet, format_pilot_review_packet,
                          format_recovery_payload, format_current_snapshot,
                          format_last_patch_snapshot, format_failures_snapshot,
                          format_lessons_snapshot, format_cockpit_snapshot,
                          sync_lessons_observability):
    """Handle all read-only display and inspection routes. Returns result string."""

    if route == "show_current":
        return format_current_snapshot(state.get_observability_snapshot())

    if route == "show_last_patch":
        return format_last_patch_snapshot(state.get_observability_snapshot())

    if route == "show_failures":
        return format_failures_snapshot(state.get_observability_snapshot())

    if route == "show_lessons":
        sync_lessons_observability(state, lesson_memory)
        return format_lessons_snapshot(state.get_observability_snapshot())

    if route == "show_cockpit":
        sync_lessons_observability(state, lesson_memory)
        return format_cockpit_snapshot(state.get_observability_snapshot())

    if route == "show_task":
        task_id = payload_task_id(payload)
        if task_id is None:
            return "Invalid payload for show_task."
        task = memory.get_task_by_id(task_id)
        return task if task else f"Task {task_id} not found."

    if route == "show_plan":
        task_id = payload_task_id(payload)
        if task_id is None:
            return "Invalid payload for show_plan."
        recent_notes = memory.get_recent_notes()
        for entry in reversed(recent_notes):
            if entry.get("tag") != "plan":
                continue
            metadata = entry.get("metadata") or {}
            if metadata.get("task_id") == task_id:
                return metadata.get("plan") or f"Plan for task {task_id} not found."
        return f"Plan for task {task_id} not found."

    if route == "show_pending_patch_reviews":
        pending = list_pending_pilot_review_patches(memory)
        if not pending:
            return "No pending pilot patch reviews."
        lines = ["Pending Pilot Patch Reviews"]
        for entry in pending:
            meta = entry.get("metadata") or {}
            packet = meta.get("review_packet") or {}
            lines.append(
                f"Patch {entry.get('id')} | task={meta.get('task_id') or 'none'} "
                f"file={meta.get('target_file') or 'none'} "
                f"symbol={meta.get('child_target_symbol') or meta.get('target_symbol') or 'none'} "
                f"child={packet.get('child_task_title') or packet.get('child_task_description') or 'none'}"
            )
        return "\n".join(lines)

    if route == "show_pending_recoveries":
        recoveries = list_pending_recoveries(memory)
        if not recoveries:
            return "No pending recoveries."
        lines = ["Pending Recoveries"]
        for entry in recoveries:
            metadata = entry.get("metadata") or {}
            lines.append(
                f"Task {metadata.get('task_id') or entry.get('id')} | "
                f"action={metadata.get('recovery_action') or 'none'} "
                f"status={metadata.get('recovery_status') or 'none'} "
                f"source_patch={metadata.get('recovery_source_patch_id') or 'none'} "
                f"target={metadata.get('target_file') or 'none'}::{metadata.get('target_symbol') or 'none'}"
            )
        return "\n".join(lines)

    if route == "show_recovery":
        task_id = payload_task_id(payload)
        if task_id is None:
            return "Invalid payload for show_recovery."
        task = memory.get_task_by_id(task_id)
        if not task:
            return f"Task {task_id} not found."
        return format_recovery_payload(task_id, task.get("metadata") or {})

    if route == "review_patch":
        patch_id = payload_patch_id(payload)
        if patch_id is None:
            return "Invalid payload for review_patch."
        patch_entry, error = find_patch_entry(memory, patch_id)
        if error or patch_entry is None:
            return error or f"Patch {patch_id} not found."
        meta, error = require_patch_metadata(patch_entry, patch_id)
        if error or meta is None:
            return error or f"Patch {patch_id} has no metadata."
        review_packet = meta.get("review_packet") or build_pilot_review_packet(patch_id, meta)
        return format_pilot_review_packet(review_packet)

    if route == "show_patch":
        patch_id = payload_patch_id(payload)
        if patch_id is None:
            return "Invalid payload for show_patch."
        patch_entry, error = find_patch_entry(memory, patch_id)
        if error or patch_entry is None:
            return error or f"Patch {patch_id} not found."
        meta, error = require_patch_metadata(patch_entry, patch_id)
        if error or meta is None:
            return error or f"Patch {patch_id} has no metadata."
        return (
            f"Patch {patch_id}\n"
            f"Source Task: {meta['task_id']}\n"
            f"File: {meta['target_file']}\n"
            f"Status: {patch_entry.get('status')}\n"
            f"Type: {meta['change_type']}\n"
            f"Risk: {meta['risk_level']}\n"
            f"Reason: {meta['reason']}\n\n"
            f"Pilot Verdict: {meta.get('pilot_verdict') or 'none'}\n"
            f"Pilot Reason: {meta.get('pilot_reason') or 'none'}\n"
            f"Pilot Guidance: {meta.get('pilot_guidance') or 'none'}\n"
            f"Recovery Action: {meta.get('recovery_action') or 'none'}\n"
            f"Recovery Status: {meta.get('recovery_status') or 'none'}\n"
            f"Recovery Reason: {meta.get('recovery_reason') or 'none'}\n\n"
            f"{meta['patch']}"
        )

    return None  # route not handled here


def _handle_task_status_route(route, payload, memory, state,
                               payload_task_id, make_dummy_vector, router):
    """Handle task lifecycle status routes: current, active, delete, block, complete, lessons."""

    if route == "current_task":
        task = memory.get_current_task()
        return task if task else "No active task found."

    if route == "active_task":
        task_id = payload_task_id(payload)
        if task_id is None:
            return "Invalid payload for active_task."
        task = memory.get_task_by_id(task_id)
        if not task:
            return f"Task {task_id} not found."
        memory.update_task_status(task_id, "active")
        return f"Task {task_id} marked as active."

    if route == "delete_task":
        task_id = payload_task_id(payload)
        if task_id is None:
            return "Invalid payload for delete_task."
        memory.delete_task(task_id)
        return f"Task {task_id} deleted."

    if route == "block_task":
        task_id = payload_task_id(payload)
        if task_id is None:
            return "Invalid payload for block_task."
        memory.update_task_status(task_id, "blocked")
        return f"Task {task_id} marked as blocked."

    if route == "complete_task":
        task_id = payload_task_id(payload)
        if task_id is None:
            return "Invalid payload for complete_task."
        memory.update_task_status(task_id, "completed")
        return f"Task {task_id} marked as completed."

    if route == "continue_task":
        task_id = payload_task_id(payload)
        if task_id is None:
            return "Invalid payload for continue_task."
        task = memory.get_task_by_id(task_id)
        if not task:
            return f"Task {task_id} not found."
        result = router.builder.continue_task(task)
        memory.store(
            make_dummy_vector(),
            tag="continued_task",
            note=f'Task {task_id} resumed | {task["note"]}',
            status="continued",
            metadata={"task_id": task_id, "continued_task": result},
        )
        return result

    if route == "lessons":
        from HiveLessonMemory import LessonMemory
        lm = LessonMemory()
        return lm.get_recent_lessons_text()

    return None  # route not handled here


def _resolve_code_task_anchor(task, ready_child, plan, state, task_metadata):
    """
    Build the coder_task and effective_plan dicts from a ready child task.
    Handles anchor resolution, recovery-mode overrides, and metadata merging.
    Returns (coder_task, effective_plan, anchor, child_target_file, child_target_symbol).
    """
    anchor = (task.get("metadata") or {}).get("anchor") or build_anchor_from_text(
        task.get("note"), state_manager=state
    )
    parent_meta = task.get("metadata") or {}
    parent_anchor = dict(parent_meta.get("anchor") or anchor or {})
    is_retry = task_metadata.get("recovery_status") == "retry_ready"

    child_target_file = (
        task_metadata.get("target_file") if is_retry else None
    ) or ready_child.get("target_file") or parent_meta.get("target_file") or parent_anchor.get("target_file")

    child_anchor_guess = build_anchor_from_text(
        ready_child.get("description", task.get("note", "")), state_manager=state
    )

    child_target_symbol = (
        task_metadata.get("target_symbol") if is_retry else None
    ) or ready_child.get("target_symbol") or child_anchor_guess.get("target_symbol") or parent_anchor.get("target_symbol")

    child_target_file = child_target_file or child_anchor_guess.get("target_file") or parent_anchor.get("target_file")

    anchor = merge_anchor_with_span({
        "target_file":   child_target_file,
        "target_symbol": child_target_symbol,
        "scope":         parent_anchor.get("scope") or "single_file",
        "anchor_level":  "symbol" if child_target_symbol else "file",
        "anchor_source": "child_task",
    }, child_target_file, child_target_symbol, state_manager=state)

    coder_task = {
        "id": task["id"], "tag": task.get("tag", "task"), "status": task.get("status", "active"),
        "note": ready_child.get("description", task.get("note", "")),
        "metadata": {
            **parent_meta,
            "target_file":            child_target_file,
            "target_symbol":          child_target_symbol,
            "change_intent":          ready_child.get("change_intent"),
            "expected_operation":     ready_child.get("expected_operation"),
            "completion_cues":        ready_child.get("completion_cues"),
            "task_type":              ready_child.get("task_type"),
            "child_task_id":          ready_child.get("task_id"),
            "parent_task_id":         task["id"],
            "anchor":                 anchor,
            "retry_source":           task_metadata.get("retry_source"),
            "pilot_guidance":         task_metadata.get("pilot_guidance"),
            "pilot_guardrail_text":   task_metadata.get("pilot_guardrail_text"),
            "reflector_summary":      task_metadata.get("reflector_summary"),
            "rejected_patch_excerpt": task_metadata.get("rejected_patch_excerpt"),
        },
        "target_file":        child_target_file,
        "target_symbol":      child_target_symbol,
        "change_intent":      ready_child.get("change_intent"),
        "expected_operation": ready_child.get("expected_operation"),
        "completion_cues":    ready_child.get("completion_cues"),
        "task_type":          ready_child.get("task_type"),
        "child_task_id":      ready_child.get("task_id"),
        "parent_task_id":     task["id"],
        "retry_source":       task_metadata.get("retry_source"),
    }
    copy_anchor_fields(coder_task["metadata"], anchor)
    copy_anchor_fields(coder_task, anchor)

    if not isinstance(plan, dict):
        plan = dict(plan)
    effective_plan = {
        **plan,
        "next_action": (
            task_metadata.get("pilot_guidance") if is_retry
            else ready_child.get("description", plan.get("next_action"))
        ),
        "tasks": [ready_child],
        "active_child_task_id":     ready_child.get("task_id"),
        "active_child_task_title":  ready_child.get("title"),
        "active_child_target_file": ready_child.get("target_file"),
    }

    return coder_task, effective_plan, anchor, child_target_file, child_target_symbol


def _store_code_task_result(result, task_id, task, ready_child, anchor,
                             child_target_symbol, task_metadata,
                             memory, state, lesson_memory,
                             make_dummy_vector, build_pilot_review_packet,
                             update_last_patch_snapshot, record_failure_observability,
                             sync_lessons_observability):
    """Store patch result in memory and update all state snapshots."""
    patch_status = result.get("status", "proposed")
    patch_label = "blocked" if patch_status == "blocked" else "pending_pilot_review"
    stored_patch_status = patch_label

    patch_metadata = {
        **result,
        "task_id":           task_id,
        "plan_id":           f"plan-{task_id}",
        "patch_id":          result.get("patch_id") or f"patch-{task_id}",
        "anchor":            anchor,
        "task_type":         None,
        "task_note":         task.get("note"),
        "pilot_verdict":     None,
        "pilot_reason":      None,
        "pilot_guidance":    None,
        "location_correct":  None,
        "task_alignment":    None,
        "plan_step_alignment": None,
        "child_task_id":              ready_child.get("task_id"),
        "child_task_description":     ready_child.get("description"),
        "child_target_file":          ready_child.get("target_file"),
        "child_target_symbol":        child_target_symbol,
        "child_change_intent":        ready_child.get("change_intent"),
        "child_expected_operation":   ready_child.get("expected_operation"),
        "child_completion_cues":      ready_child.get("completion_cues"),
        "child_task_type":            ready_child.get("task_type"),
        "recovery_action":            task_metadata.get("recovery_action"),
        "recovery_status":            "completed" if task_metadata.get("recovery_status") == "retry_ready" else None,
        "recovery_reason":            task_metadata.get("recovery_reason"),
    }
    patch_metadata["review_packet"] = build_pilot_review_packet(patch_metadata["patch_id"], patch_metadata)

    memory.store(
        make_dummy_vector(), tag="patch",
        note=f'Task {task_id} patch {patch_label} | {result.get("target_file", "unknown")}',
        status=stored_patch_status, metadata=patch_metadata,
    )
    update_last_patch_snapshot(
        state, patch_metadata,
        target_symbol=patch_metadata.get("child_target_symbol") or patch_metadata.get("context_target"),
        change_intent=patch_metadata.get("child_change_intent"),
        expected_operation=patch_metadata.get("child_expected_operation"),
        patch_status=stored_patch_status,
        validation_outcome=(
            "passed" if (
                (patch_metadata.get("sandbox_report") or {}).get("applied") is True
                and (patch_metadata.get("sandbox_report") or {}).get("syntax_valid") is True
                and (patch_metadata.get("sandbox_report") or {}).get("semantic_valid") is True
            ) else "failed" if stored_patch_status == "blocked" else "pending"
        ),
    )
    if stored_patch_status == "blocked":
        record_failure_observability(
            state,
            patch_metadata.get("llm_error") or patch_metadata.get("reason"),
            task=task, patch_data=patch_metadata,
        )
    elif task_metadata.get("recovery_status") == "retry_ready":
        updated = dict(task_metadata)
        updated["recovery_status"] = "completed"
        memory.update_task_metadata(task_id, updated)
    sync_lessons_observability(state, lesson_memory)
    return patch_metadata


def _apply_pilot_rejection(meta, recovery_payload, recovery_action, pilot_guidance,
                            guardrail_text, patch_id, memory, state, lesson_memory,
                            make_dummy_vector, update_last_patch_snapshot,
                            update_current_snapshot, sync_lessons_observability,
                            pilot_verdict="revise"):
    """
    Shared logic for pilot_revise_patch and pilot_reject_patch.
    Updates parent task metadata, stores recovery record, updates snapshots.
    Returns result message string.
    """
    parent_task_id = meta.get("task_id")
    if parent_task_id:
        parent_task = memory.get_task_by_id(parent_task_id)
        if parent_task:
            task_metadata = dict(parent_task.get("metadata") or {})
            task_metadata.update(recovery_payload)
            task_metadata["pilot_guidance"]                  = pilot_guidance
            task_metadata["pilot_guardrail_text"]            = guardrail_text
            task_metadata["reflector_summary"]               = recovery_payload.get("reflector_summary")
            task_metadata["rejected_patch_excerpt"]          = recovery_payload.get("rejected_patch_excerpt")
            task_metadata["recovery_child_task_description"] = meta.get("child_task_description")
            task_metadata["child_task_description"]          = meta.get("child_task_description")
            task_metadata["child_task_id"]                   = meta.get("child_task_id")
            task_metadata["target_file"]   = recovery_payload.get("target_file")   or task_metadata.get("target_file")
            task_metadata["target_symbol"] = recovery_payload.get("target_symbol") or task_metadata.get("target_symbol")
            task_metadata["pilot_replan_required"] = recovery_action == "replan_task"
            memory.update_task_metadata(parent_task_id, task_metadata)
            memory.store(
                make_dummy_vector(), tag="recovery",
                note=f"Task {parent_task_id} recovery {recovery_payload.get('recovery_status')} | action: {recovery_action}",
                status=recovery_payload.get("recovery_status"),
                metadata={"task_id": parent_task_id, **recovery_payload},
            )

    update_last_patch_snapshot(
        state, meta, patch_id=patch_id, patch_status="rejected",
        pilot_verdict=pilot_verdict, pilot_reason=meta.get("pilot_reason"),
        pilot_guidance=pilot_guidance, recovery_action=recovery_action,
        recovery_status=recovery_payload.get("recovery_status"),
        rejection_reason=pilot_guidance,
    )
    updated_task = memory.get_task_by_id(parent_task_id) if parent_task_id else None
    if updated_task:
        update_current_snapshot(state, task=updated_task, status=updated_task.get("status"))
    sync_lessons_observability(state, lesson_memory)
    action_word = "revision guidance" if pilot_verdict == "revise" else "rejection"
    return f"Patch {patch_id} sent back with pilot {action_word}. Recovery action: {recovery_action}."


def _handle_patch_review_route(route, payload, memory, state, lesson_memory,
                                payload_patch_id, find_patch_entry, require_patch_metadata,
                                update_patch_entry, record_pilot_guardrail,
                                decide_recovery_action, build_recovery_payload,
                                update_last_patch_snapshot, update_current_snapshot,
                                sync_lessons_observability, make_dummy_vector):
    """Handle pilot patch review routes: accept, revise, reject."""
    patch_id = payload_patch_id(payload)

    if route == "pilot_accept_patch":
        if patch_id is None:
            return "Invalid payload for pilot_accept_patch."
        patch_entry, error = find_patch_entry(memory, patch_id)
        if error or patch_entry is None:
            return error or f"Patch {patch_id} not found."
        if patch_entry.get("status") != "pending_pilot_review":
            return f"Patch {patch_id} is not awaiting pilot review."
        meta, error = require_patch_metadata(patch_entry, patch_id)
        if error or meta is None:
            return error or f"Patch {patch_id} has no metadata."
        meta = dict(meta)
        meta["pilot_verdict"] = "accept"
        meta["pilot_reason"]  = "Pilot confirmed patch intent alignment."
        meta["pilot_guidance"] = None
        meta["location_correct"] = True
        meta["task_alignment"] = True
        meta["plan_step_alignment"] = True
        update_patch_entry(memory, patch_id, metadata=meta, status="approved")
        parent_task = memory.get_task_by_id(meta.get("task_id")) if meta.get("task_id") else None
        if parent_task:
            tm = dict(parent_task.get("metadata") or {})
            tm["recovery_status"] = "completed"
            tm["recovery_action"] = tm.get("recovery_action")
            memory.update_task_metadata(meta.get("task_id"), tm)
        update_last_patch_snapshot(state, meta, patch_id=patch_id, patch_status="approved",
                                   pilot_verdict="accept", pilot_reason=meta["pilot_reason"],
                                   pilot_guidance=None)
        sync_lessons_observability(state, lesson_memory)
        return f"Patch {patch_id} accepted by pilot and marked approved."

    if route == "pilot_revise_patch":
        pilot_guidance = str(payload.get("pilot_guidance") or "").strip()
        if patch_id is None or not pilot_guidance:
            return "Invalid payload for pilot_revise_patch."
        patch_entry, error = find_patch_entry(memory, patch_id)
        if error or patch_entry is None:
            return error or f"Patch {patch_id} not found."
        meta, error = require_patch_metadata(patch_entry, patch_id)
        if error or meta is None:
            return error or f"Patch {patch_id} has no metadata."
        meta = dict(meta)
        meta["pilot_verdict"]  = "revise"
        meta["pilot_reason"]   = "Pilot requested revision for intent alignment."
        meta["pilot_guidance"] = pilot_guidance
        meta["location_correct"] = (
            False if any(t in pilot_guidance.lower() for t in ("wrong place","wrong file","wrong symbol"))
            else None
        )
        meta["task_alignment"] = False
        meta["plan_step_alignment"] = False
        recovery_action  = decide_recovery_action(meta, pilot_guidance, state_manager=state)
        recovery_payload = build_recovery_payload(meta, recovery_action, pilot_guidance, state_manager=state)
        meta.update(recovery_payload)
        update_patch_entry(memory, patch_id, metadata=meta, status="rejected")
        guardrail_text = record_pilot_guardrail(
            lesson_memory, meta, pilot_verdict="revise", pilot_reason=meta["pilot_reason"],
            pilot_guidance=pilot_guidance, location_correct=meta["location_correct"],
            task_alignment=False, plan_step_alignment=False,
        )
        return _apply_pilot_rejection(
            meta, recovery_payload, recovery_action, pilot_guidance, guardrail_text,
            patch_id, memory, state, lesson_memory, make_dummy_vector,
            update_last_patch_snapshot, update_current_snapshot,
            sync_lessons_observability, pilot_verdict="revise",
        )

    if route == "pilot_reject_patch":
        pilot_reason = str(payload.get("pilot_reason") or "").strip()
        if patch_id is None or not pilot_reason:
            return "Invalid payload for pilot_reject_patch."
        patch_entry, error = find_patch_entry(memory, patch_id)
        if error or patch_entry is None:
            return error or f"Patch {patch_id} not found."
        meta, error = require_patch_metadata(patch_entry, patch_id)
        if error or meta is None:
            return error or f"Patch {patch_id} has no metadata."
        meta = dict(meta)
        meta["pilot_verdict"]  = "reject"
        meta["pilot_reason"]   = pilot_reason
        meta["pilot_guidance"] = pilot_reason
        meta["location_correct"] = (
            False if any(t in pilot_reason.lower() for t in ("wrong place","wrong file","wrong symbol"))
            else None
        )
        meta["task_alignment"] = False
        meta["plan_step_alignment"] = False
        recovery_action  = decide_recovery_action(meta, pilot_reason, state_manager=state)
        recovery_payload = build_recovery_payload(meta, recovery_action, pilot_reason, state_manager=state)
        meta.update(recovery_payload)
        update_patch_entry(memory, patch_id, metadata=meta, status="rejected")
        guardrail_text = record_pilot_guardrail(
            lesson_memory, meta, pilot_verdict="reject", pilot_reason=pilot_reason,
            pilot_guidance=pilot_reason, location_correct=meta["location_correct"],
            task_alignment=False, plan_step_alignment=False,
        )
        return _apply_pilot_rejection(
            meta, recovery_payload, recovery_action, pilot_reason, guardrail_text,
            patch_id, memory, state, lesson_memory, make_dummy_vector,
            update_last_patch_snapshot, update_current_snapshot,
            sync_lessons_observability, pilot_verdict="reject",
        )

    return None


def _handle_plan_task(task_id, memory, state, router, lesson_memory,
                      make_dummy_vector, build_anchor_from_text,
                      enrich_task_anchor_for_planning, record_failure_observability,
                      update_current_snapshot, find_plan_for_task,
                      _initialize_child_task_statuses, _get_first_ready_child_task):
    """Execute plan_task route. Returns result dict or string."""
    task = memory.get_task_by_id(task_id)
    if not task:
        return f"Task {task_id} not found."

    task = enrich_task_anchor_for_planning(task, memory=memory, state_manager=state)
    task_metadata = task.get("metadata") or {}
    recovery_hint = ""
    if task_metadata.get("recovery_status") == "replan_ready":
        recovery_hint = (
            "PILOT REPLAN CONTEXT:\n"
            f"- Original task note: {task.get('note')}\n"
            f"- Failed child task: {task_metadata.get('child_task_description') or task_metadata.get('recovery_child_task_description') or 'none'}\n"
            f"- Pilot correction: {task_metadata.get('pilot_guidance') or task_metadata.get('recovery_reason') or 'none'}\n"
            f"- Rejected patch summary: {task_metadata.get('rejected_patch_excerpt') or 'none'}\n"
            "- Re-derive the next child task without drifting from the original goal.\n"
            "- Prefer changing the step decomposition before changing the overall task.\n"
            "- Preserve the parent task unless the pilot guidance clearly changes it."
        )

    result = router.planner.plan_task(task, hint=recovery_hint)
    anchor = task_metadata.get("anchor") or build_anchor_from_text(task.get("note"), state_manager=state)
    stored_target_file = task_metadata.get("target_file")

    if result.get("status") == "blocked":
        updated_metadata = dict(task_metadata)
        updated_metadata["pilot_replan_required"] = False
        if updated_metadata.get("recovery_status") == "replan_ready":
            updated_metadata["recovery_status"] = "blocked"
        memory.update_task_metadata(task_id, updated_metadata)
        record_failure_observability(state, result.get("llm_error", "unknown planner error"), task=task)
        memory.update_task_status(task_id, "blocked")
        memory.store(
            make_dummy_vector(), tag="plan",
            note=f'Task {task_id} planning blocked | {result.get("llm_error", "unknown planner error")}',
            status="blocked",
            metadata={"task_id": task_id, "plan_id": f"plan-{task_id}", "plan": result, "anchor": anchor},
        )
    else:
        updated_metadata = dict(task_metadata)
        updated_metadata["pilot_replan_required"] = False
        if updated_metadata.get("recovery_status") == "replan_ready":
            updated_metadata["recovery_status"] = "completed"
            updated_metadata["recovery_action"] = "replan_task"
        memory.update_task_metadata(task_id, updated_metadata)
        result = _initialize_child_task_statuses(result)

        if stored_target_file:
            deps = result.get("dependencies") or []
            if not isinstance(deps, list):
                deps = [deps]
            if stored_target_file not in deps:
                deps.insert(0, stored_target_file)
            result["dependencies"] = deps
            result["target_file"] = stored_target_file

        current_child = _get_first_ready_child_task(result)
        update_current_snapshot(state, task=task, plan=result, child=current_child, status="planned")
        memory.update_task_status(task_id, "planned")
        memory.store(
            make_dummy_vector(), tag="plan",
            note=f'Task {task_id} planned | {result["goal"]} | next: {result["next_action"]}',
            status="planned",
            metadata={"task_id": task_id, "plan_id": f"plan-{task_id}", "plan": result, "anchor": anchor},
        )
    return result


def _handle_pilot_task_intent(task_id, pilot_input, memory, state,
                               make_dummy_vector, build_anchor_from_text,
                               merge_pilot_context, extract_required_completion_cues,
                               merge_completion_cues, merge_anchor_with_span,
                               update_current_snapshot, find_plan_for_task):
    """Execute pilot_task_intent route. Returns result string."""
    task = memory.get_task_by_id(task_id)
    if not task:
        return f"Task {task_id} not found."

    metadata = dict(task.get("metadata") or {})
    pilot_context = merge_pilot_context(metadata.get("pilot_context"), pilot_input)
    anchor_update = build_anchor_from_text(pilot_input, state_manager=state)
    new_cues = extract_required_completion_cues(pilot_input)

    metadata["pilot_context"] = pilot_context
    metadata["pilot_intent"]  = pilot_context.get("current_intent")
    metadata["completion_cues"] = merge_completion_cues(metadata.get("completion_cues"), new_cues)

    existing_anchor = dict(metadata.get("anchor") or {})
    anchor_replaced = False
    if anchor_update.get("target_file"):
        old_target_file = metadata.get("target_file") or existing_anchor.get("target_file")
        if old_target_file != anchor_update["target_file"] or not anchor_update.get("target_symbol"):
            anchor_replaced = True
            existing_anchor = {}
            for key in ("target_symbol_id", "lineno", "end_lineno", "col_offset", "end_col_offset"):
                metadata.pop(key, None)
        metadata["target_file"] = anchor_update["target_file"]
        metadata["target_symbol"] = anchor_update.get("target_symbol")
    elif not metadata.get("target_file") and anchor_update.get("target_symbol"):
        metadata["target_symbol"] = anchor_update["target_symbol"]

    target_file   = existing_anchor.get("target_file")   or metadata.get("target_file")
    target_symbol = existing_anchor.get("target_symbol") or metadata.get("target_symbol")
    if target_file or target_symbol:
        metadata["anchor"] = merge_anchor_with_span(
            {**existing_anchor, "target_file": target_file, "target_symbol": target_symbol,
             "scope": existing_anchor.get("scope") or "single_file",
             "anchor_level": "symbol" if target_symbol else "file",
             "anchor_source": "pilot_guidance" if anchor_replaced else existing_anchor.get("anchor_source") or "user_input"},
            target_file, target_symbol, state_manager=state,
        )
        copy_anchor_fields(metadata, metadata["anchor"])

    metadata["pilot_replan_required"] = find_plan_for_task(memory, task_id) is not None
    memory.update_task_metadata(task_id, metadata)
    updated_task = memory.get_task_by_id(task_id)
    update_current_snapshot(state, task=updated_task, status=updated_task.get("status"))
    memory.store(
        make_dummy_vector(), tag="pilot_intent",
        note=f"Task {task_id} pilot intent updated | {pilot_context.get('intent_summary')}",
        status="updated",
        metadata={"task_id": task_id, "pilot_context": pilot_context},
    )
    if metadata.get("pilot_replan_required"):
        return f"Pilot intent updated for task {task_id}. Re-run plan task {task_id} before coding."
    return f"Pilot intent updated for task {task_id}."


def _handle_patch_apply_route(route, payload, memory, state, router,
                               payload_patch_id, find_patch_entry, require_patch_metadata,
                               find_backup_for_patch, find_plan_for_task,
                               update_last_patch_snapshot, record_failure_observability,
                               make_dummy_vector, _complete_child_task):
    """Handle apply_patch, verify_patch, rollback_patch routes."""
    patch_id = payload_patch_id(payload)
    if patch_id is None:
        return f"Invalid payload for {route}."

    patch_entry, error = find_patch_entry(memory, patch_id)
    if error or patch_entry is None:
        return error or f"Patch {patch_id} not found."

    meta, error = require_patch_metadata(patch_entry, patch_id)
    if error or meta is None:
        return error or f"Patch {patch_id} has no metadata."
    meta = dict(meta)

    if route == "apply_patch":
        if patch_entry.get("status") != "approved":
            return f"Patch {patch_id} must be accepted by the pilot and approved first."
        target_file  = meta["target_file"]
        patch_text   = meta["patch"]
        patch_reason = meta.get("reason", "")
        file_text    = state.get_effective_file_text(target_file)
        try:
            verification = router.executor.verify_patch_context(patch_text, target_file, file_text=file_text)
            if not verification["verified"]:
                record_failure_observability(state, f"Patch {patch_id} failed verification: {verification['checks']}", patch_data=meta)
                update_last_patch_snapshot(state, meta, patch_id=patch_id, patch_status="apply_failed",
                                           validation_outcome="failed",
                                           rejection_reason=f"Patch {patch_id} failed verification: {verification['checks']}")
                return f"Patch {patch_id} failed verification: {verification['checks']}"

            backup = router.executor.backup_file(target_file)
            router.executor.apply_patch(patch_text, target_file, patch_reason=patch_reason, file_text=file_text)
            memory.update_task_status(patch_id, "applied")
            updated_text = Path(target_file).read_text(encoding="utf-8")
            state.record_patch_apply(target_file, patch_id, updated_text)
            state.rebuild_repo_map()
            state.save_snapshot()

            child_task_id  = meta.get("child_task_id")
            parent_task_id = meta.get("task_id")
            if child_task_id and parent_task_id:
                plan = find_plan_for_task(memory, parent_task_id)
                if plan:
                    updated_plan = _complete_child_task(plan, child_task_id)
                    memory.store(
                        make_dummy_vector(), tag="plan",
                        note=f'Task {parent_task_id} plan updated | {updated_plan["goal"]} | next: {updated_plan.get("next_action","")}',
                        status="planned",
                        metadata={"task_id": parent_task_id, "plan_id": f"plan-{parent_task_id}", "plan": updated_plan},
                    )
            memory.store(
                make_dummy_vector(), tag="patch_apply",
                note=f"Patch {patch_id} applied to {target_file} | backup: {backup}",
                status="applied",
                metadata={"apply_id": f"apply-{patch_id}", "patch_id": patch_id,
                          "task_id": meta.get("task_id"), "plan_id": meta.get("plan_id"),
                          "target_file": target_file, "backup_path": backup},
            )
            update_last_patch_snapshot(state, meta, patch_id=patch_id, patch_status="applied",
                                       validation_outcome="passed", rejection_reason=None)
            return f"Patch {patch_id} applied successfully.\nBackup created: {backup}"
        except Exception as e:
            record_failure_observability(state, str(e), patch_data=meta)
            update_last_patch_snapshot(state, meta, patch_id=patch_id, patch_status="apply_failed",
                                       validation_outcome="failed", rejection_reason=str(e))
            return f"Patch {patch_id} failed to apply: {e}"

    if route == "verify_patch":
        target_file = meta.get("target_file")
        patch_text  = meta.get("patch", "")
        file_text   = state.get_effective_file_text(target_file)
        verification = router.executor.verify_patch_context(patch_text, target_file, file_text=file_text)
        semantic     = router.executor.validate_patch_semantics(
            patch_text, target_file, verification=verification,
            patch_reason=meta.get("reason", ""), file_text=file_text,
        )
        both_ok = verification["verified"] and semantic["valid"]
        update_last_patch_snapshot(
            state, meta, patch_id=patch_id,
            patch_status=patch_entry.get("status") or meta.get("status"),
            validation_outcome="passed" if both_ok else "failed",
            rejection_reason=None if both_ok else str({"verification": verification["checks"], "semantic": semantic["checks"]}),
        )
        if not both_ok:
            record_failure_observability(state, str({"verification": verification["checks"], "semantic": semantic["checks"]}), patch_data=meta)
        return {"patch_id": patch_id, "verified": verification["verified"], "checks": verification["checks"],
                "anchor_index": verification["anchor_index"], "semantic_valid": semantic["valid"],
                "semantic_checks": semantic["checks"], "semantic_details": semantic["details"]}

    if route == "rollback_patch":
        target_file = meta["target_file"]
        backup_path = find_backup_for_patch(memory, patch_id)
        if not backup_path:
            return f"No backup found for patch {patch_id}."
        try:
            router.executor.restore_backup(backup_path, target_file)
            memory.update_task_status(patch_id, "rolled_back")
            restored_text = Path(target_file).read_text(encoding="utf-8")
            state.record_patch_rollback(target_file, patch_id, restored_text)
            state.save_snapshot()
            update_last_patch_snapshot(state, meta, patch_id=patch_id, patch_status="rolled_back")
            return f"Patch {patch_id} rolled back successfully."
        except Exception as e:
            record_failure_observability(state, str(e), patch_data=meta)
            update_last_patch_snapshot(state, meta, patch_id=patch_id, patch_status="rollback_failed", rejection_reason=str(e))
            return f"Rollback failed: {e}"

    return None


def main():
    memory = HiveMemoryAgent(device="cpu")
    state = HiveStateManager(repo_root=".")
    state.load_snapshot()
    repo_map = RepoMap(root=".")
    state.set_repo_map(repo_map.build())

    router = Router()
    router.planner = router.planner.__class__(state_manager=state)
    interface = Interface()
    reflector = Reflector()
    lesson_memory = LessonMemory()
    sync_lessons_observability(state, lesson_memory)

    router.coder = router.coder.__class__(
        memory=memory,
        state_manager=state,
        executor=router.executor,
    )

    print("Hive Zero v0.1.2.0 Online")

    while True:
        user_input = input("\nPilot > ")
        message = interface.process_input(user_input)
        route, payload = router.route(user_input, message)
        state.set_active_route(route)
        state.save_snapshot()

        if user_input.lower().startswith("store "):
            text = user_input[6:]

            anchor = build_anchor_from_text(text, state_manager=state)
            completion_cues = extract_required_completion_cues(text)

            memory.store(
                make_dummy_vector(),
                tag=text,
                note=text,
                status="stored",
                metadata={
                    "target_file": anchor.get("target_file"),
                    "target_symbol": anchor.get("target_symbol"),
                    "completion_cues": completion_cues,
                    "anchor": anchor,
                },
            )

            result = f"Stored memory with tag: {text} | target_file: {anchor.get('target_file') or 'none'}"

        elif route == "memory":
            recent_notes = memory.get_recent_notes()
            if not recent_notes:
                result = "Hive Memory is empty."
            else:
                result = "\n".join(
                    f"Task {e['id']} [{e['tag']}] ({e['status']}) {e['note']} ({e['timestamp']})"
                    for e in recent_notes
                )

        elif route == "plan_task":
            task_id = payload_task_id(payload)
            if task_id is None:
                result = "Invalid payload for plan_task."
            else:
                result = _handle_plan_task(
                    task_id, memory, state, router, lesson_memory,
                    make_dummy_vector, build_anchor_from_text,
                    enrich_task_anchor_for_planning, record_failure_observability,
                    update_current_snapshot, find_plan_for_task,
                    _initialize_child_task_statuses, _get_first_ready_child_task,
                )

        elif route == "pilot_task_intent":
            task_id = payload_task_id(payload)
            pilot_input = str(payload.get("pilot_input") or "").strip()
            if task_id is None or not pilot_input:
                result = "Invalid payload for pilot_task_intent."
            else:
                result = _handle_pilot_task_intent(
                    task_id, pilot_input, memory, state, make_dummy_vector,
                    build_anchor_from_text, merge_pilot_context,
                    extract_required_completion_cues, merge_completion_cues,
                    merge_anchor_with_span, update_current_snapshot, find_plan_for_task,
                )

        elif route == "help":
            result = (
                "Available Commands:\n"
                "- memory | lessons | current task | help\n"
                "- show current | show last patch | show failures | show lessons | show cockpit\n"
                "- show task <id> | show patch <id> | review patch <id> | show recovery <id> | show plan <id>\n"
                "- pending patch reviews | pending recoveries\n"
                "- plan task <id> | code task <id> | continue task <id> | complete task <id>\n"
                "- active task <id> | block task <id> | delete task <id>\n"
                "- pilot task <id> <guidance>\n"
                "- pilot accept patch <id> | pilot revise patch <id> <guidance> | pilot reject patch <id> <reason>\n"
                "- approve patch <id> | reject patch <id> | apply patch <id>\n"
                "- verify patch <id> | rollback patch <id>\n"
                "- hypothesize <claim> | scan | probe <file.py> | trace arch <caller> <callee>\n"
                "- explore collatz <start> <end> | conjecture <statement> | falsify <statement>\n"
                "- show hypotheses | show code lessons | show conjectures | show math lessons\n"
                "- code status | math status | store <text>"
            )

        elif route in ("active_task", "delete_task", "block_task",
                       "complete_task", "continue_task", "lessons"):
            result = _handle_task_status_route(route, payload, memory, state,
                                                payload_task_id, make_dummy_vector, router)

        elif route == "current_task":
            result = _handle_task_status_route(route, payload, memory, state,
                                                payload_task_id, make_dummy_vector, router)

        elif route == "show_current":
            result = _handle_display_route(
                route, payload, memory, state, lesson_memory,
                payload_task_id, payload_patch_id,
                find_patch_entry, require_patch_metadata,
                list_pending_pilot_review_patches, list_pending_recoveries,
                build_pilot_review_packet, format_pilot_review_packet,
                format_recovery_payload, format_current_snapshot,
                format_last_patch_snapshot, format_failures_snapshot,
                format_lessons_snapshot, format_cockpit_snapshot,
                sync_lessons_observability)

        elif route == "show_last_patch":
            result = _handle_display_route(
                route, payload, memory, state, lesson_memory,
                payload_task_id, payload_patch_id,
                find_patch_entry, require_patch_metadata,
                list_pending_pilot_review_patches, list_pending_recoveries,
                build_pilot_review_packet, format_pilot_review_packet,
                format_recovery_payload, format_current_snapshot,
                format_last_patch_snapshot, format_failures_snapshot,
                format_lessons_snapshot, format_cockpit_snapshot,
                sync_lessons_observability)

        elif route == "show_failures":
            result = _handle_display_route(
                route, payload, memory, state, lesson_memory,
                payload_task_id, payload_patch_id,
                find_patch_entry, require_patch_metadata,
                list_pending_pilot_review_patches, list_pending_recoveries,
                build_pilot_review_packet, format_pilot_review_packet,
                format_recovery_payload, format_current_snapshot,
                format_last_patch_snapshot, format_failures_snapshot,
                format_lessons_snapshot, format_cockpit_snapshot,
                sync_lessons_observability)

        elif route == "show_lessons":
            result = _handle_display_route(
                route, payload, memory, state, lesson_memory,
                payload_task_id, payload_patch_id,
                find_patch_entry, require_patch_metadata,
                list_pending_pilot_review_patches, list_pending_recoveries,
                build_pilot_review_packet, format_pilot_review_packet,
                format_recovery_payload, format_current_snapshot,
                format_last_patch_snapshot, format_failures_snapshot,
                format_lessons_snapshot, format_cockpit_snapshot,
                sync_lessons_observability)

        elif route == "show_cockpit":
            result = _handle_display_route(
                route, payload, memory, state, lesson_memory,
                payload_task_id, payload_patch_id,
                find_patch_entry, require_patch_metadata,
                list_pending_pilot_review_patches, list_pending_recoveries,
                build_pilot_review_packet, format_pilot_review_packet,
                format_recovery_payload, format_current_snapshot,
                format_last_patch_snapshot, format_failures_snapshot,
                format_lessons_snapshot, format_cockpit_snapshot,
                sync_lessons_observability)

        elif route == "show_task":
            result = _handle_display_route(
                route, payload, memory, state, lesson_memory,
                payload_task_id, payload_patch_id,
                find_patch_entry, require_patch_metadata,
                list_pending_pilot_review_patches, list_pending_recoveries,
                build_pilot_review_packet, format_pilot_review_packet,
                format_recovery_payload, format_current_snapshot,
                format_last_patch_snapshot, format_failures_snapshot,
                format_lessons_snapshot, format_cockpit_snapshot,
                sync_lessons_observability)

        elif route == "continue_task":
            result = _handle_task_status_route(route, payload, memory, state,
                                                payload_task_id, make_dummy_vector, router)
        elif route == "code_task":
            task_id = payload_task_id(payload)
            if task_id is None:
                result = "Invalid payload for code_task."
            else:
                task = memory.get_task_by_id(task_id)
                task_metadata = (task or {}).get("metadata") or {}

                if not task:
                    result = f"Task {task_id} not found."
                elif task_metadata.get("pilot_replan_required") is True:
                    result = f"Task {task_id} has updated pilot intent. Run plan task {task_id} again before coding."
                elif task_metadata.get("recovery_status") == "blocked":
                    result = f"Task {task_id} has a blocked recovery state: {task_metadata.get('recovery_reason') or 'pilot clarification required'}"
                elif task_metadata.get("recovery_status") == "replan_ready":
                    result = f"Task {task_id} requires re-planning before coding. Run plan task {task_id}."
                else:
                    plan = find_plan_for_task(memory, task_id)
                    ready_child = None

                    if not plan:
                        result = f"Task {task_id} has no plan. Run plan task {task_id} first."
                    elif plan.get("status") == "blocked":
                        result = f"Task {task_id} has a blocked plan: {plan.get('llm_error', 'unknown planner error')}"
                    else:
                        ready_child = _get_first_ready_child_task(plan)

                    if ready_child:
                        memory.store(
                            make_dummy_vector(), tag="plan",
                            note=f'Task {task_id} plan updated | {plan.get("goal","<unknown goal>")} | next: {plan.get("next_action","")}',
                            status="planned",
                            metadata={"task_id": task_id, "plan_id": f"plan-{task_id}", "plan": plan if isinstance(plan, dict) else {}},
                        )
                        update_current_snapshot(state, task=task, plan=plan, child=ready_child,
                                                status=ready_child.get("status") or "current")

                        coder_task, effective_plan, anchor, child_target_file, child_target_symbol = (
                            _resolve_code_task_anchor(task, ready_child, plan, state, task_metadata)
                        )

                        result = router.coder.generate_patch_with_revisions(coder_task, effective_plan, reflector)

                        _store_code_task_result(
                            result, task_id, task, ready_child, anchor, child_target_symbol,
                            task_metadata, memory, state, lesson_memory, make_dummy_vector,
                            build_pilot_review_packet, update_last_patch_snapshot,
                            record_failure_observability, sync_lessons_observability,
                        )

        elif route in ("show_plan", "show_pending_patch_reviews", "show_pending_recoveries",
                       "show_recovery", "review_patch", "show_patch"):
            _display_ctx = dict(
                payload=payload, memory=memory, state=state, lesson_memory=lesson_memory,
                payload_task_id=payload_task_id, payload_patch_id=payload_patch_id,
                find_patch_entry=find_patch_entry, require_patch_metadata=require_patch_metadata,
                list_pending_pilot_review_patches=list_pending_pilot_review_patches,
                list_pending_recoveries=list_pending_recoveries,
                build_pilot_review_packet=build_pilot_review_packet,
                format_pilot_review_packet=format_pilot_review_packet,
                format_recovery_payload=format_recovery_payload,
                format_current_snapshot=format_current_snapshot,
                format_last_patch_snapshot=format_last_patch_snapshot,
                format_failures_snapshot=format_failures_snapshot,
                format_lessons_snapshot=format_lessons_snapshot,
                format_cockpit_snapshot=format_cockpit_snapshot,
                sync_lessons_observability=sync_lessons_observability,
            )
            result = _handle_display_route(route, **_display_ctx)

        elif route in ("active_task", "delete_task", "block_task", "complete_task", "lessons"):
            result = _handle_task_status_route(route, payload, memory, state,
                                                payload_task_id, make_dummy_vector, router)

        elif route in ("pilot_accept_patch", "pilot_revise_patch", "pilot_reject_patch"):
            result = _handle_patch_review_route(
                route, payload, memory, state, lesson_memory,
                payload_patch_id, find_patch_entry, require_patch_metadata,
                update_patch_entry, record_pilot_guardrail,
                decide_recovery_action, build_recovery_payload,
                update_last_patch_snapshot, update_current_snapshot,
                sync_lessons_observability, make_dummy_vector,
            )

        elif route == "approve_patch":
            patch_id = payload_patch_id(payload)
            if patch_id is None:
                result = "Invalid payload for approve_patch."
            else:
                patch_entry, error = find_patch_entry(memory, patch_id)

                if error or patch_entry is None:
                    result = error or f"Patch {patch_id} not found."
                elif (patch_entry.get("metadata") or {}).get("pilot_verdict") != "accept":
                    result = f"Patch {patch_id} must be accepted by the pilot before approval."
                else:
                    assert isinstance(patch_entry, dict)
                    success = memory.update_task_status(patch_id, "approved")
                    if success:
                        meta, meta_error = require_patch_metadata(patch_entry, patch_id)
                        if meta_error is None and meta is not None:
                            assert isinstance(meta, dict)
                            update_last_patch_snapshot(
                                state,
                                meta,
                                patch_id=patch_id,
                                patch_status="approved",
                            )
                    result = f"Patch {patch_id} approved." if success else f"Patch {patch_id} could not be approved."

        elif route == "reject_patch":
            patch_id = payload_patch_id(payload)
            if patch_id is None:
                result = "Invalid payload for reject_patch."
            else:
                patch_entry, error = find_patch_entry(memory, patch_id)

                if error or patch_entry is None:
                    result = error or f"Patch {patch_id} not found."
                elif patch_entry.get("status") == "pending_pilot_review":
                    result = f"Use pilot reject patch {patch_id} <reason> during pilot review."
                else:
                    assert isinstance(patch_entry, dict)
                    success = memory.update_task_status(patch_id, "rejected")
                    if success:
                        meta, meta_error = require_patch_metadata(patch_entry, patch_id)
                        if meta_error is None and meta is not None:
                            assert isinstance(meta, dict)
                            update_last_patch_snapshot(
                                state,
                                meta,
                                patch_id=patch_id,
                                patch_status="rejected",
                                rejection_reason=meta.get("llm_error") or meta.get("reason"),
                            )
                    result = f"Patch {patch_id} rejected." if success else f"Patch {patch_id} could not be rejected."

        elif route in ("apply_patch", "verify_patch", "rollback_patch"):
            result = _handle_patch_apply_route(
                route, payload, memory, state, router,
                payload_patch_id, find_patch_entry, require_patch_metadata,
                find_backup_for_patch, find_plan_for_task,
                update_last_patch_snapshot, record_failure_observability,
                make_dummy_vector, _complete_child_task,
            )

        elif route == "builder":
            result = payload

            anchor = build_anchor_from_text(payload.get("note") or payload.get("goal"), state_manager=state)
            completion_cues = extract_required_completion_cues(payload.get("note") or payload.get("goal"))
            pilot_context = dict(payload.get("pilot_context") or {})

            memory.store(
                make_dummy_vector(),
                tag="builder",
                note=f'{payload["goal"]} | next: {payload["next_action"]}',
                status=payload.get("status", "drafted"),
                metadata={
                    "builder_result": payload,
                    "target_file": anchor.get("target_file"),
                    "target_symbol": anchor.get("target_symbol"),
                    "completion_cues": completion_cues,
                    "anchor": anchor,
                    "pilot_context": pilot_context,
                    "pilot_intent": payload.get("pilot_intent") or pilot_context.get("current_intent"),
                    "pilot_replan_required": False,
                },
            )

        elif route in (
            "math_explore", "math_conjecture", "math_falsify",
            "show_conjectures", "show_math_lessons", "math_status",
        ):
            result = _handle_math_route(route, payload, memory, state)

        elif route in (
            "code_hypothesize", "code_scan", "code_benchmark", "code_probe",
            "code_arch_trace", "code_adversarial", "show_hypotheses",
            "show_code_lessons", "code_status",
        ):
            result = _handle_code_route(route, payload, memory, state)

        else:
            result = f"No handler for route: {route}"

        reflection = reflector.evaluate(result)

        print("\nHive Response:")
        print(result)

        print("\nReflection:")
        print(reflection)


if __name__ == "__main__":
    main()
