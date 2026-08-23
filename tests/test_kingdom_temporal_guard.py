import pytest

from kingdom.temporal_guard import (
    TemporalEvent,
    TemporalInvariantError,
    temporal_events_from_mapping,
    validate_temporal_transition,
)


def _event(status, evidence="", chapter=1):
    return TemporalEvent(
        event_id="ask-father-thomas",
        description="Ren asks Father Thomas about the furnace",
        status=status,
        evidence=evidence,
        chapter=chapter,
    )


def test_future_plan_cannot_be_promoted_to_completed_event():
    prior = (
        _event(
            "planned",
            evidence="Ren resolves to ask Father Thomas tomorrow.",
            chapter=1,
        ),
    )
    chapter = "Ren resolves to ask Father Thomas tomorrow."
    proposed = (
        _event(
            "completed",
            evidence="Ren resolves to ask Father Thomas tomorrow.",
            chapter=2,
        ),
    )

    with pytest.raises(TemporalInvariantError, match="future-oriented"):
        validate_temporal_transition(
            prior,
            proposed,
            chapter_text=chapter,
            chapter=2,
        )


def test_completed_event_requires_evidence_from_current_chapter():
    prior = (_event("planned", chapter=1),)
    proposed = (
        _event(
            "completed",
            evidence="Ren asked Father Thomas about the furnace.",
            chapter=2,
        ),
    )

    with pytest.raises(TemporalInvariantError, match="lacks verbatim evidence"):
        validate_temporal_transition(
            prior,
            proposed,
            chapter_text="Ren repaired the porch instead.",
            chapter=2,
        )


def test_realized_plan_can_advance_to_completed():
    prior = (_event("planned", chapter=1),)
    evidence = "The next morning, Ren asked Father Thomas about the furnace."
    proposed = (_event("completed", evidence=evidence, chapter=2),)

    validate_temporal_transition(
        prior,
        proposed,
        chapter_text=f"{evidence} Father Thomas frowned.",
        chapter=2,
    )


def test_completed_event_cannot_regress():
    prior = (_event("completed", evidence="done", chapter=1),)
    proposed = (_event("planned", chapter=2),)

    with pytest.raises(TemporalInvariantError, match="illegal temporal transition"):
        validate_temporal_transition(
            prior,
            proposed,
            chapter_text="Ren thought about it again.",
            chapter=2,
        )


def test_prior_event_cannot_disappear_from_state():
    prior = (_event("planned", chapter=1),)

    with pytest.raises(TemporalInvariantError, match="dropped prior events"):
        validate_temporal_transition(
            prior,
            (),
            chapter_text="Nothing relevant happens.",
            chapter=2,
        )


def test_duplicate_event_ids_are_rejected():
    duplicate = (
        _event("planned"),
        _event("planned"),
    )

    with pytest.raises(TemporalInvariantError, match="duplicate temporal event_id"):
        validate_temporal_transition(
            (),
            duplicate,
            chapter_text="",
            chapter=2,
        )


def test_mapping_parser_rejects_unknown_status():
    with pytest.raises(TemporalInvariantError, match="invalid temporal status"):
        temporal_events_from_mapping(
            [
                {
                    "event_id": "x",
                    "description": "something",
                    "status": "eventually",
                }
            ]
        )
