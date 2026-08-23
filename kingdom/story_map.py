from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1

STATE_CATEGORIES = (
    "facts",
    "character_states",
    "knowledge",
    "financial_state",
    "cultivation_state",
    "assets",
    "obligations",
    "mysteries",
    "themes",
    "tone",
    "chapter_summaries",
)

CLAIM_STATUSES = frozenset(
    {
        "blueprint",
        "planned",
        "attempted",
        "current",
        "resolved",
        "failed",
        "cancelled",
    }
)

_INITIAL_STATUSES = frozenset(CLAIM_STATUSES - {"resolved"})
_SATISFIED_DEPENDENCY_STATUSES = frozenset({"current", "resolved"})
_STATUSES_REQUIRING_SATISFIED_DEPENDENCIES = frozenset(
    {"attempted", "current", "resolved"}
)
_ALLOWED_TRANSITIONS = {
    "blueprint": frozenset(
        {"blueprint", "planned", "attempted", "current", "failed", "cancelled"}
    ),
    "planned": frozenset(
        {"planned", "attempted", "current", "resolved", "failed", "cancelled"}
    ),
    "attempted": frozenset(
        {"attempted", "current", "resolved", "failed", "cancelled"}
    ),
    "current": frozenset({"current", "resolved"}),
    "resolved": frozenset({"resolved"}),
    "failed": frozenset({"failed"}),
    "cancelled": frozenset({"cancelled"}),
}

_CLAIM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
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
        r"\bone\s+day\b",
        r"\bsomeday\b",
        r"\beventually\b",
        r"\bfuture\s+(?:founder|owner|leader|sovereign|wielder)\b",
        r"\bdestined\s+to\b",
        r"\bvows?\s+to\b",
        r"\bvowed\s+to\b",
        r"\bpromises?\s+to\b",
        r"\bpromised\s+to\b",
        r"\bhopes?\s+to\b",
        r"\bhoped\s+to\b",
        r"\baims?\s+to\b",
        r"\baimed\s+to\b",
        r"\bwould\s+one\s+day\b",
    )
)


class StoryMapError(ValueError):
    """Base error for deterministic narrative-state validation."""


class StorySchemaError(StoryMapError):
    """Raised when a proposed or persisted story map has the wrong shape."""


class StoryEvidenceError(StoryMapError):
    """Raised when a proposed claim lacks exact current-chapter provenance."""


class StoryTransitionError(StoryMapError):
    """Raised when a claim attempts an illegal temporal transition."""


class StoryDependencyError(StoryMapError):
    """Raised when a claim dependency is missing, cyclic, or unsatisfied."""


def chapter_sha256(chapter_text: str) -> str:
    return hashlib.sha256(chapter_text.encode("utf-8")).hexdigest()


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    *,
    label: str,
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
        raise StorySchemaError(f"{label} has invalid keys: " + ", ".join(details))


def _require_int(value: Any, *, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise StorySchemaError(f"{label} must be an integer >= {minimum}")
    return value


def _require_text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StorySchemaError(f"{label} must be a non-empty string")
    return value.strip()


def _require_claim_id(value: Any, *, label: str = "claim_id") -> str:
    claim_id = _require_text(value, label=label)
    if not _CLAIM_ID_RE.fullmatch(claim_id):
        raise StorySchemaError(
            f"{label} must contain only letters, digits, '.', '_', ':', or '-'"
        )
    return claim_id


def _require_status(value: Any, *, label: str = "status") -> str:
    status = _require_text(value, label=label).lower()
    if status not in CLAIM_STATUSES:
        raise StorySchemaError(
            f"{label} must be one of {sorted(CLAIM_STATUSES)}, got {status!r}"
        )
    return status


def _require_dependencies(value: Any, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise StorySchemaError(f"{label} must be a list")
    dependencies = tuple(
        _require_claim_id(item, label=f"{label} item") for item in value
    )
    if len(set(dependencies)) != len(dependencies):
        raise StorySchemaError(f"{label} contains duplicate claim ids")
    return dependencies


@dataclass(frozen=True)
class ProposedEvidence:
    source_id: str
    source_sha256: str
    chapter: int
    quote: str
    start: int | None = None
    end: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.source_id, label="evidence.source_id")
        digest = _require_text(
            self.source_sha256, label="evidence.source_sha256"
        )
        if not _SHA256_RE.fullmatch(digest):
            raise StorySchemaError("evidence.source_sha256 must be a SHA-256 hex digest")
        _require_int(self.chapter, label="evidence.chapter", minimum=1)
        _require_text(self.quote, label="evidence.quote")
        if (self.start is None) != (self.end is None):
            raise StorySchemaError(
                "evidence.start and evidence.end must be supplied together"
            )
        if self.start is not None and self.end is not None:
            _require_int(self.start, label="evidence.start")
            _require_int(self.end, label="evidence.end", minimum=1)
            if self.start >= self.end:
                raise StorySchemaError("evidence.start must be less than evidence.end")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProposedEvidence":
        if not isinstance(value, Mapping):
            raise StorySchemaError("claim evidence must be an object")
        allowed = {
            "source_id",
            "source_sha256",
            "chapter",
            "quote",
            "start",
            "end",
        }
        required = {"source_id", "source_sha256", "chapter", "quote"}
        actual = set(value)
        missing = sorted(required - actual)
        unexpected = sorted(actual - allowed)
        if missing or unexpected:
            details = []
            if missing:
                details.append(f"missing={missing}")
            if unexpected:
                details.append(f"unexpected={unexpected}")
            raise StorySchemaError(
                "claim evidence has invalid keys: " + ", ".join(details)
            )

        source_sha256 = _require_text(
            value.get("source_sha256"), label="evidence.source_sha256"
        ).lower()
        if not _SHA256_RE.fullmatch(source_sha256):
            raise StorySchemaError("evidence.source_sha256 must be a SHA-256 hex digest")

        has_start = value.get("start") is not None
        has_end = value.get("end") is not None
        if has_start != has_end:
            raise StorySchemaError("evidence.start and evidence.end must be supplied together")

        start = (
            _require_int(value.get("start"), label="evidence.start")
            if has_start
            else None
        )
        end = (
            _require_int(value.get("end"), label="evidence.end", minimum=1)
            if has_end
            else None
        )
        if start is not None and end is not None and start >= end:
            raise StorySchemaError("evidence.start must be less than evidence.end")

        return cls(
            source_id=_require_text(value.get("source_id"), label="evidence.source_id"),
            source_sha256=source_sha256,
            chapter=_require_int(value.get("chapter"), label="evidence.chapter", minimum=1),
            quote=_require_text(value.get("quote"), label="evidence.quote"),
            start=start,
            end=end,
        )


@dataclass(frozen=True)
class ClaimEvidence:
    source_id: str
    source_sha256: str
    chapter: int
    quote: str
    start: int
    end: int

    def __post_init__(self) -> None:
        _require_text(self.source_id, label="canonical provenance.source_id")
        digest = _require_text(
            self.source_sha256, label="canonical provenance.source_sha256"
        )
        if not _SHA256_RE.fullmatch(digest):
            raise StorySchemaError(
                "canonical provenance.source_sha256 must be a SHA-256 hex digest"
            )
        _require_int(self.chapter, label="canonical provenance.chapter")
        _require_text(self.quote, label="canonical provenance.quote")
        _require_int(self.start, label="canonical provenance.start")
        _require_int(self.end, label="canonical provenance.end", minimum=1)
        if self.start >= self.end:
            raise StorySchemaError(
                "canonical provenance.start must be less than canonical provenance.end"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ClaimEvidence":
        if not isinstance(value, Mapping):
            raise StorySchemaError("canonical provenance must be an object")
        _require_exact_keys(
            value,
            {"source_id", "source_sha256", "chapter", "quote", "start", "end"},
            label="canonical provenance",
        )
        source_sha256 = _require_text(
            value.get("source_sha256"),
            label="canonical provenance.source_sha256",
        ).lower()
        if not _SHA256_RE.fullmatch(source_sha256):
            raise StorySchemaError(
                "canonical provenance.source_sha256 must be a SHA-256 hex digest"
            )
        start = _require_int(
            value.get("start"), label="canonical provenance.start"
        )
        end = _require_int(
            value.get("end"), label="canonical provenance.end", minimum=1
        )
        if start >= end:
            raise StorySchemaError(
                "canonical provenance.start must be less than canonical provenance.end"
            )
        return cls(
            source_id=_require_text(
                value.get("source_id"), label="canonical provenance.source_id"
            ),
            source_sha256=source_sha256,
            chapter=_require_int(
                value.get("chapter"), label="canonical provenance.chapter"
            ),
            quote=_require_text(
                value.get("quote"), label="canonical provenance.quote"
            ),
            start=start,
            end=end,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
            "chapter": self.chapter,
            "quote": self.quote,
            "start": self.start,
            "end": self.end,
        }


@dataclass(frozen=True)
class ProposedClaim:
    claim_id: str
    category: str
    statement: str
    status: str
    depends_on: tuple[str, ...]
    evidence: ProposedEvidence

    def __post_init__(self) -> None:
        _require_claim_id(self.claim_id)
        if self.category not in STATE_CATEGORIES:
            raise StorySchemaError(f"unsupported proposed claim category: {self.category!r}")
        _require_text(self.statement, label="statement")
        if _require_status(self.status) != self.status:
            raise StorySchemaError("proposed claim status must be lowercase")
        if not isinstance(self.depends_on, tuple):
            raise StorySchemaError("proposed claim depends_on must be a tuple")
        dependencies = tuple(
            _require_claim_id(item, label="proposed claim depends_on item")
            for item in self.depends_on
        )
        if len(set(dependencies)) != len(dependencies):
            raise StorySchemaError("proposed claim depends_on contains duplicate claim ids")
        if not isinstance(self.evidence, ProposedEvidence):
            raise StorySchemaError("proposed claim evidence must be ProposedEvidence")

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        category: str,
    ) -> "ProposedClaim":
        if not isinstance(value, Mapping):
            raise StorySchemaError(f"{category} claim must be an object, not legacy text")
        _require_exact_keys(
            value,
            {"claim_id", "statement", "status", "depends_on", "evidence"},
            label=f"{category} claim",
        )
        return cls(
            claim_id=_require_claim_id(value.get("claim_id")),
            category=category,
            statement=_require_text(value.get("statement"), label="statement"),
            status=_require_status(value.get("status")),
            depends_on=_require_dependencies(
                value.get("depends_on"), label=f"{category}.depends_on"
            ),
            evidence=ProposedEvidence.from_mapping(value.get("evidence")),
        )


@dataclass(frozen=True)
class StoryMap:
    """A strict, delta-only set of typed claim proposals for one chapter."""

    chapter: int
    claims: tuple[ProposedClaim, ...]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_int(self.schema_version, label="story map schema_version", minimum=1)
        if self.schema_version != SCHEMA_VERSION:
            raise StorySchemaError(
                f"story map schema_version must be {SCHEMA_VERSION}"
            )
        _require_int(self.chapter, label="story map chapter", minimum=1)
        if not isinstance(self.claims, tuple) or not all(
            isinstance(claim, ProposedClaim) for claim in self.claims
        ):
            raise StorySchemaError("story map claims must be typed ProposedClaim objects")
        ids = [claim.claim_id for claim in self.claims]
        if len(set(ids)) != len(ids):
            raise StorySchemaError("story map contains duplicate proposed claim ids")
        if not any(
            claim.category == "chapter_summaries" for claim in self.claims
        ):
            raise StorySchemaError(
                "story map must contain at least one typed chapter_summaries claim"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StoryMap":
        if not isinstance(value, Mapping):
            raise StorySchemaError("story map must be an object")
        _require_exact_keys(
            value,
            {"schema_version", "chapter", "claims"},
            label="story map",
        )
        if value.get("schema_version") != SCHEMA_VERSION:
            raise StorySchemaError(
                f"story map schema_version must be {SCHEMA_VERSION}"
            )
        chapter = _require_int(value.get("chapter"), label="story map chapter", minimum=1)
        claims_by_category = value.get("claims")
        if not isinstance(claims_by_category, Mapping):
            raise StorySchemaError("story map claims must be an object keyed by category")
        _require_exact_keys(
            claims_by_category,
            set(STATE_CATEGORIES),
            label="story map claims",
        )

        claims: list[ProposedClaim] = []
        seen: set[str] = set()
        for category in STATE_CATEGORIES:
            raw_claims = claims_by_category[category]
            if not isinstance(raw_claims, list):
                raise StorySchemaError(f"story map claims.{category} must be a list")
            for raw_claim in raw_claims:
                claim = ProposedClaim.from_mapping(raw_claim, category=category)
                if claim.claim_id in seen:
                    raise StorySchemaError(
                        f"duplicate proposed claim_id: {claim.claim_id}"
                    )
                seen.add(claim.claim_id)
                claims.append(claim)

        summaries = [
            claim for claim in claims if claim.category == "chapter_summaries"
        ]
        if not summaries:
            raise StorySchemaError(
                "story map claims.chapter_summaries must contain at least one typed claim; "
                "an all-empty claim map is not a valid chapter update"
            )
        return cls(chapter=chapter, claims=tuple(claims))


@dataclass(frozen=True)
class CanonicalClaim:
    claim_id: str
    category: str
    statement: str
    status: str
    depends_on: tuple[str, ...]
    provenance: tuple[ClaimEvidence, ...]
    created_chapter: int
    updated_chapter: int

    def __post_init__(self) -> None:
        _require_claim_id(self.claim_id)
        if self.category not in STATE_CATEGORIES:
            raise StorySchemaError(f"unsupported canonical claim category: {self.category!r}")
        _require_text(self.statement, label="statement")
        if _require_status(self.status) != self.status:
            raise StorySchemaError("canonical claim status must be lowercase")
        if not isinstance(self.depends_on, tuple):
            raise StorySchemaError("canonical claim depends_on must be a tuple")
        dependencies = tuple(
            _require_claim_id(item, label="canonical claim depends_on item")
            for item in self.depends_on
        )
        if len(set(dependencies)) != len(dependencies):
            raise StorySchemaError("canonical claim depends_on contains duplicate claim ids")
        if (
            not isinstance(self.provenance, tuple)
            or not self.provenance
            or not all(isinstance(item, ClaimEvidence) for item in self.provenance)
        ):
            raise StorySchemaError(
                "canonical claim provenance must be a non-empty tuple of ClaimEvidence"
            )
        if self.status == "current" and (
            _looks_future_only(self.statement)
            or _looks_future_only(self.provenance[-1].quote)
        ):
            raise StoryEvidenceError(
                f"{self.claim_id}: future-plan language cannot establish current canon"
            )
        _require_int(self.created_chapter, label="created_chapter")
        _require_int(self.updated_chapter, label="updated_chapter")
        if self.created_chapter > self.updated_chapter:
            raise StorySchemaError("created_chapter cannot be after updated_chapter")
        chapters = [item.chapter for item in self.provenance]
        if chapters[0] != self.created_chapter:
            raise StorySchemaError(
                "first provenance chapter must equal canonical claim created_chapter"
            )
        if any(left >= right for left, right in zip(chapters, chapters[1:])):
            raise StorySchemaError(
                "canonical claim provenance chapters must be strictly increasing"
            )
        if chapters[-1] != self.updated_chapter:
            raise StorySchemaError(
                "latest provenance chapter must equal canonical claim updated_chapter"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CanonicalClaim":
        if not isinstance(value, Mapping):
            raise StorySchemaError("canonical claim must be an object")
        _require_exact_keys(
            value,
            {
                "claim_id",
                "category",
                "statement",
                "status",
                "depends_on",
                "provenance",
                "created_chapter",
                "updated_chapter",
            },
            label="canonical claim",
        )
        category = _require_text(value.get("category"), label="category")
        if category not in STATE_CATEGORIES:
            raise StorySchemaError(f"unsupported canonical claim category: {category!r}")
        raw_provenance = value.get("provenance")
        if not isinstance(raw_provenance, list) or not raw_provenance:
            raise StorySchemaError("canonical claim provenance must be a non-empty list")
        provenance = tuple(ClaimEvidence.from_mapping(item) for item in raw_provenance)
        created_chapter = _require_int(
            value.get("created_chapter"), label="created_chapter"
        )
        updated_chapter = _require_int(
            value.get("updated_chapter"), label="updated_chapter"
        )
        if created_chapter > updated_chapter:
            raise StorySchemaError("created_chapter cannot be after updated_chapter")
        if provenance[-1].chapter != updated_chapter:
            raise StorySchemaError(
                "latest provenance chapter must equal canonical claim updated_chapter"
            )
        return cls(
            claim_id=_require_claim_id(value.get("claim_id")),
            category=category,
            statement=_require_text(value.get("statement"), label="statement"),
            status=_require_status(value.get("status")),
            depends_on=_require_dependencies(
                value.get("depends_on"), label="canonical claim depends_on"
            ),
            provenance=provenance,
            created_chapter=created_chapter,
            updated_chapter=updated_chapter,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "category": self.category,
            "statement": self.statement,
            "status": self.status,
            "depends_on": list(self.depends_on),
            "provenance": [item.to_mapping() for item in self.provenance],
            "created_chapter": self.created_chapter,
            "updated_chapter": self.updated_chapter,
        }


@dataclass(frozen=True)
class CanonicalState:
    """Accepted claim ledger through one chapter; legacy state is a derived view."""

    through_chapter: int
    claims: tuple[CanonicalClaim, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_int(
            self.schema_version, label="canonical state schema_version", minimum=1
        )
        if self.schema_version != SCHEMA_VERSION:
            raise StorySchemaError(
                f"canonical state schema_version must be {SCHEMA_VERSION}"
            )
        _require_int(self.through_chapter, label="through_chapter")
        if not isinstance(self.claims, tuple) or not all(
            isinstance(claim, CanonicalClaim) for claim in self.claims
        ):
            raise StorySchemaError(
                "canonical state claims must be typed CanonicalClaim objects"
            )
        ids = [claim.claim_id for claim in self.claims]
        if len(set(ids)) != len(ids):
            raise StorySchemaError("canonical state contains duplicate claim ids")
        for claim in self.claims:
            if claim.updated_chapter > self.through_chapter:
                raise StorySchemaError(
                    f"{claim.claim_id}: updated_chapter exceeds canonical state history"
                )
            if any(item.chapter > self.through_chapter for item in claim.provenance):
                raise StorySchemaError(
                    f"{claim.claim_id}: provenance points beyond canonical state history"
                )
        claims_by_id = {claim.claim_id: claim for claim in self.claims}
        _assert_dependency_graph(claims_by_id)
        for claim in self.claims:
            if claim.status not in _STATUSES_REQUIRING_SATISFIED_DEPENDENCIES:
                continue
            unsatisfied = sorted(
                dependency
                for dependency in claim.depends_on
                if claims_by_id[dependency].status
                not in _SATISFIED_DEPENDENCY_STATUSES
            )
            if unsatisfied:
                raise StoryDependencyError(
                    f"{claim.claim_id}: unsatisfied dependencies {unsatisfied}"
                )

    @classmethod
    def empty(cls, *, through_chapter: int = 1) -> "CanonicalState":
        return cls(through_chapter=through_chapter)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CanonicalState":
        if not isinstance(value, Mapping):
            raise StorySchemaError("canonical state must be an object")
        _require_exact_keys(
            value,
            {"schema_version", "through_chapter", "claims"},
            label="canonical state",
        )
        if value.get("schema_version") != SCHEMA_VERSION:
            raise StorySchemaError(
                f"canonical state schema_version must be {SCHEMA_VERSION}"
            )
        raw_claims = value.get("claims")
        if not isinstance(raw_claims, list):
            raise StorySchemaError("canonical state claims must be a list")
        return cls(
            through_chapter=_require_int(
                value.get("through_chapter"), label="through_chapter"
            ),
            claims=tuple(CanonicalClaim.from_mapping(item) for item in raw_claims),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "through_chapter": self.through_chapter,
            "claims": [claim.to_mapping() for claim in self.claims],
        }

    def to_legacy_story_state(self) -> dict[str, Any]:
        """Build the old StoryState shape without accepting any unguarded text."""

        payload: dict[str, Any] = {category: [] for category in STATE_CATEGORIES}
        seen: dict[str, set[str]] = {category: set() for category in STATE_CATEGORIES}
        for claim in self.claims:
            visible = claim.status == "current" or (
                claim.category == "obligations"
                and claim.status in {"planned", "attempted"}
            )
            if not visible or claim.statement in seen[claim.category]:
                continue
            seen[claim.category].add(claim.statement)
            payload[claim.category].append(claim.statement)
        payload["rolling_summary"] = "\n".join(payload["chapter_summaries"])
        return payload


def _assert_dependency_graph(claims: Mapping[str, Any]) -> None:
    for claim_id, claim in claims.items():
        for dependency in claim.depends_on:
            if dependency == claim_id:
                raise StoryDependencyError(f"{claim_id}: claim cannot depend on itself")
            if dependency not in claims:
                raise StoryDependencyError(
                    f"{claim_id}: unknown dependency {dependency!r}"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(claim_id: str) -> None:
        if claim_id in visiting:
            raise StoryDependencyError(
                f"dependency cycle detected at claim {claim_id!r}"
            )
        if claim_id in visited:
            return
        visiting.add(claim_id)
        for dependency in claims[claim_id].depends_on:
            visit(dependency)
        visiting.remove(claim_id)
        visited.add(claim_id)

    for claim_id in claims:
        visit(claim_id)


def _looks_future_only(text: str) -> bool:
    return any(pattern.search(text) for pattern in _FUTURE_ONLY_PATTERNS)


def _find_exact_quote(
    evidence: ProposedEvidence,
    *,
    chapter_text: str,
) -> tuple[int, int]:
    if evidence.start is not None and evidence.end is not None:
        if evidence.end > len(chapter_text):
            raise StoryEvidenceError("evidence span extends beyond the current chapter")
        if chapter_text[evidence.start : evidence.end] != evidence.quote:
            raise StoryEvidenceError(
                "evidence span does not exactly match the quoted current-chapter text"
            )
        return evidence.start, evidence.end

    matches: list[int] = []
    cursor = 0
    while True:
        found = chapter_text.find(evidence.quote, cursor)
        if found < 0:
            break
        matches.append(found)
        cursor = found + 1
    if not matches:
        raise StoryEvidenceError(
            "evidence quote is not an exact substring of the current chapter"
        )
    if len(matches) > 1:
        raise StoryEvidenceError(
            "evidence quote occurs more than once; exact start/end provenance is required"
        )
    return matches[0], matches[0] + len(evidence.quote)


class StoryGuard:
    """Validate typed chapter deltas, then update canon without model authority."""

    def validate(
        self,
        state: CanonicalState,
        story_map: StoryMap,
        *,
        chapter_text: str,
        chapter: int,
        source_id: str | None = None,
    ) -> tuple[CanonicalClaim, ...]:
        if not isinstance(chapter_text, str) or not chapter_text.strip():
            raise StoryEvidenceError("current chapter text must be non-empty")
        if story_map.chapter != chapter:
            raise StoryEvidenceError(
                f"story map chapter {story_map.chapter} does not match current chapter {chapter}"
            )
        if chapter != state.through_chapter + 1:
            raise StoryTransitionError(
                f"chapter update must be contiguous: state is through {state.through_chapter}, "
                f"proposed chapter is {chapter}"
            )

        expected_source_id = source_id or f"chapter:{chapter:04d}"
        expected_hash = chapter_sha256(chapter_text)
        prior = {claim.claim_id: claim for claim in state.claims}
        accepted: list[CanonicalClaim] = []

        for proposed in story_map.claims:
            evidence = proposed.evidence
            if evidence.chapter != chapter:
                raise StoryEvidenceError(
                    f"{proposed.claim_id}: evidence chapter must be current chapter {chapter}"
                )
            if evidence.source_id != expected_source_id:
                raise StoryEvidenceError(
                    f"{proposed.claim_id}: evidence source_id must be {expected_source_id!r}"
                )
            if evidence.source_sha256 != expected_hash:
                raise StoryEvidenceError(
                    f"{proposed.claim_id}: evidence hash does not match current chapter"
                )
            start, end = _find_exact_quote(evidence, chapter_text=chapter_text)
            if proposed.status == "current" and (
                _looks_future_only(proposed.statement)
                or _looks_future_only(evidence.quote)
            ):
                raise StoryEvidenceError(
                    f"{proposed.claim_id}: future-plan language cannot establish current canon"
                )

            previous = prior.get(proposed.claim_id)
            if previous is None:
                if proposed.status not in _INITIAL_STATUSES:
                    raise StoryTransitionError(
                        f"{proposed.claim_id}: new claim cannot start as {proposed.status!r}"
                    )
                created_chapter = chapter
                provenance: tuple[ClaimEvidence, ...] = ()
            else:
                if proposed.category != previous.category:
                    raise StoryTransitionError(
                        f"{proposed.claim_id}: category is immutable "
                        f"({previous.category!r} != {proposed.category!r})"
                    )
                if proposed.statement != previous.statement:
                    raise StoryTransitionError(
                        f"{proposed.claim_id}: statement is immutable"
                    )
                if proposed.status not in _ALLOWED_TRANSITIONS[previous.status]:
                    raise StoryTransitionError(
                        f"{proposed.claim_id}: illegal transition "
                        f"{previous.status!r} -> {proposed.status!r}"
                    )
                removed_dependencies = sorted(
                    set(previous.depends_on) - set(proposed.depends_on)
                )
                if removed_dependencies:
                    raise StoryDependencyError(
                        f"{proposed.claim_id}: cannot remove dependencies "
                        f"{removed_dependencies}"
                    )
                created_chapter = previous.created_chapter
                provenance = previous.provenance

            anchor = ClaimEvidence(
                source_id=evidence.source_id,
                source_sha256=evidence.source_sha256,
                chapter=chapter,
                quote=evidence.quote,
                start=start,
                end=end,
            )
            accepted.append(
                CanonicalClaim(
                    claim_id=proposed.claim_id,
                    category=proposed.category,
                    statement=proposed.statement,
                    status=proposed.status,
                    depends_on=proposed.depends_on,
                    provenance=provenance + (anchor,),
                    created_chapter=created_chapter,
                    updated_chapter=chapter,
                )
            )

        final = dict(prior)
        final.update({claim.claim_id: claim for claim in accepted})
        _assert_dependency_graph(final)
        for claim in accepted:
            if claim.status not in _STATUSES_REQUIRING_SATISFIED_DEPENDENCIES:
                continue
            unsatisfied = sorted(
                dependency
                for dependency in claim.depends_on
                if final[dependency].status not in _SATISFIED_DEPENDENCY_STATUSES
            )
            if unsatisfied:
                raise StoryDependencyError(
                    f"{claim.claim_id}: unsatisfied dependencies {unsatisfied}"
                )
        return tuple(accepted)

    def update(
        self,
        state: CanonicalState,
        story_map: StoryMap,
        *,
        chapter_text: str,
        chapter: int,
        source_id: str | None = None,
    ) -> CanonicalState:
        accepted = self.validate(
            state,
            story_map,
            chapter_text=chapter_text,
            chapter=chapter,
            source_id=source_id,
        )
        replacements = {claim.claim_id: claim for claim in accepted}
        merged = [
            replacements.pop(claim.claim_id, claim)
            for claim in state.claims
        ]
        merged.extend(
            claim for claim in accepted if claim.claim_id in replacements
        )
        return CanonicalState(through_chapter=chapter, claims=tuple(merged))


def load_story_map(value: StoryMap | Mapping[str, Any] | str) -> StoryMap:
    if isinstance(value, StoryMap):
        return value
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise StorySchemaError(f"story map is not valid JSON: {exc}") from exc
    return StoryMap.from_mapping(value)


def load_canonical_state(
    value: CanonicalState | Mapping[str, Any] | str | None,
    *,
    through_chapter: int = 1,
) -> CanonicalState:
    if value is None:
        return CanonicalState.empty(through_chapter=through_chapter)
    if isinstance(value, CanonicalState):
        return value
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise StorySchemaError(f"canonical state is not valid JSON: {exc}") from exc
    return CanonicalState.from_mapping(value)


def validate_story_map(
    state: CanonicalState | Mapping[str, Any] | str,
    story_map: StoryMap | Mapping[str, Any] | str,
    *,
    chapter_text: str,
    chapter: int,
    source_id: str | None = None,
) -> tuple[CanonicalClaim, ...]:
    return StoryGuard().validate(
        load_canonical_state(state),
        load_story_map(story_map),
        chapter_text=chapter_text,
        chapter=chapter,
        source_id=source_id,
    )


def update_canonical_state(
    state: CanonicalState | Mapping[str, Any] | str,
    story_map: StoryMap | Mapping[str, Any] | str,
    *,
    chapter_text: str,
    chapter: int,
    source_id: str | None = None,
) -> CanonicalState:
    return StoryGuard().update(
        load_canonical_state(state),
        load_story_map(story_map),
        chapter_text=chapter_text,
        chapter=chapter,
        source_id=source_id,
    )
