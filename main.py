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


def infer_symbol_from_task_note(text, target_file, state_manager=None):
    if state_manager is None or not target_file:
        return None

    symbols = state_manager.get_symbols_for_file(target_file)
    if not symbols:
        return None

    task_text = text or ""
    task_text = re.sub(re.escape(target_file), " ", task_text, flags=re.IGNORECASE)
    lowered = task_text.lower()
    prefers_method = any(token in lowered for token in ("method", "function", "helper"))
    error_language = any(token in lowered for token in ("invalid", "error", "fail"))

    def normalize_token(token):
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

    def tokenize_text(value):
        raw_tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", (value or "").lower())
        normalized = []

        for raw in raw_tokens:
            parts = raw.split("_")
            for part in parts:
                normalized_part = normalize_token(part)
                if len(normalized_part) >= 3:
                    normalized.append(normalized_part)

        return normalized

    quoted_matches = []
    for symbol in symbols:
        patterns = [
            rf"`{re.escape(symbol)}`",
            rf'"{re.escape(symbol)}"',
            rf"'{re.escape(symbol)}'",
        ]
        if any(re.search(pattern, task_text, flags=re.IGNORECASE) for pattern in patterns):
            quoted_matches.append(symbol)

    if quoted_matches:
        return sorted(quoted_matches, key=len, reverse=True)[0]

    exact_matches = []
    for symbol in symbols:
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(symbol.lower())}(?![A-Za-z0-9_])"
        for match in re.finditer(pattern, lowered):
            trailing = lowered[match.end():match.end() + 3]
            if trailing == ".py":
                continue
            exact_matches.append(symbol)
            break

    if exact_matches:
        return sorted(exact_matches, key=len, reverse=True)[0]

    task_tokens = tokenize_text(task_text)
    if not task_tokens:
        return None

    task_token_set = set(task_tokens)
    scored = []

    for symbol in symbols:
        symbol_tokens = tokenize_text(symbol)
        if not symbol_tokens:
            continue

        symbol_token_set = set(symbol_tokens)
        overlap = task_token_set & symbol_token_set
        overlap_score = len(overlap)
        coverage_score = overlap_score / max(len(symbol_token_set), 1)
        token_hits = sum(task_tokens.count(token) for token in overlap)
        score = (overlap_score * 10) + token_hits + coverage_score

        if prefers_method:
            if symbol.startswith("_") or symbol[:1].islower():
                score += 2
            if symbol[:1].isupper():
                score -= 3

        if not error_language and {"invalid", "error", "fail"} & symbol_token_set:
            score -= 3

        if overlap_score > 0:
            scored.append({
                "symbol": symbol,
                "score": score,
                "overlap": overlap_score,
                "coverage": coverage_score,
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
    completion_cues = (
        task.get("completion_cues")
        or metadata.get("completion_cues")
        or extract_required_completion_cues(note_text)
    )

    should_reinfer_symbol = False
    if target_file:
        anchor_source = str(anchor.get("anchor_source") or "").lower()
        if not target_symbol:
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
                lines = []
                for entry in recent_notes:
                    lines.append(
                        f"Task {entry['id']} [{entry['tag']}] "
                        f"({entry['status']}) {entry['note']} ({entry['timestamp']})"
                    )
                result = "\n".join(lines)

        elif route == "plan_task":
            task_id = payload_task_id(payload)
            if task_id is None:
                result = "Invalid payload for plan_task."
            else:
                task = memory.get_task_by_id(task_id)

                if not task:
                    result = f"Task {task_id} not found."
                else:
                    task = enrich_task_anchor_for_planning(
                        task,
                        memory=memory,
                        state_manager=state,
                    )
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

                    stored_target_file = task_metadata.get("target_file")

                    anchor = task_metadata.get("anchor") or build_anchor_from_text(
                        task.get("note"),
                        state_manager=state,
                    )

                    if result.get("status") == "blocked":
                        updated_metadata = dict(task_metadata)
                        updated_metadata["pilot_replan_required"] = False
                        if updated_metadata.get("recovery_status") == "replan_ready":
                            updated_metadata["recovery_status"] = "blocked"
                        memory.update_task_metadata(task_id, updated_metadata)
                        record_failure_observability(
                            state,
                            result.get("llm_error", "unknown planner error"),
                            task=task,
                        )
                        memory.update_task_status(task_id, "blocked")

                        memory.store(
                            make_dummy_vector(),
                            tag="plan",
                            note=f'Task {task_id} planning blocked | {result.get("llm_error", "unknown planner error")}',
                            status="blocked",
                            metadata={
                                "task_id": task_id,
                                "plan_id": f"plan-{task_id}",
                                "plan": result,
                                "anchor": anchor,
                            },
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
                            dependencies = result.get("dependencies") or []

                            if not isinstance(dependencies, list):
                                dependencies = [dependencies]

                            if stored_target_file not in dependencies:
                                dependencies.insert(0, stored_target_file)

                            result["dependencies"] = dependencies
                            result["target_file"] = stored_target_file

                        current_child = _get_first_ready_child_task(result)
                        update_current_snapshot(
                            state,
                            task=task,
                            plan=result,
                            child=current_child,
                            status="planned",
                        )

                        memory.update_task_status(task_id, "planned")

                        memory.store(
                            make_dummy_vector(),
                            tag="plan",
                            note=f'Task {task_id} planned | {result["goal"]} | next: {result["next_action"]}',
                            status="planned",
                            metadata={
                                "task_id": task_id,
                                "plan_id": f"plan-{task_id}",
                                "plan": result,
                                "anchor": anchor,
                            },
                        )

        elif route == "active_task":
            task_id = payload_task_id(payload)
            if task_id is None:
                result = "Invalid payload for active_task."
            else:
                success = memory.update_task_status(task_id, "active")
                task = memory.get_task_by_id(task_id) if success else None
                if task:
                    update_current_snapshot(state, task=task, status="active")
                result = f"Task {task_id} marked as active." if success else f"Task {task_id} not found."

        elif route == "pilot_task_intent":
            task_id = payload_task_id(payload)
            pilot_input = str(payload.get("pilot_input") or "").strip()

            if task_id is None or not pilot_input:
                result = "Invalid payload for pilot_task_intent."
            else:
                task = memory.get_task_by_id(task_id)

                if not task:
                    result = f"Task {task_id} not found."
                else:
                    metadata = dict(task.get("metadata") or {})
                    pilot_context = merge_pilot_context(metadata.get("pilot_context"), pilot_input)
                    anchor_update = build_anchor_from_text(pilot_input, state_manager=state)
                    new_cues = extract_required_completion_cues(pilot_input)

                    metadata["pilot_context"] = pilot_context
                    metadata["pilot_intent"] = pilot_context.get("current_intent")
                    metadata["completion_cues"] = merge_completion_cues(
                        metadata.get("completion_cues"),
                        new_cues,
                    )

                    if not metadata.get("target_file") and anchor_update.get("target_file"):
                        metadata["target_file"] = anchor_update.get("target_file")
                    if not metadata.get("target_symbol") and anchor_update.get("target_symbol"):
                        metadata["target_symbol"] = anchor_update.get("target_symbol")

                    existing_anchor = dict(metadata.get("anchor") or {})
                    target_file = existing_anchor.get("target_file") or metadata.get("target_file")
                    target_symbol = existing_anchor.get("target_symbol") or metadata.get("target_symbol")
                    if target_file or target_symbol:
                        metadata["anchor"] = merge_anchor_with_span(
                            {
                                **existing_anchor,
                                "target_file": target_file,
                                "target_symbol": target_symbol,
                                "scope": existing_anchor.get("scope") or "single_file",
                                "anchor_level": "symbol" if target_symbol else "file",
                                "anchor_source": existing_anchor.get("anchor_source") or "user_input",
                            },
                            target_file,
                            target_symbol,
                            state_manager=state,
                        )

                    metadata["pilot_replan_required"] = find_plan_for_task(memory, task_id) is not None
                    memory.update_task_metadata(task_id, metadata)

                    updated_task = memory.get_task_by_id(task_id)
                    update_current_snapshot(state, task=updated_task, status=updated_task.get("status"))
                    memory.store(
                        make_dummy_vector(),
                        tag="pilot_intent",
                        note=f"Task {task_id} pilot intent updated | {pilot_context.get('intent_summary')}",
                        status="updated",
                        metadata={
                            "task_id": task_id,
                            "pilot_context": pilot_context,
                        },
                    )
                    if metadata.get("pilot_replan_required"):
                        result = f"Pilot intent updated for task {task_id}. Re-run plan task {task_id} before coding."
                    else:
                        result = f"Pilot intent updated for task {task_id}."

        elif route == "help":
            result = """
Available Commands:
- memory
- lessons
- pending patch reviews
- pending recoveries
- show current
- show last patch
- show failures
- show lessons
- show cockpit
- show task <id>
- show patch <id>
- review patch <id>
- show recovery <id>
- plan task <id>
- code task <id>
- continue task <id>
- complete task <id>
- active task <id>
- pilot task <id> <guidance>
- pilot accept patch <id>
- pilot revise patch <id> <guidance>
- pilot reject patch <id> <reason>
- block task <id>
- delete task <id>
- current task
- apply patch <id>
- approve patch <id>
- reject patch <id>
- verify patch <id>
- rollback patch <id>
- help
- store <text>
""".strip()

        elif route == "delete_task":
            task_id = payload_task_id(payload)
            if task_id is None:
                result = "Invalid payload for delete_task."
            else:
                success = memory.update_task_status(task_id, "deleted")
                result = f"Task {task_id} marked as deleted." if success else f"Task {task_id} not found."

        elif route == "block_task":
            task_id = payload_task_id(payload)
            if task_id is None:
                result = "Invalid payload for block_task."
            else:
                success = memory.update_task_status(task_id, "blocked")
                result = f"Task {task_id} marked as blocked." if success else f"Task {task_id} not found."

        elif route == "current_task":
            task = memory.get_current_task()
            result = task if task else "No active task found."

        elif route == "show_current":
            result = format_current_snapshot(state.get_observability_snapshot())

        elif route == "show_last_patch":
            result = format_last_patch_snapshot(state.get_observability_snapshot())

        elif route == "show_failures":
            result = format_failures_snapshot(state.get_observability_snapshot())

        elif route == "show_lessons":
            sync_lessons_observability(state, lesson_memory)
            result = format_lessons_snapshot(state.get_observability_snapshot())

        elif route == "show_cockpit":
            sync_lessons_observability(state, lesson_memory)
            result = format_cockpit_snapshot(state.get_observability_snapshot())

        elif route == "show_task":
            task_id = payload_task_id(payload)
            if task_id is None:
                result = "Invalid payload for show_task."
            else:
                task = memory.get_task_by_id(task_id)
                result = task if task else f"Task {task_id} not found."

        elif route == "continue_task":
            task_id = payload_task_id(payload)
            if task_id is None:
                result = "Invalid payload for continue_task."
            else:
                task = memory.get_task_by_id(task_id)

                if not task:
                    result = f"Task {task_id} not found."
                else:
                    result = router.builder.continue_task(task)
                    memory.store(
                        make_dummy_vector(),
                        tag="continued_task",
                        note=f'Task {task_id} resumed | {task["note"]}',
                        status="continued",
                        metadata={
                            "task_id": task_id,
                            "continued_task": result,
                        },
                    )
        elif route == "code_task":
            task_id = payload_task_id(payload)
            if task_id is None:
                result = "Invalid payload for code_task."
            else:
                task = memory.get_task_by_id(task_id)
                task_metadata = (task or {}).get("metadata") or {}

                if not task:
                    result = f"Task {task_id} not found."
                elif ((task.get("metadata") or {}).get("pilot_replan_required")) is True:
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

                    if not ready_child:
                        if not plan:
                            pass  # result already set above
                        elif plan.get("status") == "blocked":
                            pass  # result already set above
                        else:
                            result = f"Task {task_id} has no ready child task."
                    else:
                        plan = plan or {}
                        goal = plan.get("goal", "<unknown goal>")
                        next_action = plan.get("next_action", "")
                        metadata_plan = plan if isinstance(plan, dict) else {}

                        memory.store(
                            make_dummy_vector(),
                            tag="plan",
                            note=f'Task {task_id} plan updated | {goal} | next: {next_action}',
                            status="planned",
                            metadata={
                                "task_id": task_id,
                                "plan_id": f"plan-{task_id}",
                                "plan": metadata_plan,
                            },
                        )
                        update_current_snapshot(
                            state,
                            task=task,
                            plan=plan,
                            child=ready_child,
                            status=ready_child.get("status") or "current",
                        )

                        coder_task = task
                        effective_plan = plan

                        anchor = (task.get("metadata") or {}).get("anchor") or build_anchor_from_text(
                            task.get("note"),
                            state_manager=state,
                        )

                        parent_meta = task.get("metadata") or {}
                        parent_anchor = dict(parent_meta.get("anchor") or anchor or {})

                        child_target_file = (
                            task_metadata.get("target_file") if task_metadata.get("recovery_status") == "retry_ready" else None
                        ) or (
                            ready_child.get("target_file")
                            or parent_meta.get("target_file")
                            or parent_anchor.get("target_file")
                        )

                        child_anchor_guess = build_anchor_from_text(
                            ready_child.get("description", task.get("note", "")),
                            state_manager=state,
                        )

                        child_target_symbol = (
                            task_metadata.get("target_symbol") if task_metadata.get("recovery_status") == "retry_ready" else None
                        ) or (
                            ready_child.get("target_symbol")
                            or child_anchor_guess.get("target_symbol")
                            or parent_anchor.get("target_symbol")
                        )

                        child_target_file = (
                            child_target_file
                            or child_anchor_guess.get("target_file")
                            or parent_anchor.get("target_file")
                        )

                        anchor = merge_anchor_with_span({
                            "target_file": child_target_file,
                            "target_symbol": child_target_symbol,
                            "scope": parent_anchor.get("scope") or "single_file",
                            "anchor_level": "symbol" if child_target_symbol else "file",
                            "anchor_source": "child_task",
                        }, child_target_file, child_target_symbol, state_manager=state)

                        coder_task = {
                            "id": task["id"],
                            "tag": task.get("tag", "task"),
                            "status": task.get("status", "active"),
                            "note": ready_child.get("description", task.get("note", "")),
                            "metadata": {
                                **parent_meta,
                                "target_file": child_target_file,
                                "target_symbol": child_target_symbol,
                                "change_intent": ready_child.get("change_intent"),
                                "expected_operation": ready_child.get("expected_operation"),
                                "completion_cues": ready_child.get("completion_cues"),
                                "task_type": ready_child.get("task_type"),
                                "child_task_id": ready_child.get("task_id"),
                                "parent_task_id": task["id"],
                                "anchor": anchor,
                                "retry_source": task_metadata.get("retry_source"),
                                "pilot_guidance": task_metadata.get("pilot_guidance"),
                                "pilot_guardrail_text": task_metadata.get("pilot_guardrail_text"),
                                "reflector_summary": task_metadata.get("reflector_summary"),
                                "rejected_patch_excerpt": task_metadata.get("rejected_patch_excerpt"),
                            },
                            "target_file": child_target_file,
                            "target_symbol": child_target_symbol,
                            "change_intent": ready_child.get("change_intent"),
                            "expected_operation": ready_child.get("expected_operation"),
                            "completion_cues": ready_child.get("completion_cues"),
                            "task_type": ready_child.get("task_type"),
                            "child_task_id": ready_child.get("task_id"),
                            "parent_task_id": task["id"],
                            "retry_source": task_metadata.get("retry_source"),
                        }
                        copy_anchor_fields(coder_task["metadata"], anchor)
                        copy_anchor_fields(coder_task, anchor)

                        if not isinstance(plan, dict):
                            plan = dict(plan)

                        effective_plan = {
                            **plan,
                            "next_action": (
                                task_metadata.get("pilot_guidance")
                                if task_metadata.get("recovery_status") == "retry_ready"
                                else ready_child.get("description", plan.get("next_action"))
                            ),
                            "tasks": [ready_child],
                            "active_child_task_id": ready_child.get("task_id"),
                            "active_child_task_title": ready_child.get("title"),
                            "active_child_target_file": ready_child.get("target_file"),
                        }

                        result = router.coder.generate_patch_with_revisions(coder_task, effective_plan, reflector)

                        patch_status = result.get("status", "proposed")
                        patch_label = "blocked" if patch_status == "blocked" else "pending_pilot_review"
                        stored_patch_status = "blocked" if patch_status == "blocked" else "pending_pilot_review"

                        patch_metadata = {
                            **result,
                            "task_id": task_id,
                            "plan_id": f"plan-{task_id}",
                            "patch_id": result.get("patch_id") or f"patch-{task_id}",
                            "anchor": anchor,
                            "task_type": effective_plan.get("task_type"),
                            "task_note": task.get("note"),
                            "pilot_verdict": None,
                            "pilot_reason": None,
                            "pilot_guidance": None,
                            "location_correct": None,
                            "task_alignment": None,
                            "plan_step_alignment": None,
                        }

                        patch_metadata["child_task_id"] = ready_child.get("task_id")
                        patch_metadata["child_task_description"] = ready_child.get("description")
                        patch_metadata["child_target_file"] = ready_child.get("target_file")
                        patch_metadata["child_target_symbol"] = child_target_symbol
                        patch_metadata["child_change_intent"] = ready_child.get("change_intent")
                        patch_metadata["child_expected_operation"] = ready_child.get("expected_operation")
                        patch_metadata["child_completion_cues"] = ready_child.get("completion_cues")
                        patch_metadata["child_task_type"] = ready_child.get("task_type")
                        patch_metadata["recovery_action"] = task_metadata.get("recovery_action")
                        patch_metadata["recovery_status"] = "completed" if task_metadata.get("recovery_status") == "retry_ready" else None
                        patch_metadata["recovery_reason"] = task_metadata.get("recovery_reason")
                        patch_metadata["review_packet"] = build_pilot_review_packet(
                            patch_metadata["patch_id"],
                            patch_metadata,
                        )

                        memory.store(
                            make_dummy_vector(),
                            tag="patch",
                            note=f'Task {task_id} patch {patch_label} | {result.get("target_file", "unknown")}',
                            status=stored_patch_status,
                            metadata=patch_metadata,
                        )
                        update_last_patch_snapshot(
                            state,
                            patch_metadata,
                            target_symbol=patch_metadata.get("child_target_symbol") or patch_metadata.get("context_target"),
                            change_intent=patch_metadata.get("child_change_intent"),
                            expected_operation=patch_metadata.get("child_expected_operation"),
                            patch_status=stored_patch_status,
                            validation_outcome=(
                                "passed"
                                if (patch_metadata.get("sandbox_report") or {}).get("applied") is True
                                and (patch_metadata.get("sandbox_report") or {}).get("syntax_valid") is True
                                and (patch_metadata.get("sandbox_report") or {}).get("semantic_valid") is True
                                else "failed"
                                if stored_patch_status == "blocked"
                                else "pending"
                            ),
                        )
                        if stored_patch_status == "blocked":
                            record_failure_observability(
                                state,
                                patch_metadata.get("llm_error") or patch_metadata.get("reason"),
                                task=coder_task,
                                patch_data=patch_metadata,
                            )
                        elif task_metadata.get("recovery_status") == "retry_ready":
                            updated_task_metadata = dict(task_metadata)
                            updated_task_metadata["recovery_status"] = "completed"
                            memory.update_task_metadata(task_id, updated_task_metadata)
                        sync_lessons_observability(state, lesson_memory)

        elif route == "show_plan":
            task_id = payload_task_id(payload)
            if task_id is None:
                result = "Invalid payload for show_plan."
            else:
                recent_notes = memory.get_recent_notes()

                latest_plan = None
                for entry in reversed(recent_notes):
                    if entry.get("tag") != "plan":
                        continue

                    metadata = entry.get("metadata") or {}
                    if metadata.get("task_id") == task_id:
                        latest_plan = metadata.get("plan")
                        break

                result = latest_plan if latest_plan else f"Plan for task {task_id} not found."

        elif route == "show_pending_patch_reviews":
            pending_reviews = list_pending_pilot_review_patches(memory)
            if not pending_reviews:
                result = "No pending pilot patch reviews."
            else:
                lines = ["Pending Pilot Patch Reviews"]
                for entry in pending_reviews:
                    meta = entry.get("metadata") or {}
                    packet = meta.get("review_packet") or {}
                    lines.append(
                        f"Patch {entry.get('id')} | task={meta.get('task_id') or 'none'} "
                        f"file={meta.get('target_file') or 'none'} "
                        f"symbol={meta.get('child_target_symbol') or meta.get('target_symbol') or 'none'} "
                        f"child={packet.get('child_task_title') or packet.get('child_task_description') or 'none'}"
                    )
                result = "\n".join(lines)

        elif route == "show_pending_recoveries":
            recoveries = list_pending_recoveries(memory)
            if not recoveries:
                result = "No pending recoveries."
            else:
                lines = ["Pending Recoveries"]
                for entry in recoveries:
                    metadata = entry.get("metadata") or {}
                    lines.append(
                        f"Task {metadata.get('task_id') or entry.get('id')} | action={metadata.get('recovery_action') or 'none'} "
                        f"status={metadata.get('recovery_status') or 'none'} "
                        f"source_patch={metadata.get('recovery_source_patch_id') or 'none'} "
                        f"target={metadata.get('target_file') or 'none'}::{metadata.get('target_symbol') or 'none'}"
                    )
                result = "\n".join(lines)

        elif route == "show_recovery":
            task_id = payload_task_id(payload)
            if task_id is None:
                result = "Invalid payload for show_recovery."
            else:
                task = memory.get_task_by_id(task_id)
                if not task:
                    result = f"Task {task_id} not found."
                else:
                    metadata = task.get("metadata") or {}
                    result = format_recovery_payload(task_id, metadata)

        elif route == "review_patch":
            patch_id = payload_patch_id(payload)
            if patch_id is None:
                result = "Invalid payload for review_patch."
            else:
                patch_entry, error = find_patch_entry(memory, patch_id)
                if error or patch_entry is None:
                    result = error or f"Patch {patch_id} not found."
                else:
                    meta, error = require_patch_metadata(patch_entry, patch_id)
                    if error or meta is None:
                        result = error or f"Patch {patch_id} has no metadata."
                    else:
                        review_packet = meta.get("review_packet") or build_pilot_review_packet(patch_id, meta)
                        result = format_pilot_review_packet(review_packet)

        elif route == "show_patch":
            patch_id = payload_patch_id(payload)
            if patch_id is None:
                result = "Invalid payload for show_patch."
            else:
                patch_entry, error = find_patch_entry(memory, patch_id)

                if error or patch_entry is None:
                    result = error or f"Patch {patch_id} not found."
                else:
                    assert isinstance(patch_entry, dict)
                    meta, error = require_patch_metadata(patch_entry, patch_id)
                    if error or meta is None:
                        result = error or f"Patch {patch_id} has no metadata."
                    else:
                        assert isinstance(meta, dict)
                        result = (
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

        elif route == "pilot_accept_patch":
            patch_id = payload_patch_id(payload)
            if patch_id is None:
                result = "Invalid payload for pilot_accept_patch."
            else:
                patch_entry, error = find_patch_entry(memory, patch_id)
                if error or patch_entry is None:
                    result = error or f"Patch {patch_id} not found."
                elif patch_entry.get("status") != "pending_pilot_review":
                    result = f"Patch {patch_id} is not awaiting pilot review."
                else:
                    meta, error = require_patch_metadata(patch_entry, patch_id)
                    if error or meta is None:
                        result = error or f"Patch {patch_id} has no metadata."
                    else:
                        meta = dict(meta)
                        meta["pilot_verdict"] = "accept"
                        meta["pilot_reason"] = "Pilot confirmed patch intent alignment."
                        meta["pilot_guidance"] = None
                        meta["location_correct"] = True
                        meta["task_alignment"] = True
                        meta["plan_step_alignment"] = True
                        update_patch_entry(memory, patch_id, metadata=meta, status="approved")
                        parent_task = memory.get_task_by_id(meta.get("task_id")) if meta.get("task_id") else None
                        if parent_task:
                            task_metadata = dict(parent_task.get("metadata") or {})
                            task_metadata["recovery_status"] = "completed"
                            task_metadata["recovery_action"] = task_metadata.get("recovery_action")
                            memory.update_task_metadata(meta.get("task_id"), task_metadata)
                        update_last_patch_snapshot(
                            state,
                            meta,
                            patch_id=patch_id,
                            patch_status="approved",
                            pilot_verdict="accept",
                            pilot_reason=meta["pilot_reason"],
                            pilot_guidance=None,
                        )
                        sync_lessons_observability(state, lesson_memory)
                        result = f"Patch {patch_id} accepted by pilot and marked approved."

        elif route == "pilot_revise_patch":
            patch_id = payload_patch_id(payload)
            pilot_guidance = str(payload.get("pilot_guidance") or "").strip()
            if patch_id is None or not pilot_guidance:
                result = "Invalid payload for pilot_revise_patch."
            else:
                patch_entry, error = find_patch_entry(memory, patch_id)
                if error or patch_entry is None:
                    result = error or f"Patch {patch_id} not found."
                else:
                    meta, error = require_patch_metadata(patch_entry, patch_id)
                    if error or meta is None:
                        result = error or f"Patch {patch_id} has no metadata."
                    else:
                        meta = dict(meta)
                        meta["pilot_verdict"] = "revise"
                        meta["pilot_reason"] = "Pilot requested revision for intent alignment."
                        meta["pilot_guidance"] = pilot_guidance
                        meta["location_correct"] = False if "wrong place" in pilot_guidance.lower() or "wrong file" in pilot_guidance.lower() or "wrong symbol" in pilot_guidance.lower() else None
                        meta["task_alignment"] = False
                        meta["plan_step_alignment"] = False
                        recovery_action = decide_recovery_action(meta, pilot_guidance, state_manager=state)
                        recovery_payload = build_recovery_payload(meta, recovery_action, pilot_guidance, state_manager=state)
                        meta.update(recovery_payload)
                        update_patch_entry(memory, patch_id, metadata=meta, status="rejected")
                        guardrail_text = record_pilot_guardrail(
                            lesson_memory,
                            meta,
                            pilot_verdict="revise",
                            pilot_reason=meta["pilot_reason"],
                            pilot_guidance=pilot_guidance,
                            location_correct=meta["location_correct"],
                            task_alignment=False,
                            plan_step_alignment=False,
                        )
                        parent_task_id = meta.get("task_id")
                        if parent_task_id:
                            parent_task = memory.get_task_by_id(parent_task_id)
                            if parent_task:
                                task_metadata = dict(parent_task.get("metadata") or {})
                                task_metadata.update(recovery_payload)
                                task_metadata["pilot_guidance"] = pilot_guidance
                                task_metadata["pilot_guardrail_text"] = guardrail_text
                                task_metadata["reflector_summary"] = recovery_payload.get("reflector_summary")
                                task_metadata["rejected_patch_excerpt"] = recovery_payload.get("rejected_patch_excerpt")
                                task_metadata["recovery_child_task_description"] = meta.get("child_task_description")
                                task_metadata["child_task_description"] = meta.get("child_task_description")
                                task_metadata["child_task_id"] = meta.get("child_task_id")
                                task_metadata["target_file"] = recovery_payload.get("target_file") or task_metadata.get("target_file")
                                task_metadata["target_symbol"] = recovery_payload.get("target_symbol") or task_metadata.get("target_symbol")
                                task_metadata["pilot_replan_required"] = recovery_action == "replan_task"
                                memory.update_task_metadata(parent_task_id, task_metadata)
                                memory.store(
                                    make_dummy_vector(),
                                    tag="recovery",
                                    note=f"Task {parent_task_id} recovery {recovery_payload.get('recovery_status')} | action: {recovery_action}",
                                    status=recovery_payload.get("recovery_status"),
                                    metadata={"task_id": parent_task_id, **recovery_payload},
                                )
                        update_last_patch_snapshot(
                            state,
                            meta,
                            patch_id=patch_id,
                            patch_status="rejected",
                            pilot_verdict="revise",
                            pilot_reason=meta["pilot_reason"],
                            pilot_guidance=pilot_guidance,
                            recovery_action=recovery_action,
                            recovery_status=recovery_payload.get("recovery_status"),
                            rejection_reason=pilot_guidance,
                        )
                        updated_task = memory.get_task_by_id(parent_task_id) if parent_task_id else None
                        if updated_task:
                            update_current_snapshot(state, task=updated_task, status=updated_task.get("status"))
                        sync_lessons_observability(state, lesson_memory)
                        result = f"Patch {patch_id} sent back with pilot revision guidance. Recovery action: {recovery_action}."

        elif route == "pilot_reject_patch":
            patch_id = payload_patch_id(payload)
            pilot_reason = str(payload.get("pilot_reason") or "").strip()
            if patch_id is None or not pilot_reason:
                result = "Invalid payload for pilot_reject_patch."
            else:
                patch_entry, error = find_patch_entry(memory, patch_id)
                if error or patch_entry is None:
                    result = error or f"Patch {patch_id} not found."
                else:
                    meta, error = require_patch_metadata(patch_entry, patch_id)
                    if error or meta is None:
                        result = error or f"Patch {patch_id} has no metadata."
                    else:
                        meta = dict(meta)
                        meta["pilot_verdict"] = "reject"
                        meta["pilot_reason"] = pilot_reason
                        meta["pilot_guidance"] = pilot_reason
                        meta["location_correct"] = False if any(token in pilot_reason.lower() for token in ("wrong place", "wrong file", "wrong symbol")) else None
                        meta["task_alignment"] = False
                        meta["plan_step_alignment"] = False
                        recovery_action = decide_recovery_action(meta, pilot_reason, state_manager=state)
                        recovery_payload = build_recovery_payload(meta, recovery_action, pilot_reason, state_manager=state)
                        meta.update(recovery_payload)
                        update_patch_entry(memory, patch_id, metadata=meta, status="rejected")
                        guardrail_text = record_pilot_guardrail(
                            lesson_memory,
                            meta,
                            pilot_verdict="reject",
                            pilot_reason=pilot_reason,
                            pilot_guidance=pilot_reason,
                            location_correct=meta["location_correct"],
                            task_alignment=False,
                            plan_step_alignment=False,
                        )
                        parent_task_id = meta.get("task_id")
                        if parent_task_id:
                            parent_task = memory.get_task_by_id(parent_task_id)
                            if parent_task:
                                task_metadata = dict(parent_task.get("metadata") or {})
                                task_metadata.update(recovery_payload)
                                task_metadata["pilot_guidance"] = pilot_reason
                                task_metadata["pilot_guardrail_text"] = guardrail_text
                                task_metadata["reflector_summary"] = recovery_payload.get("reflector_summary")
                                task_metadata["rejected_patch_excerpt"] = recovery_payload.get("rejected_patch_excerpt")
                                task_metadata["recovery_child_task_description"] = meta.get("child_task_description")
                                task_metadata["child_task_description"] = meta.get("child_task_description")
                                task_metadata["child_task_id"] = meta.get("child_task_id")
                                task_metadata["target_file"] = recovery_payload.get("target_file") or task_metadata.get("target_file")
                                task_metadata["target_symbol"] = recovery_payload.get("target_symbol") or task_metadata.get("target_symbol")
                                task_metadata["pilot_replan_required"] = recovery_action == "replan_task"
                                memory.update_task_metadata(parent_task_id, task_metadata)
                                memory.store(
                                    make_dummy_vector(),
                                    tag="recovery",
                                    note=f"Task {parent_task_id} recovery {recovery_payload.get('recovery_status')} | action: {recovery_action}",
                                    status=recovery_payload.get("recovery_status"),
                                    metadata={"task_id": parent_task_id, **recovery_payload},
                                )
                        update_last_patch_snapshot(
                            state,
                            meta,
                            patch_id=patch_id,
                            patch_status="rejected",
                            pilot_verdict="reject",
                            pilot_reason=pilot_reason,
                            pilot_guidance=pilot_reason,
                            recovery_action=recovery_action,
                            recovery_status=recovery_payload.get("recovery_status"),
                            rejection_reason=pilot_reason,
                        )
                        updated_task = memory.get_task_by_id(parent_task_id) if parent_task_id else None
                        if updated_task:
                            update_current_snapshot(state, task=updated_task, status=updated_task.get("status"))
                        sync_lessons_observability(state, lesson_memory)
                        result = f"Patch {patch_id} rejected by pilot. Recovery action: {recovery_action}."

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

        elif route == "apply_patch":
            patch_id = payload_patch_id(payload)
            if patch_id is None:
                result = "Invalid payload for apply_patch."
            else:
                patch_entry, error = find_patch_entry(memory, patch_id)

                if error or patch_entry is None:
                    result = error or f"Patch {patch_id} not found."
                elif patch_entry.get("status") != "approved":
                    result = f"Patch {patch_id} must be accepted by the pilot and approved first."
                else:
                    assert isinstance(patch_entry, dict)
                    meta, error = require_patch_metadata(patch_entry, patch_id)

                    if error or meta is None:
                        result = error or f"Patch {patch_id} has no metadata."
                    else:
                        assert isinstance(meta, dict)
                        target_file = meta["target_file"]
                        patch_text = meta["patch"]
                        patch_reason = meta.get("reason", "")
                        file_text = state.get_effective_file_text(target_file)

                        try:
                            verification = router.executor.verify_patch_context(
                                patch_text,
                                target_file,
                                file_text=file_text,
                            )

                            if not verification["verified"]:
                                record_failure_observability(
                                    state,
                                    f"Patch {patch_id} failed verification: {verification['checks']}",
                                    patch_data=meta,
                                )
                                update_last_patch_snapshot(
                                    state,
                                    meta,
                                    patch_id=patch_id,
                                    patch_status="apply_failed",
                                    validation_outcome="failed",
                                    rejection_reason=f"Patch {patch_id} failed verification: {verification['checks']}",
                                )
                                result = f"Patch {patch_id} failed verification: {verification['checks']}"
                            else:
                                backup = router.executor.backup_file(target_file)
                                router.executor.apply_patch(
                                    patch_text,
                                    target_file,
                                    patch_reason=patch_reason,
                                    file_text=file_text,
                                )

                                memory.update_task_status(patch_id, "applied")
                                updated_text = Path(target_file).read_text(encoding="utf-8")
                                state.record_patch_apply(target_file, patch_id, updated_text)

                                # Keep repo map up to date after an applied patch.
                                state.rebuild_repo_map()
                                state.save_snapshot()

                                child_task_id = meta.get("child_task_id")
                                parent_task_id = meta.get("task_id")

                                if child_task_id and parent_task_id:
                                    plan = find_plan_for_task(memory, parent_task_id)
                                    if plan:
                                        updated_plan = _complete_child_task(plan, child_task_id)

                                        memory.store(
                                            make_dummy_vector(),
                                            tag="plan",
                                            note=f'Task {parent_task_id} plan updated | {updated_plan["goal"]} | next: {updated_plan.get("next_action", "")}',
                                            status="planned",
                                            metadata={
                                                "task_id": parent_task_id,
                                                "plan_id": f"plan-{parent_task_id}",
                                                "plan": updated_plan,
                                            },
                                        )

                                memory.store(
                                    make_dummy_vector(),
                                    tag="patch_apply",
                                    note=f"Patch {patch_id} applied to {target_file} | backup: {backup}",
                                    status="applied",
                                    metadata={
                                        "apply_id": f"apply-{patch_id}",
                                        "patch_id": patch_id,
                                        "task_id": meta.get("task_id"),
                                        "plan_id": meta.get("plan_id"),
                                        "target_file": target_file,
                                        "backup_path": backup,
                                    },
                                )
                                update_last_patch_snapshot(
                                    state,
                                    meta,
                                    patch_id=patch_id,
                                    patch_status="applied",
                                    validation_outcome="passed",
                                    rejection_reason=None,
                                )

                                result = f"Patch {patch_id} applied successfully.\nBackup created: {backup}"
                        
                        
                        except Exception as e:
                            record_failure_observability(
                                state,
                                str(e),
                                patch_data=meta,
                            )
                            update_last_patch_snapshot(
                                state,
                                meta,
                                patch_id=patch_id,
                                patch_status="apply_failed",
                                validation_outcome="failed",
                                rejection_reason=str(e),
                            )
                            result = f"Patch {patch_id} failed to apply: {e}"

        elif route == "verify_patch":
            patch_id = payload_patch_id(payload)
            if patch_id is None:
                result = "Invalid payload for verify_patch."
            else:
                patch_entry, error = find_patch_entry(memory, patch_id)

                if error or patch_entry is None:
                    result = error or f"Patch {patch_id} not found."
                else:
                    assert isinstance(patch_entry, dict)
                    meta, error = require_patch_metadata(patch_entry, patch_id)

                    if error or meta is None:
                        result = error or f"Patch {patch_id} has no metadata."
                    else:
                        assert isinstance(meta, dict)
                        target_file = meta.get("target_file")
                        patch_text = meta.get("patch", "")
                        file_text = state.get_effective_file_text(target_file)

                        verification = router.executor.verify_patch_context(
                            patch_text,
                            target_file,
                            file_text=file_text,
                        )
                        semantic = router.executor.validate_patch_semantics(
                            patch_text,
                            target_file,
                            verification=verification,
                            patch_reason=meta.get("reason", ""),
                            file_text=file_text,
                        )

                        result = {
                            "patch_id": patch_id,
                            "verified": verification["verified"],
                            "checks": verification["checks"],
                            "anchor_index": verification["anchor_index"],
                            "semantic_valid": semantic["valid"],
                            "semantic_checks": semantic["checks"],
                            "semantic_details": semantic["details"],
                        }
                        update_last_patch_snapshot(
                            state,
                            meta,
                            patch_id=patch_id,
                            patch_status=patch_entry.get("status") or meta.get("status"),
                            validation_outcome="passed" if verification["verified"] and semantic["valid"] else "failed",
                            rejection_reason=None if verification["verified"] and semantic["valid"] else str({
                                "verification": verification["checks"],
                                "semantic": semantic["checks"],
                            }),
                        )
                        if not verification["verified"] or not semantic["valid"]:
                            record_failure_observability(
                                state,
                                str({
                                    "verification": verification["checks"],
                                    "semantic": semantic["checks"],
                                }),
                                patch_data=meta,
                            )

        elif route == "rollback_patch":
            patch_id = payload_patch_id(payload)
            if patch_id is None:
                result = "Invalid payload for rollback_patch."
            else:
                patch_entry, error = find_patch_entry(memory, patch_id)

                if error or patch_entry is None:
                    result = error or f"Patch {patch_id} not found."
                else:
                    assert isinstance(patch_entry, dict)
                    meta, error = require_patch_metadata(patch_entry, patch_id)

                    if error or meta is None:
                        result = error or f"Patch {patch_id} has no metadata."
                    else:
                        assert isinstance(meta, dict)
                        target_file = meta["target_file"]
                        backup_path = find_backup_for_patch(memory, patch_id)

                        if not backup_path:
                            result = f"No backup found for patch {patch_id}."
                        else:
                            try:
                                router.executor.restore_backup(backup_path, target_file)
                                memory.update_task_status(patch_id, "rolled_back")
                                restored_text = Path(target_file).read_text(encoding="utf-8")
                                state.record_patch_rollback(target_file, patch_id, restored_text)
                                state.save_snapshot()
                                update_last_patch_snapshot(
                                    state,
                                    meta,
                                    patch_id=patch_id,
                                    patch_status="rolled_back",
                                )
                                result = f"Patch {patch_id} rolled back successfully."
                            except Exception as e:
                                record_failure_observability(
                                    state,
                                    str(e),
                                    patch_data=meta,
                                )
                                update_last_patch_snapshot(
                                    state,
                                    meta,
                                    patch_id=patch_id,
                                    patch_status="rollback_failed",
                                    rejection_reason=str(e),
                                )
                                result = f"Rollback failed: {e}"

        elif route == "complete_task":
            task_id = payload_task_id(payload)
            if task_id is None:
                result = "Invalid payload for complete_task."
            else:
                success = memory.update_task_status(task_id, "completed")
                result = f"Task {task_id} marked as completed." if success else f"Task {task_id} not found."

        elif route == "lessons":
            sync_lessons_observability(state, lesson_memory)
            result = format_lessons_snapshot(state.get_observability_snapshot())

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

        else:
            result = f"No handler for route: {route}"

        reflection = reflector.evaluate(result)

        print("\nHive Response:")
        print(result)

        print("\nReflection:")
        print(reflection)


if __name__ == "__main__":
    main()
