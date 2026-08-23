import json

import pytest

from kingdom.story_map import (
    SCHEMA_VERSION,
    STATE_CATEGORIES,
    CanonicalClaim,
    CanonicalState,
    ClaimEvidence,
    StoryDependencyError,
    StoryEvidenceError,
    StoryGuard,
    StorySchemaError,
    StoryTransitionError,
    chapter_sha256,
    load_canonical_state,
    load_story_map,
    update_canonical_state,
    validate_story_map,
)


def _empty_categories():
    return {category: [] for category in STATE_CATEGORIES}


def _evidence(chapter_text, quote, chapter=2, **overrides):
    value = {
        "source_id": f"chapter:{chapter:04d}",
        "source_sha256": chapter_sha256(chapter_text),
        "chapter": chapter,
        "quote": quote,
    }
    value.update(overrides)
    return value


def _claim(claim_id, statement, evidence, *, status="current", depends_on=()):
    return {
        "claim_id": claim_id,
        "statement": statement,
        "status": status,
        "depends_on": list(depends_on),
        "evidence": evidence,
    }


def _payload(chapter, claims):
    return {
        "schema_version": SCHEMA_VERSION,
        "chapter": chapter,
        "claims": claims,
    }


def _with_summary(chapter_text, entries, *, chapter=2):
    claims = _empty_categories()
    for category, claim in entries:
        claims[category].append(claim)
    if not claims["chapter_summaries"]:
        quote = "Ren closes the ledger."
        claims["chapter_summaries"].append(
            _claim(
                f"summary:{chapter:04d}",
                f"Chapter {chapter} closes with Ren at the ledger.",
                _evidence(chapter_text, quote, chapter),
            )
        )
    return _payload(chapter, claims)


def _blueprint_claim(claim_id, statement, *, depends_on=(), category="cultivation_state"):
    source = f"Blueprint milestone: {statement}"
    evidence = ClaimEvidence(
        source_id="seed:future-blueprint",
        source_sha256=chapter_sha256(source),
        chapter=0,
        quote=source,
        start=0,
        end=len(source),
    )
    return CanonicalClaim(
        claim_id=claim_id,
        category=category,
        statement=statement,
        status="blueprint",
        depends_on=tuple(depends_on),
        provenance=(evidence,),
        created_chapter=0,
        updated_chapter=0,
    )


def test_all_state_categories_are_typed_guarded_and_legacy_derived():
    evidence_by_category = {
        "facts": "Ren deposits his first earned dollar.",
        "character_states": "Ren relaxes after checking the balance.",
        "knowledge": "Ren learns that equal breaths transfer no money.",
        "financial_state": "The account balance stands at twelve dollars.",
        "cultivation_state": "Ren completes a stable profitable breath.",
        "assets": "Ren owns the repaired delivery bicycle.",
        "obligations": "Ren owes Mira twelve dollars for the repair.",
        "mysteries": "The source of the legal deposits remains unknown.",
        "themes": "Usefulness matters more than the displayed price.",
        "tone": "The scene settles into wary comedy.",
        "chapter_summaries": "Ren closes the ledger.",
    }
    chapter_text = "\n".join(evidence_by_category.values())
    claims = _empty_categories()
    expected = {}
    for index, category in enumerate(STATE_CATEGORIES, start=1):
        statement = f"Canonical {category} claim {index}."
        expected[category] = statement
        quote = evidence_by_category[category]
        claims[category].append(
            _claim(
                f"{category}:{index}",
                statement,
                _evidence(chapter_text, quote),
            )
        )

    story_map = load_story_map(json.dumps(_payload(2, claims)))
    state = update_canonical_state(
        CanonicalState.empty(through_chapter=1),
        story_map,
        chapter_text=chapter_text,
        chapter=2,
    )

    legacy = state.to_legacy_story_state()
    for category in STATE_CATEGORIES:
        assert legacy[category] == [expected[category]]
    assert legacy["rolling_summary"] == expected["chapter_summaries"]
    assert all(claim.provenance[-1].source_sha256 == chapter_sha256(chapter_text) for claim in state.claims)
    assert load_canonical_state(json.dumps(state.to_mapping())) == state


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda evidence: evidence.update(chapter=1), "evidence chapter"),
        (lambda evidence: evidence.update(source_id="seed:blueprint"), "source_id"),
        (lambda evidence: evidence.update(source_sha256="0" * 64), "evidence hash"),
        (lambda evidence: evidence.update(quote="This sentence is absent."), "exact substring"),
    ],
)
def test_current_claim_requires_exact_current_chapter_provenance(mutate, message):
    chapter_text = "Ren closes the ledger."
    evidence = _evidence(chapter_text, chapter_text)
    mutate(evidence)
    claims = _empty_categories()
    claims["chapter_summaries"].append(
        _claim("summary:0002", "Ren closes the ledger.", evidence)
    )

    with pytest.raises(StoryEvidenceError, match=message):
        update_canonical_state(
            CanonicalState.empty(through_chapter=1),
            _payload(2, claims),
            chapter_text=chapter_text,
            chapter=2,
        )


def test_explicit_evidence_span_must_match_exact_chapter_slice():
    chapter_text = "Ren closes the ledger."
    evidence = _evidence(
        chapter_text,
        chapter_text,
        start=1,
        end=len(chapter_text) + 1,
    )
    claims = _empty_categories()
    claims["chapter_summaries"].append(
        _claim("summary:0002", "Ren closes the ledger.", evidence)
    )

    with pytest.raises(StoryEvidenceError, match="span extends beyond"):
        update_canonical_state(
            CanonicalState.empty(through_chapter=1),
            _payload(2, claims),
            chapter_text=chapter_text,
            chapter=2,
        )


def test_future_plan_cannot_be_current_but_can_remain_noncanonical_blueprint():
    chapter_text = (
        "Ren closes the ledger. "
        "Ren will enter the Fifth Realm tomorrow."
    )
    future_quote = "Ren will enter the Fifth Realm tomorrow."
    future_claim = _claim(
        "realm:fifth",
        "Ren enters the Fifth Realm",
        _evidence(chapter_text, future_quote),
        status="current",
    )
    current_payload = _with_summary(
        chapter_text,
        [("cultivation_state", future_claim)],
    )

    with pytest.raises(StoryEvidenceError, match="future-plan language"):
        update_canonical_state(
            CanonicalState.empty(through_chapter=1),
            current_payload,
            chapter_text=chapter_text,
            chapter=2,
        )

    future_claim["status"] = "blueprint"
    blueprint_state = update_canonical_state(
        CanonicalState.empty(through_chapter=1),
        _with_summary(chapter_text, [("cultivation_state", future_claim)]),
        chapter_text=chapter_text,
        chapter=2,
    )
    assert blueprint_state.to_legacy_story_state()["cultivation_state"] == []

    persisted_future = _blueprint_claim(
        "realm:future-fifth",
        "Ren will enter the Fifth Realm tomorrow",
    ).to_mapping()
    persisted_future["status"] = "current"
    with pytest.raises(StoryEvidenceError, match="future-plan language"):
        load_canonical_state(
            {
                "schema_version": SCHEMA_VERSION,
                "through_chapter": 1,
                "claims": [persisted_future],
            }
        )


def test_blueprint_can_promote_with_actual_evidence_but_cannot_regress():
    milestone = _blueprint_claim("realm:second", "Ren enters the Second Realm")
    initial = CanonicalState(through_chapter=1, claims=(milestone,))
    chapter_two = "Ren closes the ledger. Ren enters the Second Realm."
    promoted = update_canonical_state(
        initial,
        _with_summary(
            chapter_two,
            [
                (
                    "cultivation_state",
                    _claim(
                        milestone.claim_id,
                        milestone.statement,
                        _evidence(chapter_two, "Ren enters the Second Realm."),
                    ),
                )
            ],
        ),
        chapter_text=chapter_two,
        chapter=2,
    )
    promoted_claim = next(
        claim for claim in promoted.claims if claim.claim_id == milestone.claim_id
    )
    assert promoted_claim.status == "current"
    assert [item.chapter for item in promoted_claim.provenance] == [0, 2]

    chapter_three = "Ren closes the ledger. Ren studies the realm map."
    regression = _with_summary(
        chapter_three,
        [
            (
                "cultivation_state",
                _claim(
                    milestone.claim_id,
                    milestone.statement,
                    _evidence(chapter_three, "Ren studies the realm map.", 3),
                    status="planned",
                ),
            )
        ],
        chapter=3,
    )
    with pytest.raises(StoryTransitionError, match="illegal transition"):
        update_canonical_state(
            promoted,
            regression,
            chapter_text=chapter_three,
            chapter=3,
        )


def test_dependency_must_be_satisfied_before_blueprint_promotion():
    prerequisite = _blueprint_claim(
        "realm:circulation",
        "Ren establishes Circulation of Wealth",
    )
    milestone = _blueprint_claim(
        "realm:treasury",
        "Ren enters the Treasury Domain",
        depends_on=(prerequisite.claim_id,),
    )
    initial = CanonicalState(
        through_chapter=1,
        claims=(prerequisite, milestone),
    )
    chapter_text = (
        "Ren closes the ledger. "
        "Ren establishes Circulation of Wealth. "
        "Ren enters the Treasury Domain."
    )
    milestone_only = _with_summary(
        chapter_text,
        [
            (
                "cultivation_state",
                _claim(
                    milestone.claim_id,
                    milestone.statement,
                    _evidence(chapter_text, "Ren enters the Treasury Domain."),
                    depends_on=milestone.depends_on,
                ),
            )
        ],
    )
    with pytest.raises(StoryDependencyError, match="unsatisfied dependencies"):
        StoryGuard().update(
            initial,
            load_story_map(milestone_only),
            chapter_text=chapter_text,
            chapter=2,
        )

    both_promoted = _with_summary(
        chapter_text,
        [
            (
                "cultivation_state",
                _claim(
                    milestone.claim_id,
                    milestone.statement,
                    _evidence(chapter_text, "Ren enters the Treasury Domain."),
                    depends_on=milestone.depends_on,
                ),
            ),
            (
                "cultivation_state",
                _claim(
                    prerequisite.claim_id,
                    prerequisite.statement,
                    _evidence(
                        chapter_text,
                        "Ren establishes Circulation of Wealth.",
                    ),
                ),
            ),
        ],
    )
    accepted = validate_story_map(
        initial,
        both_promoted,
        chapter_text=chapter_text,
        chapter=2,
    )
    assert {claim.claim_id for claim in accepted} >= {
        prerequisite.claim_id,
        milestone.claim_id,
    }


def test_dependency_removal_and_cycles_are_rejected():
    prerequisite = _blueprint_claim("setup:first", "Ren earns the first setup")
    milestone = _blueprint_claim(
        "payoff:first",
        "Ren earns the first payoff",
        depends_on=(prerequisite.claim_id,),
    )
    initial = CanonicalState(through_chapter=1, claims=(prerequisite, milestone))
    chapter_text = "Ren closes the ledger. Ren earns the first payoff."
    removed = _with_summary(
        chapter_text,
        [
            (
                "cultivation_state",
                _claim(
                    milestone.claim_id,
                    milestone.statement,
                    _evidence(chapter_text, "Ren earns the first payoff."),
                    status="blueprint",
                    depends_on=(),
                ),
            )
        ],
    )
    with pytest.raises(StoryDependencyError, match="cannot remove dependencies"):
        update_canonical_state(
            initial,
            removed,
            chapter_text=chapter_text,
            chapter=2,
        )

    cycle_text = "Ren closes the ledger. Ren sketches two linked possibilities."
    common_evidence = _evidence(
        cycle_text,
        "Ren sketches two linked possibilities.",
    )
    cycle = _with_summary(
        cycle_text,
        [
            (
                "facts",
                _claim(
                    "plan:left",
                    "Left blueprint node",
                    common_evidence,
                    status="blueprint",
                    depends_on=("plan:right",),
                ),
            ),
            (
                "facts",
                _claim(
                    "plan:right",
                    "Right blueprint node",
                    common_evidence,
                    status="blueprint",
                    depends_on=("plan:left",),
                ),
            ),
        ],
    )
    with pytest.raises(StoryDependencyError, match="cycle"):
        update_canonical_state(
            CanonicalState.empty(through_chapter=1),
            cycle,
            chapter_text=cycle_text,
            chapter=2,
        )


def test_empty_or_legacy_state_payload_cannot_bypass_typed_claim_validation():
    empty = _payload(2, _empty_categories())
    with pytest.raises(StorySchemaError, match="all-empty claim map"):
        load_story_map(empty)

    direct_legacy = _payload(2, _empty_categories())
    direct_legacy["rolling_summary"] = "Ren already owns the Grand Exchange."
    with pytest.raises(StorySchemaError, match="unexpected"):
        load_story_map(direct_legacy)

    untyped = _empty_categories()
    untyped["facts"] = ["Ren already owns the Grand Exchange."]
    untyped["chapter_summaries"] = [
        _claim(
            "summary:0002",
            "Ren closes the ledger.",
            _evidence("Ren closes the ledger.", "Ren closes the ledger."),
        )
    ]
    with pytest.raises(StorySchemaError, match="not legacy text"):
        load_story_map(_payload(2, untyped))

    missing_category = _empty_categories()
    del missing_category["assets"]
    with pytest.raises(StorySchemaError, match="missing=.*assets"):
        load_story_map(_payload(2, missing_category))


def test_chapter_updates_must_be_contiguous():
    chapter_text = "Ren closes the ledger."
    payload = _with_summary(chapter_text, [], chapter=3)
    with pytest.raises(StoryTransitionError, match="contiguous"):
        update_canonical_state(
            CanonicalState.empty(through_chapter=1),
            payload,
            chapter_text=chapter_text,
            chapter=3,
        )


def test_persisted_blueprint_provenance_allows_chapter_zero_but_not_invalid_canon():
    prerequisite = _blueprint_claim(
        "realm:circulation",
        "Ren establishes Circulation of Wealth",
    )
    milestone = _blueprint_claim(
        "realm:treasury",
        "Ren enters the Treasury Domain",
        depends_on=(prerequisite.claim_id,),
    )
    blueprint_state = CanonicalState(
        through_chapter=1,
        claims=(prerequisite, milestone),
    )

    assert load_canonical_state(json.dumps(blueprint_state.to_mapping())) == blueprint_state

    invalid_claim = milestone.to_mapping()
    invalid_claim["status"] = "current"
    invalid_state = blueprint_state.to_mapping()
    invalid_state["claims"] = [prerequisite.to_mapping(), invalid_claim]
    with pytest.raises(StoryDependencyError, match="unsatisfied dependencies"):
        load_canonical_state(invalid_state)
