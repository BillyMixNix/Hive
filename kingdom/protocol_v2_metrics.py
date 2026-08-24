"""Deterministic longitudinal metrics for ADI Protocol v2.

The model-facing portion of this module is deliberately small: a judge may
propose a :class:`MetricJudgment`, but it cannot calculate or alter the
deterministic promotion, obligation, revision, or trajectory measurements.
This module performs no model or network calls.

``degradation_index`` is expressed in *error-equivalent units*.  Each observed
discrete error contributes one unit and each 0--100 severity score contributes
0--1.  The deterministic draft-to-final token edit ratio is retained as a
diagnostic, but is deliberately excluded from degradation: the two treatments
use different pre-registered revision procedures, so revision activity is not
itself an error.  ``repair_burden_score`` instead measures residual work still
needed after the final response.  Open obligations are recorded as dependency
load, not counted as degradation: a condition must not be penalized merely for
remembering more obligations.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


METRICS_SCHEMA_VERSION = 1
CONDITIONS = frozenset({"baseline", "kingdom"})
MAX_FINDINGS_PER_CHAPTER = 10_000
MAX_TEXT_ITEMS = 100
MAX_TEXT_ITEM_CHARS = 4_000
_FLOAT_DIGITS = 12
_MAX_DEGRADATION_INDEX = 5 * MAX_FINDINGS_PER_CHAPTER + 2
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


class ProtocolV2MetricsError(ValueError):
    """Raised when a Protocol-v2 metric payload is malformed or inconsistent."""


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], *, label: str
) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing={missing}")
        if unexpected:
            details.append(f"unexpected={unexpected}")
        raise ProtocolV2MetricsError(
            f"{label} has invalid keys: " + ", ".join(details)
        )


def _require_int(
    value: Any,
    *,
    label: str,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolV2MetricsError(f"{label} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        maximum_text = "" if maximum is None else f" and <= {maximum}"
        raise ProtocolV2MetricsError(
            f"{label} must be >= {minimum}{maximum_text}"
        )
    return value


def _require_float(
    value: Any,
    *,
    label: str,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolV2MetricsError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < minimum or result > maximum:
        raise ProtocolV2MetricsError(
            f"{label} must be finite and between {minimum} and {maximum}"
        )
    return result


def _require_condition(value: Any) -> str:
    if not isinstance(value, str):
        raise ProtocolV2MetricsError("condition must be a string")
    condition = value.strip().lower()
    if condition not in CONDITIONS:
        raise ProtocolV2MetricsError(
            f"condition must be one of {sorted(CONDITIONS)}, got {condition!r}"
        )
    return condition


def _require_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ProtocolV2MetricsError(f"{label} must be a boolean")
    return value


def _require_text_list(
    value: Any, *, label: str, require_nonempty: bool
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProtocolV2MetricsError(f"{label} must be a list")
    if require_nonempty and not value:
        raise ProtocolV2MetricsError(f"{label} must contain at least one item")
    if len(value) > MAX_TEXT_ITEMS:
        raise ProtocolV2MetricsError(
            f"{label} may contain at most {MAX_TEXT_ITEMS} items"
        )
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ProtocolV2MetricsError(
                f"{label}[{index}] must be a non-empty string"
            )
        text = item.strip()
        if len(text) > MAX_TEXT_ITEM_CHARS:
            raise ProtocolV2MetricsError(
                f"{label}[{index}] exceeds {MAX_TEXT_ITEM_CHARS} characters"
            )
        result.append(text)
    if len(result) != len(set(result)):
        raise ProtocolV2MetricsError(f"{label} contains duplicate items")
    return tuple(result)


def _rounded(value: float) -> float:
    return round(value, _FLOAT_DIGITS)


def _require_derived_float(value: Any, expected: float, *, label: str) -> None:
    observed = _require_float(
        value,
        label=label,
        minimum=-float(_MAX_DEGRADATION_INDEX),
        maximum=float(_MAX_DEGRADATION_INDEX),
    )
    if not math.isclose(observed, expected, rel_tol=0.0, abs_tol=10**-_FLOAT_DIGITS):
        raise ProtocolV2MetricsError(
            f"{label} is inconsistent: expected {expected}, got {observed}"
        )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tokenize(text: str) -> tuple[str, ...]:
    return tuple(_TOKEN_RE.findall(text))


def _token_edit_distance(left: Sequence[str], right: Sequence[str]) -> int:
    """Return exact Levenshtein distance with O(min(n, m)) memory."""

    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for left_index, left_token in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_token in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_token != right_token),
                )
            )
        previous = current
    return previous[-1]


@dataclass(frozen=True)
class MetricJudgment:
    """Strict model-proposed measurements for one condition/chapter.

    Continuity is split into three mutually exclusive counts so the stated
    causal and obligation hypotheses cannot disappear inside a generic score:
    factual contradictions, missing/broken causal prerequisites, and
    contradicted/false-resolved/due-forgotten obligations.  Their sum is the
    public ``continuity_violations`` metric.  Scores use 0 for no observed
    problem and 100 for maximal observed drift or residual repair burden.  A
    non-zero judgment must cite at least one evidence item; every judgment must
    contain a rationale.
    """

    chapter: int
    factual_continuity_violations: int
    causal_prerequisite_violations: int
    obligation_violations: int
    progression_economic_errors: int
    intent_drift_score: float
    repair_burden_score: float
    rationale: tuple[str, ...]
    evidence: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "chapter", _require_int(self.chapter, label="chapter", minimum=2)
        )
        object.__setattr__(
            self,
            "factual_continuity_violations",
            _require_int(
                self.factual_continuity_violations,
                label="factual_continuity_violations",
                maximum=MAX_FINDINGS_PER_CHAPTER,
            ),
        )
        object.__setattr__(
            self,
            "causal_prerequisite_violations",
            _require_int(
                self.causal_prerequisite_violations,
                label="causal_prerequisite_violations",
                maximum=MAX_FINDINGS_PER_CHAPTER,
            ),
        )
        object.__setattr__(
            self,
            "obligation_violations",
            _require_int(
                self.obligation_violations,
                label="obligation_violations",
                maximum=MAX_FINDINGS_PER_CHAPTER,
            ),
        )
        object.__setattr__(
            self,
            "progression_economic_errors",
            _require_int(
                self.progression_economic_errors,
                label="progression_economic_errors",
                maximum=MAX_FINDINGS_PER_CHAPTER,
            ),
        )
        object.__setattr__(
            self,
            "intent_drift_score",
            _require_float(
                self.intent_drift_score,
                label="intent_drift_score",
                minimum=0.0,
                maximum=100.0,
            ),
        )
        object.__setattr__(
            self,
            "repair_burden_score",
            _require_float(
                self.repair_burden_score,
                label="repair_burden_score",
                minimum=0.0,
                maximum=100.0,
            ),
        )
        if not isinstance(self.rationale, tuple):
            raise ProtocolV2MetricsError("rationale must be a tuple")
        if not isinstance(self.evidence, tuple):
            raise ProtocolV2MetricsError("evidence must be a tuple")
        rationale = _require_text_list(
            list(self.rationale), label="rationale", require_nonempty=True
        )
        evidence = _require_text_list(
            list(self.evidence), label="evidence", require_nonempty=False
        )
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "evidence", evidence)
        has_finding = any(
            (
                self.factual_continuity_violations,
                self.causal_prerequisite_violations,
                self.obligation_violations,
                self.progression_economic_errors,
                self.intent_drift_score,
                self.repair_burden_score,
            )
        )
        if has_finding and not self.evidence:
            raise ProtocolV2MetricsError(
                "a non-zero metric judgment requires at least one evidence item"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MetricJudgment":
        if not isinstance(value, Mapping):
            raise ProtocolV2MetricsError("metric judgment must be an object")
        _require_exact_keys(
            value,
            {
                "schema_version",
                "chapter",
                "continuity_violations",
                "factual_continuity_violations",
                "causal_prerequisite_violations",
                "obligation_violations",
                "progression_economic_errors",
                "intent_drift_score",
                "repair_burden_score",
                "rationale",
                "evidence",
            },
            label="metric judgment",
        )
        if _require_int(
            value["schema_version"], label="schema_version"
        ) != METRICS_SCHEMA_VERSION:
            raise ProtocolV2MetricsError(
                f"metric judgment schema_version must be {METRICS_SCHEMA_VERSION}"
            )
        result = cls(
            chapter=value["chapter"],
            factual_continuity_violations=value[
                "factual_continuity_violations"
            ],
            causal_prerequisite_violations=value[
                "causal_prerequisite_violations"
            ],
            obligation_violations=value["obligation_violations"],
            progression_economic_errors=value["progression_economic_errors"],
            intent_drift_score=value["intent_drift_score"],
            repair_burden_score=value["repair_burden_score"],
            rationale=_require_text_list(
                value["rationale"], label="rationale", require_nonempty=True
            ),
            evidence=_require_text_list(
                value["evidence"], label="evidence", require_nonempty=False
            ),
        )
        if value["continuity_violations"] != result.continuity_violations:
            raise ProtocolV2MetricsError(
                "continuity_violations must equal factual + causal-prerequisite "
                "+ obligation violations"
            )
        return result

    @property
    def continuity_violations(self) -> int:
        return (
            self.factual_continuity_violations
            + self.causal_prerequisite_violations
            + self.obligation_violations
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": METRICS_SCHEMA_VERSION,
            "chapter": self.chapter,
            "continuity_violations": self.continuity_violations,
            "factual_continuity_violations": (
                self.factual_continuity_violations
            ),
            "causal_prerequisite_violations": (
                self.causal_prerequisite_violations
            ),
            "obligation_violations": self.obligation_violations,
            "progression_economic_errors": self.progression_economic_errors,
            "intent_drift_score": self.intent_drift_score,
            "repair_burden_score": self.repair_burden_score,
            "rationale": list(self.rationale),
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class RevisionChange:
    """Content-addressed, deterministic token-edit measurement."""

    draft_sha256: str
    final_sha256: str
    draft_char_count: int
    final_char_count: int
    draft_token_count: int
    final_token_count: int
    token_edit_distance: int

    def __post_init__(self) -> None:
        for label in ("draft_sha256", "final_sha256"):
            value = getattr(self, label)
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                raise ProtocolV2MetricsError(
                    f"{label} must be a lowercase SHA-256 digest"
                )
        for label in (
            "draft_char_count",
            "final_char_count",
            "draft_token_count",
            "final_token_count",
            "token_edit_distance",
        ):
            object.__setattr__(
                self, label, _require_int(getattr(self, label), label=label)
            )
        maximum_distance = max(self.draft_token_count, self.final_token_count)
        if self.token_edit_distance > maximum_distance:
            raise ProtocolV2MetricsError(
                "token_edit_distance cannot exceed the larger token count"
            )
        if self.draft_sha256 == self.final_sha256 and any(
            (
                self.draft_char_count != self.final_char_count,
                self.draft_token_count != self.final_token_count,
                self.token_edit_distance != 0,
            )
        ):
            raise ProtocolV2MetricsError(
                "identical text digests require identical sizes and zero edits"
            )

    @property
    def change_ratio(self) -> float:
        denominator = max(self.draft_token_count, self.final_token_count, 1)
        return _rounded(self.token_edit_distance / denominator)

    @classmethod
    def measure(cls, draft_text: str, final_text: str) -> "RevisionChange":
        if not isinstance(draft_text, str) or not isinstance(final_text, str):
            raise ProtocolV2MetricsError("draft_text and final_text must be strings")
        draft_tokens = _tokenize(draft_text)
        final_tokens = _tokenize(final_text)
        return cls(
            draft_sha256=_sha256(draft_text),
            final_sha256=_sha256(final_text),
            draft_char_count=len(draft_text),
            final_char_count=len(final_text),
            draft_token_count=len(draft_tokens),
            final_token_count=len(final_tokens),
            token_edit_distance=_token_edit_distance(draft_tokens, final_tokens),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "RevisionChange":
        if not isinstance(value, Mapping):
            raise ProtocolV2MetricsError("revision change must be an object")
        _require_exact_keys(
            value,
            {
                "draft_sha256",
                "final_sha256",
                "draft_char_count",
                "final_char_count",
                "draft_token_count",
                "final_token_count",
                "token_edit_distance",
                "change_ratio",
            },
            label="revision change",
        )
        result = cls(
            draft_sha256=value["draft_sha256"],
            final_sha256=value["final_sha256"],
            draft_char_count=value["draft_char_count"],
            final_char_count=value["final_char_count"],
            draft_token_count=value["draft_token_count"],
            final_token_count=value["final_token_count"],
            token_edit_distance=value["token_edit_distance"],
        )
        _require_derived_float(
            value["change_ratio"], result.change_ratio, label="change_ratio"
        )
        return result

    def to_mapping(self) -> dict[str, Any]:
        return {
            "draft_sha256": self.draft_sha256,
            "final_sha256": self.final_sha256,
            "draft_char_count": self.draft_char_count,
            "final_char_count": self.final_char_count,
            "draft_token_count": self.draft_token_count,
            "final_token_count": self.final_token_count,
            "token_edit_distance": self.token_edit_distance,
            "change_ratio": self.change_ratio,
        }


@dataclass(frozen=True)
class ChapterMetrics:
    """Combined judge and deterministic measurements for one branch.

    ``unresolved_obligations`` is the number of canonical open obligations at
    chapter end.  It measures dependency load and is deliberately excluded from
    ``degradation_index``.  A forgotten or contradicted obligation belongs in
    the continuity-violation count instead.
    """

    condition: str
    admissible: bool
    judgment: MetricJudgment
    illegal_state_promotions: int
    unresolved_obligations: int
    revision_change: RevisionChange

    def __post_init__(self) -> None:
        object.__setattr__(self, "condition", _require_condition(self.condition))
        object.__setattr__(
            self, "admissible", _require_bool(self.admissible, label="admissible")
        )
        if not isinstance(self.judgment, MetricJudgment):
            raise ProtocolV2MetricsError("judgment must be a MetricJudgment")
        object.__setattr__(
            self,
            "illegal_state_promotions",
            _require_int(
                self.illegal_state_promotions,
                label="illegal_state_promotions",
                maximum=MAX_FINDINGS_PER_CHAPTER,
            ),
        )
        object.__setattr__(
            self,
            "unresolved_obligations",
            _require_int(
                self.unresolved_obligations,
                label="unresolved_obligations",
                maximum=MAX_FINDINGS_PER_CHAPTER,
            ),
        )
        if not isinstance(self.revision_change, RevisionChange):
            raise ProtocolV2MetricsError(
                "revision_change must be a RevisionChange"
            )

    @property
    def chapter(self) -> int:
        return self.judgment.chapter

    @property
    def revision_change_ratio(self) -> float:
        return self.revision_change.change_ratio

    @property
    def degradation_index(self) -> float:
        return _rounded(
            self.judgment.continuity_violations
            + self.illegal_state_promotions
            + self.judgment.progression_economic_errors
            + self.judgment.intent_drift_score / 100.0
            + self.judgment.repair_burden_score / 100.0
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ChapterMetrics":
        if not isinstance(value, Mapping):
            raise ProtocolV2MetricsError("chapter metrics must be an object")
        _require_exact_keys(
            value,
            {
                "schema_version",
                "condition",
                "chapter",
                "admissible",
                "judgment",
                "illegal_state_promotions",
                "unresolved_obligations",
                "revision_change",
                "revision_change_ratio",
                "degradation_index",
            },
            label="chapter metrics",
        )
        if _require_int(
            value["schema_version"], label="schema_version"
        ) != METRICS_SCHEMA_VERSION:
            raise ProtocolV2MetricsError(
                f"chapter metrics schema_version must be {METRICS_SCHEMA_VERSION}"
            )
        result = cls(
            condition=value["condition"],
            admissible=value["admissible"],
            judgment=MetricJudgment.from_mapping(value["judgment"]),
            illegal_state_promotions=value["illegal_state_promotions"],
            unresolved_obligations=value["unresolved_obligations"],
            revision_change=RevisionChange.from_mapping(value["revision_change"]),
        )
        if value["chapter"] != result.chapter:
            raise ProtocolV2MetricsError(
                "chapter metrics chapter must match judgment chapter"
            )
        _require_derived_float(
            value["revision_change_ratio"],
            result.revision_change_ratio,
            label="revision_change_ratio",
        )
        _require_derived_float(
            value["degradation_index"],
            result.degradation_index,
            label="degradation_index",
        )
        return result

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": METRICS_SCHEMA_VERSION,
            "condition": self.condition,
            "chapter": self.chapter,
            "admissible": self.admissible,
            "judgment": self.judgment.to_mapping(),
            "illegal_state_promotions": self.illegal_state_promotions,
            "unresolved_obligations": self.unresolved_obligations,
            "revision_change": self.revision_change.to_mapping(),
            "revision_change_ratio": self.revision_change_ratio,
            "degradation_index": self.degradation_index,
        }


def least_squares_slope(points: Sequence[tuple[int, float]]) -> float | None:
    """Return y-units per chapter, or ``None`` for a one-point trajectory."""

    if not isinstance(points, Sequence) or not points:
        raise ProtocolV2MetricsError("slope requires at least one point")
    parsed: list[tuple[int, float]] = []
    seen_chapters: set[int] = set()
    for index, point in enumerate(points):
        if (
            isinstance(point, (str, bytes))
            or not isinstance(point, Sequence)
            or len(point) != 2
        ):
            raise ProtocolV2MetricsError(
                f"points[{index}] must be a (chapter, value) tuple"
            )
        chapter = _require_int(point[0], label=f"points[{index}].chapter", minimum=2)
        value = _require_float(
            point[1],
            label=f"points[{index}].value",
            minimum=0.0,
            maximum=float(_MAX_DEGRADATION_INDEX),
        )
        if chapter in seen_chapters:
            raise ProtocolV2MetricsError("slope chapters must be unique")
        seen_chapters.add(chapter)
        parsed.append((chapter, value))
    if len(parsed) == 1:
        return None
    mean_x = sum(chapter for chapter, _ in parsed) / len(parsed)
    mean_y = sum(value for _, value in parsed) / len(parsed)
    denominator = sum((chapter - mean_x) ** 2 for chapter, _ in parsed)
    if denominator == 0:
        raise ProtocolV2MetricsError("slope chapters must not all be equal")
    numerator = sum(
        (chapter - mean_x) * (value - mean_y) for chapter, value in parsed
    )
    return _rounded(numerator / denominator)


@dataclass(frozen=True)
class ConditionTrajectory:
    """Chapter-by-chapter degradation trajectory for one matched condition."""

    condition: str
    chapters: tuple[ChapterMetrics, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "condition", _require_condition(self.condition))
        if not isinstance(self.chapters, tuple) or not self.chapters:
            raise ProtocolV2MetricsError(
                "chapters must be a non-empty tuple of ChapterMetrics"
            )
        previous = 1
        for metric in self.chapters:
            if not isinstance(metric, ChapterMetrics):
                raise ProtocolV2MetricsError(
                    "chapters must contain only ChapterMetrics"
                )
            if metric.condition != self.condition:
                raise ProtocolV2MetricsError(
                    "every chapter condition must match trajectory condition"
                )
            if metric.chapter <= previous:
                raise ProtocolV2MetricsError(
                    "trajectory chapters must be unique and strictly increasing"
                )
            previous = metric.chapter

    @classmethod
    def aggregate(
        cls, condition: str, chapters: Iterable[ChapterMetrics]
    ) -> "ConditionTrajectory":
        if isinstance(chapters, (str, bytes)):
            raise ProtocolV2MetricsError("chapters must be an iterable")
        try:
            parsed = tuple(chapters)
        except TypeError as exc:
            raise ProtocolV2MetricsError("chapters must be an iterable") from exc
        if not all(isinstance(item, ChapterMetrics) for item in parsed):
            raise ProtocolV2MetricsError(
                "chapters must contain only ChapterMetrics"
            )
        return cls(
            condition=condition,
            chapters=tuple(sorted(parsed, key=lambda item: item.chapter)),
        )

    @property
    def degradation_slope(self) -> float | None:
        return least_squares_slope(
            tuple(
                (metric.chapter, metric.degradation_index)
                for metric in self.chapters
            )
        )

    @property
    def mean_degradation_index(self) -> float:
        return _rounded(
            sum(metric.degradation_index for metric in self.chapters)
            / len(self.chapters)
        )

    def aggregate_mapping(self) -> dict[str, Any]:
        count = len(self.chapters)
        return {
            "chapter_count": count,
            "admissible_chapters": sum(
                metric.admissible for metric in self.chapters
            ),
            "rejected_chapters": sum(
                not metric.admissible for metric in self.chapters
            ),
            "continuity_violations": sum(
                metric.judgment.continuity_violations for metric in self.chapters
            ),
            "factual_continuity_violations": sum(
                metric.judgment.factual_continuity_violations
                for metric in self.chapters
            ),
            "causal_prerequisite_violations": sum(
                metric.judgment.causal_prerequisite_violations
                for metric in self.chapters
            ),
            "obligation_violations": sum(
                metric.judgment.obligation_violations
                for metric in self.chapters
            ),
            "illegal_state_promotions": sum(
                metric.illegal_state_promotions for metric in self.chapters
            ),
            "unresolved_obligations": sum(
                metric.unresolved_obligations for metric in self.chapters
            ),
            "progression_economic_errors": sum(
                metric.judgment.progression_economic_errors
                for metric in self.chapters
            ),
            "mean_intent_drift_score": _rounded(
                sum(metric.judgment.intent_drift_score for metric in self.chapters)
                / count
            ),
            "mean_repair_burden_score": _rounded(
                sum(
                    metric.judgment.repair_burden_score
                    for metric in self.chapters
                )
                / count
            ),
            "mean_revision_change_ratio": _rounded(
                sum(metric.revision_change_ratio for metric in self.chapters)
                / count
            ),
            "mean_degradation_index": self.mean_degradation_index,
            "degradation_slope": self.degradation_slope,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ConditionTrajectory":
        if not isinstance(value, Mapping):
            raise ProtocolV2MetricsError("condition trajectory must be an object")
        _require_exact_keys(
            value,
            {"schema_version", "condition", "chapters", "aggregate"},
            label="condition trajectory",
        )
        if _require_int(
            value["schema_version"], label="schema_version"
        ) != METRICS_SCHEMA_VERSION:
            raise ProtocolV2MetricsError(
                f"condition trajectory schema_version must be {METRICS_SCHEMA_VERSION}"
            )
        if not isinstance(value["chapters"], list):
            raise ProtocolV2MetricsError("condition trajectory chapters must be a list")
        result = cls(
            condition=value["condition"],
            chapters=tuple(
                ChapterMetrics.from_mapping(item) for item in value["chapters"]
            ),
        )
        expected = result.aggregate_mapping()
        observed = value["aggregate"]
        if not isinstance(observed, Mapping):
            raise ProtocolV2MetricsError("condition trajectory aggregate must be an object")
        _require_exact_keys(observed, set(expected), label="condition trajectory aggregate")
        for key, expected_value in expected.items():
            observed_value = observed[key]
            if expected_value is None:
                if observed_value is not None:
                    raise ProtocolV2MetricsError(f"aggregate {key} must be null")
            elif isinstance(expected_value, float):
                _require_derived_float(
                    observed_value, expected_value, label=f"aggregate {key}"
                )
            elif observed_value != expected_value:
                raise ProtocolV2MetricsError(
                    f"aggregate {key} is inconsistent: "
                    f"expected {expected_value}, got {observed_value}"
                )
        return result

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": METRICS_SCHEMA_VERSION,
            "condition": self.condition,
            "chapters": [metric.to_mapping() for metric in self.chapters],
            "aggregate": self.aggregate_mapping(),
        }


def load_metric_judgment(payload: str) -> MetricJudgment:
    try:
        value = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProtocolV2MetricsError("metric judgment is not valid JSON") from exc
    return MetricJudgment.from_mapping(value)


def load_condition_trajectory(payload: str) -> ConditionTrajectory:
    try:
        value = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProtocolV2MetricsError("condition trajectory is not valid JSON") from exc
    return ConditionTrajectory.from_mapping(value)
