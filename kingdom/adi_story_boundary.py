from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .story_map import (
    CanonicalClaim,
    CanonicalState,
    ClaimEvidence,
    STATE_CATEGORIES,
    StoryGuard,
    StoryMap,
)


BOUNDARY_SCHEMA_VERSION = 1
BOUNDARY_PROTOCOL_ID = "adi-story-boundary-v1"


class StoryBoundaryError(ValueError):
    """Raised when frozen story authority or a candidate chapter is invalid."""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_sha256(value: Any) -> str:
    return _sha256_text(_canonical_json(value))


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _line_span(text: str, start: int, end: int) -> str:
    lines = text.splitlines()
    if start < 1 or end < start or end > len(lines):
        raise StoryBoundaryError(
            f"invalid frozen source span {start}-{end}; seed has {len(lines)} lines"
        )
    return "\n".join(lines[start - 1 : end]) + "\n"


def _require_keys(value: Mapping[str, Any], expected: set[str], *, label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise StoryBoundaryError(
            f"{label} has invalid keys: missing={missing}, unexpected={unexpected}"
        )


def _find_unique_quote(source: str, quote: str, *, label: str) -> tuple[int, int]:
    first = source.find(quote)
    if first < 0:
        raise StoryBoundaryError(f"{label} evidence is absent from its frozen source")
    if source.find(quote, first + 1) >= 0:
        raise StoryBoundaryError(f"{label} evidence is not unique in its frozen source")
    return first, first + len(quote)


def _text_items(value: Any, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise StoryBoundaryError(f"{label} must be a list")
    items = tuple(str(item).strip() for item in value)
    if any(not item for item in items):
        raise StoryBoundaryError(f"{label} cannot contain empty text")
    return items


@dataclass(frozen=True)
class BoundaryGuardReport:
    protocol: str
    chapter: int
    chapter_sha256: str
    accepted_claim_count: int
    canonical_state_sha256: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "chapter": self.chapter,
            "chapter_sha256": self.chapter_sha256,
            "accepted_claim_count": self.accepted_claim_count,
            "canonical_state_sha256": self.canonical_state_sha256,
        }


@dataclass(frozen=True)
class ADIStoryBoundary:
    """Frozen current/future boundary shared by both ADI conditions."""

    raw: Mapping[str, Any]
    source_map_sha256: str
    seed_sha256: str
    contract_sha256: str
    partitions: Mapping[str, str]
    partition_roles: Mapping[str, str]
    chapter_one_text: str
    chapter_one_sha256: str
    chapter_one_tail: str
    chapter_one_tail_sha256: str
    immutable_rules: tuple[Mapping[str, str], ...]
    initial_state: CanonicalState
    initial_state_sha256: str
    future_intent: tuple[str, ...]
    chapter_frontiers: Mapping[int, tuple[str, ...]]
    locked_terms_by_chapter: Mapping[int, tuple[str, ...]]
    forbidden_patterns_by_chapter: Mapping[int, tuple[Mapping[str, str], ...]]
    opening_requirements_by_chapter: Mapping[int, Mapping[str, Any]]

    @classmethod
    def from_text(
        cls,
        *,
        seed: str,
        contract: str,
        source_map_text: str,
    ) -> "ADIStoryBoundary":
        try:
            raw = json.loads(source_map_text)
        except json.JSONDecodeError as exc:
            raise StoryBoundaryError(f"STORY_MAP.json is malformed: {exc}") from exc
        if not isinstance(raw, Mapping):
            raise StoryBoundaryError("STORY_MAP.json must contain one JSON object")
        _require_keys(
            raw,
            {
                "schema_version",
                "benchmark_id",
                "seed_sha256",
                "contract_sha256",
                "published_through_chapter",
                "partitions",
                "chapter_one",
                "immutable_rules",
                "initial_claims",
                "future_intent",
                "chapter_frontiers",
                "locked_terms_by_chapter",
                "forbidden_patterns_by_chapter",
                "opening_requirements_by_chapter",
            },
            label="STORY_MAP.json",
        )
        if raw["schema_version"] != BOUNDARY_SCHEMA_VERSION:
            raise StoryBoundaryError(
                f"unsupported story boundary schema {raw['schema_version']!r}"
            )
        if raw["benchmark_id"] != "ADI-001":
            raise StoryBoundaryError("story boundary benchmark_id must be ADI-001")
        if raw["published_through_chapter"] != 1:
            raise StoryBoundaryError("pilot story boundary must be published through Chapter 1")

        seed_hash = _sha256_text(seed)
        contract_hash = _sha256_text(contract)
        if raw["seed_sha256"] != seed_hash:
            raise StoryBoundaryError("story boundary seed_sha256 does not match SEED.md")
        if raw["contract_sha256"] != contract_hash:
            raise StoryBoundaryError("story boundary contract_sha256 does not match CONTRACT.md")

        raw_partitions = raw["partitions"]
        if not isinstance(raw_partitions, list) or not raw_partitions:
            raise StoryBoundaryError("story boundary partitions must be a non-empty list")
        partitions: dict[str, str] = {}
        roles: dict[str, str] = {}
        covered: list[int] = []
        for index, item in enumerate(raw_partitions):
            if not isinstance(item, Mapping):
                raise StoryBoundaryError(f"partitions[{index}] must be an object")
            _require_keys(
                item,
                {"source_id", "role", "line_start", "line_end", "sha256"},
                label=f"partitions[{index}]",
            )
            source_id = str(item["source_id"])
            role = str(item["role"])
            if source_id in partitions:
                raise StoryBoundaryError(f"duplicate source partition {source_id!r}")
            if role not in {"timeless", "published", "future"}:
                raise StoryBoundaryError(f"invalid source partition role {role!r}")
            start = int(item["line_start"])
            end = int(item["line_end"])
            text = _line_span(seed, start, end)
            if _sha256_text(text) != item["sha256"]:
                raise StoryBoundaryError(f"source partition {source_id!r} hash mismatch")
            partitions[source_id] = text
            roles[source_id] = role
            covered.extend(range(start, end + 1))
        expected_lines = list(range(1, len(seed.splitlines()) + 1))
        if covered != expected_lines:
            raise StoryBoundaryError("source partitions must cover SEED.md exactly once in order")

        chapter_one = raw["chapter_one"]
        if not isinstance(chapter_one, Mapping):
            raise StoryBoundaryError("chapter_one must be an object")
        _require_keys(
            chapter_one,
            {
                "source_id",
                "prose_line_start",
                "prose_line_end",
                "sha256",
                "tail_line_start",
                "tail_line_end",
                "tail_sha256",
                "narrator_foreshadowing",
            },
            label="chapter_one",
        )
        chapter_source_id = str(chapter_one["source_id"])
        if roles.get(chapter_source_id) != "published":
            raise StoryBoundaryError("Chapter One must point to a published partition")
        chapter_text = _line_span(
            seed,
            int(chapter_one["prose_line_start"]),
            int(chapter_one["prose_line_end"]),
        )
        if _sha256_text(chapter_text) != chapter_one["sha256"]:
            raise StoryBoundaryError("Chapter One prose hash mismatch")
        tail = _line_span(
            seed,
            int(chapter_one["tail_line_start"]),
            int(chapter_one["tail_line_end"]),
        )
        if _sha256_text(tail) != chapter_one["tail_sha256"]:
            raise StoryBoundaryError("Chapter One tail hash mismatch")

        immutable_rules_raw = raw["immutable_rules"]
        if not isinstance(immutable_rules_raw, list) or not immutable_rules_raw:
            raise StoryBoundaryError("immutable_rules must be a non-empty list")
        immutable_rules: list[Mapping[str, str]] = []
        for index, item in enumerate(immutable_rules_raw):
            if not isinstance(item, Mapping):
                raise StoryBoundaryError(f"immutable_rules[{index}] must be an object")
            _require_keys(item, {"rule_id", "text"}, label=f"immutable_rules[{index}]")
            immutable_rules.append(
                {"rule_id": str(item["rule_id"]), "text": str(item["text"])}
            )

        initial_claims_raw = raw["initial_claims"]
        if not isinstance(initial_claims_raw, list) or not initial_claims_raw:
            raise StoryBoundaryError("initial_claims must be a non-empty list")
        claims: list[CanonicalClaim] = []
        for index, item in enumerate(initial_claims_raw):
            if not isinstance(item, Mapping):
                raise StoryBoundaryError(f"initial_claims[{index}] must be an object")
            _require_keys(
                item,
                {
                    "claim_id",
                    "category",
                    "statement",
                    "status",
                    "depends_on",
                    "source_id",
                    "evidence",
                },
                label=f"initial_claims[{index}]",
            )
            source_id = str(item["source_id"])
            if roles.get(source_id) not in {"timeless", "published"}:
                raise StoryBoundaryError(
                    f"initial claim {item['claim_id']!r} cites non-current source {source_id!r}"
                )
            evidence_text = str(item["evidence"])
            start, end = _find_unique_quote(
                partitions[source_id],
                evidence_text,
                label=f"initial claim {item['claim_id']}",
            )
            source_chapter = 1 if roles[source_id] == "published" else 0
            claims.append(
                CanonicalClaim(
                    claim_id=str(item["claim_id"]),
                    category=str(item["category"]),
                    statement=str(item["statement"]),
                    status=str(item["status"]),
                    depends_on=tuple(str(dep) for dep in item["depends_on"]),
                    provenance=(
                        ClaimEvidence(
                            source_id=source_id,
                            source_sha256=_sha256_text(partitions[source_id]),
                            chapter=source_chapter,
                            quote=evidence_text,
                            start=start,
                            end=end,
                        ),
                    ),
                    created_chapter=source_chapter,
                    updated_chapter=source_chapter,
                )
            )
        initial_state = CanonicalState(through_chapter=1, claims=tuple(claims))

        future_intent = _text_items(raw["future_intent"], label="future_intent")
        frontiers = {
            int(chapter): _text_items(items, label=f"chapter_frontiers.{chapter}")
            for chapter, items in raw["chapter_frontiers"].items()
        }
        locked_terms = {
            int(chapter): _text_items(items, label=f"locked_terms_by_chapter.{chapter}")
            for chapter, items in raw["locked_terms_by_chapter"].items()
        }
        forbidden_patterns: dict[int, tuple[Mapping[str, str], ...]] = {}
        for chapter, patterns in raw["forbidden_patterns_by_chapter"].items():
            if not isinstance(patterns, list):
                raise StoryBoundaryError(
                    f"forbidden_patterns_by_chapter.{chapter} must be a list"
                )
            normalized_patterns: list[Mapping[str, str]] = []
            for item in patterns:
                if not isinstance(item, Mapping):
                    raise StoryBoundaryError("forbidden pattern must be an object")
                _require_keys(item, {"rule_id", "pattern", "message"}, label="forbidden pattern")
                re.compile(str(item["pattern"]), re.IGNORECASE | re.DOTALL)
                normalized_patterns.append(
                    {
                        "rule_id": str(item["rule_id"]),
                        "pattern": str(item["pattern"]),
                        "message": str(item["message"]),
                    }
                )
            forbidden_patterns[int(chapter)] = tuple(normalized_patterns)

        opening_requirements: dict[int, Mapping[str, Any]] = {}
        for chapter, requirement in raw["opening_requirements_by_chapter"].items():
            if not isinstance(requirement, Mapping):
                raise StoryBoundaryError("opening requirement must be an object")
            _require_keys(
                requirement,
                {"within_chars", "required_any_groups"},
                label=f"opening_requirements_by_chapter.{chapter}",
            )
            groups = requirement["required_any_groups"]
            if not isinstance(groups, list) or not groups:
                raise StoryBoundaryError("opening required_any_groups must be non-empty")
            opening_requirements[int(chapter)] = {
                "within_chars": int(requirement["within_chars"]),
                "required_any_groups": tuple(
                    _text_items(group, label="opening requirement group") for group in groups
                ),
            }

        boundary = cls(
            raw=_deep_freeze(raw),
            source_map_sha256=_sha256_text(source_map_text),
            seed_sha256=seed_hash,
            contract_sha256=contract_hash,
            partitions=MappingProxyType(dict(partitions)),
            partition_roles=MappingProxyType(dict(roles)),
            chapter_one_text=chapter_text,
            chapter_one_sha256=_sha256_text(chapter_text),
            chapter_one_tail=tail,
            chapter_one_tail_sha256=_sha256_text(tail),
            immutable_rules=tuple(_deep_freeze(item) for item in immutable_rules),
            initial_state=initial_state,
            initial_state_sha256=canonical_sha256(initial_state.to_mapping()),
            future_intent=future_intent,
            chapter_frontiers=MappingProxyType(dict(frontiers)),
            locked_terms_by_chapter=MappingProxyType(dict(locked_terms)),
            forbidden_patterns_by_chapter=MappingProxyType(
                {
                    chapter: tuple(_deep_freeze(item) for item in patterns)
                    for chapter, patterns in forbidden_patterns.items()
                }
            ),
            opening_requirements_by_chapter=MappingProxyType(
                {
                    chapter: _deep_freeze(requirement)
                    for chapter, requirement in opening_requirements.items()
                }
            ),
        )
        boundary._validate_initial_authority()
        return boundary

    def _validate_initial_authority(self) -> None:
        locked = tuple(
            term.casefold()
            for terms in self.locked_terms_by_chapter.values()
            for term in terms
        )
        for claim in self.initial_state.claims:
            lowered = claim.statement.casefold()
            collisions = [term for term in locked if term in lowered]
            if collisions:
                raise StoryBoundaryError(
                    f"initial current claim {claim.claim_id!r} contains locked future term"
                )

    def shared_writer_packet(self, *, chapter: int) -> str:
        if chapter not in self.chapter_frontiers:
            raise StoryBoundaryError(f"no frozen story frontier for Chapter {chapter}")
        rules = "\n".join(
            f"- [{item['rule_id']}] {item['text']}" for item in self.immutable_rules
        )
        frontier = "\n".join(f"- {item}" for item in self.chapter_frontiers[chapter])
        future = "\n".join(f"- {item}" for item in self.future_intent)
        foreshadowing = "\n".join(
            f"- {item}" for item in self.raw["chapter_one"]["narrator_foreshadowing"]
        )
        return (
            "SHARED STATIC STORY AUTHORITY PACKET\n"
            "Only claims in the condition's validated prior-chapter memory are current canon.\n"
            "Anything labeled future intent or narrator foreshadowing has NOT happened, is NOT unlocked, "
            "and is NOT character knowledge.\n\n"
            f"IMMUTABLE RULES:\n{rules}\n\n"
            f"ELIGIBLE CHAPTER {chapter} FRONTIER:\n{frontier}\n\n"
            f"LOCKED LONG-HORIZON AUTHOR INTENT (direction only, never present fact):\n{future}\n\n"
            f"PUBLISHED NARRATOR FORESHADOWING (not Ren's knowledge or achievement):\n{foreshadowing}\n"
        )

    @staticmethod
    def baseline_memory_packet(state: CanonicalState) -> str:
        """Conventional control memory: flat rolling notes without graph metadata."""
        notes: dict[str, list[str]] = {category: [] for category in STATE_CATEGORIES}
        for claim in state.claims:
            notes[claim.category].append(f"[{claim.status}] {claim.statement}")
        return (
            f"CONVENTIONAL PRIOR-CHAPTER MEMORY (verified through Chapter {state.through_chapter}):\n"
            + json.dumps(
                {
                    "through_chapter": state.through_chapter,
                    "flat_status_labeled_notes": notes,
                },
                indent=2,
                ensure_ascii=False,
            )
        )

    @staticmethod
    def kingdom_memory_packet(state: CanonicalState) -> str:
        """Treatment memory: typed claims with statuses, dependencies, and provenance."""
        return (
            f"KINGDOM STRUCTURED CLAIM LEDGER (verified through Chapter {state.through_chapter}):\n"
            + json.dumps(state.to_mapping(), indent=2, ensure_ascii=False)
        )

    def extractor_authority_packet(self, state: CanonicalState) -> str:
        rules = "\n".join(
            f"- [{item['rule_id']}] {item['text']}" for item in self.immutable_rules
        )
        return (
            f"IMMUTABLE RULES:\n{rules}\n\n"
            "PRIOR ACCEPTED CANONICAL CLAIM LEDGER:\n"
            + json.dumps(state.to_mapping(), indent=2, ensure_ascii=False)
        )

    def evaluator_packet(self, contract: str) -> str:
        blocks = []
        for item in self.raw["partitions"]:
            source_id = str(item["source_id"])
            role = str(item["role"])
            label = {
                "timeless": "TIMELESS RULE/PREMISE",
                "published": "PUBLISHED CURRENT CANON",
                "future": "LOCKED FUTURE BLUEPRINT — NOT CURRENT ACHIEVEMENT",
            }[role]
            blocks.append(f"=== {label}: {source_id} ===\n{self.partitions[source_id]}")
        return (
            "TEMPORALLY LABELED CANONICAL SEED:\n"
            + "\n".join(blocks)
            + "\n\nAUTHORIAL CONTRACT (goals do not imply current completion):\n"
            + contract
        )

    def validate_chapter_text(self, text: str, *, chapter: int) -> None:
        if not isinstance(text, str) or not text.strip():
            raise StoryBoundaryError("candidate chapter is empty")
        lowered = text.casefold()
        for term in self.locked_terms_by_chapter.get(chapter, ()):
            if term.casefold() in lowered:
                raise StoryBoundaryError(
                    f"Chapter {chapter} prematurely used locked future term {term!r}"
                )
        for item in self.forbidden_patterns_by_chapter.get(chapter, ()):
            if re.search(item["pattern"], text, re.IGNORECASE | re.DOTALL):
                raise StoryBoundaryError(
                    f"Chapter {chapter} failed {item['rule_id']}: {item['message']}"
                )
        requirement = self.opening_requirements_by_chapter.get(chapter)
        if requirement:
            opening = lowered[: int(requirement["within_chars"])]
            for group in requirement["required_any_groups"]:
                if not any(term.casefold() in opening for term in group):
                    raise StoryBoundaryError(
                        f"Chapter {chapter} opening did not reconcile the published endpoint; "
                        f"expected one of {list(group)}"
                    )

    def validate_and_update(
        self,
        state: CanonicalState,
        proposed: StoryMap,
        *,
        chapter_text: str,
        chapter: int,
    ) -> tuple[CanonicalState, BoundaryGuardReport]:
        self.validate_chapter_text(chapter_text, chapter=chapter)
        locked = tuple(term.casefold() for term in self.locked_terms_by_chapter.get(chapter, ()))
        weak_tokens = {
            "about",
            "after",
            "again",
            "being",
            "chapter",
            "current",
            "fujitsu",
            "into",
            "from",
            "have",
            "having",
            "himself",
            "ren",
            "that",
            "their",
            "there",
            "these",
            "they",
            "this",
            "through",
            "with",
        }
        for claim in proposed.claims:
            combined = f"{claim.statement}\n{claim.evidence.quote}".casefold()
            if any(term in combined for term in locked):
                raise StoryBoundaryError(
                    f"{claim.claim_id}: proposed state contains locked future canon"
                )
            if len(claim.evidence.quote.strip()) < 12:
                raise StoryBoundaryError(
                    f"{claim.claim_id}: evidence quote is too short to establish canon"
                )
            statement_tokens = {
                token.casefold()
                for token in re.findall(r"[A-Za-z][A-Za-z'’-]{2,}", claim.statement)
                if token.casefold() not in weak_tokens
            }
            evidence_tokens = {
                token.casefold()
                for token in re.findall(r"[A-Za-z][A-Za-z'’-]{2,}", claim.evidence.quote)
                if token.casefold() not in weak_tokens
            }
            if statement_tokens and len(statement_tokens & evidence_tokens) < min(
                2, len(statement_tokens)
            ):
                raise StoryBoundaryError(
                    f"{claim.claim_id}: statement is not textually grounded in its evidence quote"
                )
            statement_numbers = set(re.findall(r"(?<![A-Za-z])\$?\d[\d,]*(?:\.\d+)?", claim.statement))
            evidence_numbers = set(re.findall(r"(?<![A-Za-z])\$?\d[\d,]*(?:\.\d+)?", claim.evidence.quote))
            normalized_evidence = {item.replace("$", "").replace(",", "") for item in evidence_numbers}
            unsupported = {
                item
                for item in statement_numbers
                if item.replace("$", "").replace(",", "") not in normalized_evidence
            }
            if unsupported:
                raise StoryBoundaryError(
                    f"{claim.claim_id}: statement numbers lack quoted evidence {sorted(unsupported)}"
                )
        updated = StoryGuard().update(
            state,
            proposed,
            chapter_text=chapter_text,
            chapter=chapter,
        )
        report = BoundaryGuardReport(
            protocol=BOUNDARY_PROTOCOL_ID,
            chapter=chapter,
            chapter_sha256=_sha256_text(chapter_text),
            accepted_claim_count=len(proposed.claims),
            canonical_state_sha256=canonical_sha256(updated.to_mapping()),
        )
        return updated, report


def load_adi_story_boundary(
    *,
    seed: str,
    contract: str,
    source_map_text: str,
) -> ADIStoryBoundary:
    return ADIStoryBoundary.from_text(
        seed=seed,
        contract=contract,
        source_map_text=source_map_text,
    )
