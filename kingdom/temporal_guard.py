from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


EVENT_STATUSES = frozenset({"planned", "attempted", "completed", "failed", "cancelled"})

_ALLOWED_TRANSITIONS = {
    "planned": frozenset({"planned", "attempted", "completed", "cancelled"}),
    "attempted": frozenset({"attempted", "completed", "failed"}),
    "completed": frozenset({"completed"}),
    "failed": frozenset({"failed"}),
    "cancelled": frozenset({"cancelled"}),
}

_FUTURE_ONLY_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bwill\b",
        r"\btomorrow\b",
        r"\bplans?\s+to\b",
        r"\bplanned\s+to\b",
        r"\bintends?\s+to\b",
        r"\bintended\s+to\b",
        r"\bresolves?\s+to\b",
        r"\bresolved\s+to\b",
        r"\bdecides?\s+to\b",
        r"\bdecided\s+to\b",
        r"\bgoing\s+to\b",
        r"\bneeds?\s+to\b",
        r"\bmust\b",
        r"\bshould\b",
    )
)


class TemporalInvariantError(ValueError):
    """Raised when a narrative-state update violates temporal evidence rules."""


@dataclass(frozen=True)
class TemporalEvent:
    event_id: str
    description: str
    status: str
    evidence: str = ""
    chapter: int | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TemporalEvent":
        event_id = str(value.get("event_id") or "").strip()
        description = str(value.get("description") or "").strip()
        status = str(value.get("status") or "").strip().lower()
        evidence = str(value.get("evidence") or "").strip()
        raw_chapter = value.get("chapter")
        chapter = int(raw_chapter) if raw_chapter is not None else None

        if not event_id:
            raise TemporalInvariantError("temporal event is missing event_id")
        if not description:
            raise TemporalInvariantError(f"{event_id}: temporal event is missing description")
        if status not in EVENT_STATUSES:
            raise TemporalInvariantError(
                f"{event_id}: invalid temporal status {status!r}; "
                f"expected one of {sorted(EVENT_STATUSES)}"
            )
        return cls(
            event_id=event_id,
            description=description,
            status=status,
            evidence=evidence,
            chapter=chapter,
        )


def _normalize_for_match(text: str) -> str:
    return " ".join(text.split()).casefold()


def _evidence_is_in_chapter(evidence: str, chapter_text: str) -> bool:
    if not evidence.strip():
        return False
    return _normalize_for_match(evidence) in _normalize_for_match(chapter_text)


def _looks_future_only(evidence: str) -> bool:
    return any(pattern.search(evidence) for pattern in _FUTURE_ONLY_PATTERNS)


def _index(events: Sequence[TemporalEvent]) -> dict[str, TemporalEvent]:
    indexed: dict[str, TemporalEvent] = {}
    for event in events:
        if event.event_id in indexed:
            raise TemporalInvariantError(f"duplicate temporal event_id: {event.event_id}")
        indexed[event.event_id] = event
    return indexed


def validate_temporal_transition(
    prior_events: Sequence[TemporalEvent],
    proposed_events: Sequence[TemporalEvent],
    *,
    chapter_text: str,
    chapter: int,
) -> None:
    """Validate that temporal state cannot outrun the prose that supposedly caused it.

    The guard is deliberately conservative. Any new terminal/attempt state or any
    status advancement must carry a verbatim evidence span from the current chapter.
    A completion claim whose only evidence is future-oriented language is rejected.
    """

    prior = _index(prior_events)
    proposed = _index(proposed_events)

    missing = sorted(set(prior) - set(proposed))
    if missing:
        raise TemporalInvariantError(
            "temporal state update dropped prior events: " + ", ".join(missing)
        )

    for event_id, current in proposed.items():
        previous = prior.get(event_id)

        if previous is not None:
            allowed = _ALLOWED_TRANSITIONS[previous.status]
            if current.status not in allowed:
                raise TemporalInvariantError(
                    f"{event_id}: illegal temporal transition "
                    f"{previous.status!r} -> {current.status!r}"
                )

        status_changed = previous is None or previous.status != current.status
        needs_current_evidence = status_changed and current.status in {
            "attempted",
            "completed",
            "failed",
            "cancelled",
        }

        if needs_current_evidence:
            if current.chapter != chapter:
                raise TemporalInvariantError(
                    f"{event_id}: status {current.status!r} must be attributed "
                    f"to current chapter {chapter}"
                )
            if not _evidence_is_in_chapter(current.evidence, chapter_text):
                raise TemporalInvariantError(
                    f"{event_id}: status {current.status!r} lacks verbatim "
                    "evidence from the current chapter"
                )

        if current.status == "completed" and status_changed:
            if _looks_future_only(current.evidence):
                raise TemporalInvariantError(
                    f"{event_id}: completion evidence is future-oriented; "
                    "a plan/intention cannot be promoted to a completed event"
                )


def temporal_events_from_mapping(
    values: Sequence[Mapping[str, Any]],
) -> tuple[TemporalEvent, ...]:
    return tuple(TemporalEvent.from_mapping(value) for value in values)
