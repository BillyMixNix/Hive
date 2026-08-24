"""Deterministic observation, authority, event, and bitemporal-state core.

This module is intentionally domain-neutral and model-free.  Model output may be
converted into proposals by an adapter, but only ``AuthorityPolicy`` decisions
and immutable ledger records can affect a canonical state projection.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
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
    if isinstance(value, (list, tuple, set, frozenset)):
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
    DISPUTED = "disputed"
    FALSE = "false"
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
        claim_ids = {claim.claim_id for claim in self.claims}
        if len(claim_ids) != len(self.claims):
            raise ModelInvariantError("claim IDs within an event must be unique")
        if any(effect.claim_id not in claim_ids for effect in self.effects):
            raise ModelInvariantError("every state effect must cite a claim in the event")
        if any(claim.recorded_at != self.recorded_at for claim in self.claims):
            raise ModelInvariantError("event and claim record sequences must match")
        claims_by_id = {claim.claim_id: claim for claim in self.claims}
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


@dataclass(frozen=True)
class Contradiction:
    contradiction_id: str
    key: FactKey
    claim_ids: tuple[str, ...]
    overlap_from: int
    resolution: str
    resolved_by_claim_id: str | None = None


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
        for cell in self.cells:
            if cell.key == key:
                return cell.value
        return default

    def cell(self, key: FactKey) -> StateCell | None:
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
                }
                for item in self.history
            ],
            "known_at": self.known_at,
            "noncanonical": self.noncanonical,
            "valid_at": self.valid_at,
        }


class AuthorityPolicy:
    """Deterministic admission policy; confidence alone never grants authority."""

    def __init__(self, registered_inference_rules: Iterable[str] = ()) -> None:
        self.registered_inference_rules = frozenset(registered_inference_rules)
        rule_hash = sha256_text(canonical_json(sorted(self.registered_inference_rules)))[:12]
        self.policy_id = f"hive-authority-v1:{rule_hash}"

    def decide(self, event: CanonicalEvent) -> PromotionDecision:
        evidence_hash = sha256_text(canonical_json([asdict(item) for item in event.evidence]))
        if not event.effects:
            return PromotionDecision(
                event.event_id,
                DecisionStatus.REJECT,
                self.policy_id,
                "no_world_effects",
                evidence_hash,
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
        return tuple(self._decisions[event.event_id] for event in self.events)

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

    def _validate_evidence(self, evidence: Iterable[EvidenceRef]) -> None:
        for ref in evidence:
            observed = self._observations.get(ref.observation_id)
            if observed is None:
                raise ModelInvariantError(f"unknown evidence observation {ref.observation_id}")
            if ref.source_id != observed.source_id or ref.source_sha256 != observed.source_sha256:
                raise ModelInvariantError("evidence source identity or hash does not match")

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
        self._validate_evidence(event.evidence)
        for claim in event.claims:
            self._validate_evidence(claim.evidence)
            if claim.claim_id in self._claims:
                raise ModelInvariantError(f"duplicate claim ID {claim.claim_id}")
            for dependency in claim.depends_on_claim_ids:
                if dependency not in self._claims:
                    raise ModelInvariantError(f"unknown claim dependency {dependency}")
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
            if target.effective_time > event.effective_time:
                raise ModelInvariantError("events cannot causally depend on future-effective events")
            if self._has_dependency_path(dependency, event.event_id):
                raise ModelInvariantError("event dependency cycle")
        decision = self.policy.decide(event)
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
    def _requirement_met(cells: Mapping[FactKey, StateCell], requirement: Requirement) -> bool:
        cell = cells.get(requirement.key)
        if requirement.op is RequirementOp.EXISTS:
            return cell is not None
        if requirement.op is RequirementOp.ABSENT:
            return cell is None
        if requirement.op is RequirementOp.EQ:
            return cell is not None and cell.value == requirement.value
        if requirement.op is RequirementOp.GTE:
            return (
                cell is not None
                and isinstance(cell.value, (int, float))
                and not isinstance(cell.value, bool)
                and isinstance(requirement.value, (int, float))
                and cell.value >= requirement.value
            )
        raise ModelInvariantError(f"unknown requirement operator {requirement.op}")

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

        # Equal-time, mutually unordered authoritative writes are a dispute.  A
        # lexical ID or input ordering may never decide which value is true.
        conflict_events: set[str] = set()
        claims_by_id = {
            claim.claim_id: claim for event in visible for claim in event.claims
        }
        by_time_key: dict[tuple[int, FactKey], list[tuple[CanonicalEvent, StateEffect]]] = {}
        for event in visible:
            if self._decisions[event.event_id].status is not DecisionStatus.ADMIT:
                continue
            for effect in event.effects:
                if effect.op is EffectOp.SET:
                    by_time_key.setdefault((event.effective_time, effect.key), []).append((event, effect))
        for (effective_time, key), writes in by_time_key.items():
            values = {canonical_json(effect.value) for _, effect in writes}
            if len(values) <= 1:
                continue
            unordered = [
                (left, right)
                for index, (left, left_effect) in enumerate(writes)
                for right, right_effect in writes[index + 1 :]
                if not self._event_reaches(left.event_id, right.event_id)
                and not self._event_reaches(right.event_id, left.event_id)
                and left_effect.claim_id
                not in claims_by_id[right_effect.claim_id].supersedes_claim_ids
                and right_effect.claim_id
                not in claims_by_id[left_effect.claim_id].supersedes_claim_ids
            ]
            if not unordered:
                continue
            claim_ids = tuple(sorted(effect.claim_id for _, effect in writes))
            contradiction_id = "conflict_" + sha256_text(
                canonical_json([key.text, effective_time, list(claim_ids)])
            )[:16]
            contradictions.append(
                Contradiction(
                    contradiction_id=contradiction_id,
                    key=key,
                    claim_ids=claim_ids,
                    overlap_from=effective_time,
                    resolution="unresolved",
                )
            )
            ambiguous.add(key)
            conflict_events.update(event.event_id for event, _ in writes)

        current_time = -1
        for event in visible:
            if event.effective_time != current_time:
                current_time = event.effective_time
                for key, cell in tuple(cells.items()):
                    if cell.valid_to is not None and cell.valid_to <= current_time:
                        del cells[key]

            policy_decision = self._decisions[event.event_id]
            if event.event_id in conflict_events:
                for effect in event.effects:
                    cells.pop(effect.key, None)
                    ambiguous.add(effect.key)
                decisions[event.event_id] = ReplayDecision(event.event_id, False, "unresolved_contradiction")
                continue
            if policy_decision.status is not DecisionStatus.ADMIT:
                decisions[event.event_id] = ReplayDecision(event.event_id, False, policy_decision.reason)
                continue
            if any(dep in excluded or dep not in applied for dep in event.hard_dependencies):
                decisions[event.event_id] = ReplayDecision(event.event_id, False, "missing_hard_dependency")
                continue
            event_claims = {claim.claim_id: claim for claim in event.claims}
            effect_claims = [event_claims[effect.claim_id] for effect in event.effects]
            if any(
                dependency not in applied_claims
                for claim in effect_claims
                for dependency in claim.depends_on_claim_ids
            ):
                decisions[event.event_id] = ReplayDecision(event.event_id, False, "missing_claim_dependency")
                continue
            if not all(self._requirement_met(cells, item) for item in event.requirements):
                decisions[event.event_id] = ReplayDecision(event.event_id, False, "precondition_failed")
                continue

            claims = {claim.claim_id: claim for claim in event.claims}
            trial = dict(cells)
            trial_history: list[StateTransition] = []
            rejection: str | None = None
            for effect in event.effects:
                claim = claims[effect.claim_id]
                existing = trial.get(effect.key)
                if effect.op is EffectOp.SET:
                    if effect.expected_previous is not None and (
                        existing is None or existing.value != effect.expected_previous
                    ):
                        rejection = "expected_previous_mismatch"
                        break
                    if existing is not None and existing.value != effect.value:
                        licensed = (
                            effect.expected_previous == existing.value
                            or existing.source_claim_id in claim.supersedes_claim_ids
                        )
                        if not licensed:
                            rejection = "unlicensed_supersession"
                            break
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
                        )
                    )
                elif effect.op is EffectOp.DELETE:
                    if effect.expected_previous is not None and (
                        existing is None or existing.value != effect.expected_previous
                    ):
                        rejection = "expected_previous_mismatch"
                        break
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
                        )
                    )
                elif effect.op is EffectOp.INCREMENT:
                    before = 0 if existing is None else existing.value
                    if not isinstance(before, (int, float)) or isinstance(before, bool):
                        rejection = "increment_non_numeric"
                        break
                    if not isinstance(effect.value, (int, float)) or isinstance(effect.value, bool):
                        rejection = "increment_non_numeric"
                        break
                    after = before + effect.value
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
                        )
                    )
                else:  # pragma: no cover - Enum construction prevents this.
                    rejection = "unknown_effect"
                    break
            if rejection:
                decisions[event.event_id] = ReplayDecision(event.event_id, False, rejection)
                continue
            cells = trial
            history.extend(trial_history)
            applied.add(event.event_id)
            applied_claims.update(effect.claim_id for effect in event.effects)
            decisions[event.event_id] = ReplayDecision(event.event_id, True, "admitted")

        for key, cell in tuple(cells.items()):
            if cell.valid_to is not None and cell.valid_to <= valid_at:
                del cells[key]

        # Explicit disputed/false assertions remain visible beside the accepted
        # fact.  Sequentially superseded claims, plans, and failed actions are
        # history/epistemic records rather than contradictions.
        all_claims = [claim for event in visible for claim in event.claims]
        superseded_ids = {
            superseded
            for claim in all_claims
            for superseded in claim.supersedes_claim_ids
        }
        for claim in all_claims:
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
            if claim.truth not in {TruthStatus.DISPUTED, TruthStatus.FALSE}:
                continue
            claim_ids = tuple(sorted((active.source_claim_id, claim.claim_id)))
            if any(item.key == claim.key and item.claim_ids == claim_ids for item in contradictions):
                continue
            contradictions.append(
                Contradiction(
                    contradiction_id="conflict_" + sha256_text(
                        canonical_json([claim.key.text, list(claim_ids)])
                    )[:16],
                    key=claim.key,
                    claim_ids=claim_ids,
                    overlap_from=max(active.valid_from, claim.valid_from),
                    resolution="authority",
                    resolved_by_claim_id=active.source_claim_id,
                )
            )

        return StateSnapshot(
            valid_at=valid_at,
            known_at=known,
            cells=tuple(sorted(cells.values(), key=lambda item: item.key)),
            history=tuple(history),
            contradictions=tuple(sorted(contradictions, key=lambda item: item.contradiction_id)),
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
        if claim.truth is TruthStatus.FALSE:
            return TemporalStatus.FALSE
        if claim.truth is TruthStatus.DISPUTED:
            return TemporalStatus.DISPUTED
        snapshot = self.replay(valid_at=valid_at, known_at=known)
        if any(claim_id in conflict.claim_ids and conflict.resolution == "unresolved" for conflict in snapshot.contradictions):
            return TemporalStatus.DISPUTED
        cell = snapshot.cell(claim.key)
        if cell is not None and cell.source_claim_id == claim_id:
            return TemporalStatus.CURRENT
        visible_claims = [
            item
            for item in self._claims.values()
            if item.recorded_at <= known and item.valid_from <= valid_at
        ]
        if any(claim_id in item.supersedes_claim_ids for item in visible_claims):
            return TemporalStatus.SUPERSEDED
        if claim.valid_to is not None and claim.valid_to <= valid_at:
            return TemporalStatus.HISTORICAL
        return TemporalStatus.HISTORICAL
