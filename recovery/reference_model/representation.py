"""Immutable representation, selective decompression, solver, and ablation."""

from __future__ import annotations

import itertools
import json
from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Any, ClassVar, Iterable, Mapping, Protocol, Sequence

from hive_reference.model import (
    DecisionStatus,
    EdgeKind,
    EffectOp,
    EventLedger,
    EvidenceRef,
    FactKey,
    RequirementOp,
    TruthStatus,
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


def _require_exact_rep_enum(
    value: Any,
    enum_type: type[Enum],
    field_name: str,
) -> None:
    if type(value) is not enum_type:
        raise RepresentationInvariantError(
            f"{field_name} must be an exact {enum_type.__name__} member"
        )


def _is_normalized_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_configuration_hash(component: Any, field_name: str) -> str:
    """Return an explicit normalized configuration digest or fail closed."""

    digest = getattr(component, "configuration_hash", None)
    if not _is_normalized_sha256(digest):
        raise RepresentationInvariantError(
            f"{field_name} requires a normalized immutable configuration hash"
        )
    return digest


@dataclass(frozen=True)
class OriginManifest:
    origin: OriginKind
    discovery_automatic: bool
    training_ids: tuple[str, ...] = ()
    human_semantic_dependencies: tuple[str, ...] = ()
    oracle_assisted: bool = False

    def __post_init__(self) -> None:
        _require_exact_rep_enum(self.origin, OriginKind, "origin kind")


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
        self.validate_integrity()

    def validate_integrity(self) -> None:
        values = tuple(asdict(self).values())
        if any(type(value) is not int for value in values):
            raise RepresentationInvariantError(
                "representation costs must be exact nonnegative integers"
            )
        if any(value < 0 for value in values):
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
        _require_exact_rep_enum(
            self.component_kind, ComponentKind, "component kind"
        )
        _require_exact_rep_enum(
            self.compression_kind, CompressionKind, "compression kind"
        )
        if type(self.origin) is not OriginManifest:
            raise RepresentationInvariantError(
                "component origin must be an exact OriginManifest"
            )
        for task_kind in self.applicable_task_kinds:
            _require_exact_rep_enum(
                task_kind, TaskKind, "component applicable task kind"
            )
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
class SourceComponentManifestEntry:
    """Immutable identity and producer metadata for one full-source component."""

    component_id: str
    content_hash: str
    component_kind: ComponentKind
    available_from_record: int
    effective_time: int | None
    recorded_at: int | None
    keys: tuple[FactKey, ...]
    produced_keys: tuple[FactKey, ...]
    source_event_ids: tuple[str, ...]
    applicable_task_kinds: tuple[TaskKind, ...]

    def __post_init__(self) -> None:
        _require_exact_rep_enum(
            self.component_kind, ComponentKind, "manifest component kind"
        )
        for task_kind in self.applicable_task_kinds:
            _require_exact_rep_enum(
                task_kind, TaskKind, "manifest applicable task kind"
            )
        if not self.component_id:
            raise RepresentationInvariantError("manifest components require an ID")
        if (
            len(self.content_hash) != 64
            or any(character not in "0123456789abcdef" for character in self.content_hash)
        ):
            raise RepresentationInvariantError("manifest component hashes must be SHA-256 hex")
        if self.available_from_record < 0:
            raise RepresentationInvariantError("manifest availability must be nonnegative")
        if self.effective_time is not None and self.effective_time < 0:
            raise RepresentationInvariantError("manifest effective time must be nonnegative")
        if self.recorded_at is not None and self.recorded_at < 0:
            raise RepresentationInvariantError("manifest record time must be nonnegative")
        if tuple(sorted(set(self.keys))) != self.keys:
            raise RepresentationInvariantError("manifest keys must be sorted and unique")
        if tuple(sorted(set(self.produced_keys))) != self.produced_keys:
            raise RepresentationInvariantError(
                "manifest produced keys must be sorted and unique"
            )
        if len(self.source_event_ids) != len(set(self.source_event_ids)):
            raise RepresentationInvariantError("manifest source event IDs must be unique")
        if len(self.applicable_task_kinds) != len(set(self.applicable_task_kinds)):
            raise RepresentationInvariantError("manifest task kinds must be unique")
        if self.component_kind is not ComponentKind.TRANSITION and self.produced_keys:
            raise RepresentationInvariantError(
                "only admitted transition components may be state producers"
            )
        if self.component_kind in {
            ComponentKind.TRANSITION,
            ComponentKind.CONSTRAINT,
        } and (
            self.effective_time is None
            or self.recorded_at is None
            or self.available_from_record != self.recorded_at
        ):
            raise RepresentationInvariantError(
                "executable manifest entries require matching event record availability"
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "available_from_record": self.available_from_record,
            "component_id": self.component_id,
            "component_kind": self.component_kind.value,
            "content_hash": self.content_hash,
            "effective_time": self.effective_time,
            "recorded_at": self.recorded_at,
            "keys": [
                {"predicate": key.predicate, "subject": key.subject}
                for key in self.keys
            ],
            "produced_keys": [
                {"predicate": key.predicate, "subject": key.subject}
                for key in self.produced_keys
            ],
            "source_event_ids": list(self.source_event_ids),
            "applicable_task_kinds": [
                kind.value for kind in self.applicable_task_kinds
            ],
        }


@dataclass(frozen=True)
class RepresentationVersion:
    """A representation sealed to one complete canonical-source manifest.

    Directly constructed roots, compressors, and interchange protocols must
    explicitly supply ``source_component_manifest_hash``.  Registered
    descendants must retain that commitment unchanged.
    """

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
    source_component_manifest_hash: str
    source_component_manifest: tuple[SourceComponentManifestEntry, ...] = ()

    def __post_init__(self) -> None:
        if type(self.origin) is not OriginManifest:
            raise RepresentationInvariantError(
                "representation origin must be an exact OriginManifest"
            )
        _require_exact_rep_enum(
            self.validation_status,
            ValidationStatus,
            "representation validation status",
        )
        if type(self.cost) is not CostBreakdown:
            raise RepresentationInvariantError(
                "representation cost must be an exact CostBreakdown"
            )
        self.cost.validate_integrity()
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
        if self.components and not self.source_component_manifest:
            raise RepresentationInvariantError(
                "nonempty representations require an explicit trusted "
                "full-source component manifest"
            )
        manifest_ids = [item.component_id for item in self.source_component_manifest]
        if len(manifest_ids) != len(set(manifest_ids)):
            raise RepresentationInvariantError("source component manifest IDs must be unique")
        if (
            tuple(
                sorted(
                    self.source_component_manifest,
                    key=lambda item: item.component_id,
                )
            )
            != self.source_component_manifest
        ):
            raise RepresentationInvariantError("source component manifest must be ID-sorted")
        computed_manifest_hash = self.compute_source_component_manifest_hash(
            self.source_component_manifest
        )
        if not _is_normalized_sha256(self.source_component_manifest_hash):
            raise RepresentationInvariantError(
                "source component manifest requires an explicit normalized "
                "SHA-256 commitment"
            )
        if self.source_component_manifest_hash != computed_manifest_hash:
            raise RepresentationInvariantError(
                "source component manifest does not match its sealed commitment"
            )
        outside_manifest = set(component_ids) - set(manifest_ids)
        if outside_manifest:
            raise RepresentationInvariantError(
                "representation components are absent from the full-source manifest: "
                f"{sorted(outside_manifest)}"
            )
        manifest_by_id = {
            item.component_id: item for item in self.source_component_manifest
        }
        mismatched_components = tuple(
            component.component_id
            for component in self.components
            if self._manifest_entry(component)
            != manifest_by_id[component.component_id]
        )
        if mismatched_components:
            raise RepresentationInvariantError(
                "representation components do not match their trusted manifest entries: "
                f"{sorted(mismatched_components)}"
            )
        self.validate_cost_integrity()
        self._validate_dependency_dag()

    @staticmethod
    def _manifest_entry(
        component: RepresentationComponent,
    ) -> SourceComponentManifestEntry:
        effective_time: int | None = None
        recorded_at: int | None = None
        produced_keys: tuple[FactKey, ...] = ()
        if component.component_kind in {
            ComponentKind.TRANSITION,
            ComponentKind.CONSTRAINT,
        }:
            payload = component.payload()
            try:
                effective_time = int(payload["effective_time"])
                recorded_at = int(payload["recorded_at"])
                if component.component_kind is ComponentKind.TRANSITION:
                    produced_keys = tuple(
                        sorted(
                            {
                                FactKey(
                                    str(effect["key"]["subject"]),
                                    str(effect["key"]["predicate"]),
                                )
                                for effect in payload["effects"]
                            }
                        )
                    )
            except (KeyError, TypeError, ValueError) as exc:
                raise RepresentationInvariantError(
                    f"executable component {component.component_id} has malformed payload"
                ) from exc
        return SourceComponentManifestEntry(
            component_id=component.component_id,
            content_hash=component.content_hash,
            component_kind=component.component_kind,
            available_from_record=component.available_from_record,
            effective_time=effective_time,
            recorded_at=recorded_at,
            keys=tuple(sorted(set(component.keys))),
            produced_keys=produced_keys,
            source_event_ids=tuple(component.source_event_ids),
            applicable_task_kinds=tuple(component.applicable_task_kinds),
        )

    @classmethod
    def build_source_component_manifest(
        cls,
        components: Sequence[RepresentationComponent],
    ) -> tuple[SourceComponentManifestEntry, ...]:
        return tuple(
            sorted(
                (cls._manifest_entry(component) for component in components),
                key=lambda item: item.component_id,
            )
        )

    @staticmethod
    def compute_source_component_manifest_hash(
        source_component_manifest: Sequence[SourceComponentManifestEntry],
    ) -> str:
        return sha256_text(
            canonical_json(
                [item.to_mapping() for item in source_component_manifest]
            )
        )

    @classmethod
    def compute_packet_bytes(
        cls,
        components: Sequence[RepresentationComponent],
        source_component_manifest: Sequence[SourceComponentManifestEntry],
        source_component_manifest_hash: str,
    ) -> int:
        """Byte size of the canonical supplied representation envelope."""

        if not _is_normalized_sha256(source_component_manifest_hash):
            raise RepresentationInvariantError(
                "packet envelope requires an explicit normalized manifest commitment"
            )
        return len(
            canonical_json(
                {
                    "components": [asdict(item) for item in components],
                    "source_component_manifest": [
                        item.to_mapping() for item in source_component_manifest
                    ],
                    "source_component_manifest_hash": source_component_manifest_hash,
                }
            ).encode("utf-8")
        )

    @property
    def computed_packet_bytes(self) -> int:
        return self.compute_packet_bytes(
            self.components,
            self.source_component_manifest,
            self.source_component_manifest_hash,
        )

    def validate_cost_integrity(self) -> None:
        """Revalidate immutable cost records at every governance boundary."""

        if type(self.cost) is not CostBreakdown:
            raise RepresentationInvariantError(
                "representation cost must be an exact CostBreakdown"
            )
        self.cost.validate_integrity()
        if self.cost.packet_bytes != self.computed_packet_bytes:
            raise RepresentationInvariantError(
                "reported packet_bytes must equal canonical computed_packet_bytes"
            )

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
            "source_component_manifest": [
                item.to_mapping() for item in self.source_component_manifest
            ],
            "source_component_manifest_hash": self.source_component_manifest_hash,
            "source_ledger_hash": self.source_ledger_hash,
            "validation_status": self.validation_status.value,
            "version": self.version,
        }

    def subset(self, component_ids: Iterable[str], *, representation_id: str | None = None) -> "RepresentationVersion":
        chosen = frozenset(component_ids)
        unknown = chosen - {item.component_id for item in self.components}
        if unknown:
            raise RepresentationInvariantError(
                "subset requested unknown component IDs: "
                f"{sorted(unknown)}"
            )
        components = tuple(item for item in self.components if item.component_id in chosen)
        component_bytes = self.compute_packet_bytes(
            components,
            self.source_component_manifest,
            self.source_component_manifest_hash,
        )
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
        _require_exact_rep_enum(self.kind, TaskKind, "task query kind")
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

    def __post_init__(self) -> None:
        _require_exact_rep_enum(
            self.completeness, SolveStatus, "decompressed view completeness"
        )

    @property
    def selected_component_ids(self) -> tuple[str, ...]:
        return tuple(component.component_id for component in self.selected_components)


@dataclass(frozen=True, order=True, slots=True)
class RepresentationRootCommitment:
    """Externally trusted identity of one canonical representation root.

    This value is deliberately separate from ``RepresentationVersion``.  A
    packet can recompute a perfectly self-consistent manifest after deleting
    source components, so a manifest hash carried only inside that packet is
    an integrity check, not a trust anchor.  The experiment/bootstrap protocol
    must create and preserve this commitment from an independently accepted
    root before any candidate packet is evaluated.
    """

    source_ledger_hash: str
    source_component_manifest_hash: str
    family_id: str
    codec_id: str
    schema_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "source_ledger_hash",
            "family_id",
            "codec_id",
            "schema_id",
        ):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise RepresentationInvariantError(
                    f"trusted representation root requires nonempty {field_name}"
                )
        if not _is_normalized_sha256(self.source_component_manifest_hash):
            raise RepresentationInvariantError(
                "trusted representation root requires a normalized manifest hash"
            )

    @classmethod
    def from_trusted_representation(
        cls,
        representation: RepresentationVersion,
    ) -> "RepresentationRootCommitment":
        """Seal an already authenticated bootstrap root.

        Calling this method is a trust decision.  It must not be used to bless
        an untrusted candidate merely because that candidate is internally
        self-consistent.
        """

        # Reconstructing the frozen value reruns all representation invariants,
        # including manifest and packet-size integrity, in case a caller
        # retained and mutated an object alias.
        replace(representation)
        return cls(
            source_ledger_hash=representation.source_ledger_hash,
            source_component_manifest_hash=(
                representation.source_component_manifest_hash
            ),
            family_id=representation.family_id,
            codec_id=representation.codec_id,
            schema_id=representation.schema_id,
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "codec_id": self.codec_id,
            "family_id": self.family_id,
            "schema_id": self.schema_id,
            "source_component_manifest_hash": (
                self.source_component_manifest_hash
            ),
            "source_ledger_hash": self.source_ledger_hash,
        }

    def matches(self, representation: RepresentationVersion) -> bool:
        return (
            representation.source_ledger_hash == self.source_ledger_hash
            and representation.source_component_manifest_hash
            == self.source_component_manifest_hash
            and representation.family_id == self.family_id
            and representation.codec_id == self.codec_id
            and representation.schema_id == self.schema_id
        )


@dataclass(frozen=True)
class SolverOutcome:
    query_id: str
    status: SolveStatus
    answer: Any
    used_component_ids: tuple[str, ...]
    evidence_observation_ids: tuple[str, ...]
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        _require_exact_rep_enum(self.status, SolveStatus, "solver outcome status")


class ConfigurationFingerprinted(Protocol):
    """Replaceable collaborators must expose a stable configuration digest."""

    @property
    def configuration_hash(self) -> str: ...


class Decompressor(ConfigurationFingerprinted, Protocol):
    def decompress(
        self,
        representation: RepresentationVersion,
        query: TaskQuery,
    ) -> DecompressedView: ...


class Solver(ConfigurationFingerprinted, Protocol):
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
                        "epistemically_admissible": (
                            ledger.policy.claim_has_epistemic_authority(
                                claims[effect.claim_id]
                            )
                        ),
                        "expected_previous": effect.expected_previous,
                        "expected_previous_specified": (
                            effect.expected_previous_specified
                        ),
                        "increment_by": effect.increment_by,
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
                        "truth": claims[effect.claim_id].truth.value,
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
                        # Every effect reads the prior cell, including a plain
                        # SET: replay must see an earlier producer to decide
                        # whether changing its value is a licensed
                        # supersession.  Omitting plain SET keys can make a
                        # selectively reconstructed overwrite look like the
                        # first write and incorrectly admit its dependants.
                        | {effect.key for effect in event.effects}
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
        injected_executable = tuple(
            component.component_id
            for component in extra_components
            if component.component_kind
            in {ComponentKind.TRANSITION, ComponentKind.CONSTRAINT}
        )
        if injected_executable:
            raise RepresentationInvariantError(
                "extra components cannot inject executable transitions or constraints: "
                f"{sorted(injected_executable)}"
            )
        self._validate_extra_component_lineage(ledger, extra_components)
        components.extend(extra_components)
        ordered = tuple(sorted(components, key=lambda item: item.component_id))
        source_component_manifest = (
            RepresentationVersion.build_source_component_manifest(ordered)
        )
        source_component_manifest_hash = (
            RepresentationVersion.compute_source_component_manifest_hash(
                source_component_manifest
            )
        )
        packet_bytes = RepresentationVersion.compute_packet_bytes(
            ordered,
            source_component_manifest,
            source_component_manifest_hash,
        )
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
                "epistemic_unknown_vs_absence",
                "source_lineage",
                "full_source_component_manifest",
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
            source_component_manifest=source_component_manifest,
            source_component_manifest_hash=source_component_manifest_hash,
        )


@dataclass(frozen=True, slots=True)
class SelectiveDecompressor:
    """Closed decompressor bound to externally authenticated source roots."""

    decompressor_id: ClassVar[str] = "hive-selective-decompressor-v1"
    trusted_roots: tuple[RepresentationRootCommitment, ...]

    def __post_init__(self) -> None:
        if type(self.trusted_roots) is not tuple or not self.trusted_roots:
            raise RepresentationInvariantError(
                "selective decompressor requires at least one external trusted root"
            )
        if any(type(root) is not RepresentationRootCommitment for root in self.trusted_roots):
            raise RepresentationInvariantError(
                "selective decompressor roots must be exact immutable commitments"
            )
        if len(self.trusted_roots) != len(set(self.trusted_roots)):
            raise RepresentationInvariantError(
                "selective decompressor trusted roots must be unique"
            )
        if tuple(sorted(self.trusted_roots)) != self.trusted_roots:
            raise RepresentationInvariantError(
                "selective decompressor trusted roots must be sorted"
            )

    @property
    def configuration_hash(self) -> str:
        return sha256_text(
            canonical_json(
                {
                    "component": self.decompressor_id,
                    "configuration_version": 2,
                    "trusted_roots": [
                        root.to_mapping() for root in self.trusted_roots
                    ],
                }
            )
        )

    def decompress(self, representation: RepresentationVersion, query: TaskQuery) -> DecompressedView:
        try:
            # Re-run the representation's structural invariants at this trust
            # boundary; a frozen dataclass alone is not an authenticity proof.
            replace(representation)
        except (RepresentationInvariantError, TypeError, ValueError):
            return DecompressedView(
                query_id=query.query_id,
                selected_components=(),
                missing_dependencies=("invalid_representation_envelope",),
                completeness=SolveStatus.INCOMPLETE,
                supporting_bytes_read=0,
            )
        if not any(root.matches(representation) for root in self.trusted_roots):
            return DecompressedView(
                query_id=query.query_id,
                selected_components=(),
                missing_dependencies=("untrusted_representation_root",),
                completeness=SolveStatus.INCOMPLETE,
                supporting_bytes_read=0,
            )
        manifest_by_id = {
            item.component_id: item
            for item in representation.source_component_manifest
        }
        visible_components = {
            item.component_id: item
            for item in representation.components
            if item.available_from_record <= query.known_at
        }
        # A changed or newly injected executable component must never reach
        # replay merely because its envelope still resembles a transition.
        untrusted_executable_ids = {
            component_id
            for component_id, component in visible_components.items()
            if component.component_kind
            in {ComponentKind.TRANSITION, ComponentKind.CONSTRAINT}
            and (
                component_id not in manifest_by_id
                or manifest_by_id[component_id].content_hash
                != component.content_hash
                or manifest_by_id[component_id].component_kind
                is not component.component_kind
            )
        }
        by_id = {
            component_id: component
            for component_id, component in visible_components.items()
            if component_id not in untrusted_executable_ids
        }
        event_id = str(query.parameters().get("event_id", ""))
        query_keys = set(query.keys)

        def relevant(expected: SourceComponentManifestEntry) -> bool:
            if query.kind not in expected.applicable_task_kinds:
                return False
            event_match = event_id in expected.source_event_ids
            if not (bool(set(expected.keys) & query_keys) or event_match):
                return False
            return not (
                expected.effective_time is not None
                and expected.effective_time > query.valid_at
                and not event_match
            )

        selected = {
            component_id
            for component_id in by_id
            if component_id in manifest_by_id
            and relevant(manifest_by_id[component_id])
        }
        missing: set[str] = set()
        expected_producers_by_key: dict[
            FactKey, list[SourceComponentManifestEntry]
        ] = {}
        for entry in representation.source_component_manifest:
            # Rejected constraint events normally produce no canonical value,
            # but an admissible DISPUTED/UNKNOWN claim can produce an explicit
            # unknown overlay.  Conservatively index constraint keys here;
            # replay uses the sealed per-effect authority/truth metadata to
            # decide whether a selected constraint actually establishes it.
            indexed_keys = (
                entry.produced_keys
                if entry.component_kind is ComponentKind.TRANSITION
                else (
                    entry.keys
                    if entry.component_kind is ComponentKind.CONSTRAINT
                    else ()
                )
            )
            for key in indexed_keys:
                expected_producers_by_key.setdefault(key, []).append(entry)

        # Seed relevance from the immutable full-source index as well as the
        # surviving subset.  This exposes deletion of any canonical component
        # that should be available for the task, including a later writer when
        # only an older same-key value remains in the packet.
        for expected in representation.source_component_manifest:
            if expected.available_from_record > query.known_at:
                continue
            if not relevant(expected):
                continue
            if expected.component_id not in by_id:
                missing.add(expected.component_id)
            elif expected.component_id not in selected:
                selected.add(expected.component_id)

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
                component_time = int(component.payload()["effective_time"])
                for item in component.payload().get("input_keys", ()):
                    key = FactKey(str(item["subject"]), str(item["predicate"]))
                    for producer in expected_producers_by_key.get(key, ()):
                        # Same-time peers are required together, but a source
                        # record not yet known at the query cutoff is neither
                        # selectable nor missing.
                        if (
                            producer.available_from_record > query.known_at
                            or producer.effective_time is None
                            or producer.effective_time > component_time
                        ):
                            continue
                        producer_id = producer.component_id
                        if producer_id not in by_id:
                            missing.add(producer_id)
                        elif producer_id not in selected:
                            selected.add(producer_id)
                            pending.append(producer_id)
        components = tuple(sorted((by_id[item] for item in selected if item in by_id), key=lambda item: item.component_id))
        lineage_missing = [item.component_id for item in components if not item.evidence]
        missing.update(lineage_missing)
        # Count the complete representation material exposed to the solver,
        # not merely the compact payload strings.  Provenance, dependencies,
        # validity metadata, and the schema-bearing component envelope are
        # part of the supplied state cost.
        supporting_bytes = RepresentationVersion.compute_packet_bytes(
            components,
            representation.source_component_manifest,
            representation.source_component_manifest_hash,
        )
        return DecompressedView(
            query_id=query.query_id,
            selected_components=components,
            missing_dependencies=tuple(sorted(missing)),
            completeness=SolveStatus.COMPLETE if selected and not missing else SolveStatus.INCOMPLETE,
            supporting_bytes_read=supporting_bytes,
        )


@dataclass(frozen=True, slots=True)
class DeterministicReferenceSolver:
    solver_id: ClassVar[str] = "hive-deterministic-reference-solver-v1"

    @property
    def configuration_hash(self) -> str:
        return sha256_text(
            canonical_json(
                {
                    "component": self.solver_id,
                    "configuration_version": 1,
                    "state": "stateless",
                }
            )
        )

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
    def _requirement_met(
        state: Mapping[FactKey, Any],
        item: Mapping[str, Any],
        ambiguous_keys: Iterable[FactKey] = (),
    ) -> bool:
        key = FactKey(str(item["key"]["subject"]), str(item["key"]["predicate"]))
        if key in ambiguous_keys:
            return False
        op = RequirementOp(str(item["op"]))
        if op is RequirementOp.EXISTS:
            return key in state
        if op is RequirementOp.ABSENT:
            return key not in state
        if op is RequirementOp.EQ:
            return key in state and canonical_json(state[key]) == canonical_json(
                item.get("value")
            )
        if op is RequirementOp.GTE:
            value = state.get(key)
            expected = item.get("value")
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and isinstance(expected, (int, float))
                and not isinstance(expected, bool)
                and value >= expected
            )
        return False

    @staticmethod
    def _effects_incompatible(
        left: Mapping[str, Any],
        right: Mapping[str, Any],
    ) -> bool:
        """Mirror canonical simultaneous-effect conflict semantics."""

        left_op = EffectOp(str(left["op"]))
        right_op = EffectOp(str(right["op"]))
        if left_op is right_op:
            if left_op is EffectOp.SET:
                return (
                    canonical_json(left.get("value"))
                    != canonical_json(right.get("value"))
                    or int(left["valid_from"]) != int(right["valid_from"])
                    or left.get("valid_to") != right.get("valid_to")
                )
            return left_op is not EffectOp.DELETE
        return True

    def _evaluate_event_effects(
        self,
        event: Mapping[str, Any],
        cells: Mapping[FactKey, Mapping[str, Any]],
        *,
        validate: bool,
    ) -> tuple[dict[FactKey, dict[str, Any]], bool]:
        """Apply one atomic packet event, optionally checking replay guards."""

        trial = {key: dict(cell) for key, cell in cells.items()}
        for effect in event["effects"]:
            key = self._key(effect["key"])
            existing = trial.get(key)
            current = None if existing is None else existing["value"]
            expected = effect.get("expected_previous")
            expected_specified = effect.get("expected_previous_specified")
            if type(expected_specified) is not bool:
                return trial, True
            expected_matches = (
                expected_specified
                and existing is not None
                and canonical_json(current) == canonical_json(expected)
            )
            supersedes_existing = (
                existing is not None
                and str(existing["source_claim_id"])
                in {
                    str(item)
                    for item in effect.get("supersedes_claim_ids", ())
                }
            )
            op = EffectOp(str(effect["op"]))
            if op is EffectOp.SET:
                if validate and expected_specified and not expected_matches:
                    return trial, True
                changes_existing_state = (
                    existing is not None
                    and (
                        canonical_json(current)
                        != canonical_json(effect.get("value"))
                        or existing.get("valid_to") != effect.get("valid_to")
                    )
                )
                if (
                    validate
                    and changes_existing_state
                    and not expected_matches
                    and not supersedes_existing
                ):
                    return trial, True
                trial[key] = {
                    "source_claim_id": str(effect["claim_id"]),
                    "valid_to": effect.get("valid_to"),
                    "value": effect.get("value"),
                }
            elif op is EffectOp.DELETE:
                if validate and expected_specified and not expected_matches:
                    return trial, True
                if (
                    validate
                    and existing is not None
                    and not expected_matches
                    and not supersedes_existing
                ):
                    return trial, True
                trial.pop(key, None)
            elif op is EffectOp.INCREMENT:
                increment_by = effect.get("increment_by")
                result = effect.get("value")
                if (
                    not isinstance(expected, (int, float))
                    or isinstance(expected, bool)
                    or not isinstance(increment_by, (int, float))
                    or isinstance(increment_by, bool)
                    or not isinstance(result, (int, float))
                    or isinstance(result, bool)
                    or canonical_json(expected + increment_by)
                    != canonical_json(result)
                ):
                    return trial, True
                if validate and (
                    existing is None
                    or canonical_json(current) != canonical_json(expected)
                ):
                    return trial, True
                trial[key] = {
                    "source_claim_id": str(effect["claim_id"]),
                    "valid_to": effect.get("valid_to"),
                    "value": result,
                }
        return trial, False

    def _state_at(
        self,
        view: DecompressedView,
        at_time: int,
        *,
        known_at: int,
        exclude_event_id: str | None = None,
    ) -> tuple[dict[FactKey, Any], set[str], set[FactKey]]:
        events = [
            event
            for event in self._events(view, known_at=known_at)
            if int(event["effective_time"]) <= at_time
            and event["event_id"] != exclude_event_id
        ]

        # The cell envelope is internal to deterministic replay.  Only values
        # are returned to a solver, but claim lineage and validity are retained
        # long enough to enforce supersession and temporal prerequisites.
        cells: dict[FactKey, dict[str, Any]] = {}
        applied: set[str] = set()
        applied_claims: set[str] = set()
        contradictions: list[dict[str, Any]] = []
        ambiguous: set[FactKey] = set()
        claims_by_id = {
            str(effect["claim_id"]): effect
            for event in events
            for effect in event["effects"]
        }
        claim_event_ids = {
            str(effect["claim_id"]): str(event["event_id"])
            for event in events
            for effect in event["effects"]
        }

        def active_conflict_claim_ids(
            contradiction: Mapping[str, Any],
            valid_at: int,
        ) -> frozenset[str]:
            return frozenset(
                claim_id
                for claim_id in contradiction["claim_ids"]
                if claim_id in claims_by_id
                and int(claims_by_id[claim_id]["valid_from"]) <= valid_at
                and (
                    claims_by_id[claim_id].get("valid_to") is None
                    or valid_at < int(claims_by_id[claim_id]["valid_to"])
                )
            )

        def refresh_ambiguity(valid_at: int) -> set[FactKey]:
            active_keys: set[FactKey] = set()
            for contradiction in contradictions:
                if contradiction["resolution"] != "unresolved":
                    continue
                if active_conflict_claim_ids(contradiction, valid_at):
                    active_keys.add(contradiction["key"])
                else:
                    contradiction["resolution"] = "expired"
            return active_keys

        cursor = 0
        while cursor < len(events):
            current_time = int(events[cursor]["effective_time"])
            group_end = cursor
            while (
                group_end < len(events)
                and int(events[group_end]["effective_time"]) == current_time
            ):
                group_end += 1
            group = events[cursor:group_end]
            cursor = group_end

            for key, cell in tuple(cells.items()):
                valid_to = cell.get("valid_to")
                if valid_to is not None and int(valid_to) <= current_time:
                    del cells[key]
            ambiguous = refresh_ambiguity(current_time)

            group_ids = {str(event["event_id"]) for event in group}
            predecessors: dict[str, set[str]] = {}
            for event in group:
                event_id = str(event["event_id"])
                prior_ids = {
                    str(item)
                    for item in (
                        *event.get("hard_dependencies", ()),
                        *event.get("causal_parents", ()),
                    )
                }
                for effect in event["effects"]:
                    for claim_id in (
                        *effect.get("depends_on_claim_ids", ()),
                        *effect.get("supersedes_claim_ids", ()),
                    ):
                        source_event_id = claim_event_ids.get(str(claim_id))
                        if source_event_id is not None:
                            prior_ids.add(source_event_id)
                predecessors[event_id] = prior_ids & group_ids

            pending = {str(event["event_id"]): event for event in group}
            while pending:
                pending_ids = set(pending)
                stage = sorted(
                    (
                        event
                        for event_id, event in pending.items()
                        if not (predecessors[event_id] & pending_ids)
                    ),
                    key=lambda item: (
                        int(item["recorded_at"]),
                        str(item["event_id"]),
                    ),
                )
                if not stage:
                    raise RepresentationInvariantError(
                        "same-time event ordering cycle in representation"
                    )

                stage_ids = {str(item["event_id"]) for item in stage}
                stage_start_cells = {
                    key: dict(cell) for key, cell in cells.items()
                }
                stage_start_ambiguous = frozenset(ambiguous)
                stage_start_values = {
                    key: cell["value"]
                    for key, cell in stage_start_cells.items()
                }
                uncertainty_candidates: list[
                    tuple[FactKey, str, int, Any]
                ] = []
                for uncertain_event in stage:
                    if any(
                        str(dependency) not in applied
                        for dependency in (
                            *uncertain_event.get("hard_dependencies", ()),
                            *uncertain_event.get("causal_parents", ()),
                        )
                    ):
                        continue
                    if not all(
                        self._requirement_met(
                            stage_start_values,
                            item,
                            stage_start_ambiguous,
                        )
                        for item in uncertain_event["requirements"]
                    ):
                        continue
                    for effect in uncertain_event["effects"]:
                        try:
                            truth = TruthStatus(str(effect["truth"]))
                        except (KeyError, ValueError) as exc:
                            raise RepresentationInvariantError(
                                "compressed effect has invalid epistemic truth metadata"
                            ) from exc
                        epistemically_admissible = effect.get(
                            "epistemically_admissible"
                        )
                        if type(epistemically_admissible) is not bool:
                            raise RepresentationInvariantError(
                                "compressed effect has invalid epistemic authority metadata"
                            )
                        if (
                            truth
                            not in {TruthStatus.DISPUTED, TruthStatus.UNKNOWN}
                            or not epistemically_admissible
                        ):
                            continue
                        if any(
                            str(dependency) not in applied_claims
                            for dependency in effect.get(
                                "depends_on_claim_ids", ()
                            )
                        ):
                            continue
                        valid_from = int(effect["valid_from"])
                        valid_to = effect.get("valid_to")
                        if not (
                            valid_from <= current_time
                            and (
                                valid_to is None
                                or current_time < int(valid_to)
                            )
                        ):
                            continue
                        key = self._key(effect["key"])
                        if (
                            key in stage_start_cells
                            and key not in stage_start_ambiguous
                        ):
                            continue
                        claim_id = str(effect["claim_id"])
                        uncertainty_candidates.append(
                            (key, claim_id, valid_from, valid_to)
                        )

                for key, claim_id, valid_from, valid_to in uncertainty_candidates:
                    if any(
                        contradiction["resolution"] == "unresolved"
                        and contradiction["claim_ids"] == (claim_id,)
                        for contradiction in contradictions
                    ):
                        continue
                    contradictions.append(
                        {
                            "claim_ids": (claim_id,),
                            "key": key,
                            "overlap_from": valid_from,
                            "overlap_to": valid_to,
                            "resolution": "unresolved",
                        }
                    )
                    ambiguous.add(key)

                eligible: list[Mapping[str, Any]] = []
                resolving_keys_by_event: dict[str, frozenset[FactKey]] = {}
                for event in stage:
                    if event["decision"] != DecisionStatus.ADMIT.value:
                        continue
                    if any(
                        str(dependency) not in applied
                        for dependency in event.get("hard_dependencies", ())
                    ):
                        continue
                    if any(
                        str(dependency) not in applied
                        for dependency in event.get("causal_parents", ())
                    ):
                        continue
                    if any(
                        str(dependency) not in applied_claims
                        for effect in event["effects"]
                        for dependency in effect.get("depends_on_claim_ids", ())
                    ):
                        continue
                    values = {key: cell["value"] for key, cell in cells.items()}
                    if not all(
                        self._requirement_met(values, item, ambiguous)
                        for item in event["requirements"]
                    ):
                        continue
                    resolving_keys: set[FactKey] = set()
                    ambiguity_rejection = False
                    for effect in event["effects"]:
                        key = self._key(effect["key"])
                        active_conflicting_ids: set[str] = set()
                        for contradiction in contradictions:
                            if (
                                contradiction["key"] == key
                                and contradiction["resolution"] == "unresolved"
                            ):
                                active_conflicting_ids.update(
                                    active_conflict_claim_ids(
                                        contradiction,
                                        current_time,
                                    )
                                )
                        if not active_conflicting_ids:
                            continue
                        explicitly_superseded = active_conflicting_ids <= {
                            str(item)
                            for item in effect.get("supersedes_claim_ids", ())
                        }
                        same_stage_epistemic = all(
                            TruthStatus(str(claims_by_id[claim_id]["truth"]))
                            in {TruthStatus.DISPUTED, TruthStatus.UNKNOWN}
                            and claim_event_ids.get(claim_id) in stage_ids
                            for claim_id in active_conflicting_ids
                        )
                        if not explicitly_superseded and not same_stage_epistemic:
                            ambiguity_rejection = True
                            break
                        resolving_keys.add(key)
                    if ambiguity_rejection:
                        continue
                    evaluation_cells = dict(cells)
                    for key in resolving_keys:
                        evaluation_cells.pop(key, None)
                    _, rejected = self._evaluate_event_effects(
                        event,
                        evaluation_cells,
                        validate=True,
                    )
                    if rejected:
                        continue
                    eligible.append(event)
                    resolving_keys_by_event[str(event["event_id"])] = frozenset(
                        resolving_keys
                    )

                effects_by_key: dict[
                    FactKey,
                    list[tuple[Mapping[str, Any], Mapping[str, Any]]],
                ] = {}
                for event in eligible:
                    for effect in event["effects"]:
                        effects_by_key.setdefault(
                            self._key(effect["key"]), []
                        ).append((event, effect))

                conflict_events: set[str] = set()
                conflict_claims: dict[FactKey, set[str]] = {}
                for key, writes in effects_by_key.items():
                    for index, (left_event, left_effect) in enumerate(writes):
                        for right_event, right_effect in writes[index + 1 :]:
                            left_id = str(left_event["event_id"])
                            right_id = str(right_event["event_id"])
                            if left_id == right_id:
                                continue
                            if not self._effects_incompatible(
                                left_effect,
                                right_effect,
                            ):
                                continue
                            conflict_events.update((left_id, right_id))
                            conflict_claims.setdefault(key, set()).update(
                                (
                                    str(left_effect["claim_id"]),
                                    str(right_effect["claim_id"]),
                                )
                            )

                for key, claim_id_set in conflict_claims.items():
                    claim_ids = tuple(sorted(claim_id_set))
                    finite_ends = [
                        claims_by_id[claim_id].get("valid_to")
                        for claim_id in claim_ids
                        if claims_by_id[claim_id].get("valid_to") is not None
                    ]
                    contradictions.append(
                        {
                            "claim_ids": claim_ids,
                            "key": key,
                            "overlap_from": current_time,
                            "overlap_to": min(finite_ends) if finite_ends else None,
                            "resolution": "unresolved",
                        }
                    )
                    ambiguous.add(key)

                for event in eligible:
                    event_id = str(event["event_id"])
                    if event_id in conflict_events:
                        continue
                    application_cells = dict(cells)
                    for key in resolving_keys_by_event[event_id]:
                        application_cells.pop(key, None)
                    cells, rejected = self._evaluate_event_effects(
                        event,
                        application_cells,
                        validate=False,
                    )
                    if rejected:  # pragma: no cover - eligibility proved it.
                        continue
                    applied.add(event_id)
                    applied_claims.update(
                        str(effect["claim_id"])
                        for effect in event["effects"]
                    )
                    for effect in event["effects"]:
                        key = self._key(effect["key"])
                        superseded = {
                            str(item)
                            for item in effect.get("supersedes_claim_ids", ())
                        }
                        for contradiction in contradictions:
                            active_conflicting_ids = active_conflict_claim_ids(
                                contradiction,
                                current_time,
                            )
                            if (
                                contradiction["key"] == key
                                and contradiction["resolution"] == "unresolved"
                                and active_conflicting_ids
                                and (
                                    active_conflicting_ids <= superseded
                                    or (
                                        len(contradiction["claim_ids"]) == 1
                                        and all(
                                            TruthStatus(
                                                str(
                                                    claims_by_id[claim_id][
                                                        "truth"
                                                    ]
                                                )
                                            )
                                            in {
                                                TruthStatus.DISPUTED,
                                                TruthStatus.UNKNOWN,
                                            }
                                            and claim_event_ids.get(claim_id)
                                            in stage_ids
                                            for claim_id in active_conflicting_ids
                                        )
                                    )
                                )
                            ):
                                contradiction["resolution"] = (
                                    "superseded"
                                    if active_conflicting_ids <= superseded
                                    else "authority"
                                )
                                contradiction["resolved_by_claim_id"] = str(
                                    effect["claim_id"]
                                )
                    ambiguous = refresh_ambiguity(current_time)

                for event in stage:
                    pending.pop(str(event["event_id"]))

        for key, cell in tuple(cells.items()):
            valid_to = cell.get("valid_to")
            if valid_to is not None and int(valid_to) <= at_time:
                del cells[key]
        ambiguous = refresh_ambiguity(at_time)
        return (
            {
                key: cell["value"]
                for key, cell in cells.items()
                if key not in ambiguous
            },
            applied,
            ambiguous,
        )

    @staticmethod
    def _effective_owner(
        state: Mapping[FactKey, Any],
        item: str,
        ambiguous_keys: Iterable[FactKey] = (),
    ) -> tuple[Any, bool]:
        ambiguous = frozenset(ambiguous_keys)
        seen: set[str] = set()
        current = item
        while current not in seen:
            seen.add(current)
            owner_key = FactKey(current, "owner")
            if owner_key in ambiguous:
                return None, True
            owner = state.get(owner_key)
            if owner is not None:
                return owner, False
            inside_key = FactKey(current, "inside")
            if inside_key in ambiguous:
                return None, True
            parent = state.get(inside_key)
            if parent is None:
                return None, False
            current = str(parent)
        return None, False

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
        state, _, ambiguous = self._state_at(
            view,
            query.valid_at,
            known_at=query.known_at,
        )
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
                answer, derived_ambiguous = self._effective_owner(
                    state,
                    str(parameters["item"]),
                    ambiguous,
                )
                if derived_ambiguous:
                    return SolverOutcome(
                        query.query_id,
                        SolveStatus.INCOMPLETE,
                        None,
                        view.selected_component_ids,
                        evidence,
                        "ambiguous_state",
                    )
            elif query.keys:
                if query.keys[0] in ambiguous:
                    return SolverOutcome(
                        query.query_id,
                        SolveStatus.INCOMPLETE,
                        None,
                        view.selected_component_ids,
                        evidence,
                        "ambiguous_state",
                    )
                answer = state.get(query.keys[0])
            else:
                answer = None
        elif query.kind is TaskKind.CHANGES:
            start = int(parameters["from_time"])
            finish = int(parameters["to_time"])
            before, _, before_ambiguous = self._state_at(
                view,
                start,
                known_at=query.known_at,
            )
            after, _, after_ambiguous = self._state_at(
                view,
                finish,
                known_at=query.known_at,
            )
            key = query.keys[0]
            if key in before_ambiguous or key in after_ambiguous:
                return SolverOutcome(
                    query.query_id,
                    SolveStatus.INCOMPLETE,
                    None,
                    view.selected_component_ids,
                    evidence,
                    "ambiguous_state",
                )
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
            pre_state, _, ambiguous = self._state_at(
                view,
                query.valid_at,
                known_at=query.known_at,
                exclude_event_id=target_id,
            )
            required_keys = {
                self._key(item["key"])
                for item in target["requirements"]
            }
            if required_keys & ambiguous:
                return SolverOutcome(
                    query.query_id,
                    SolveStatus.INCOMPLETE,
                    None,
                    view.selected_component_ids,
                    evidence,
                    "ambiguous_state",
                )
            answer = all(
                self._requirement_met(pre_state, item, ambiguous)
                for item in target["requirements"]
            )
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


@dataclass(frozen=True, slots=True)
class RepresentationEvaluator:
    """Frozen evaluator whose replaceable collaborators identify their configuration."""

    decompressor: Decompressor
    solver: Solver
    evaluator_id: ClassVar[str] = "hive-representation-evaluator-v1"

    def __post_init__(self) -> None:
        _require_configuration_hash(self.decompressor, "decompressor")
        _require_configuration_hash(self.solver, "solver")
        if not isinstance(self.solver.solver_id, str) or not self.solver.solver_id.strip():
            raise RepresentationInvariantError("solver requires a nonempty solver_id")

    @property
    def configuration_hash(self) -> str:
        """Recompute the full collaborator fingerprint so later mutation is visible."""

        return sha256_text(
            canonical_json(
                {
                    "decompressor": {
                        "configuration_hash": _require_configuration_hash(
                            self.decompressor,
                            "decompressor",
                        ),
                        "type": (
                            f"{type(self.decompressor).__module__}."
                            f"{type(self.decompressor).__qualname__}"
                        ),
                    },
                    "evaluator": self.evaluator_id,
                    "solver": {
                        "configuration_hash": _require_configuration_hash(
                            self.solver,
                            "solver",
                        ),
                        "solver_id": self.solver.solver_id,
                        "type": (
                            f"{type(self.solver).__module__}."
                            f"{type(self.solver).__qualname__}"
                        ),
                    },
                }
            )
        )

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
    necessity_scope: str
    causal_necessity_demonstrated: bool
    evaluated_subsets: int
    minimum_component_count: int | None
    minimal_component_sets: tuple[tuple[str, ...], ...]
    singleton_essential: tuple[str, ...]
    singleton_redundant: tuple[str, ...]


class RepresentationAblator:
    """Find subsets that pass the frozen fail-closed representation contract.

    This is exact over enumerated component subsets, not a causal-necessity
    oracle.  A sealed full-source manifest conservatively treats removal of a
    potentially relevant source component as information loss unless another
    representation object carries an independently validated replacement
    certificate.  Reports expose that scope explicitly.
    """

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
                representation_id=representation.representation_id,
                status="invalid_baseline",
                algorithm="none",
                necessity_scope="none",
                causal_necessity_demonstrated=False,
                evaluated_subsets=1,
                minimum_component_count=None,
                minimal_component_sets=(),
                singleton_essential=(),
                singleton_redundant=(),
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
                representation_id=representation.representation_id,
                status="complete",
                algorithm="exact_contract_subset_minimum",
                necessity_scope="fail_closed_representation_contract",
                causal_necessity_demonstrated=False,
                evaluated_subsets=evaluated,
                minimum_component_count=minimum_count,
                minimal_component_sets=tuple(minimal),
                singleton_essential=tuple(sorted(essential)),
                singleton_redundant=tuple(sorted(redundant)),
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
            representation_id=representation.representation_id,
            status="complete",
            algorithm="one_contract_minimal_approximation",
            necessity_scope="fail_closed_representation_contract",
            causal_necessity_demonstrated=False,
            evaluated_subsets=evaluated,
            minimum_component_count=len(working),
            minimal_component_sets=(tuple(working),),
            singleton_essential=tuple(sorted(essential)),
            singleton_redundant=tuple(sorted(redundant)),
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
