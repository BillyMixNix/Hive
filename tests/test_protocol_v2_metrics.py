import copy
import json

import pytest

from kingdom.protocol_v2_metrics import (
    METRICS_SCHEMA_VERSION,
    ChapterMetrics,
    ConditionTrajectory,
    MetricJudgment,
    ProtocolV2MetricsError,
    RevisionChange,
    least_squares_slope,
    load_condition_trajectory,
    load_metric_judgment,
)


def _judgment(
    chapter=2,
    *,
    intent=0,
    repair=0,
    continuity=0,
    causal=0,
    obligations=0,
    progression=0,
):
    has_finding = any(
        (intent, repair, continuity, causal, obligations, progression)
    )
    return MetricJudgment(
        chapter=chapter,
        factual_continuity_violations=continuity,
        causal_prerequisite_violations=causal,
        obligation_violations=obligations,
        progression_economic_errors=progression,
        intent_drift_score=intent,
        repair_burden_score=repair,
        rationale=("The chapter was checked against the frozen authority.",),
        evidence=("A grounded observation from the chapter.",) if has_finding else (),
    )


def _chapter(chapter=2, *, condition="baseline", intent=0, repair=0):
    return ChapterMetrics(
        condition=condition,
        admissible=True,
        judgment=_judgment(chapter, intent=intent, repair=repair),
        illegal_state_promotions=0,
        unresolved_obligations=0,
        revision_change=RevisionChange.measure("Ren walks home.", "Ren walks home."),
    )


def test_metric_judgment_strict_json_round_trip():
    judgment = _judgment(
        continuity=2, progression=1, intent=25.5, repair=40
    )
    payload = judgment.to_mapping()

    assert payload["schema_version"] == METRICS_SCHEMA_VERSION
    assert MetricJudgment.from_mapping(payload) == judgment
    assert load_metric_judgment(json.dumps(payload)) == judgment


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("chapter", 1),
        ("chapter", True),
        ("factual_continuity_violations", -1),
        ("causal_prerequisite_violations", 10_001),
        ("progression_economic_errors", 1.5),
        ("intent_drift_score", -0.1),
        ("intent_drift_score", 100.1),
        ("repair_burden_score", float("nan")),
    ],
)
def test_metric_judgment_rejects_invalid_ranges_and_types(field, invalid):
    payload = _judgment().to_mapping()
    payload[field] = invalid
    with pytest.raises(ProtocolV2MetricsError):
        MetricJudgment.from_mapping(payload)


def test_metric_judgment_rejects_unknown_keys_and_unsupported_findings():
    payload = _judgment().to_mapping()
    payload["winner"] = "kingdom"
    with pytest.raises(ProtocolV2MetricsError, match="unexpected"):
        MetricJudgment.from_mapping(payload)

    payload = _judgment().to_mapping()
    payload["factual_continuity_violations"] = 1
    payload["continuity_violations"] = 1
    with pytest.raises(ProtocolV2MetricsError, match="requires at least one evidence"):
        MetricJudgment.from_mapping(payload)

    payload = _judgment(causal=1, obligations=2).to_mapping()
    payload["continuity_violations"] = 2
    with pytest.raises(ProtocolV2MetricsError, match="must equal"):
        MetricJudgment.from_mapping(payload)


def test_revision_change_is_deterministic_and_content_addressed():
    draft = "Ren walks home."
    final = "Ren walks slowly home."

    first = RevisionChange.measure(draft, final)
    second = RevisionChange.measure(draft, final)

    assert first == second
    assert first.draft_token_count == 4
    assert first.final_token_count == 5
    assert first.token_edit_distance == 1
    assert first.change_ratio == 0.2
    assert first.draft_sha256 != first.final_sha256
    assert RevisionChange.from_mapping(first.to_mapping()) == first


def test_revision_change_ignores_whitespace_only_edits_but_preserves_hashes():
    change = RevisionChange.measure("Ren walks home.", "Ren  walks\nhome.")

    assert change.change_ratio == 0.0
    assert change.token_edit_distance == 0
    assert change.draft_sha256 != change.final_sha256


def test_revision_mapping_rejects_forged_derived_ratio():
    payload = RevisionChange.measure("one two", "one three").to_mapping()
    payload["change_ratio"] = 0.0
    with pytest.raises(ProtocolV2MetricsError, match="inconsistent"):
        RevisionChange.from_mapping(payload)


def test_chapter_metrics_combines_raw_counts_scores_and_revision_change():
    metric = ChapterMetrics(
        condition="baseline",
        admissible=False,
        judgment=_judgment(
            continuity=2, progression=1, intent=50, repair=40
        ),
        illegal_state_promotions=3,
        unresolved_obligations=4,
        revision_change=RevisionChange.measure(
            "Ren walks home.", "Ren walks slowly home."
        ),
    )

    # 2 + 3 + 1 + .5 intent + .4 residual repair burden.
    # Four open obligations are dependency load, not errors.
    assert metric.degradation_index == 6.9
    assert metric.revision_change_ratio == 0.2
    assert ChapterMetrics.from_mapping(metric.to_mapping()) == metric


def test_open_obligation_load_does_not_mechanically_raise_degradation():
    common = {
        "condition": "baseline",
        "admissible": True,
        "judgment": _judgment(),
        "illegal_state_promotions": 0,
        "revision_change": RevisionChange.measure("same", "same"),
    }

    low_load = ChapterMetrics(unresolved_obligations=1, **common)
    high_load = ChapterMetrics(unresolved_obligations=50, **common)

    assert low_load.degradation_index == high_load.degradation_index


def test_revision_activity_is_diagnostic_not_degradation():
    common = {
        "condition": "baseline",
        "admissible": True,
        "judgment": _judgment(repair=25),
        "illegal_state_promotions": 0,
        "unresolved_obligations": 0,
    }
    unchanged = ChapterMetrics(
        revision_change=RevisionChange.measure("same", "same"), **common
    )
    rewritten = ChapterMetrics(
        revision_change=RevisionChange.measure("one two", "three four"), **common
    )

    assert unchanged.revision_change_ratio != rewritten.revision_change_ratio
    assert unchanged.degradation_index == rewritten.degradation_index == 0.25


def test_chapter_mapping_rejects_forged_derived_index():
    payload = _chapter().to_mapping()
    payload["degradation_index"] = 99
    with pytest.raises(ProtocolV2MetricsError, match="inconsistent"):
        ChapterMetrics.from_mapping(payload)


def test_least_squares_slope_and_irregular_chapter_spacing():
    assert least_squares_slope(((2, 0.1), (3, 0.2), (4, 0.3))) == 0.1
    assert least_squares_slope(((2, 1.0), (4, 2.0), (8, 4.0))) == 0.5


def test_one_chapter_slope_is_null():
    metric = _chapter(intent=25)
    trajectory = ConditionTrajectory.aggregate("baseline", [metric])

    assert trajectory.degradation_slope is None
    assert trajectory.to_mapping()["aggregate"]["degradation_slope"] is None


def test_condition_trajectory_aggregates_and_round_trips_json():
    chapters = [
        _chapter(2, intent=10),
        _chapter(3, intent=20),
        _chapter(4, intent=30),
    ]
    trajectory = ConditionTrajectory.aggregate("baseline", reversed(chapters))
    aggregate = trajectory.aggregate_mapping()

    assert trajectory.degradation_slope == 0.1
    assert aggregate["chapter_count"] == 3
    assert aggregate["admissible_chapters"] == 3
    assert aggregate["mean_degradation_index"] == 0.2
    encoded = json.dumps(trajectory.to_mapping(), sort_keys=True)
    assert load_condition_trajectory(encoded) == trajectory


def test_trajectory_rejects_mixed_conditions_duplicate_chapters_and_forgery():
    with pytest.raises(ProtocolV2MetricsError, match="condition"):
        ConditionTrajectory(
            "baseline",
            (_chapter(condition="baseline"), _chapter(3, condition="kingdom")),
        )

    with pytest.raises(ProtocolV2MetricsError, match="strictly increasing"):
        ConditionTrajectory("baseline", (_chapter(), _chapter()))

    payload = ConditionTrajectory.aggregate("baseline", [_chapter()]).to_mapping()
    forged = copy.deepcopy(payload)
    forged["aggregate"]["continuity_violations"] = 8
    with pytest.raises(ProtocolV2MetricsError, match="inconsistent"):
        ConditionTrajectory.from_mapping(forged)


def test_slope_rejects_empty_duplicate_and_nonfinite_inputs():
    with pytest.raises(ProtocolV2MetricsError, match="at least one"):
        least_squares_slope(())
    with pytest.raises(ProtocolV2MetricsError, match="unique"):
        least_squares_slope(((2, 0.0), (2, 1.0)))
    with pytest.raises(ProtocolV2MetricsError, match="finite"):
        least_squares_slope(((2, 0.0), (3, float("inf"))))
