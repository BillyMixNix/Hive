"""Deterministic observation, authority, event, and bitemporal-state core.

This module is intentionally domain-neutral and model-free.  Model output may be
converted into proposals by an adapter, but only ``AuthorityPolicy`` decisions
and immutable ledger records can affect a canonical state projection.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


JSONScalar = str | int | float | bool | None


def _json_ready(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_mapping"):
        return _json_ready(value.to_mapping())
    if hasattr(value, "__dataclass_fields__"):
        return _json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        converted = [_json_ready(item) for item in value]
        return sorted(
            converted,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Return the stable JSON form used by every content hash."""

    return json.dumps(
        _json_ready(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ModelInvariantError(ValueError):
    """A proposed ledger object violates a deterministic authority invariant."""


class EvidenceBasis(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    PROPOSED = "proposed"
    PLANNED = "planned"
    PREDICTED = "predicted"
    UNKNOWN = "unknown"


class TruthStatus(str, Enum):
    ACCEPTED = "accepted"
    DISPUTED = "disputed"
    FALSE = "false"
    UNKNOWN = "unknown"


class Authority(str, Enum):
    CANONICAL = "canonical"
    DERIVED = "derived"
    EXTERNAL = "external"
    MODEL = "model"
    COUNTERFACTUAL = "counterfactual"


class DecisionStatus(str, Enum):
    ADMIT = "admit"
    REJECT = "reject"
    DISPUTE = "dispute"


class TemporalStatus(str, Enum):
    CURRENT = "current"
    HISTORICAL = "historical"
    SUPERSEDED = "superseded"
    FUTURE = "future"
    UNKNOWN = "unknown"


class RequirementOp(str, Enum):
    EQ = "eq"
    EXISTS = "exists"
    ABSENT = "absent"
    GTE = "gte"


class EffectOp(str, Enum):
    SET = "set"
    DELETE = "delete"
    INCREMENT = "increment"


class EdgeKind(str, Enum):
    CAUSE = "cause"
    PRECONDITION = "precondition"
    EVIDENCE = "evidence"
    SUPERSEDES = "supersedes"
    CONTAINS = "contains"
    TEMPORAL_BEFORE = "temporal_before"


def _require_exact_enum(value: Any, enum_type: type[Enum], field_name: str) -> None:
    """Reject strings and foreign enum values at typed authority boundaries."""

    if type(value) is not enum_type:
        raise ModelInvariantError(
            f"{field_name} must be an exact {enum_type.__name__} member"
        )


@dataclass(frozen=True, order=True)
class FactKey:
    subject: str
    predicate: str

    def __post_init__(self) -> None:
        if not self.subject.strip() or not self.predicate.strip():
            raise ModelInvariantError("fact keys require nonempty subject and predicate")

    @property
    def text(self) -> str:
        return f"{self.subject}.{self.predicate}"


@dataclass(frozen=True)
class Observation:
    observation_id: str
    source_id: str
    recorded_at: int
    payload_json: str
    source_sha256: str
    provenance: tuple[str, ...]

    @classmethod
    def create(
        cls,
        observation_id: str,
        source_id: str,
        recorded_at: int,
        payload: Mapping[str, Any],
        *,
        provenance: Sequence[str],
    ) -> "Observation":
        payload_json = canonical_json(dict(payload))
        return cls(
            observation_id=observation_id,
            source_id=source_id,
            recorded_at=recorded_at,
            payload_json=payload_json,
            source_sha256=sha256_text(f"{source_id}|{payload_json}"),
            provenance=tuple(provenance),
        )

    def __post_init__(self) -> None:
        if not self.observation_id or not self.source_id:
            raise ModelInvariantError("observation IDs and sources are required")
        if self.recorded_at < 0 or not self.provenance:
            raise ModelInvariantError("observations require a record sequence and provenance")
        try:
            parsed = json.loads(self.payload_json)
        except json.JSONDecodeError as exc:
            raise ModelInvariantError("observation payload is not JSON") from exc
        if canonical_json(parsed) != self.payload_json:
            raise ModelInvariantError("observation payload must be canonical JSON")
        expected = sha256_text(f"{self.source_id}|{self.payload_json}")
        if self.source_sha256 != expected:
            raise ModelInvariantError("observation content hash does not match")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "payload": json.loads(self.payload_json),
            "provenance": list(self.provenance),
            "recorded_at": self.recorded_at,
            "source_id": self.source_id,
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True)
class EvidenceRef:
    observation_id: str
    source_id: str
    source_sha256: str
    locator: str

    @classmethod
    def from_observation(cls, observation: Observation, locator: str = "payload") -> "EvidenceRef":
        return cls(
            observation_id=observation.observation_id,
            source_id=observation.source_id,
            source_sha256=observation.source_sha256,
            locator=locator,
        )

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Requirement:
    key: FactKey
    op: RequirementOp
    value: JSONScalar = None

    def __post_init__(self) -> None:
        _require_exact_enum(self.op, RequirementOp, "requirement op")


@dataclass(frozen=True)
class ClaimRevision:
    claim_id: str
    key: FactKey
    value: JSONScalar
    basis: EvidenceBasis
    truth: TruthStatus
    authority: Authority
    valid_from: int
    valid_to: int | None
    recorded_at: int
    evidence: tuple[EvidenceRef, ...]
    depends_on_claim_ids: tuple[str, ...] = ()
    supersedes_claim_ids: tuple[str, ...] = ()
    derivation_rule_id: str | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        _require_exact_enum(self.basis, EvidenceBasis, "claim basis")
        _require_exact_enum(self.truth, TruthStatus, "claim truth")
        _require_exact_enum(self.authority, Authority, "claim authority")
        if not self.claim_id:
            raise ModelInvariantError("claim_id is required")
        if self.valid_from < 0 or self.recorded_at < 0:
            raise ModelInvariantError("claim times must be nonnegative")
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ModelInvariantError("claim validity interval must be half-open and nonempty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ModelInvariantError("claim confidence must be between zero and one")
        if not self.evidence:
            raise ModelInvariantError("every claim requires evidence")
        if self.basis is EvidenceBasis.INFERRED and not self.derivation_rule_id:
            raise ModelInvariantError("inferred claims require a named derivation rule")

    @property
    def content_hash(self) -> str:
        return sha256_text(canonical_json(asdict(self)))


@dataclass(frozen=True)
class StateEffect:
    claim_id: str
    key: FactKey
    op: EffectOp
    value: JSONScalar = None
    expected_previous: JSONScalar = None
    increment_by: JSONScalar = None
    expected_previous_specified: bool = False

    def __post_init__(self) -> None:
        _require_exact_enum(self.op, EffectOp, "state effect op")
        if type(self.expected_previous_specified) is not bool:
            raise ModelInvariantError(
                "expected_previous_specified must be an exact boolean"
            )
        # Preserve the original convenient API for non-null guards while
        # making a null-valued guard explicit and distinguishable from no
        # guard.  Callers express the latter with
        # ``expected_previous=None, expected_previous_specified=True``.
        if self.expected_previous is not None and not self.expected_previous_specified:
            object.__setattr__(self, "expected_previous_specified", True)
        if self.op is EffectOp.DELETE and self.value is not None:
            raise ModelInvariantError("DELETE effects must have a null value")
        if self.op is EffectOp.INCREMENT:
            operands = (self.expected_previous, self.increment_by, self.value)
            if any(
                not isinstance(item, (int, float)) or isinstance(item, bool)
                for item in operands
            ):
                raise ModelInvariantError(
                    "INCREMENT effects require numeric expected_previous, "
                    "increment_by, and result value"
                )
            if canonical_json(self.expected_previous + self.increment_by) != canonical_json(
                self.value
            ):
                raise ModelInvariantError(
                    "INCREMENT result must equal expected_previous plus increment_by"
                )
        elif self.increment_by is not None:
            raise ModelInvariantError("increment_by is only valid for INCREMENT effects")


@dataclass(frozen=True)
class CanonicalEvent:
    event_id: str
    event_type: str
    effective_time: int
    recorded_at: int
    entities: tuple[str, ...]
    requirements: tuple[Requirement, ...]
    effects: tuple[StateEffect, ...]
    claims: tuple[ClaimRevision, ...]
    causal_parents: tuple[str, ...]
    hard_dependencies: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]
    edges: tuple[tuple[EdgeKind, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.event_id or not self.event_type:
            raise ModelInvariantError("event ID and type are required")
        if self.effective_time < 0 or self.recorded_at < 0:
            raise ModelInvariantError("event times must be nonnegative")
        if not self.evidence:
            raise ModelInvariantError("events require evidence")
        for edge in self.edges:
            if not isinstance(edge, tuple) or len(edge) != 2:
                raise ModelInvariantError("event edges must be (EdgeKind, target_id) pairs")
            _require_exact_enum(edge[0], EdgeKind, "event edge kind")
        claim_ids = {claim.claim_id for claim in self.claims}
        if len(claim_ids) != len(self.claims):
            raise ModelInvariantError("claim IDs within an event must be unique")
        effect_keys = {effect.key for effect in self.effects}
        if len(effect_keys) != len(self.effects):
            raise ModelInvariantError("state effect keys within an event must be unique")
        if any(effect.claim_id not in claim_ids for effect in self.effects):
            raise ModelInvariantError("every state effect must cite a claim in the event")
        if any(claim.recorded_at != self.recorded_at for claim in self.claims):
            raise ModelInvariantError("event and claim record sequences must match")
        claims_by_id = {claim.claim_id: claim for claim in self.claims}
        if any(
            effect.key != claims_by_id[effect.claim_id].key
            or canonical_json(effect.value)
            != canonical_json(claims_by_id[effect.claim_id].value)
            for effect in self.effects
        ):
            raise ModelInvariantError(
                "every state effect key and value must match its cited claim"
            )
        if any(
            claims_by_id[effect.claim_id].valid_from != self.effective_time
            for effect in self.effects
        ):
            raise ModelInvariantError(
                "effect claim valid_from must match the event effective_time"
            )

    @property
    def content_hash(self) -> str:
        return sha256_text(canonical_json(asdict(self)))


@dataclass(frozen=True)
class PromotionDecision:
    event_id: str
    status: DecisionStatus
    policy_id: str
    reason: str
    evidence_sha256: str
    event_content_hash: str

    def __post_init__(self) -> None:
        _require_exact_enum(self.status, DecisionStatus, "promotion decision status")


@dataclass(frozen=True)
class Contradiction:
    contradiction_id: str
    key: FactKey
    claim_ids: tuple[str, ...]
    overlap_from: int
    resolution: str
    resolved_by_claim_id: str | None = None
    overlap_to: int | None = None


@dataclass(frozen=True)
class StateCell:
    key: FactKey
    value: JSONScalar
    source_claim_id: str
    source_event_id: str
    valid_from: int
    valid_to: int | None
    recorded_at: int


@dataclass(frozen=True)
class StateTransition:
    key: FactKey
    before: JSONScalar
    after: JSONScalar
    effective_time: int
    source_event_id: str
    source_claim_id: str
    replaced_claim_id: str | None = None


@dataclass(frozen=True)
class ReplayDecision:
    event_id: str
    admitted: bool
    reason: str


@dataclass(frozen=True)
class StateSnapshot:
    valid_at: int
    known_at: int
    cells: tuple[StateCell, ...]
    history: tuple[StateTransition, ...]
    contradictions: tuple[Contradiction, ...]
    ambiguous_keys: tuple[FactKey, ...]
    decisions: tuple[ReplayDecision, ...]
    noncanonical: bool = False

    def value(self, key: FactKey, default: Any = None) -> Any:
        if key in self.ambiguous_keys:
            return default
        for cell in self.cells:
            if cell.key == key:
                return cell.value
        return default

    def cell(self, key: FactKey) -> StateCell | None:
        if key in self.ambiguous_keys:
            return None
        return next((cell for cell in self.cells if cell.key == key), None)

    @property
    def digest(self) -> str:
        return sha256_text(canonical_json(self.to_mapping()))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "ambiguous_keys": [key.text for key in self.ambiguous_keys],
            "cells": [
                {
                    "key": cell.key.text,
                    "recorded_at": cell.recorded_at,
                    "source_claim_id": cell.source_claim_id,
                    "source_event_id": cell.source_event_id,
                    "valid_from": cell.valid_from,
                    "valid_to": cell.valid_to,
                    "value": cell.value,
                }
                for cell in self.cells
            ],
            "contradictions": [
                {
                    "claim_ids": list(item.claim_ids),
                    "contradiction_id": item.contradiction_id,
                    "key": item.key.text,
                    "overlap_from": item.overlap_from,
                    "overlap_to": item.overlap_to,
                    "resolution": item.resolution,
                    "resolved_by_claim_id": item.resolved_by_claim_id,
                }
                for item in self.contradictions
            ],
            "decisions": [asdict(item) for item in self.decisions],
            "history": [
                {
                    "after": item.after,
                    "before": item.before,
                    "effective_time": item.effective_time,
                    "key": item.key.text,
                    "source_claim_id": item.source_claim_id,
                    "source_event_id": item.source_event_id,
                    "replaced_claim_id": item.replaced_claim_id,
                }
                for item in self.history
            ],
            "known_at": self.known_at,
            "noncanonical": self.noncanonical,
            "valid_at": self.valid_at,
        }


@dataclass(frozen=True, init=False, slots=True)
class AuthorityPolicy:
    """Deterministic admission policy; confidence alone never grants authority."""

    registered_inference_rules: frozenset[str]

    def __init__(self, registered_inference_rules: Iterable[str] = ()) -> None:
        object.__setattr__(
            self,
            "registered_inference_rules",
            frozenset(registered_inference_rules),
        )

    @property
    def policy_id(self) -> str:
        rule_hash = sha256_text(canonical_json(sorted(self.registered_inference_rules)))[:12]
        return f"hive-authority-v1:{rule_hash}"

    def claim_has_epistemic_authority(self, claim: ClaimRevision) -> bool:
        """Whether a non-accepted claim may establish explicit uncertainty.

        This intentionally ignores ``truth`` while preserving the same
        evidence-basis and authority boundary used for world-state promotion.
        Runtime event/claim dependencies and preconditions are checked by
        replay before the uncertainty overlay is materialized.
        """

        if claim.basis is EvidenceBasis.OBSERVED:
            return claim.authority is Authority.CANONICAL
        if claim.basis is EvidenceBasis.INFERRED:
            return (
                claim.authority is Authority.DERIVED
                and bool(claim.derivation_rule_id)
                and claim.derivation_rule_id in self.registered_inference_rules
                and bool(claim.depends_on_claim_ids)
            )
        return False

    def decide(self, event: CanonicalEvent) -> PromotionDecision:
        evidence_hash = sha256_text(canonical_json([asdict(item) for item in event.evidence]))
        event_content_hash = event.content_hash
        if not event.effects:
            return PromotionDecision(
                event.event_id,
                DecisionStatus.REJECT,
                self.policy_id,
                "no_world_effects",
                evidence_hash,
                event_content_hash,
            )
        claims = {claim.claim_id: claim for claim in event.claims}
        effect_claims = [claims[effect.claim_id] for effect in event.effects]
        if any(claim.truth is TruthStatus.DISPUTED for claim in effect_claims):
            status, reason = DecisionStatus.DISPUTE, "disputed_claim"
        elif any(claim.truth is not TruthStatus.ACCEPTED for claim in effect_claims):
            status, reason = DecisionStatus.REJECT, "truth_not_accepted"
        elif any(
            claim.basis in {
                EvidenceBasis.PROPOSED,
                EvidenceBasis.PLANNED,
                EvidenceBasis.PREDICTED,
                EvidenceBasis.UNKNOWN,
            }
            for claim in effect_claims
        ):
            status, reason = DecisionStatus.REJECT, "non_promotable_basis"
        elif any(
            claim.basis is EvidenceBasis.OBSERVED and claim.authority is not Authority.CANONICAL
            for claim in effect_claims
        ):
            status, reason = DecisionStatus.REJECT, "observed_claim_not_canonical"
        elif any(
            claim.basis is EvidenceBasis.INFERRED
            and (
                claim.authority is not Authority.DERIVED
                or not claim.derivation_rule_id
                or claim.derivation_rule_id not in self.registered_inference_rules
                or not claim.depends_on_claim_ids
            )
            for claim in effect_claims
        ):
            status, reason = DecisionStatus.REJECT, "unlicensed_inference"
        else:
            status, reason = DecisionStatus.ADMIT, "authority_policy_passed"
        return PromotionDecision(
            event.event_id,
            status,
            self.policy_id,
            reason,
            evidence_hash,
            event_content_hash,
        )


class EventLedger:
    """Append-only observation/event/decision ledger with pure replay."""

    def __init__(self, policy: AuthorityPolicy | None = None) -> None:
        self.policy = policy or AuthorityPolicy()
        self._observations: dict[str, Observation] = {}
        self._events: dict[str, CanonicalEvent] = {}
        self._decisions: dict[str, PromotionDecision] = {}
        self._claims: dict[str, ClaimRevision] = {}
        self._record_sequences: set[int] = set()

    @property
    def observations(self) -> tuple[Observation, ...]:
        return tuple(sorted(self._observations.values(), key=lambda item: item.observation_id))

    @property
    def events(self) -> tuple[CanonicalEvent, ...]:
        return tuple(sorted(self._events.values(), key=lambda item: (item.recorded_at, item.event_id)))

    @property
    def decisions(self) -> tuple[PromotionDecision, ...]:
        return tuple(self._decision_for(event) for event in self.events)

    @property
    def head_record_seq(self) -> int:
        values = [item.recorded_at for item in self._observations.values()]
        values.extend(item.recorded_at for item in self._events.values())
        return max(values, default=0)

    @property
    def digest(self) -> str:
        return sha256_text(
            canonical_json(
                {
                    "decisions": [asdict(item) for item in self.decisions],
                    "events": [asdict(item) for item in self.events],
                    "observations": [item.to_mapping() for item in self.observations],
                    "policy_id": self.policy.policy_id,
                }
            )
        )

    def append_observation(self, observation: Observation) -> None:
        if observation.observation_id in self._observations:
            raise ModelInvariantError(f"duplicate observation ID {observation.observation_id}")
        self._observations[observation.observation_id] = observation

    def _validate_evidence(
        self,
        evidence: Iterable[EvidenceRef],
        *,
        recorded_at: int,
    ) -> None:
        for ref in evidence:
            observed = self._observations.get(ref.observation_id)
            if observed is None:
                raise ModelInvariantError(f"unknown evidence observation {ref.observation_id}")
            if ref.source_id != observed.source_id or ref.source_sha256 != observed.source_sha256:
                raise ModelInvariantError("evidence source identity or hash does not match")
            if observed.recorded_at > recorded_at:
                raise ModelInvariantError(
                    "evidence cannot be recorded after the record that cites it"
                )

    def _decision_for(self, event: CanonicalEvent) -> PromotionDecision:
        decision = self._decisions.get(event.event_id)
        if decision is None:
            raise ModelInvariantError(f"event {event.event_id} has no promotion decision")
        expected = self.policy.decide(event)
        if decision != expected:
            raise ModelInvariantError(
                "promotion decision does not match the recomputed authority decision"
            )
        return decision

    def _has_dependency_path(self, start: str, target: str) -> bool:
        pending = [start]
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            event = self._events.get(current)
            if event is not None:
                pending.extend(event.hard_dependencies)
                pending.extend(event.causal_parents)
        return False

    def append_event(self, event: CanonicalEvent) -> PromotionDecision:
        if event.event_id in self._events:
            raise ModelInvariantError(f"duplicate event ID {event.event_id}")
        if event.recorded_at in self._record_sequences:
            raise ModelInvariantError("event record sequences must be unique")
        self._validate_evidence(event.evidence, recorded_at=event.recorded_at)
        for claim in event.claims:
            self._validate_evidence(claim.evidence, recorded_at=claim.recorded_at)
            if claim.claim_id in self._claims:
                raise ModelInvariantError(f"duplicate claim ID {claim.claim_id}")
            for dependency in claim.depends_on_claim_ids:
                target = self._claims.get(dependency)
                if target is None:
                    raise ModelInvariantError(f"unknown claim dependency {dependency}")
                if target.recorded_at > claim.recorded_at:
                    raise ModelInvariantError(
                        "claims cannot depend on claims recorded in the future"
                    )
            for superseded_id in claim.supersedes_claim_ids:
                target = self._claims.get(superseded_id)
                if target is None:
                    raise ModelInvariantError(f"unknown superseded claim {superseded_id}")
                if target.key != claim.key or target.recorded_at >= claim.recorded_at:
                    raise ModelInvariantError("supersession requires same key and a later record")
        all_dependencies = set(event.hard_dependencies) | set(event.causal_parents)
        if event.event_id in all_dependencies:
            raise ModelInvariantError("events cannot depend on themselves")
        for dependency in all_dependencies:
            target = self._events.get(dependency)
            if target is None:
                raise ModelInvariantError(f"unknown event dependency {dependency}")
            if target.recorded_at > event.recorded_at:
                raise ModelInvariantError(
                    "events cannot depend on events recorded in the future"
                )
            if target.effective_time > event.effective_time:
                raise ModelInvariantError("events cannot causally depend on future-effective events")
            if self._has_dependency_path(dependency, event.event_id):
                raise ModelInvariantError("event dependency cycle")
        decision = self.policy.decide(event)
        if (
            decision.event_id != event.event_id
            or decision.event_content_hash != event.content_hash
        ):
            raise ModelInvariantError(
                "promotion decision does not match the full event content"
            )
        self._events[event.event_id] = event
        self._decisions[event.event_id] = decision
        self._record_sequences.add(event.recorded_at)
        self._claims.update({claim.claim_id: claim for claim in event.claims})
        return decision

    def _event_reaches(self, start: str, target: str) -> bool:
        if start == target:
            return True
        return self._has_dependency_path(start, target)

    @staticmethod
    def _requirement_met(
        cells: Mapping[FactKey, StateCell],
        requirement: Requirement,
        ambiguous_keys: Iterable[FactKey] = (),
    ) -> bool:
        # Ambiguity is an explicit unknown-state overlay, never absence.
        if requirement.key in ambiguous_keys:
            return False
        cell = cells.get(requirement.key)
        if requirement.op is RequirementOp.EXISTS:
            return cell is not None
        if requirement.op is RequirementOp.ABSENT:
            return cell is None
        if requirement.op is RequirementOp.EQ:
            return (
                cell is not None
                and canonical_json(cell.value) == canonical_json(requirement.value)
            )
        if requirement.op is RequirementOp.GTE:
            return (
                cell is not None
                and isinstance(cell.value, (int, float))
                and not isinstance(cell.value, bool)
                and isinstance(requirement.value, (int, float))
                and not isinstance(requirement.value, bool)
                and cell.value >= requirement.value
            )
        raise ModelInvariantError(f"unknown requirement operator {requirement.op}")

    @staticmethod
    def _effects_incompatible(
        left: StateEffect,
        right: StateEffect,
        left_claim: ClaimRevision,
        right_claim: ClaimRevision,
    ) -> bool:
        """Whether unordered, simultaneous effects have an order-dependent result."""

        if left.op is right.op:
            if left.op is EffectOp.SET:
                return (
                    canonical_json(left.value) != canonical_json(right.value)
                    or left_claim.valid_from != right_claim.valid_from
                    or left_claim.valid_to != right_claim.valid_to
                )
            # Deletions are idempotent.  Increments are still competing
            # assertions of transition authority unless explicitly ordered.
            return left.op is not EffectOp.DELETE
        return True

    @staticmethod
    def _evaluate_event_effects(
        event: CanonicalEvent,
        cells: Mapping[FactKey, StateCell],
        *,
        validate: bool,
    ) -> tuple[dict[FactKey, StateCell], list[StateTransition], str | None]:
        """Apply one atomic event to a trial state, optionally checking guards."""

        claims = {claim.claim_id: claim for claim in event.claims}
        trial = dict(cells)
        trial_history: list[StateTransition] = []
        for effect in event.effects:
            claim = claims[effect.claim_id]
            existing = trial.get(effect.key)
            expected_matches = (
                effect.expected_previous_specified
                and existing is not None
                and canonical_json(existing.value)
                == canonical_json(effect.expected_previous)
            )
            supersedes_existing = (
                existing is not None
                and existing.source_claim_id in claim.supersedes_claim_ids
            )
            if effect.op is EffectOp.SET:
                if (
                    validate
                    and effect.expected_previous_specified
                    and not expected_matches
                ):
                    return trial, trial_history, "expected_previous_mismatch"
                changes_existing_state = (
                    existing is not None
                    and (
                        canonical_json(existing.value) != canonical_json(effect.value)
                        or existing.valid_to != claim.valid_to
                    )
                )
                if (
                    validate
                    and changes_existing_state
                    and not expected_matches
                    and not supersedes_existing
                ):
                    return trial, trial_history, "unlicensed_supersession"
                before = None if existing is None else existing.value
                trial[effect.key] = StateCell(
                    key=effect.key,
                    value=effect.value,
                    source_claim_id=claim.claim_id,
                    source_event_id=event.event_id,
                    valid_from=claim.valid_from,
                    valid_to=claim.valid_to,
                    recorded_at=claim.recorded_at,
                )
                trial_history.append(
                    StateTransition(
                        key=effect.key,
                        before=before,
                        after=effect.value,
                        effective_time=event.effective_time,
                        source_event_id=event.event_id,
                        source_claim_id=claim.claim_id,
                        replaced_claim_id=(
                            None if existing is None else existing.source_claim_id
                        ),
                    )
                )
            elif effect.op is EffectOp.DELETE:
                if (
                    validate
                    and effect.expected_previous_specified
                    and not expected_matches
                ):
                    return trial, trial_history, "expected_previous_mismatch"
                if (
                    validate
                    and existing is not None
                    and not expected_matches
                    and not supersedes_existing
                ):
                    return trial, trial_history, "unlicensed_deletion"
                before = None if existing is None else existing.value
                trial.pop(effect.key, None)
                trial_history.append(
                    StateTransition(
                        effect.key,
                        before,
                        None,
                        event.effective_time,
                        event.event_id,
                        claim.claim_id,
                        None if existing is None else existing.source_claim_id,
                    )
                )
            elif effect.op is EffectOp.INCREMENT:
                if validate and (
                    existing is None
                    or canonical_json(existing.value)
                    != canonical_json(effect.expected_previous)
                ):
                    return trial, trial_history, "expected_previous_mismatch"
                before = effect.expected_previous if existing is None else existing.value
                after = effect.value
                trial[effect.key] = StateCell(
                    effect.key,
                    after,
                    claim.claim_id,
                    event.event_id,
                    claim.valid_from,
                    claim.valid_to,
                    claim.recorded_at,
                )
                trial_history.append(
                    StateTransition(
                        effect.key,
                        before,
                        after,
                        event.effective_time,
                        event.event_id,
                        claim.claim_id,
                        None if existing is None else existing.source_claim_id,
                    )
                )
            else:  # pragma: no cover - Enum construction prevents this.
                return trial, trial_history, "unknown_effect"
        return trial, trial_history, None

    @staticmethod
    def _claim_valid_at(claim: ClaimRevision, valid_at: int) -> bool:
        return claim.valid_from <= valid_at and (
            claim.valid_to is None or valid_at < claim.valid_to
        )

    @classmethod
    def _active_conflict_claim_ids(
        cls,
        contradiction: Contradiction,
        claims_by_id: Mapping[str, ClaimRevision],
        valid_at: int,
    ) -> frozenset[str]:
        return frozenset(
            claim_id
            for claim_id in contradiction.claim_ids
            if claim_id in claims_by_id
            and cls._claim_valid_at(claims_by_id[claim_id], valid_at)
        )

    @staticmethod
    def _overlap_to(claims: Iterable[ClaimRevision]) -> int | None:
        finite_ends = [claim.valid_to for claim in claims if claim.valid_to is not None]
        return min(finite_ends) if finite_ends else None

    def replay(
        self,
        *,
        valid_at: int,
        known_at: int | None = None,
        exclude_event_ids: Iterable[str] = (),
        noncanonical: bool = False,
    ) -> StateSnapshot:
        """Project state at world time ``valid_at`` using ledger knowledge ``known_at``."""

        if valid_at < 0:
            raise ModelInvariantError("valid_at must be nonnegative")
        known = self.head_record_seq if known_at is None else known_at
        excluded = frozenset(exclude_event_ids)
        visible = [
            event
            for event in self._events.values()
            if event.recorded_at <= known
            and event.effective_time <= valid_at
            and event.event_id not in excluded
        ]
        visible.sort(key=lambda item: (item.effective_time, item.recorded_at, item.event_id))

        cells: dict[FactKey, StateCell] = {}
        history: list[StateTransition] = []
        decisions: dict[str, ReplayDecision] = {}
        contradictions: list[Contradiction] = []
        ambiguous: set[FactKey] = set()
        applied: set[str] = set()
        applied_claims: set[str] = set()

        claims_by_id = {
            claim.claim_id: claim for event in visible for claim in event.claims
        }
        claim_event_ids = {
            claim.claim_id: event.event_id
            for event in visible
            for claim in event.claims
        }

        def refresh_ambiguity(at_time: int) -> set[FactKey]:
            active_keys: set[FactKey] = set()
            for index, contradiction in enumerate(contradictions):
                if contradiction.resolution != "unresolved":
                    continue
                active_ids = self._active_conflict_claim_ids(
                    contradiction, claims_by_id, at_time
                )
                if active_ids:
                    active_keys.add(contradiction.key)
                else:
                    contradictions[index] = replace(
                        contradiction, resolution="expired"
                    )
            return active_keys

        # Events at one effective time are evaluated in explicit causal layers.
        # Peers in a layer see the same starting state, so record order cannot
        # make a false precondition poison a valid peer or choose between
        # incompatible authoritative effects.
        cursor = 0
        while cursor < len(visible):
            current_time = visible[cursor].effective_time
            group_end = cursor
            while (
                group_end < len(visible)
                and visible[group_end].effective_time == current_time
            ):
                group_end += 1
            group = visible[cursor:group_end]
            cursor = group_end

            for key, cell in tuple(cells.items()):
                if cell.valid_to is not None and cell.valid_to <= current_time:
                    del cells[key]
            ambiguous = refresh_ambiguity(current_time)

            group_ids = {event.event_id for event in group}
            predecessors: dict[str, set[str]] = {}
            for event in group:
                event_claims = {claim.claim_id: claim for claim in event.claims}
                effect_claims = [event_claims[effect.claim_id] for effect in event.effects]
                prior_ids = set(event.hard_dependencies) | set(event.causal_parents)
                for claim in effect_claims:
                    for claim_id in (
                        *claim.depends_on_claim_ids,
                        *claim.supersedes_claim_ids,
                    ):
                        source_event_id = claim_event_ids.get(claim_id)
                        if source_event_id is not None:
                            prior_ids.add(source_event_id)
                predecessors[event.event_id] = prior_ids & group_ids

            pending = {event.event_id: event for event in group}
            while pending:
                pending_ids = set(pending)
                stage = sorted(
                    (
                        event
                        for event in pending.values()
                        if not (predecessors[event.event_id] & pending_ids)
                    ),
                    key=lambda item: (item.recorded_at, item.event_id),
                )
                if not stage:  # Defensive: append-time record ordering makes this unreachable.
                    raise ModelInvariantError("same-time event ordering cycle")

                # A well-authorized observation or licensed inference whose
                # truth is explicitly DISPUTED/UNKNOWN establishes epistemic
                # unknown, not world-state absence.  Materialize that overlay
                # before peer requirements are evaluated so ABSENT cannot turn
                # uncertainty into a positive fact.  Plans, proposals,
                # predictions, untrusted observations, and dependency- or
                # precondition-failed assertions do not receive this power.
                stage_start_cells = dict(cells)
                stage_start_ambiguous = frozenset(ambiguous)
                uncertainty_candidates: list[
                    tuple[StateEffect, ClaimRevision]
                ] = []
                for uncertain_event in stage:
                    if any(
                        dep in excluded or dep not in applied
                        for dep in (
                            *uncertain_event.hard_dependencies,
                            *uncertain_event.causal_parents,
                        )
                    ):
                        continue
                    if not all(
                        self._requirement_met(
                            stage_start_cells,
                            item,
                            stage_start_ambiguous,
                        )
                        for item in uncertain_event.requirements
                    ):
                        continue
                    uncertain_claims = {
                        claim.claim_id: claim for claim in uncertain_event.claims
                    }
                    for effect in uncertain_event.effects:
                        claim = uncertain_claims[effect.claim_id]
                        if claim.truth not in {
                            TruthStatus.DISPUTED,
                            TruthStatus.UNKNOWN,
                        }:
                            continue
                        if not self.policy.claim_has_epistemic_authority(claim):
                            continue
                        if any(
                            dependency not in applied_claims
                            for dependency in claim.depends_on_claim_ids
                        ):
                            continue
                        if not self._claim_valid_at(claim, current_time):
                            continue
                        # An already established accepted cell resolves a later
                        # uncertain assertion by authority.  The ordinary
                        # contradiction pass below still records that dispute.
                        if (
                            effect.key in stage_start_cells
                            and effect.key not in stage_start_ambiguous
                        ):
                            continue
                        uncertainty_candidates.append((effect, claim))

                # Materialize the complete candidate set only after every
                # uncertain peer was assessed against the immutable pre-stage
                # view.  Peer iteration/record order therefore cannot make one
                # uncertainty invalidate another's ABSENT precondition.
                for effect, claim in uncertainty_candidates:
                    if any(
                        contradiction.resolution == "unresolved"
                        and contradiction.claim_ids == (claim.claim_id,)
                        for contradiction in contradictions
                    ):
                        continue
                    contradictions.append(
                        Contradiction(
                            contradiction_id="epistemic_"
                            + sha256_text(
                                canonical_json(
                                    [effect.key.text, claim.claim_id]
                                )
                            )[:16],
                            key=effect.key,
                            claim_ids=(claim.claim_id,),
                            overlap_from=claim.valid_from,
                            resolution="unresolved",
                            overlap_to=claim.valid_to,
                        )
                    )
                    ambiguous.add(effect.key)

                eligible: list[CanonicalEvent] = []
                resolving_keys_by_event: dict[str, frozenset[FactKey]] = {}
                for event in stage:
                    policy_decision = self._decision_for(event)
                    if policy_decision.status is not DecisionStatus.ADMIT:
                        decisions[event.event_id] = ReplayDecision(
                            event.event_id, False, policy_decision.reason
                        )
                        continue
                    if any(
                        dep in excluded or dep not in applied
                        for dep in event.hard_dependencies
                    ):
                        decisions[event.event_id] = ReplayDecision(
                            event.event_id, False, "missing_hard_dependency"
                        )
                        continue
                    # ``causal_parents`` are executable event dependencies:
                    # the asserted cause must itself have been admitted and
                    # applied.  Informational graph links belong in ``edges``
                    # and do not gate replay merely by being present there.
                    if any(
                        dep in excluded or dep not in applied
                        for dep in event.causal_parents
                    ):
                        decisions[event.event_id] = ReplayDecision(
                            event.event_id, False, "missing_causal_parent"
                        )
                        continue
                    event_claims = {claim.claim_id: claim for claim in event.claims}
                    effect_claims = [
                        event_claims[effect.claim_id] for effect in event.effects
                    ]
                    if any(
                        dependency not in applied_claims
                        for claim in effect_claims
                        for dependency in claim.depends_on_claim_ids
                    ):
                        decisions[event.event_id] = ReplayDecision(
                            event.event_id, False, "missing_claim_dependency"
                        )
                        continue
                    if not all(
                        self._requirement_met(cells, item, ambiguous)
                        for item in event.requirements
                    ):
                        decisions[event.event_id] = ReplayDecision(
                            event.event_id, False, "precondition_failed"
                        )
                        continue
                    resolving_keys: set[FactKey] = set()
                    ambiguity_rejection = False
                    for effect in event.effects:
                        active_conflicting_ids = frozenset().union(
                            *(
                                self._active_conflict_claim_ids(
                                    contradiction, claims_by_id, current_time
                                )
                                for contradiction in contradictions
                                if contradiction.key == effect.key
                                and contradiction.resolution == "unresolved"
                            )
                        )
                        if not active_conflicting_ids:
                            continue
                        claim = event_claims[effect.claim_id]
                        explicitly_superseded = active_conflicting_ids <= frozenset(
                            claim.supersedes_claim_ids
                        )
                        same_stage_epistemic = all(
                            claims_by_id[claim_id].truth
                            in {TruthStatus.DISPUTED, TruthStatus.UNKNOWN}
                            and claim_event_ids.get(claim_id)
                            in {item.event_id for item in stage}
                            for claim_id in active_conflicting_ids
                        )
                        if not explicitly_superseded and not same_stage_epistemic:
                            ambiguity_rejection = True
                            break
                        resolving_keys.add(effect.key)
                    if ambiguity_rejection:
                        decisions[event.event_id] = ReplayDecision(
                            event.event_id, False, "unresolved_contradiction"
                        )
                        continue
                    evaluation_cells = dict(cells)
                    for key in resolving_keys:
                        evaluation_cells.pop(key, None)
                    _, _, rejection = self._evaluate_event_effects(
                        event, evaluation_cells, validate=True
                    )
                    if rejection is not None:
                        decisions[event.event_id] = ReplayDecision(
                            event.event_id, False, rejection
                        )
                        continue
                    eligible.append(event)
                    resolving_keys_by_event[event.event_id] = frozenset(
                        resolving_keys
                    )

                effects_by_key: dict[
                    FactKey, list[tuple[CanonicalEvent, StateEffect]]
                ] = {}
                for event in eligible:
                    for effect in event.effects:
                        effects_by_key.setdefault(effect.key, []).append(
                            (event, effect)
                        )

                conflict_events: set[str] = set()
                conflict_claims: dict[FactKey, set[str]] = {}
                for key, writes in effects_by_key.items():
                    for index, (left_event, left_effect) in enumerate(writes):
                        for right_event, right_effect in writes[index + 1 :]:
                            if left_event.event_id == right_event.event_id:
                                continue
                            left_claim = claims_by_id[left_effect.claim_id]
                            right_claim = claims_by_id[right_effect.claim_id]
                            if not self._effects_incompatible(
                                left_effect,
                                right_effect,
                                left_claim,
                                right_claim,
                            ):
                                continue
                            conflict_events.update(
                                (left_event.event_id, right_event.event_id)
                            )
                            conflict_claims.setdefault(key, set()).update(
                                (left_effect.claim_id, right_effect.claim_id)
                            )

                for key, ids in sorted(
                    conflict_claims.items(), key=lambda item: item[0]
                ):
                    claim_ids = tuple(sorted(ids))
                    contradiction_id = "conflict_" + sha256_text(
                        canonical_json([key.text, current_time, list(claim_ids)])
                    )[:16]
                    contradictions.append(
                        Contradiction(
                            contradiction_id=contradiction_id,
                            key=key,
                            claim_ids=claim_ids,
                            overlap_from=current_time,
                            resolution="unresolved",
                            overlap_to=self._overlap_to(
                                claims_by_id[claim_id] for claim_id in claim_ids
                            ),
                        )
                    )
                    ambiguous.add(key)

                for event in eligible:
                    if event.event_id in conflict_events:
                        decisions[event.event_id] = ReplayDecision(
                            event.event_id, False, "unresolved_contradiction"
                        )
                        continue
                    application_cells = dict(cells)
                    for key in resolving_keys_by_event[event.event_id]:
                        application_cells.pop(key, None)
                    cells, event_history, rejection = self._evaluate_event_effects(
                        event, application_cells, validate=False
                    )
                    if rejection is not None:  # pragma: no cover - eligibility proved it.
                        decisions[event.event_id] = ReplayDecision(
                            event.event_id, False, rejection
                        )
                        continue
                    history.extend(event_history)
                    applied.add(event.event_id)
                    applied_claims.update(effect.claim_id for effect in event.effects)
                    decisions[event.event_id] = ReplayDecision(
                        event.event_id, True, "admitted"
                    )

                    event_claims = {
                        claim.claim_id: claim for claim in event.claims
                    }
                    for effect in event.effects:
                        claim = event_claims[effect.claim_id]
                        superseded = frozenset(claim.supersedes_claim_ids)
                        for index, contradiction in enumerate(contradictions):
                            active_conflicting_ids = self._active_conflict_claim_ids(
                                contradiction, claims_by_id, current_time
                            )
                            if (
                                contradiction.key == claim.key
                                and contradiction.resolution == "unresolved"
                                and active_conflicting_ids
                                and (
                                    active_conflicting_ids <= superseded
                                    or (
                                        len(contradiction.claim_ids) == 1
                                        and all(
                                            claims_by_id[claim_id].truth
                                            in {
                                                TruthStatus.DISPUTED,
                                                TruthStatus.UNKNOWN,
                                            }
                                            and claim_event_ids.get(claim_id)
                                            in {item.event_id for item in stage}
                                            for claim_id in active_conflicting_ids
                                        )
                                    )
                                )
                            ):
                                resolved_by_supersession = (
                                    active_conflicting_ids <= superseded
                                )
                                resolved_claim_ids = (
                                    contradiction.claim_ids
                                    if resolved_by_supersession
                                    else tuple(
                                        sorted(
                                            (
                                                *contradiction.claim_ids,
                                                claim.claim_id,
                                            )
                                        )
                                    )
                                )
                                contradictions[index] = replace(
                                    contradiction,
                                    resolution=(
                                        "superseded"
                                        if resolved_by_supersession
                                        else "authority"
                                    ),
                                    resolved_by_claim_id=claim.claim_id,
                                    claim_ids=resolved_claim_ids,
                                )
                    ambiguous = refresh_ambiguity(current_time)

                for event in stage:
                    pending.pop(event.event_id)

        for key, cell in tuple(cells.items()):
            if cell.valid_to is not None and cell.valid_to <= valid_at:
                del cells[key]
        ambiguous = refresh_ambiguity(valid_at)

        # Explicit disputed/false assertions remain visible beside the accepted
        # fact.  Sequentially superseded claims, plans, and failed actions are
        # history/epistemic records rather than contradictions.
        all_claims = [claim for event in visible for claim in event.claims]
        superseded_ids = {
            superseded
            for claim_id in applied_claims
            for claim in (claims_by_id[claim_id],)
            for superseded in claim.supersedes_claim_ids
        }
        for claim in all_claims:
            if not self._claim_valid_at(claim, valid_at):
                continue
            active = cells.get(claim.key)
            if active is None or active.source_claim_id == claim.claim_id:
                continue
            if claim.claim_id in superseded_ids:
                continue
            if claim.basis in {
                EvidenceBasis.PROPOSED,
                EvidenceBasis.PLANNED,
                EvidenceBasis.PREDICTED,
                EvidenceBasis.UNKNOWN,
            }:
                continue
            if claim.truth not in {
                TruthStatus.DISPUTED,
                TruthStatus.FALSE,
                TruthStatus.UNKNOWN,
            }:
                continue
            claim_ids = tuple(sorted((active.source_claim_id, claim.claim_id)))
            if any(item.key == claim.key and item.claim_ids == claim_ids for item in contradictions):
                continue
            active_claim = claims_by_id[active.source_claim_id]
            overlap_from = max(active.valid_from, claim.valid_from)
            overlap_to = self._overlap_to((active_claim, claim))
            if overlap_to is not None and overlap_from >= overlap_to:
                continue
            contradictions.append(
                Contradiction(
                    contradiction_id="conflict_" + sha256_text(
                        canonical_json([claim.key.text, list(claim_ids)])
                    )[:16],
                    key=claim.key,
                    claim_ids=claim_ids,
                    overlap_from=overlap_from,
                    resolution="authority",
                    resolved_by_claim_id=active.source_claim_id,
                    overlap_to=overlap_to,
                )
            )

        return StateSnapshot(
            valid_at=valid_at,
            known_at=known,
            cells=tuple(
                sorted(
                    (cell for key, cell in cells.items() if key not in ambiguous),
                    key=lambda item: item.key,
                )
            ),
            history=tuple(history),
            contradictions=tuple(
                sorted(
                    (
                        item
                        for item in contradictions
                        if not (
                            len(item.claim_ids) == 1
                            and item.resolution == "expired"
                        )
                    ),
                    key=lambda item: item.contradiction_id,
                )
            ),
            ambiguous_keys=tuple(sorted(ambiguous)),
            decisions=tuple(decisions[event.event_id] for event in visible),
            noncanonical=noncanonical or bool(excluded),
        )

    def counterfactual(self, *, valid_at: int, exclude_event_ids: Iterable[str]) -> StateSnapshot:
        return self.replay(
            valid_at=valid_at,
            known_at=self.head_record_seq,
            exclude_event_ids=exclude_event_ids,
            noncanonical=True,
        )

    def temporal_status(
        self,
        claim_id: str,
        *,
        valid_at: int,
        known_at: int | None = None,
    ) -> TemporalStatus:
        """Derive a claim's temporal view; callers cannot author ``current``."""

        claim = self._claims.get(claim_id)
        if claim is None:
            return TemporalStatus.UNKNOWN
        known = self.head_record_seq if known_at is None else known_at
        if claim.recorded_at > known or claim.valid_from > valid_at:
            return TemporalStatus.FUTURE
        snapshot = self.replay(valid_at=valid_at, known_at=known)
        applied_event_ids = {
            item.event_id for item in snapshot.decisions if item.admitted
        }
        effective_superseders = (
            event_claims[effect.claim_id]
            for event in self._events.values()
            if event.event_id in applied_event_ids
            for event_claims in (
                {item.claim_id: item for item in event.claims},
            )
            for effect in event.effects
        )
        if any(
            claim_id in superseder.supersedes_claim_ids
            for superseder in effective_superseders
        ):
            return TemporalStatus.SUPERSEDED
        # A successful guarded state transition deterministically replaces the
        # active source claim even when the author did not repeat that lineage
        # in ``supersedes_claim_ids``.  Replay records that derived lineage so
        # the old and new claims cannot both appear CURRENT.
        if any(
            transition.replaced_claim_id == claim_id
            for transition in snapshot.history
        ):
            return TemporalStatus.SUPERSEDED
        if claim.valid_to is not None and claim.valid_to <= valid_at:
            return TemporalStatus.HISTORICAL
        return TemporalStatus.CURRENT
