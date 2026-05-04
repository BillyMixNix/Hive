import re
from work_ontology import build_work_profile


def _normalize_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _extract_sentences(text):
    clean = _normalize_text(text)
    if not clean:
        return []
    parts = re.split(r"(?<=[.!?])\s+", clean)
    return [part.strip() for part in parts if part.strip()]


def _extract_constraint_lines(text):
    sentences = _extract_sentences(text)
    markers = (
        "without",
        "do not",
        "don't",
        "must",
        "should",
        "need to",
        "needs to",
        "keep",
        "preserve",
        "avoid",
        "instead of",
    )
    constraints = []
    seen = set()

    for sentence in sentences:
        lowered = sentence.lower()
        if not any(marker in lowered for marker in markers):
            continue
        normalized = sentence.rstrip(".")
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        constraints.append(normalized)

    return constraints[:4]


def build_pilot_context(raw_input, existing_context=None):
    clean = _normalize_text(raw_input)
    existing_context = dict(existing_context or {})
    history = list(existing_context.get("history") or [])

    if clean:
        history.append(clean)

    current_intent = clean or _normalize_text(existing_context.get("current_intent"))
    if not current_intent:
        current_intent = "Clarify the requested implementation target."

    sentences = _extract_sentences(current_intent)
    intent_summary = sentences[0] if sentences else current_intent

    return {
        "source": "pilot",
        "raw_input": clean,
        "current_intent": current_intent,
        "intent_summary": intent_summary,
        "constraints": _extract_constraint_lines(current_intent),
        "history": history[-6:],
    }


def merge_pilot_context(existing_context, new_input):
    return build_pilot_context(new_input, existing_context=existing_context)


def format_pilot_brief(task_or_context):
    if isinstance(task_or_context, dict) and "pilot_context" in task_or_context:
        pilot_context = dict(task_or_context.get("pilot_context") or {})
    else:
        metadata = (task_or_context or {}).get("metadata") or {}
        pilot_context = dict(metadata.get("pilot_context") or {})

    current_intent = _normalize_text(pilot_context.get("current_intent"))
    if not current_intent:
        current_intent = _normalize_text(
            (task_or_context or {}).get("note")
            or (task_or_context or {}).get("goal")
        ) or "No additional pilot intent recorded."

    lines = [
        f"- Current intent: {current_intent}",
        f"- Intent summary: {_normalize_text(pilot_context.get('intent_summary')) or current_intent}",
    ]

    constraints = [
        _normalize_text(item)
        for item in (pilot_context.get("constraints") or [])
        if _normalize_text(item)
    ]
    if constraints:
        lines.append("- Constraints:")
        lines.extend(f"  - {item}" for item in constraints[:4])
    else:
        lines.append("- Constraints: none recorded")

    history = [
        _normalize_text(item)
        for item in (pilot_context.get("history") or [])
        if _normalize_text(item)
    ]
    if history:
        lines.append("- Recent pilot guidance:")
        lines.extend(f"  - {item}" for item in history[-3:])

    return "\n".join(lines)


class BuilderAgent:
    def _work_fields(self, raw_input):
        profile = build_work_profile(task={"note": raw_input})
        return {
            "work_mode": profile.get("work_mode"),
            "domain": profile.get("domain"),
            "artifact": profile.get("artifact"),
            "operation": profile.get("operation"),
            "validation": profile.get("validation"),
        }

    def build(self, message):
        raw_input = message.get("intent", "").strip()
        pilot_context = build_pilot_context(raw_input)

        if not raw_input:
            return {
                "goal": "clarify build target",
                "note": "Clarify the requested implementation target.",
                "dependencies": ["main.py"],
                "next_action": "Clarify the requested implementation target",
                "status": "drafted",
                "source": "builder",
                "pilot_context": pilot_context,
                "pilot_intent": pilot_context.get("current_intent"),
                **self._work_fields(raw_input),
            }

        return {
            "goal": raw_input,
            "note": raw_input,
            "dependencies": ["main.py"],
            "next_action": "Inspect the most relevant implementation area",
            "status": "drafted",
            "source": "builder",
            "pilot_context": pilot_context,
            "pilot_intent": pilot_context.get("current_intent"),
            **self._work_fields(raw_input),
        }

    def continue_task(self, task):
        note = task.get("note", "").strip() or task.get("goal", "").strip() or "Resume current task"
        pilot_context = merge_pilot_context((task.get("metadata") or {}).get("pilot_context"), note)

        return {
            "goal": note,
            "note": note,
            "dependencies": ["main.py"],
            "next_action": "Resume implementation from stored task context",
            "status": "continued",
            "source": "builder",
            "pilot_context": pilot_context,
            "pilot_intent": pilot_context.get("current_intent"),
            **self._work_fields(note),
        }
