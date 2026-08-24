"""Immutable representation, selective decompression, solver, and ablation."""

from __future__ import annotations

import itertools
import json
from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Any, Iterable, Mapping, Protocol, Sequence

from hive_reference.model import (
    DecisionStatus,
    EdgeKind,
    EffectOp,
    EventLedger,
    EvidenceRef,
    FactKey,
    RequirementOp,
    canonical_json,
    sha256_text,
)


class RepresentationInvariantError(ValueError):
    """A representation or reconstruction violated its closed-world contract."""


class CompressionKind(str, Enum):
    STRUCTURAL = "structural"
    CAUSAL = "causal"
    CONCEPTUAL = "conceptual"
    TEMPORAL = "temporal"
    PROCEDURAL = "procedural"
    FAILURE = "failure"


class ComponentKind(str, Enum):
    ATOM = "atom"
    TRANSITION = "transition"
    CAUSAL_RULE = "causal_rule"
    CONCEPT = "concept"
    PROCEDURE = "procedure"
    CONSTRAINT = "constraint"


class OriginKind(str, Enum):
    HANDCRAFTED = "handcrafted"
    DETERMINISTIC_HEURISTIC = "deterministic_heuristic"
    MODEL_PROPOSED = "model_proposed"
    DATA_LEARNED = "data_learned"
    AUTOMATICALLY_DISCOVERED = "automatically_discovered"


class ValidationStatus(str, Enum):
    UNTESTED = "untested"
    SCHEMA_VALIDATED = "schema_validated"
    DETERMINISTICALLY_VALIDATED = "deterministically_validated"
    EMPIRICALLY_VALIDATED = "empirically_validated"
    TRANSFER_VALIDATED = "transfer_validated"
    REJECTED = "rejected"


class TaskKind(str, Enum):
    VALUE_AT = "value_at"
    CHANGES = "changes"
    CAN_APPLY = "can_apply"
    REJECT_PROMOTION = "reject_promotion"


CONTAINMENT_OWNER_OPERATOR = "inherit_owner_through_containment_v1"


class SolveStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class OriginManifest:
    origin: OriginKind
    discovery_automatic: bool
    training_ids: tuple[str, ...] = ()
    human_semantic_dependencies: tuple[str, ...] = ()
    oracle_assisted: bool = False


@dataclass(frozen=True)
class ConceptDefinition:
    """Bidirectional abstraction proposal; validation remains separate from origin."""

    concept_id: str
    invariant: str
    scope: tuple[str, ...]
    known_instances: tuple[str, ...]
    counterexamples: tuple[str, ...]
    prerequisites: tuple[str, ...]
    causal_implications: tuple[str, ...]
    reconstruction_rules: tuple[str, ...]
    uncertainty: float
    evidence: tuple[EvidenceRef, ...]
    origin: OriginManifest

    def __post_init__(self) -> None:
        if not self.concept_id or not self.invariant or not self.scope:
            raise RepresentationInvariantError("concepts require ID, invariant, and scope")
        if not self.reconstruction_rules or not self.evidence:
            raise RepresentationInvariantError("concepts require reconstruction rules and evidence")
        if not 0.0 <= self.uncertainty <= 1.0:
            raise RepresentationInvariantError("concept uncertainty must be in [0, 1]")

    def to_component(
        self,
        *,
        keys: Sequence[FactKey],
        source_event_ids: Sequence[str],
        preserved_distinctions: Sequence[str],
        available_from_record: int,
        discarded_distinctions: Sequence[str] = (),
    ) -> "RepresentationComponent":
        return RepresentationComponent(
            component_id=f"component:concept:{self.concept_id}",
            component_kind=ComponentKind.CONCEPT,
            compression_kind=CompressionKind.CONCEPTUAL,
            keys=tuple(keys),
            payload_json=canonical_json(asdict(self)),
            source_event_ids=tuple(source_event_ids),
            source_claim_ids=(),
            preserved_distinctions=tuple(preserved_distinctions),
            discarded_distinctions=tuple(discarded_distinctions),
            unmodeled_distinctions=("outside_concept_scope",),
            dependency_component_ids=(),
            evidence=self.evidence,
            applicable_task_kinds=tuple(TaskKind),
            confidence=1.0 - self.uncertainty,
            known_failure_modes=("counterexample_or_scope_loss",),
            origin=self.origin,
            available_from_record=available_from_record,
        )


@dataclass(frozen=True)
class CostBreakdown:
    packet_bytes: int = 0
    schema_bytes: int = 0
    ontology_bytes: int = 0
    code_config_bytes: int = 0
    lookup_bytes: int = 0
    preprocessing_steps: int = 0
    preprocessing_model_calls: int = 0
    solver_model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    human_authored_domain_bytes: int = 0

    def __post_init__(self) -> None:
        if any(value < 0 for value in asdict(self).values()):
            raise RepresentationInvariantError("representation costs cannot be negative")

    @property
    def cold_effective_bytes(self) -> int:
        return (
            self.packet_bytes
            + self.schema_bytes
            + self.ontology_bytes
            + self.code_config_bytes
            + self.lookup_bytes
        )


@dataclass(frozen=True)
class RepresentationComponent:
    component_id: str
    component_kind: ComponentKind
    compression_kind: CompressionKind
    keys: tuple[FactKey, ...]
    payload_json: str
    source_event_ids: tuple[str, ...]
    source_claim_ids: tuple[str, ...]
    preserved_distinctions: tuple[str, ...]
    discarded_distinctions: tuple[str, ...]
    unmodeled_distinctions: tuple[str, ...]
    dependency_component_ids: tuple[str, ...]
    evidence: tuple[EvidenceRef, ...]
    applicable_task_kinds: tuple[TaskKind, ...]
    confidence: float
    known_failure_modes: tuple[str, ...]
    origin: OriginManifest
    available_from_record: int

    def __post_init__(self) -> None:
        if not self.component_id or not self.source_event_ids or not self.evidence:
            raise RepresentationInvariantError("components require ID, source events, and evidence")
        if not 0.0 <= self.confidence <= 1.0:
            raise RepresentationInvariantError("component confidence must be between zero and one")
        if self.available_from_record < 0:
            raise RepresentationInvariantError("component availability must be nonnegative")
        try:
            payload = json.loads(self.payload_json)
        except json.JSONDecodeError as exc:
            raise RepresentationInvariantError("component payload is not JSON") from exc
        if canonical_json(payload) != self.payload_json:
            raise RepresentationInvariantError("component payload must use canonical JSON")
        preserved = set(self.preserved_distinctions)
        discarded = set(self.discarded_distinctions)
        if preserved & discarded:
            raise RepresentationInvariantError("preserved and discarded distinctions must be disjoint")
        if self.component_id in self.dependency_component_ids:
            raise RepresentationInvariantError("components cannot depend on themselves")

    @property
    def content_hash(self) -> str:
        return sha256_text(canonical_json(asdict(self)))

    def payload(self) -> Mapping[str, Any]:
        return json.loads(self.payload_json)


@dataclass(frozen=True)
class RepresentationVersion:
    representation_id: str
    family_id: str
    version: int
    parent_id: str | None
    source_ledger_hash: str
    codec_id: str
    schema_id: str
    components: tuple[RepresentationComponent, ...]
    preservation_scope: tuple[str, ...]
    known_failure_modes: tuple[str, ...]
    origin: OriginManifest
    validation_status: ValidationStatus
    cost: CostBreakdown

    def __post_init__(self) -> None:
        if not self.representation_id or not self.family_id or self.version < 1:
            raise RepresentationInvariantError("representations require IDs and positive version")
        component_ids = [component.component_id for component in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise RepresentationInvariantError("component IDs must be unique")
        known = set(component_ids)
        for component in self.components:
            missing = set(component.dependency_component_ids) - known
            if missing:
                raise RepresentationInvariantError(
                    f"component {component.component_id} has missing dependencies {sorted(missing)}"
                )
        self._validate_dependency_dag()

    def _validate_dependency_dag(self) -> None:
        by_id = {item.component_id: item for item in self.components}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(component_id: str) -> None:
            if component_id in visited:
                return
            if component_id in visiting:
                raise RepresentationInvariantError("component dependency cycle")
            visiting.add(component_id)
            for dependency in by_id[component_id].dependency_component_ids:
                visit(dependency)
            visiting.remove(component_id)
            visited.add(component_id)

        for component_id in by_id:
            visit(component_id)

    @property
    def content_hash(self) -> str:
        return sha256_text(canonical_json(self.to_mapping()))

    def to_mapping(self) -> dict[str, Any]:
        return {
            "codec_id": self.codec_id,
            "components": [asdict(item) for item in self.components],
            "cost": asdict(self.cost),
            "family_id": self.family_id,
            "known_failure_modes": list(self.known_failure_modes),
            "origin": asdict(self.origin),
            "parent_id": self.parent_id,
            "preservation_scope": list(self.preservation_scope),
            "representation_id": self.representation_id,
            "schema_id": self.schema_id,
            "source_ledger_hash": self.source_ledger_hash,
            "validation_status": self.validation_status.value,
            "version": self.version,
        }

    def subset(self, component_ids: Iterable[str], *, representation_id: str | None = None) -> "RepresentationVersion":
        chosen = frozenset(component_ids)
        components = tuple(item for item in self.components if item.component_id in chosen)
        component_bytes = len(canonical_json([asdict(item) for item in components]).encode("utf-8"))
        return replace(
            self,
            representation_id=representation_id or f"{self.representation_id}:subset:{sha256_text(canonical_json(sorted(chosen)))[:10]}",
            components=components,
            cost=replace(self.cost, packet_bytes=component_bytes),
        )


@dataclass(frozen=True)
class TaskQuery:
    query_id: str
    kind: TaskKind
    keys: tuple[FactKey, ...]
    valid_at: int
    known_at: int
    parameters_json: str = "{}"

    def __post_init__(self) -> None:
        if not self.query_id or self.valid_at < 0 or self.known_at < 0:
            raise RepresentationInvariantError("queries require ID and nonnegative cutoffs")
        try:
            parameters = json.loads(self.parameters_json)
        except json.JSONDecodeError as exc:
            raise RepresentationInvariantError("query parameters are not JSON") from exc
        if canonical_json(parameters) != self.parameters_json:
            raise RepresentationInvariantError("query parameters must use canonical JSON")

    def parameters(self) -> Mapping[str, Any]:
        return json.loads(self.parameters_json)


@dataclass(frozen=True)
class DecompressedView:
    query_id: str
    selected_components: tuple[RepresentationComponent, ...]
    missing_dependencies: tuple[str, ...]
    completeness: SolveStatus
    supporting_bytes_read: int

    @property
    def selected_component_ids(self) -> tuple[str, ...]:
        return tuple(component.component_id for component in self.selected_components)


@dataclass(frozen=True)
class SolverOutcome:
    query_id: str
    status: SolveStatus
    answer: Any
    used_component_ids: tuple[str, ...]
    evidence_observation_ids: tuple[str, ...]
    failure_reason: str | None = None


class Solver(Protocol):
    solver_id: str

    def solve(self, view: DecompressedView, query: TaskQuery) -> SolverOutcome: ...


class ReferenceCompressor:
    """Handcrafted structural codec over the generic ledger.

    The codec intentionally keeps event semantics supplied by humans/code.  It
    is useful for reference plumbing and must not be described as learned.
    """

    codec_id = "hive-reference-structural-v1"
    schema_id = "hive-reference-event-component-v1"

    @staticmethod
    def _key_mapping(key: FactKey) -> dict[str, str]:
        return {"predicate": key.predicate, "subject": key.subject}

    @staticmethod
    def _validate_extra_component_lineage(
        ledger: EventLedger,
        components: Sequence[RepresentationComponent],
    ) -> None:
        """Validate asserted lineage against the immutable source ledger.

        Extra components are proposals layered on top of canonical events.  A
        component cannot make itself look older than any event, claim, or
        observation it cites, and a copied ID with a forged source identity or
        hash is not evidence.
        """

        events_by_id = {event.event_id: event for event in ledger.events}
        claims_by_id = {
            claim.claim_id: claim
            for event in ledger.events
            for claim in event.claims
        }
        observations_by_id = {
            observation.observation_id: observation
            for observation in ledger.observations
        }
        for component in components:
            availability: list[int] = []
            cited_evidence: set[EvidenceRef] = set()
            for event_id in component.source_event_ids:
                event = events_by_id.get(event_id)
                if event is None:
                    raise RepresentationInvariantError(
                        f"component {component.component_id} cites unknown source event {event_id}"
                    )
                availability.append(event.recorded_at)
                cited_evidence.update(event.evidence)
            for claim_id in component.source_claim_ids:
                claim = claims_by_id.get(claim_id)
                if claim is None:
                    raise RepresentationInvariantError(
                        f"component {component.component_id} cites unknown source claim {claim_id}"
                    )
                availability.append(claim.recorded_at)
                cited_evidence.update(claim.evidence)
            for evidence in component.evidence:
                observation = observations_by_id.get(evidence.observation_id)
                if observation is None:
                    raise RepresentationInvariantError(
                        f"component {component.component_id} cites unknown evidence observation "
                        f"{evidence.observation_id}"
                    )
                if (
                    evidence.source_id != observation.source_id
                    or evidence.source_sha256 != observation.source_sha256
                ):
                    raise RepresentationInvariantError(
                        f"component {component.component_id} evidence source identity or hash "
                        "does not match the ledger"
                    )
                if evidence not in cited_evidence:
                    raise RepresentationInvariantError(
                        f"component {component.component_id} evidence is not attached to a cited "
                        "source event or claim"
                    )
                availability.append(observation.recorded_at)
            latest_source_record = max(availability)
            if component.available_from_record < latest_source_record:
                raise RepresentationInvariantError(
                    f"component {component.component_id} is available before its latest cited "
                    f"source record {latest_source_record}"
                )

    def compress(
        self,
        ledger: EventLedger,
        *,
        representation_id: str,
        version: int = 1,
        parent_id: str | None = None,
        extra_components: Sequence[RepresentationComponent] = (),
        schema_bytes: int = 0,
        ontology_bytes: int = 0,
        code_config_bytes: int = 0,
        human_authored_domain_bytes: int = 0,
    ) -> RepresentationVersion:
        components: list[RepresentationComponent] = []
        event_component_ids = {event.event_id: f"component:event:{event.event_id}" for event in ledger.events}
        claim_event_ids = {
            claim.claim_id: event.event_id
            for event in ledger.events
            for claim in event.claims
        }
        decisions = {item.event_id: item for item in ledger.decisions}
        for event in ledger.events:
            decision = decisions[event.event_id]
            claims = {claim.claim_id: claim for claim in event.claims}
            payload = {
                "decision": decision.status.value,
                "decision_reason": decision.reason,
                "effective_time": event.effective_time,
                "effects": [
                    {
                        "claim_id": effect.claim_id,
                        "expected_previous": effect.expected_previous,
                        "key": self._key_mapping(effect.key),
                        "op": effect.op.value,
                        "value": effect.value,
                        "valid_from": claims[effect.claim_id].valid_from,
                        "valid_to": claims[effect.claim_id].valid_to,
                        "depends_on_claim_ids": list(
                            claims[effect.claim_id].depends_on_claim_ids
                        ),
                        "supersedes_claim_ids": list(
                            claims[effect.claim_id].supersedes_claim_ids
                        ),
                    }
                    for effect in event.effects
                ],
                "event_id": event.event_id,
                "event_type": event.event_type,
                "causal_parents": list(event.causal_parents),
                "hard_dependencies": list(event.hard_dependencies),
                "input_keys": [
                    self._key_mapping(key)
                    for key in sorted(
                        {requirement.key for requirement in event.requirements}
                        | {
                            effect.key
                            for effect in event.effects
                            if effect.op in {EffectOp.DELETE, EffectOp.INCREMENT}
                            or effect.expected_previous is not None
                        }
                    )
                ],
                "recorded_at": event.recorded_at,
                "requirements": [
                    {
                        "key": self._key_mapping(requirement.key),
                        "op": requirement.op.value,
                        "value": requirement.value,
                    }
                    for requirement in event.requirements
                ],
            }
            all_keys = tuple(sorted({item.key for item in event.effects} | {item.key for item in event.requirements}))
            preservation = (
                f"authority:{event.event_id}",
                f"effective_time:{event.event_id}",
                f"record_time:{event.event_id}",
                *(f"state:{key.text}" for key in all_keys),
            )
            dependency_event_ids = set(event.hard_dependencies) | set(
                event.causal_parents
            )
            dependency_event_ids.update(
                claim_event_ids[claim_dependency]
                for claim in event.claims
                for claim_dependency in claim.depends_on_claim_ids
            )
            components.append(
                RepresentationComponent(
                    component_id=event_component_ids[event.event_id],
                    component_kind=(
                        ComponentKind.TRANSITION
                        if decision.status is DecisionStatus.ADMIT
                        else ComponentKind.CONSTRAINT
                    ),
                    compression_kind=(
                        CompressionKind.STRUCTURAL
                        if decision.status is DecisionStatus.ADMIT
                        else CompressionKind.FAILURE
                    ),
                    keys=all_keys,
                    payload_json=canonical_json(payload),
                    source_event_ids=(event.event_id,),
                    source_claim_ids=tuple(claim.claim_id for claim in event.claims),
                    preserved_distinctions=tuple(preservation),
                    discarded_distinctions=("observation_surface_form", "actor_display_name"),
                    unmodeled_distinctions=("raw_untyped_semantics",),
                    dependency_component_ids=tuple(
                        sorted(
                            event_component_ids[item]
                            for item in dependency_event_ids
                        )
                    ),
                    evidence=event.evidence,
                    applicable_task_kinds=tuple(TaskKind),
                    confidence=1.0,
                    known_failure_modes=("requires_human_typed_event_semantics",),
                    origin=OriginManifest(
                        OriginKind.HANDCRAFTED,
                        discovery_automatic=False,
                        human_semantic_dependencies=(self.schema_id,),
                    ),
                    available_from_record=event.recorded_at,
                )
            )
        self._validate_extra_component_lineage(ledger, extra_components)
        components.extend(extra_components)
        ordered = tuple(sorted(components, key=lambda item: item.component_id))
        packet_bytes = len(canonical_json([asdict(item) for item in ordered]).encode("utf-8"))
        return RepresentationVersion(
            representation_id=representation_id,
            family_id="hive-reference-structural",
            version=version,
            parent_id=parent_id,
            source_ledger_hash=ledger.digest,
            codec_id=self.codec_id,
            schema_id=self.schema_id,
            components=ordered,
            preservation_scope=(
                "typed_state_effects",
                "preconditions",
                "event_and_record_time",
                "authority_decision",
                "hard_dependencies",
                "causal_parents",
                "claim_dependencies",
                "claim_validity_and_supersession",
                "source_lineage",
            ),
            known_failure_modes=(
                "does_not_discover_event_semantics",
                "does_not_encode_unmodeled_raw_meaning",
            ),
            origin=OriginManifest(
                OriginKind.HANDCRAFTED,
                discovery_automatic=False,
                human_semantic_dependencies=(self.schema_id, self.codec_id),
            ),
            validation_status=ValidationStatus.SCHEMA_VALIDATED,
            cost=CostBreakdown(
                packet_bytes=packet_bytes,
                schema_bytes=schema_bytes,
                ontology_bytes=ontology_bytes,
                code_config_bytes=code_config_bytes,
                preprocessing_steps=len(ledger.events),
                human_authored_domain_bytes=human_authored_domain_bytes,
            ),
        )


class SelectiveDecompressor:
    """Closed decompressor: it can read packet components and nothing else."""

    def decompress(self, representation: RepresentationVersion, query: TaskQuery) -> DecompressedView:
        by_id = {
            item.component_id: item
            for item in representation.components
            if item.available_from_record <= query.known_at
        }
        event_id = str(query.parameters().get("event_id", ""))
        selected = {
            item.component_id
            for item in by_id.values()
            if query.kind in item.applicable_task_kinds
            and (
                bool(set(item.keys) & set(query.keys))
                or event_id in item.source_event_ids
                or (
                    item.component_kind is ComponentKind.CAUSAL_RULE
                    and bool(set(item.keys) & set(query.keys))
                )
            )
        }
        missing: set[str] = set()
        producers_by_key: dict[FactKey, set[str]] = {}
        for component in by_id.values():
            if component.component_kind not in {
                ComponentKind.TRANSITION,
                ComponentKind.CONSTRAINT,
            }:
                continue
            for effect in component.payload().get("effects", ()):
                key = FactKey(
                    str(effect["key"]["subject"]),
                    str(effect["key"]["predicate"]),
                )
                producers_by_key.setdefault(key, set()).add(component.component_id)
        pending = list(selected)
        while pending:
            current = pending.pop()
            component = by_id.get(current)
            if component is None:
                missing.add(current)
                continue
            for dependency in component.dependency_component_ids:
                if dependency not in by_id:
                    missing.add(dependency)
                elif dependency not in selected:
                    selected.add(dependency)
                    pending.append(dependency)
            if component.component_kind in {
                ComponentKind.TRANSITION,
                ComponentKind.CONSTRAINT,
            }:
                for item in component.payload().get("input_keys", ()):
                    key = FactKey(str(item["subject"]), str(item["predicate"]))
                    for producer_id in sorted(producers_by_key.get(key, ())):
                        if producer_id not in selected:
                            selected.add(producer_id)
                            pending.append(producer_id)
        components = tuple(sorted((by_id[item] for item in selected if item in by_id), key=lambda item: item.component_id))
        lineage_missing = [item.component_id for item in components if not item.evidence]
        missing.update(lineage_missing)
        # Count the complete representation material exposed to the solver,
        # not merely the compact payload strings.  Provenance, dependencies,
        # validity metadata, and the schema-bearing component envelope are
        # part of the supplied state cost.
        supporting_bytes = len(canonical_json([asdict(item) for item in components]).encode("utf-8"))
        return DecompressedView(
            query_id=query.query_id,
            selected_components=components,
            missing_dependencies=tuple(sorted(missing)),
            completeness=SolveStatus.COMPLETE if selected and not missing else SolveStatus.INCOMPLETE,
            supporting_bytes_read=supporting_bytes,
        )


class DeterministicReferenceSolver:
    solver_id = "hive-deterministic-reference-solver-v1"

    @staticmethod
    def _key(payload: Mapping[str, str]) -> FactKey:
        return FactKey(str(payload["subject"]), str(payload["predicate"]))

    def _events(
        self,
        view: DecompressedView,
        *,
        known_at: int | None = None,
    ) -> list[Mapping[str, Any]]:
        events = [
            item.payload()
            for item in view.selected_components
            if item.component_kind in {ComponentKind.TRANSITION, ComponentKind.CONSTRAINT}
            and item.payload().get("event_id")
            and (known_at is None or int(item.payload()["recorded_at"]) <= known_at)
        ]
        return sorted(events, key=lambda item: (int(item["effective_time"]), int(item["recorded_at"]), str(item["event_id"])))

    @staticmethod
    def _event_reaches(
        events_by_id: Mapping[str, Mapping[str, Any]],
        start: str,
        target: str,
    ) -> bool:
        pending = [start]
        seen: set[str] = set()
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            event = events_by_id.get(current)
            if event is not None:
                pending.extend(str(item) for item in event.get("hard_dependencies", ()))
                pending.extend(str(item) for item in event.get("causal_parents", ()))
        return False

    @staticmethod
    def _requirement_met(state: Mapping[FactKey, Any], item: Mapping[str, Any]) -> bool:
        key = FactKey(str(item["key"]["subject"]), str(item["key"]["predicate"]))
        op = RequirementOp(str(item["op"]))
        if op is RequirementOp.EXISTS:
            return key in state
        if op is RequirementOp.ABSENT:
            return key not in state
        if op is RequirementOp.EQ:
            return state.get(key) == item.get("value")
        if op is RequirementOp.GTE:
            value = state.get(key)
            expected = item.get("value")
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and isinstance(expected, (int, float))
                and value >= expected
            )
        return False

    def _state_at(
        self,
        view: DecompressedView,
        at_time: int,
        *,
        known_at: int,
        exclude_event_id: str | None = None,
    ) -> tuple[dict[FactKey, Any], set[str]]:
        events = [
            event
            for event in self._events(view, known_at=known_at)
            if int(event["effective_time"]) <= at_time
            and event["event_id"] != exclude_event_id
        ]
        events_by_id = {str(event["event_id"]): event for event in events}

        # Match EventLedger's refusal to resolve mutually unordered,
        # equal-effective-time authoritative writes by record order or ID.
        conflict_events: set[str] = set()
        writes_by_time_key: dict[
            tuple[int, FactKey], list[tuple[Mapping[str, Any], Mapping[str, Any]]]
        ] = {}
        for event in events:
            if event["decision"] != DecisionStatus.ADMIT.value:
                continue
            for effect in event["effects"]:
                if effect["op"] == EffectOp.SET.value:
                    key = self._key(effect["key"])
                    writes_by_time_key.setdefault(
                        (int(event["effective_time"]), key), []
                    ).append((event, effect))
        for writes in writes_by_time_key.values():
            if len({canonical_json(effect.get("value")) for _, effect in writes}) <= 1:
                continue
            unordered = any(
                not self._event_reaches(
                    events_by_id, str(left["event_id"]), str(right["event_id"])
                )
                and not self._event_reaches(
                    events_by_id, str(right["event_id"]), str(left["event_id"])
                )
                and str(left_effect["claim_id"])
                not in {
                    str(item)
                    for item in right_effect.get("supersedes_claim_ids", ())
                }
                and str(right_effect["claim_id"])
                not in {
                    str(item)
                    for item in left_effect.get("supersedes_claim_ids", ())
                }
                for index, (left, left_effect) in enumerate(writes)
                for right, right_effect in writes[index + 1 :]
            )
            if unordered:
                conflict_events.update(str(event["event_id"]) for event, _ in writes)

        # The cell envelope is internal to deterministic replay.  Only values
        # are returned to a solver, but claim lineage and validity are retained
        # long enough to enforce supersession and temporal prerequisites.
        cells: dict[FactKey, dict[str, Any]] = {}
        applied: set[str] = set()
        applied_claims: set[str] = set()
        current_time = -1
        for event in events:
            event_time = int(event["effective_time"])
            if event_time != current_time:
                current_time = event_time
                for key, cell in tuple(cells.items()):
                    valid_to = cell.get("valid_to")
                    if valid_to is not None and int(valid_to) <= current_time:
                        del cells[key]

            event_id = str(event["event_id"])
            if event_id in conflict_events:
                for effect in event["effects"]:
                    cells.pop(self._key(effect["key"]), None)
                continue
            if event["decision"] != DecisionStatus.ADMIT.value:
                continue
            if any(dependency not in applied for dependency in event.get("hard_dependencies", [])):
                continue
            if any(
                str(dependency) not in applied_claims
                for effect in event["effects"]
                for dependency in effect.get("depends_on_claim_ids", ())
            ):
                continue
            values = {key: cell["value"] for key, cell in cells.items()}
            if not all(self._requirement_met(values, item) for item in event["requirements"]):
                continue

            trial = {key: dict(cell) for key, cell in cells.items()}
            rejection = False
            for effect in event["effects"]:
                key = self._key(effect["key"])
                existing = trial.get(key)
                current = None if existing is None else existing["value"]
                expected = effect.get("expected_previous")
                op = EffectOp(str(effect["op"]))
                if op is EffectOp.SET:
                    if expected is not None and (
                        existing is None or current != expected
                    ):
                        rejection = True
                        break
                    if existing is not None and current != effect.get("value"):
                        licensed = (
                            expected == current
                            or str(existing["source_claim_id"])
                            in {
                                str(item)
                                for item in effect.get("supersedes_claim_ids", ())
                            }
                        )
                        if not licensed:
                            rejection = True
                            break
                    trial[key] = {
                        "source_claim_id": str(effect["claim_id"]),
                        "valid_to": effect.get("valid_to"),
                        "value": effect.get("value"),
                    }
                elif op is EffectOp.DELETE:
                    if expected is not None and (
                        existing is None or current != expected
                    ):
                        rejection = True
                        break
                    trial.pop(key, None)
                elif op is EffectOp.INCREMENT:
                    before = 0 if existing is None else current
                    amount = effect.get("value")
                    if (
                        not isinstance(before, (int, float))
                        or isinstance(before, bool)
                        or not isinstance(amount, (int, float))
                        or isinstance(amount, bool)
                    ):
                        rejection = True
                        break
                    trial[key] = {
                        "source_claim_id": str(effect["claim_id"]),
                        "valid_to": effect.get("valid_to"),
                        "value": before + amount,
                    }
            if rejection:
                continue
            cells = trial
            applied.add(event_id)
            applied_claims.update(str(effect["claim_id"]) for effect in event["effects"])

        for key, cell in tuple(cells.items()):
            valid_to = cell.get("valid_to")
            if valid_to is not None and int(valid_to) <= at_time:
                del cells[key]
        return {key: cell["value"] for key, cell in cells.items()}, applied

    @staticmethod
    def _effective_owner(state: Mapping[FactKey, Any], item: str) -> Any:
        seen: set[str] = set()
        current = item
        while current not in seen:
            seen.add(current)
            owner = state.get(FactKey(current, "owner"))
            if owner is not None:
                return owner
            parent = state.get(FactKey(current, "inside"))
            if parent is None:
                return None
            current = str(parent)
        return None

    def solve(self, view: DecompressedView, query: TaskQuery) -> SolverOutcome:
        evidence = tuple(
            sorted({ref.observation_id for item in view.selected_components for ref in item.evidence})
        )
        if view.completeness is not SolveStatus.COMPLETE:
            return SolverOutcome(
                query.query_id,
                SolveStatus.INCOMPLETE,
                None,
                view.selected_component_ids,
                evidence,
                "missing representation dependency or no relevant component",
            )
        parameters = query.parameters()
        state, _ = self._state_at(view, query.valid_at, known_at=query.known_at)
        if query.kind is TaskKind.VALUE_AT:
            if parameters.get("derive") == "owner_through_containment":
                required_rule = str(parameters.get("rule_id", "containment_owner_v1"))
                required_operator = str(
                    parameters.get("rule_operator", CONTAINMENT_OWNER_OPERATOR)
                )
                available_rules = {
                    (
                        str(component.payload().get("rule_id")),
                        str(component.payload().get("operator")),
                    )
                    for component in view.selected_components
                    if component.component_kind is ComponentKind.CAUSAL_RULE
                }
                if (
                    required_operator != CONTAINMENT_OWNER_OPERATOR
                    or (required_rule, required_operator) not in available_rules
                ):
                    return SolverOutcome(
                        query.query_id,
                        SolveStatus.INCOMPLETE,
                        None,
                        view.selected_component_ids,
                        evidence,
                        "required executable causal operator is absent or unsupported",
                    )
                answer = self._effective_owner(state, str(parameters["item"]))
            elif query.keys:
                answer = state.get(query.keys[0])
            else:
                answer = None
        elif query.kind is TaskKind.CHANGES:
            start = int(parameters["from_time"])
            finish = int(parameters["to_time"])
            before, _ = self._state_at(view, start, known_at=query.known_at)
            after, _ = self._state_at(view, finish, known_at=query.known_at)
            key = query.keys[0]
            answer = {"before": before.get(key), "after": after.get(key)}
        elif query.kind is TaskKind.CAN_APPLY:
            target_id = str(parameters["event_id"])
            target = next(
                (
                    item
                    for item in self._events(view, known_at=query.known_at)
                    if item["event_id"] == target_id
                ),
                None,
            )
            if target is None:
                return SolverOutcome(
                    query.query_id,
                    SolveStatus.INCOMPLETE,
                    None,
                    view.selected_component_ids,
                    evidence,
                    "target event is absent from the reconstruction",
                )
            pre_state, _ = self._state_at(
                view,
                query.valid_at,
                known_at=query.known_at,
                exclude_event_id=target_id,
            )
            answer = all(self._requirement_met(pre_state, item) for item in target["requirements"])
        elif query.kind is TaskKind.REJECT_PROMOTION:
            target_id = str(parameters["event_id"])
            target = next(
                (
                    item
                    for item in self._events(view, known_at=query.known_at)
                    if item["event_id"] == target_id
                ),
                None,
            )
            if target is None:
                return SolverOutcome(
                    query.query_id,
                    SolveStatus.INCOMPLETE,
                    None,
                    view.selected_component_ids,
                    evidence,
                    "target event is absent from the reconstruction",
                )
            answer = target["decision"] != DecisionStatus.ADMIT.value
        else:  # pragma: no cover
            return SolverOutcome(
                query.query_id,
                SolveStatus.UNSUPPORTED,
                None,
                view.selected_component_ids,
                evidence,
                "unsupported task kind",
            )
        return SolverOutcome(
            query.query_id,
            SolveStatus.COMPLETE,
            answer,
            view.selected_component_ids,
            evidence,
        )


@dataclass(frozen=True)
class TaskExpectation:
    query: TaskQuery
    expected_answer: Any


@dataclass(frozen=True)
class EvaluationSummary:
    representation_id: str
    all_passed: bool
    passed: int
    total: int
    outcomes: tuple[SolverOutcome, ...]


class RepresentationEvaluator:
    def __init__(self, decompressor: SelectiveDecompressor, solver: Solver) -> None:
        self.decompressor = decompressor
        self.solver = solver

    def evaluate(
        self,
        representation: RepresentationVersion,
        tasks: Sequence[TaskExpectation],
    ) -> EvaluationSummary:
        outcomes = tuple(
            self.solver.solve(self.decompressor.decompress(representation, item.query), item.query)
            for item in tasks
        )
        passed = sum(
            outcome.status is SolveStatus.COMPLETE and outcome.answer == expectation.expected_answer
            for outcome, expectation in zip(outcomes, tasks)
        )
        return EvaluationSummary(
            representation.representation_id,
            passed == len(tasks),
            passed,
            len(tasks),
            outcomes,
        )


@dataclass(frozen=True)
class SufficiencyReport:
    representation_id: str
    status: str
    algorithm: str
    evaluated_subsets: int
    minimum_component_count: int | None
    minimal_component_sets: tuple[tuple[str, ...], ...]
    singleton_essential: tuple[str, ...]
    singleton_redundant: tuple[str, ...]


class RepresentationAblator:
    def __init__(self, evaluator: RepresentationEvaluator, *, exact_limit: int = 12) -> None:
        self.evaluator = evaluator
        self.exact_limit = exact_limit

    def minimize(
        self,
        representation: RepresentationVersion,
        tasks: Sequence[TaskExpectation],
    ) -> SufficiencyReport:
        baseline = self.evaluator.evaluate(representation, tasks)
        if not baseline.all_passed:
            return SufficiencyReport(
                representation.representation_id,
                "invalid_baseline",
                "none",
                1,
                None,
                (),
                (),
                (),
            )
        component_ids = tuple(item.component_id for item in representation.components)
        evaluated = 1
        essential: list[str] = []
        redundant: list[str] = []
        for component_id in component_ids:
            subset_ids = tuple(item for item in component_ids if item != component_id)
            try:
                trial = representation.subset(subset_ids)
                result = self.evaluator.evaluate(trial, tasks)
            except RepresentationInvariantError:
                result = None
            evaluated += 1
            (redundant if result is not None and result.all_passed else essential).append(component_id)

        if len(component_ids) <= self.exact_limit:
            minimal: list[tuple[str, ...]] = []
            minimum_count: int | None = None
            for size in range(len(component_ids) + 1):
                for chosen in itertools.combinations(component_ids, size):
                    try:
                        result = self.evaluator.evaluate(representation.subset(chosen), tasks)
                    except RepresentationInvariantError:
                        result = None
                    evaluated += 1
                    if result is not None and result.all_passed:
                        minimum_count = size
                        minimal.append(tuple(chosen))
                if minimal:
                    break
            return SufficiencyReport(
                representation.representation_id,
                "complete",
                "exact_subset_minimum",
                evaluated,
                minimum_count,
                tuple(minimal),
                tuple(sorted(essential)),
                tuple(sorted(redundant)),
            )

        working = list(component_ids)
        changed = True
        while changed:
            changed = False
            for component_id in tuple(working):
                chosen = tuple(item for item in working if item != component_id)
                try:
                    result = self.evaluator.evaluate(representation.subset(chosen), tasks)
                except RepresentationInvariantError:
                    result = None
                evaluated += 1
                if result is not None and result.all_passed:
                    working.remove(component_id)
                    changed = True
        return SufficiencyReport(
            representation.representation_id,
            "complete",
            "one_minimal_approximation",
            evaluated,
            len(working),
            (tuple(working),),
            tuple(sorted(essential)),
            tuple(sorted(redundant)),
        )


def make_causal_rule_component(
    *,
    component_id: str,
    keys: Sequence[FactKey],
    rule_id: str,
    rule: str,
    source_event_ids: Sequence[str],
    evidence: Sequence[EvidenceRef],
    available_from_record: int,
    dependencies: Sequence[str] = (),
    operator: str = CONTAINMENT_OWNER_OPERATOR,
) -> RepresentationComponent:
    """Create a human-supplied rule while preserving its honest origin label."""

    return RepresentationComponent(
        component_id=component_id,
        component_kind=ComponentKind.CAUSAL_RULE,
        compression_kind=CompressionKind.CAUSAL,
        keys=tuple(keys),
        payload_json=canonical_json(
            {"operator": operator, "rule": rule, "rule_id": rule_id}
        ),
        source_event_ids=tuple(source_event_ids),
        source_claim_ids=(),
        preserved_distinctions=(f"causal_rule:{rule_id}",),
        discarded_distinctions=(),
        unmodeled_distinctions=("causal_validity_outside_declared_scope",),
        dependency_component_ids=tuple(dependencies),
        evidence=tuple(evidence),
        applicable_task_kinds=(TaskKind.VALUE_AT,),
        confidence=1.0,
        known_failure_modes=("handcrafted_rule_not_causal_discovery",),
        origin=OriginManifest(
            OriginKind.HANDCRAFTED,
            discovery_automatic=False,
            human_semantic_dependencies=(rule_id,),
        ),
        available_from_record=available_from_record,
    )
