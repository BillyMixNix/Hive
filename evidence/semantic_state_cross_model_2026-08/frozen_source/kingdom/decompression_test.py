"""A small, falsification-first benchmark for task-reversible decompression.

This module is intentionally standalone.  It does not alter Kingdom execution
or claim that Hive can learn the compact representation.  It tests whether one
frozen, query-blind typed ledger preserves enough temporal and causal structure
for a fixed model to solve held-out questions with less solve context.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import re
import subprocess
import time
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from hive_llm import OLLAMA_URL, ask_hive
from kingdom.protocol_v2_audit import AuditInvariantError, ProtocolV2AuditStore
from kingdom.webnovel_benchmark import _ollama_model_digest


PROTOCOL_ID = "hive-decompression-smoke-v1"
PROTOCOL_SCHEMA_VERSION = 1
CASE_PACK_SCHEMA_VERSION = 1
OUTPUT_SCHEMA_VERSION = 1
MODEL = "qwen2.5-coder:7b"
MODEL_DIGEST = (
    "dae161e27b0e90dd1856c8bb3209201fd6736d8eb66298e75ed87571486f4364"
)
NUM_CTX = 32_768
NUM_PREDICT = 2_048
TEMPERATURE = 0.0
SEED = 73_021
TIMEOUT_SECONDS = 900
PRIMARY_CALLS = 18
ABLATION_CALLS = 2
TOTAL_CALLS = PRIMARY_CALLS + ABLATION_CALLS
CONDITIONS = ("raw", "retrieval", "compressed")
ANSWER_CHOICES = frozenset({"A", "B", "C", "D", "INSUFFICIENT"})
REASONING_CODES = frozenset(
    {
        "CURRENT_NOT_PLANNED",
        "INFERRED_CONTAINMENT",
        "SUPERSEDED_TRANSFORMATION",
        "EARNED_LEDGER",
        "TRUTH_VS_KNOWLEDGE",
        "INSUFFICIENT_EVIDENCE",
    }
)
CRITICAL_SOURCE_FILES = (
    "hive_llm.py",
    "kingdom/protocol_v2_audit.py",
    "kingdom/webnovel_benchmark.py",
    "kingdom/decompression_test.py",
    "benchmarks/decompression_test/CASE_PACK.json",
    "benchmarks/decompression_test/PROTOCOL.md",
    "tests/test_decompression_test.py",
)


class CasePackError(ValueError):
    """The frozen synthetic pack is structurally or semantically invalid."""


class ModelOutputRejected(ValueError):
    """A complete model response violated the strict result contract."""


@dataclass(frozen=True)
class Requirement:
    key: str
    op: str
    value: Any


@dataclass(frozen=True)
class Effect:
    op: str
    key: str
    value: Any


@dataclass(frozen=True)
class Event:
    event_id: str
    role: str
    effective_time: int
    record_time: int
    kind: str
    authority: str
    status: str
    actor: str
    requires: tuple[Requirement, ...]
    effects: tuple[Effect, ...]
    prose: str


@dataclass(frozen=True)
class ClaimChoice:
    claim_id: str
    statement: str
    truth_class: str


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    family: str
    load: str
    event_count: int
    support_depth: int
    seed: int
    question: str
    query_time: int
    query_kind: str
    query_params: Mapping[str, Any]
    options: Mapping[str, str]
    correct_choice: str
    reasoning_code: str
    events: tuple[Event, ...]
    required_event_refs: tuple[str, ...]
    allowed_event_refs: tuple[str, ...]
    rejected_event_refs: tuple[str, ...]
    claims: tuple[ClaimChoice, ...]
    current_claim_ids: tuple[str, ...]
    ablation_event_id: str
    control_ablation_event_id: str


@dataclass(frozen=True)
class ReplayResult:
    state: Mapping[str, Any]
    applied_event_ids: tuple[str, ...]
    rejected_event_ids: tuple[str, ...]


@dataclass(frozen=True)
class ParsedAnswer:
    case_id: str
    answer_choice: str
    ordered_event_refs: tuple[str, ...]
    rejected_event_refs: tuple[str, ...]
    selected_current_claim_ids: tuple[str, ...]
    reasoning_code: str


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    condition: str
    valid_output: bool
    primary_pass: bool
    answer_correct: bool
    chronology_authority_correct: bool
    reconstruction_correct: bool
    current_claims_correct: bool
    illegal_state_promotions: int
    required_ref_recall: float
    allowed_ref_precision: float
    compression_loss: bool
    failure_reasons: tuple[str, ...]


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _write_exclusive(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def _opaque(prefix: str, case_id: str, role: str) -> str:
    return prefix + hashlib.sha256(f"{case_id}|{role}".encode()).hexdigest()[:9]


def _event(
    case_id: str,
    role: str,
    effective_time: int,
    *,
    kind: str = "actual",
    authority: str = "canonical",
    status: str = "completed",
    actor: str = "registry",
    requires: Sequence[tuple[str, str, Any]] = (),
    effects: Sequence[tuple[str, str, Any]] = (),
    prose: str,
    record_time: int | None = None,
) -> Event:
    return Event(
        event_id=_opaque("e_", case_id, role),
        role=role,
        effective_time=effective_time,
        record_time=effective_time if record_time is None else record_time,
        kind=kind,
        authority=authority,
        status=status,
        actor=actor,
        requires=tuple(Requirement(*item) for item in requires),
        effects=tuple(Effect(*item) for item in effects),
        prose=prose,
    )


def _requirement_met(state: Mapping[str, Any], requirement: Requirement) -> bool:
    actual = state.get(requirement.key)
    if requirement.op == "eq":
        return actual == requirement.value
    if requirement.op == "gte":
        return isinstance(actual, (int, float)) and actual >= requirement.value
    if requirement.op == "absent":
        return requirement.key not in state
    raise CasePackError(f"unknown requirement operator {requirement.op!r}")


def replay_events(events: Sequence[Event], *, through_time: int) -> ReplayResult:
    """Deterministically replay authoritative completed events through one time."""

    state: dict[str, Any] = {}
    applied: list[str] = []
    rejected: list[str] = []
    ordered = sorted(
        events, key=lambda event: (event.effective_time, event.record_time, event.event_id)
    )
    for event in ordered:
        if event.effective_time > through_time:
            continue
        eligible = (
            event.authority == "canonical"
            and event.status == "completed"
            and event.kind in {"actual", "observation", "message"}
            and all(_requirement_met(state, req) for req in event.requires)
        )
        if not eligible:
            rejected.append(event.event_id)
            continue
        for effect in event.effects:
            if effect.op == "set":
                state[effect.key] = copy.deepcopy(effect.value)
            elif effect.op == "inc":
                state[effect.key] = state.get(effect.key, 0) + effect.value
            elif effect.op == "delete":
                state.pop(effect.key, None)
            else:
                raise CasePackError(f"unknown effect operator {effect.op!r}")
        applied.append(event.event_id)
    return ReplayResult(
        state=copy.deepcopy(state),
        applied_event_ids=tuple(applied),
        rejected_event_ids=tuple(rejected),
    )


def _without_last_effect(
    events: Sequence[Event], target_event_id: str
) -> tuple[Event, ...]:
    """Model the exact counterfactual exposed by one wire-level unknown atom."""

    result: list[Event] = []
    matched = False
    for event in events:
        if event.event_id != target_event_id:
            result.append(event)
            continue
        if matched or not event.effects:
            raise CasePackError("ablation target must be one unique event with an effect")
        matched = True
        result.append(replace(event, effects=event.effects[:-1]))
    if not matched:
        raise CasePackError("ablation target event is absent")
    return tuple(result)


def _follow_location(state: Mapping[str, Any], item: str) -> str:
    seen: set[str] = set()
    current = item
    while True:
        if current in seen:
            raise CasePackError("containment cycle in deterministic oracle")
        seen.add(current)
        direct = state.get(f"location:{current}")
        if direct is not None:
            return str(direct)
        parent = state.get(f"inside:{current}")
        if parent is None:
            return "UNKNOWN"
        current = str(parent)


def _answer_from_state(
    query_kind: str, params: Mapping[str, Any], state: Mapping[str, Any]
) -> str:
    if query_kind == "value":
        return str(state.get(str(params["key"]), "UNKNOWN"))
    if query_kind == "location":
        return _follow_location(state, str(params["item"]))
    if query_kind == "transformation":
        forms = [
            form
            for form in params["forms"]
            if state.get(f"exists:{form}") is True
        ]
        if len(forms) != 1:
            return "UNKNOWN"
        form = forms[0]
        owner = state.get(f"owner:{form}", "UNKNOWN")
        grade = state.get(f"grade:{form}", 0)
        return f"{form}|owner={owner}|grade={grade}"
    if query_kind == "economics":
        person = str(params["person"])
        obligation = str(params["obligation"])
        return (
            f"balance={state.get(f'balance:{person}', 'UNKNOWN')}|"
            f"obligation={state.get(f'obligation:{obligation}', 'UNKNOWN')}|"
            f"xp={state.get(f'xp:{person}', 'UNKNOWN')}|"
            f"key={state.get(f'asset:{person}:key', False)}"
        )
    if query_kind == "truth_knowledge":
        item = str(params["item"])
        observer = str(params["observer"])
        return (
            f"truth={state.get(f'owner:{item}', 'UNKNOWN')}@"
            f"{state.get(f'location:{item}', 'UNKNOWN')}|"
            f"known={state.get(f'knows:{observer}:owner:{item}', 'UNKNOWN')}@"
            f"{state.get(f'knows:{observer}:location:{item}', 'UNKNOWN')}"
        )
    raise CasePackError(f"unknown query kind {query_kind!r}")


def _answer_from_replay(case: BenchmarkCase) -> str:
    state = replay_events(case.events, through_time=case.query_time).state
    return _answer_from_state(case.query_kind, case.query_params, state)


def _options(correct_slot: str, correct: str, distractors: Sequence[str]) -> dict[str, str]:
    if correct_slot not in {"A", "B", "C", "D"}:
        raise CasePackError(f"invalid correct option slot {correct_slot!r}")
    if len(distractors) != 3 or len(set(distractors) | {correct}) != 4:
        raise CasePackError("every case requires three distinct distractors")
    result: dict[str, str] = {}
    iterator = iter(distractors)
    for slot in ("A", "B", "C", "D"):
        result[slot] = correct if slot == correct_slot else next(iterator)
    return result


def _claims(case_id: str, options: Mapping[str, str], correct_slot: str) -> tuple[ClaimChoice, ...]:
    wrong_classes = iter(("historical", "planned", "hallucinated"))
    claims: list[ClaimChoice] = []
    for slot in ("A", "B", "C", "D"):
        truth_class = "current" if slot == correct_slot else next(wrong_classes)
        claims.append(
            ClaimChoice(
                claim_id=_opaque("c_", case_id, f"option_{slot}"),
                statement=options[slot],
                truth_class=truth_class,
            )
        )
    return tuple(claims)


def _names(seed: int, count: int, prefix: str) -> list[str]:
    rng = random.Random(seed)
    syllables = ["Ari", "Bex", "Cira", "Daro", "Eli", "Fenn", "Gia", "Hale"]
    rng.shuffle(syllables)
    return [f"{prefix}{syllables[index]}" for index in range(count)]


def _case_suffix(case_id: str) -> str:
    return hashlib.sha256(f"entity|{case_id}".encode()).hexdigest()[:4].upper()


def _pad_events(
    case_id: str,
    events: Sequence[Event],
    *,
    target_count: int,
    seed: int,
    focus: str,
) -> tuple[Event, ...]:
    """Add deterministic query-blind decoys without touching focal state keys."""

    if len(events) > target_count:
        raise CasePackError(
            f"{case_id} has {len(events)} critical events but target is {target_count}"
        )
    padded = list(events)
    rng = random.Random(seed ^ 0xD3C0)
    while len(padded) < target_count:
        index = len(padded) + 1
        decoy_role = f"decoy_{index:02d}"
        actor = f"Archivist{rng.randrange(10, 99)}"
        time_value = rng.randrange(0, 30)
        mode = index % 4
        if mode == 0:
            kind, authority, status = "plan", "noncanonical", "planned"
            prose = (
                f"A draft mentions {focus}, but only proposes changing unrelated "
                f"ledger D{index}; it never takes effect."
            )
        elif mode == 1:
            kind, authority, status = "rumor", "noncanonical", "reported"
            prose = (
                f"A rumor repeats the words {focus} and transfer, while making no "
                f"authoritative change to the focal world."
            )
        else:
            kind, authority, status = "actual", "canonical", "completed"
            prose = (
                f"{actor} performs an unrelated inventory update D{index}; "
                f"the focal {focus} is unaffected."
            )
        padded.append(
            _event(
                case_id,
                decoy_role,
                time_value,
                kind=kind,
                authority=authority,
                status=status,
                actor=actor,
                effects=(("set", f"decoy:{case_id}:{index}", index),),
                prose=prose,
                record_time=100 + index,
            )
        )
    # Raw history is deliberately record ordered, not silently event-time sorted.
    return tuple(sorted(padded, key=lambda event: (event.record_time, event.event_id)))


def _temporal_case(spec: Mapping[str, Any]) -> BenchmarkCase:
    case_id = str(spec["case_id"])
    depth = int(spec["support_depth"])
    origin, target, planned, future = _names(int(spec["seed"]), 4, "")
    item = "Seal" + _case_suffix(case_id)
    events: list[Event] = [
        _event(
            case_id,
            "origin",
            0,
            actor="registry",
            effects=(("set", f"owner:{item}", origin),),
            prose=f"The canonical registry creates {item} and records {origin} as owner.",
        )
    ]
    required_roles = ["origin"]
    prerequisites: list[tuple[str, str, Any]] = [(f"owner:{item}", "eq", origin)]
    for index in range(max(depth - 2, 0)):
        role = f"permit_{index + 1}"
        key = f"permit:{item}:{index + 1}"
        events.append(
            _event(
                case_id,
                role,
                index + 1,
                actor=f"authority-{index + 1}",
                effects=(("set", key, True),),
                prose=f"Authority {index + 1} issues an effective prerequisite for {item}.",
            )
        )
        prerequisites.append((key, "eq", True))
        required_roles.append(role)
    transfer_time = max(depth, 2) + 1
    events.append(
        _event(
            case_id,
            "planned_transfer",
            1,
            kind="plan",
            authority="noncanonical",
            status="planned",
            actor=origin,
            effects=(("set", f"owner:{item}", planned),),
            prose=(
                f"{origin} drafts a future plan to give {item} to {planned}; "
                "the plan has not been executed."
            ),
            record_time=50,
        )
    )
    events.append(
        _event(
            case_id,
            "actual_transfer",
            transfer_time,
            actor="registry",
            requires=tuple(prerequisites),
            effects=(("set", f"owner:{item}", target),),
            prose=(
                f"After every listed prerequisite is satisfied, the registry "
                f"transfers {item} from {origin} to {target}."
            ),
        )
    )
    required_roles.append("actual_transfer")
    events.append(
        _event(
            case_id,
            "future_transfer",
            transfer_time + 3,
            actor="registry",
            requires=((f"owner:{item}", "eq", target),),
            effects=(("set", f"owner:{item}", future),),
            prose=f"At a later time, the registry transfers {item} from {target} to {future}.",
        )
    )
    events_tuple = _pad_events(
        case_id,
        events,
        target_count=int(spec["event_count"]),
        seed=int(spec["seed"]),
        focus=item,
    )
    correct = target
    options = _options(str(spec["correct_slot"]), correct, (origin, planned, future))
    claims = _claims(case_id, options, str(spec["correct_slot"]))
    by_role = {event.role: event.event_id for event in events_tuple}
    required = tuple(by_role[role] for role in required_roles)
    relevant = tuple(
        by_role[role]
        for role in (*required_roles, "planned_transfer", "future_transfer")
    )
    current_claim = next(claim.claim_id for claim in claims if claim.truth_class == "current")
    return BenchmarkCase(
        case_id=case_id,
        family=str(spec["family"]),
        load=str(spec["load"]),
        event_count=int(spec["event_count"]),
        support_depth=depth,
        seed=int(spec["seed"]),
        question=f"Who canonically owns {item} at effective time T{transfer_time}?",
        query_time=transfer_time,
        query_kind="value",
        query_params={"key": f"owner:{item}"},
        options=options,
        correct_choice=str(spec["correct_slot"]),
        reasoning_code="CURRENT_NOT_PLANNED",
        events=events_tuple,
        required_event_refs=required,
        allowed_event_refs=relevant,
        rejected_event_refs=(
            by_role["planned_transfer"],
            by_role["future_transfer"],
        ),
        claims=claims,
        current_claim_ids=(current_claim,),
        ablation_event_id=by_role[required_roles[-2] if depth > 2 else "origin"],
        control_ablation_event_id=next(
            event.event_id for event in events_tuple if event.role.startswith("decoy_")
        ),
    )


def _containment_case(spec: Mapping[str, Any]) -> BenchmarkCase:
    case_id = str(spec["case_id"])
    depth = int(spec["support_depth"])
    owner, claimed_owner = _names(int(spec["seed"]), 2, "")
    suffix = _case_suffix(case_id)
    item = "Coin" + suffix
    root = "Crate" + suffix
    intermediates = [f"Box{index}{suffix}" for index in range(1, depth - 1)]
    path = [item, *intermediates, root]
    events: list[Event] = []
    required_roles: list[str] = []
    for index, (child, parent) in enumerate(zip(path, path[1:]), start=1):
        role = f"contain_{index}"
        effects: list[tuple[str, str, Any]] = [("set", f"inside:{child}", parent)]
        if index == 1:
            effects.extend(
                [
                    ("set", f"owner:{item}", owner),
                    ("set", f"exists:{item}", True),
                ]
            )
        events.append(
            _event(
                case_id,
                role,
                index - 1,
                actor=owner,
                effects=effects,
                prose=f"{owner} canonically places {child} inside {parent}.",
            )
        )
        required_roles.append(role)
    move_time = len(required_roles) + 1
    events.append(
        _event(
            case_id,
            "move_root",
            move_time,
            actor=owner,
            effects=(("set", f"location:{root}", "Dock"),),
            prose=f"{owner} moves {root}, with its contents, to Dock.",
        )
    )
    required_roles.append("move_root")
    events.append(
        _event(
            case_id,
            "planned_removal",
            move_time - 1,
            kind="plan",
            authority="noncanonical",
            status="planned",
            actor=claimed_owner,
            effects=(("set", f"location:{item}", "Pocket"),),
            prose=f"{claimed_owner} plans to remove {item} into a pocket, but does not do so.",
            record_time=70,
        )
    )
    events.append(
        _event(
            case_id,
            "future_destroy",
            move_time + 3,
            actor=owner,
            effects=(("set", f"exists:{item}", False),),
            prose=f"Later, {owner} destroys the nested container chain and {item} with it.",
        )
    )
    events_tuple = _pad_events(
        case_id,
        events,
        target_count=int(spec["event_count"]),
        seed=int(spec["seed"]),
        focus=item,
    )
    options = _options(
        str(spec["correct_slot"]), "Dock", ("Store", "Pocket", "UNKNOWN")
    )
    claims = _claims(case_id, options, str(spec["correct_slot"]))
    by_role = {event.role: event.event_id for event in events_tuple}
    required = tuple(by_role[role] for role in required_roles)
    relevant = tuple(
        by_role[role]
        for role in (*required_roles, "planned_removal", "future_destroy")
    )
    current_claim = next(claim.claim_id for claim in claims if claim.truth_class == "current")
    return BenchmarkCase(
        case_id=case_id,
        family=str(spec["family"]),
        load=str(spec["load"]),
        event_count=int(spec["event_count"]),
        support_depth=depth,
        seed=int(spec["seed"]),
        question=f"Where is {item} at T{move_time}, following containment transitively?",
        query_time=move_time,
        query_kind="location",
        query_params={"item": item},
        options=options,
        correct_choice=str(spec["correct_slot"]),
        reasoning_code="INFERRED_CONTAINMENT",
        events=events_tuple,
        required_event_refs=required,
        allowed_event_refs=relevant,
        rejected_event_refs=(
            by_role["planned_removal"],
            by_role["future_destroy"],
        ),
        claims=claims,
        current_claim_ids=(current_claim,),
        ablation_event_id=by_role[required_roles[-2] if len(required_roles) > 2 else required_roles[0]],
        control_ablation_event_id=next(
            event.event_id for event in events_tuple if event.role.startswith("decoy_")
        ),
    )


def _transformation_case(spec: Mapping[str, Any]) -> BenchmarkCase:
    case_id = str(spec["case_id"])
    depth = int(spec["support_depth"])
    origin, target = _names(int(spec["seed"]), 2, "")
    suffix = _case_suffix(case_id)
    forms = [f"Ore{suffix}", f"Ingot{suffix}", f"Blade{suffix}"]
    events: list[Event] = [
        _event(
            case_id,
            "create_ore",
            0,
            actor=origin,
            effects=(
                ("set", f"exists:{forms[0]}", True),
                ("set", f"owner:{forms[0]}", origin),
                ("set", f"grade:{forms[0]}", 0),
            ),
            prose=f"{origin} canonically creates and owns {forms[0]}.",
        )
    ]
    required_roles = ["create_ore"]
    if depth >= 2:
        events.append(
            _event(
                case_id,
                "refine",
                1,
                actor=origin,
                requires=((f"exists:{forms[0]}", "eq", True),),
                effects=(
                    ("set", f"exists:{forms[0]}", False),
                    ("set", f"exists:{forms[1]}", True),
                    ("set", f"owner:{forms[1]}", origin),
                    ("set", f"grade:{forms[1]}", 0),
                ),
                prose=f"{origin} consumes {forms[0]} and transforms it into {forms[1]}.",
            )
        )
        required_roles.append("refine")
    if depth >= 3:
        events.append(
            _event(
                case_id,
                "transfer",
                2,
                actor="registry",
                requires=((f"owner:{forms[1]}", "eq", origin),),
                effects=(("set", f"owner:{forms[1]}", target),),
                prose=f"The registry transfers {forms[1]} from {origin} to {target}.",
            )
        )
        required_roles.append("transfer")
    if depth >= 4:
        events.append(
            _event(
                case_id,
                "forge",
                3,
                actor=target,
                requires=((f"owner:{forms[1]}", "eq", target),),
                effects=(
                    ("set", f"exists:{forms[1]}", False),
                    ("set", f"exists:{forms[2]}", True),
                    ("set", f"owner:{forms[2]}", target),
                    ("set", f"grade:{forms[2]}", 1),
                ),
                prose=f"{target} consumes {forms[1]} and forges {forms[2]} at grade 1.",
            )
        )
        required_roles.append("forge")
    if depth >= 5:
        events.append(
            _event(
                case_id,
                "upgrade",
                4,
                actor=target,
                requires=((f"grade:{forms[2]}", "eq", 1),),
                effects=(("set", f"grade:{forms[2]}", 2),),
                prose=f"{target} completes the earned upgrade of {forms[2]} to grade 2.",
            )
        )
        required_roles.append("upgrade")
    query_time = depth - 1
    active_form = forms[0] if depth == 1 else forms[1] if depth <= 3 else forms[2]
    active_owner = target if depth >= 3 else origin
    grade = 2 if depth >= 5 else 1 if depth >= 4 else 0
    correct = f"{active_form}|owner={active_owner}|grade={grade}"
    events.append(
        _event(
            case_id,
            "planned_upgrade",
            query_time,
            kind="plan",
            authority="noncanonical",
            status="planned",
            actor=active_owner,
            effects=(("set", f"grade:{active_form}", grade + 1),),
            prose=f"A plan proposes a later grade {grade + 1} for {active_form}; it is not current.",
            record_time=80,
        )
    )
    events.append(
        _event(
            case_id,
            "rumor_old_form",
            query_time,
            kind="rumor",
            authority="noncanonical",
            status="reported",
            actor="observer",
            effects=(("set", f"exists:{forms[0]}", True),),
            prose=f"A rumor claims the superseded {forms[0]} still exists.",
            record_time=81,
        )
    )
    events_tuple = _pad_events(
        case_id,
        events,
        target_count=int(spec["event_count"]),
        seed=int(spec["seed"]),
        focus=active_form,
    )
    query_params = {"forms": forms}
    target_event_id = next(
        event.event_id for event in events_tuple if event.role == required_roles[-1]
    )
    counterfactual_state = replay_events(
        _without_last_effect(events_tuple, target_event_id), through_time=query_time
    ).state
    counterfactual = _answer_from_state(
        "transformation", query_params, counterfactual_state
    )
    candidate_distractors = (
        *((counterfactual,) if counterfactual != correct else ()),
        f"{forms[0]}|owner={origin}|grade=0",
        f"{active_form}|owner={active_owner}|grade={grade + 1}",
        f"{forms[-1]}|owner={origin}|grade=1",
    )
    distractors = tuple(dict.fromkeys(candidate_distractors))[:3]
    if len(distractors) != 3:
        raise CasePackError("transformation distractors are not distinct")
    options = _options(str(spec["correct_slot"]), correct, distractors)
    claims = _claims(case_id, options, str(spec["correct_slot"]))
    by_role = {event.role: event.event_id for event in events_tuple}
    required = tuple(by_role[role] for role in required_roles)
    relevant = tuple(
        by_role[role]
        for role in (*required_roles, "planned_upgrade", "rumor_old_form")
    )
    current_claim = next(claim.claim_id for claim in claims if claim.truth_class == "current")
    return BenchmarkCase(
        case_id=case_id,
        family=str(spec["family"]),
        load=str(spec["load"]),
        event_count=int(spec["event_count"]),
        support_depth=depth,
        seed=int(spec["seed"]),
        question=f"What is the current form, owner, and earned grade at T{query_time}?",
        query_time=query_time,
        query_kind="transformation",
        query_params=query_params,
        options=options,
        correct_choice=str(spec["correct_slot"]),
        reasoning_code="SUPERSEDED_TRANSFORMATION",
        events=events_tuple,
        required_event_refs=required,
        allowed_event_refs=relevant,
        rejected_event_refs=(by_role["planned_upgrade"], by_role["rumor_old_form"]),
        claims=claims,
        current_claim_ids=(current_claim,),
        ablation_event_id=by_role[required_roles[-1]],
        control_ablation_event_id=next(
            event.event_id for event in events_tuple if event.role.startswith("decoy_")
        ),
    )


def _economics_case(spec: Mapping[str, Any]) -> BenchmarkCase:
    case_id = str(spec["case_id"])
    depth = int(spec["support_depth"])
    person = _names(int(spec["seed"]), 1, "")[0]
    obligation = "O" + _case_suffix(case_id)
    events: list[Event] = [
        _event(
            case_id,
            "initial_ledger",
            0,
            actor="ledger",
            effects=(
                ("set", f"balance:{person}", 5),
                ("set", f"obligation:{obligation}", 4),
                ("set", f"xp:{person}", 0),
                ("set", f"asset:{person}:key", False),
            ),
            prose=(
                f"The canonical ledger opens {person} with balance 5, obligation "
                f"{obligation} owing 4, XP 0, and no key."
            ),
        )
    ]
    required_roles = ["initial_ledger"]
    if depth >= 2:
        events.append(
            _event(
                case_id,
                "job",
                1,
                actor=person,
                requires=((f"balance:{person}", "eq", 5),),
                effects=(
                    ("set", f"balance:{person}", 10),
                    ("set", f"xp:{person}", 1),
                ),
                prose=f"{person} completes a job, earning 5 currency and 1 XP.",
            )
        )
        required_roles.append("job")
    if depth >= 3:
        events.append(
            _event(
                case_id,
                "partial_payment",
                2,
                actor=person,
                requires=(
                    (f"balance:{person}", "eq", 10),
                    (f"obligation:{obligation}", "eq", 4),
                ),
                effects=(
                    ("set", f"balance:{person}", 7),
                    ("set", f"obligation:{obligation}", 1),
                ),
                prose=f"{person} pays 3 toward {obligation}; balance becomes 7 and 1 remains due.",
            )
        )
        required_roles.append("partial_payment")
    if depth >= 4:
        events.append(
            _event(
                case_id,
                "final_payment",
                3,
                actor=person,
                requires=(
                    (f"balance:{person}", "eq", 7),
                    (f"obligation:{obligation}", "eq", 1),
                ),
                effects=(
                    ("set", f"balance:{person}", 6),
                    ("set", f"obligation:{obligation}", 0),
                ),
                prose=f"{person} pays the final 1; balance becomes 6 and {obligation} closes.",
            )
        )
        required_roles.append("final_payment")
    if depth >= 5:
        events.append(
            _event(
                case_id,
                "blocked_purchase",
                4,
                kind="actual",
                authority="canonical",
                status="attempted",
                actor=person,
                requires=((f"balance:{person}", "gte", 7),),
                effects=(
                    ("set", f"balance:{person}", -1),
                    ("set", f"asset:{person}:key", True),
                ),
                prose=f"{person} attempts to buy a key for 7, but balance 6 is insufficient; no state changes.",
            )
        )
        required_roles.append("blocked_purchase")
    query_time = depth - 1
    events.extend(
        [
            _event(
                case_id,
                "planned_gift",
                query_time,
                kind="plan",
                authority="noncanonical",
                status="planned",
                actor="benefactor",
                effects=(("inc", f"balance:{person}", 10),),
                prose=f"A draft promises {person} a future gift of 10; it is not paid.",
                record_time=90,
            ),
            _event(
                case_id,
                "false_receipt",
                query_time,
                kind="claim",
                authority="noncanonical",
                status="reported",
                actor="clerk",
                effects=(("set", f"obligation:{obligation}", 0),),
                prose=f"An unauthenticated receipt claims {obligation} is settled.",
                record_time=91,
            ),
        ]
    )
    events_tuple = _pad_events(
        case_id,
        events,
        target_count=int(spec["event_count"]),
        seed=int(spec["seed"]),
        focus=f"{person} balance obligation",
    )
    replayed = replay_events(events_tuple, through_time=query_time).state
    correct = (
        f"balance={replayed[f'balance:{person}']}|"
        f"obligation={replayed[f'obligation:{obligation}']}|"
        f"xp={replayed[f'xp:{person}']}|"
        f"key={replayed[f'asset:{person}:key']}"
    )
    ablation_role = "final_payment" if any(
        event.role == "final_payment" for event in events_tuple
    ) else required_roles[-1]
    query_params = {"person": person, "obligation": obligation}
    target_event_id = next(
        event.event_id for event in events_tuple if event.role == ablation_role
    )
    counterfactual_state = replay_events(
        _without_last_effect(events_tuple, target_event_id), through_time=query_time
    ).state
    counterfactual = _answer_from_state("economics", query_params, counterfactual_state)
    candidate_distractors = (
        *((counterfactual,) if counterfactual != correct else ()),
        f"balance={replayed[f'balance:{person}'] + 10}|obligation=0|xp={replayed[f'xp:{person}']}|key=False",
        f"balance={replayed[f'balance:{person}'] - 7}|obligation={replayed[f'obligation:{obligation}']}|xp={replayed[f'xp:{person}']}|key=True",
        f"balance=5|obligation=4|xp=0|key=False",
    )
    distractors = tuple(dict.fromkeys(candidate_distractors))[:3]
    if len(distractors) != 3:
        raise CasePackError("economics distractors are not distinct")
    options = _options(str(spec["correct_slot"]), correct, distractors)
    claims = _claims(case_id, options, str(spec["correct_slot"]))
    by_role = {event.role: event.event_id for event in events_tuple}
    required = tuple(by_role[role] for role in required_roles)
    relevant = tuple(
        by_role[role]
        for role in (*required_roles, "planned_gift", "false_receipt")
    )
    current_claim = next(claim.claim_id for claim in claims if claim.truth_class == "current")
    rejected = [by_role["planned_gift"], by_role["false_receipt"]]
    if "blocked_purchase" in by_role:
        rejected.append(by_role["blocked_purchase"])
    return BenchmarkCase(
        case_id=case_id,
        family=str(spec["family"]),
        load=str(spec["load"]),
        event_count=int(spec["event_count"]),
        support_depth=depth,
        seed=int(spec["seed"]),
        question=(
            f"What is {person}'s canonical balance, remaining {obligation}, XP, "
            f"and key ownership at T{query_time}?"
        ),
        query_time=query_time,
        query_kind="economics",
        query_params=query_params,
        options=options,
        correct_choice=str(spec["correct_slot"]),
        reasoning_code="EARNED_LEDGER",
        events=events_tuple,
        required_event_refs=required,
        allowed_event_refs=relevant,
        rejected_event_refs=tuple(rejected),
        claims=claims,
        current_claim_ids=(current_claim,),
        ablation_event_id=by_role[
            "final_payment" if "final_payment" in by_role else required_roles[-1]
        ],
        control_ablation_event_id=next(
            event.event_id for event in events_tuple if event.role.startswith("decoy_")
        ),
    )


def _intent_case(spec: Mapping[str, Any]) -> BenchmarkCase:
    case_id = str(spec["case_id"])
    depth = int(spec["support_depth"])
    origin, observer, current_owner, proposed_owner = _names(int(spec["seed"]), 4, "")
    item = "Key" + _case_suffix(case_id)
    events: list[Event] = [
        _event(
            case_id,
            "initial_truth",
            0,
            actor="registry",
            effects=(
                ("set", f"owner:{item}", origin),
                ("set", f"location:{item}", "Vault"),
            ),
            prose=f"The registry records {origin} owning {item}, located in Vault.",
        )
    ]
    required_roles = ["initial_truth"]
    if depth >= 2:
        events.append(
            _event(
                case_id,
                "observation",
                1,
                kind="observation",
                actor=observer,
                requires=((f"owner:{item}", "eq", origin),),
                effects=(
                    ("set", f"knows:{observer}:owner:{item}", origin),
                    ("set", f"knows:{observer}:location:{item}", "Vault"),
                ),
                prose=f"{observer} directly observes {origin} with {item} in Vault.",
            )
        )
        required_roles.append("observation")
    if depth >= 3:
        events.append(
            _event(
                case_id,
                "transfer",
                2,
                actor="registry",
                requires=((f"owner:{item}", "eq", origin),),
                effects=(("set", f"owner:{item}", current_owner),),
                prose=f"The registry transfers {item} from {origin} to {current_owner}.",
            )
        )
        required_roles.append("transfer")
    if depth >= 4:
        events.append(
            _event(
                case_id,
                "authenticated_message",
                3,
                kind="message",
                actor="registry",
                requires=((f"owner:{item}", "eq", current_owner),),
                effects=(("set", f"knows:{observer}:owner:{item}", current_owner),),
                prose=f"An authenticated receipt tells {observer} that {current_owner} now owns {item}; it gives no new location.",
            )
        )
        required_roles.append("authenticated_message")
    if depth >= 5:
        events.append(
            _event(
                case_id,
                "private_move",
                4,
                actor=current_owner,
                requires=((f"owner:{item}", "eq", current_owner),),
                effects=(("set", f"location:{item}", "Drawer"),),
                prose=f"{current_owner} privately moves {item} from Vault to Drawer; {observer} is not informed.",
            )
        )
        required_roles.append("private_move")
    query_time = depth - 1
    events.extend(
        [
            _event(
                case_id,
                "private_plan",
                1,
                kind="plan",
                authority="noncanonical",
                status="planned",
                actor=origin,
                effects=(("set", f"owner:{item}", proposed_owner),),
                prose=f"{origin} privately plans to give {item} to {proposed_owner}; the plan is not performed.",
                record_time=70,
            ),
            _event(
                case_id,
                "rumor",
                2,
                kind="rumor",
                authority="noncanonical",
                status="reported",
                actor="bystander",
                effects=(("set", f"knows:{observer}:owner:{item}", proposed_owner),),
                prose=f"A bystander rumor says {proposed_owner} owns {item}; rumor is not knowledge or title.",
                record_time=71,
            ),
        ]
    )
    events_tuple = _pad_events(
        case_id,
        events,
        target_count=int(spec["event_count"]),
        seed=int(spec["seed"]),
        focus=f"{observer} {item} owner location",
    )
    replayed = replay_events(events_tuple, through_time=query_time).state
    correct = (
        f"truth={replayed.get(f'owner:{item}', 'UNKNOWN')}@"
        f"{replayed.get(f'location:{item}', 'UNKNOWN')}|"
        f"known={replayed.get(f'knows:{observer}:owner:{item}', 'UNKNOWN')}@"
        f"{replayed.get(f'knows:{observer}:location:{item}', 'UNKNOWN')}"
    )
    query_params = {"item": item, "observer": observer}
    target_event_id = next(
        event.event_id for event in events_tuple if event.role == required_roles[-1]
    )
    counterfactual_state = replay_events(
        _without_last_effect(events_tuple, target_event_id), through_time=query_time
    ).state
    counterfactual = _answer_from_state(
        "truth_knowledge", query_params, counterfactual_state
    )
    candidate_distractors = [
        *((counterfactual,) if counterfactual != correct else ()),
        f"truth={proposed_owner}@Vault|known={proposed_owner}@Vault",
        f"truth={replayed.get(f'owner:{item}', 'UNKNOWN')}@{replayed.get(f'location:{item}', 'UNKNOWN')}|known={replayed.get(f'owner:{item}', 'UNKNOWN')}@UNKNOWN",
        f"truth={origin}@Vault|known=UNKNOWN@UNKNOWN",
        f"truth={current_owner}@Drawer|known={proposed_owner}@Vault",
    ]
    distractors_list: list[str] = []
    for candidate in candidate_distractors:
        if candidate != correct and candidate not in distractors_list:
            distractors_list.append(candidate)
        if len(distractors_list) == 3:
            break
    distractors = tuple(distractors_list)
    options = _options(str(spec["correct_slot"]), correct, distractors)
    claims = _claims(case_id, options, str(spec["correct_slot"]))
    by_role = {event.role: event.event_id for event in events_tuple}
    required = tuple(by_role[role] for role in required_roles)
    relevant = tuple(by_role[role] for role in (*required_roles, "private_plan", "rumor"))
    current_claim = next(claim.claim_id for claim in claims if claim.truth_class == "current")
    return BenchmarkCase(
        case_id=case_id,
        family=str(spec["family"]),
        load=str(spec["load"]),
        event_count=int(spec["event_count"]),
        support_depth=depth,
        seed=int(spec["seed"]),
        question=(
            f"At T{query_time}, what is the actual owner/location of {item}, and "
            f"what owner/location does {observer} know?"
        ),
        query_time=query_time,
        query_kind="truth_knowledge",
        query_params=query_params,
        options=options,
        correct_choice=str(spec["correct_slot"]),
        reasoning_code="TRUTH_VS_KNOWLEDGE",
        events=events_tuple,
        required_event_refs=required,
        allowed_event_refs=relevant,
        rejected_event_refs=(by_role["private_plan"], by_role["rumor"]),
        claims=claims,
        current_claim_ids=(current_claim,),
        ablation_event_id=by_role[required_roles[-1]],
        control_ablation_event_id=next(
            event.event_id for event in events_tuple if event.role.startswith("decoy_")
        ),
    )


_CASE_BUILDERS = {
    "temporal_authority": _temporal_case,
    "containment": _containment_case,
    "transformation": _transformation_case,
    "economics_obligations": _economics_case,
    "intent_knowledge": _intent_case,
}


def load_case_pack(path: str | Path) -> tuple[Mapping[str, Any], tuple[BenchmarkCase, ...]]:
    source = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(source, object_pairs_hook=_reject_duplicate_pairs)
    except json.JSONDecodeError as error:
        raise CasePackError(f"case pack is not strict JSON: {error}") from error
    if not isinstance(payload, dict):
        raise CasePackError("case pack root must be an object")
    if payload.get("schema_version") != CASE_PACK_SCHEMA_VERSION:
        raise CasePackError("unsupported case pack schema")
    specs = payload.get("cases")
    if not isinstance(specs, list) or len(specs) != 20:
        raise CasePackError("case pack must contain exactly 20 cases")
    cases: list[BenchmarkCase] = []
    seen: set[str] = set()
    for spec in specs:
        if not isinstance(spec, dict):
            raise CasePackError("case specification must be an object")
        expected_keys = {
            "case_id",
            "family",
            "load",
            "event_count",
            "support_depth",
            "seed",
            "correct_slot",
        }
        if set(spec) != expected_keys:
            raise CasePackError(
                f"case specification keys differ: {sorted(set(spec) ^ expected_keys)}"
            )
        case_id = str(spec["case_id"])
        if case_id in seen:
            raise CasePackError(f"duplicate case id {case_id}")
        seen.add(case_id)
        builder = _CASE_BUILDERS.get(str(spec["family"]))
        if builder is None:
            raise CasePackError(f"unknown family {spec['family']!r}")
        cases.append(builder(spec))
    validate_case_pack(payload, tuple(cases))
    return payload, tuple(cases)


def _reject_duplicate_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ModelOutputRejected(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _event_body(event: Event, *, include_prose: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "event_id": event.event_id,
        "effective_time": event.effective_time,
        "record_time": event.record_time,
        "kind": event.kind,
        "authority": event.authority,
        "status": event.status,
        "actor": event.actor,
        "requires": [asdict(requirement) for requirement in event.requires],
        "effects": [asdict(effect) for effect in event.effects],
    }
    if include_prose:
        body["history_text"] = event.prose
    return body


def _raw_event(event: Event) -> dict[str, Any]:
    body = _event_body(event, include_prose=True)
    body["source_sha256"] = _sha256_text(_canonical_json(body))
    return body


_KIND_CODES = {
    "actual": "A",
    "plan": "P",
    "rumor": "R",
    "claim": "C",
    "observation": "O",
    "message": "M",
}
_AUTHORITY_CODES = {"canonical": "K", "noncanonical": "N"}
_STATUS_CODES = {
    "completed": "C",
    "planned": "P",
    "attempted": "A",
    "reported": "R",
}


def compact_event(event: Event) -> list[Any]:
    """A fixed-position typed record; provenance lives in the opaque ref index."""

    return [
        event.event_id,
        event.effective_time,
        event.record_time,
        _KIND_CODES[event.kind],
        _AUTHORITY_CODES[event.authority],
        _STATUS_CODES[event.status],
        [[item.key, item.op, item.value] for item in event.requires],
        [[item.op, item.key, item.value] for item in event.effects],
    ]


def compressed_packet(case: BenchmarkCase) -> dict[str, Any]:
    """Return a query-blind compact representation of the complete history."""

    return {
        "format": "compact_typed_ledger_v1",
        "record_columns": ["ref", "effective_t", "record_t", "kind", "authority", "status", "requires", "effects"],
        "records": [compact_event(event) for event in case.events],
    }


def raw_packet(case: BenchmarkCase) -> dict[str, Any]:
    return {
        "format": "full_verbose_history_v1",
        "events_in_record_order": [_raw_event(event) for event in case.events],
    }


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _lexical_tokens(value: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(value)]


def retrieval_packet(case: BenchmarkCase) -> dict[str, Any]:
    """A strong conventional lexical retrieval plus generic dependency closure."""

    documents = [_raw_event(event) for event in case.events]
    texts = [_canonical_json(document) for document in documents]
    tokenized = [_lexical_tokens(text) for text in texts]
    query = case.question + " " + " ".join(case.options.values())
    query_terms = _lexical_tokens(query)
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))
    average_length = sum(map(len, tokenized)) / max(len(tokenized), 1)
    scores: list[tuple[float, str, dict[str, Any]]] = []
    for document, tokens in zip(documents, tokenized):
        frequencies = Counter(tokens)
        score = 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            document_count = len(documents)
            df = document_frequency[term]
            inverse = math.log(1.0 + (document_count - df + 0.5) / (df + 0.5))
            denominator = frequency + 1.2 * (
                1.0 - 0.75 + 0.75 * len(tokens) / max(average_length, 1.0)
            )
            score += inverse * (frequency * 2.2 / denominator)
        scores.append((score, str(document["event_id"]), document))
    scores.sort(key=lambda item: (-item[0], item[1]))

    byte_budget = min(
        len(_canonical_json(raw_packet(case)).encode("utf-8")),
        4 * len(_canonical_json(compressed_packet(case)).encode("utf-8")),
    )
    score_by_id = {event_id: score for score, event_id, _ in scores}
    event_by_id = {event.event_id: event for event in case.events}
    ranked_ids = [event_id for _, event_id, _ in scores]
    selected_ids: list[str] = ranked_ids[: min(3, len(ranked_ids))]

    stop_tokens = {
        "set",
        "inc",
        "delete",
        "eq",
        "gte",
        "true",
        "false",
        "actual",
        "canonical",
        "completed",
        "decoy",
    }

    def semantic_tokens(event: Event) -> set[str]:
        values: list[str] = []
        for requirement in event.requires:
            values.extend((requirement.key, str(requirement.value)))
        for effect in event.effects:
            values.extend((effect.key, str(effect.value)))
        return {
            token
            for token in _lexical_tokens(" ".join(values))
            if token not in stop_tokens and len(token) >= 3
        }

    # Generic backward/forward closure over structured keys and values.  It is
    # query-conditioned through the BM25 seeds but has no access to gold refs.
    changed = True
    while changed:
        changed = False
        frontier = set().union(
            *(semantic_tokens(event_by_id[event_id]) for event_id in selected_ids)
        )
        for event_id in ranked_ids:
            if event_id in selected_ids:
                continue
            if frontier & semantic_tokens(event_by_id[event_id]):
                selected_ids.append(event_id)
                changed = True

    # Add ranked raw chunks while the conservative four-times-C context budget
    # permits.  B is intentionally allowed more state than C to avoid a weak
    # retrieval straw man; actual prompt tokens remain reported.
    candidate_ids = [*selected_ids, *[item for item in ranked_ids if item not in selected_ids]]
    selected: list[dict[str, Any]] = []
    for event_id in candidate_ids:
        document = next(document for _, item_id, document in scores if item_id == event_id)
        score = score_by_id[event_id]
        candidate = {
            "format": "retrieved_raw_chunks_v1",
            "retrieval": "deterministic BM25 lexical seeds plus key/value dependency closure",
            "chunks": [*selected, {**document, "retrieval_score": round(score, 9)}],
            "omitted_event_count": len(documents) - len(selected) - 1,
        }
        if len(_canonical_json(candidate).encode("utf-8")) <= byte_budget:
            selected.append({**document, "retrieval_score": round(score, 9)})
    if not selected:
        selected.append({**scores[0][2], "retrieval_score": round(scores[0][0], 9)})
    return {
        "format": "retrieved_raw_chunks_v1",
        "retrieval": "deterministic BM25 lexical seeds plus key/value dependency closure",
        "chunks": selected,
        "omitted_event_count": len(documents) - len(selected),
    }


def representation_packet(case: BenchmarkCase, condition: str) -> dict[str, Any]:
    if condition == "raw":
        return raw_packet(case)
    if condition == "retrieval":
        return retrieval_packet(case)
    if condition == "compressed":
        return compressed_packet(case)
    raise ValueError(f"unknown condition {condition!r}")


def _case_prompt_payload(case: BenchmarkCase, condition: str) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "question": case.question,
        "query_effective_time": case.query_time,
        "options": dict(case.options),
        "candidate_current_claims": [
            {"claim_id": claim.claim_id, "statement": claim.statement}
            for claim in case.claims
        ],
        "representation": representation_packet(case, condition),
    }


SOLVER_PROMPT_PREFIX = """HIVE DECOMPRESSION TEST — FROZEN SOLVER v1

Solve each independent synthetic world using only its supplied representation.
Effective time determines chronology; record time is only arrival order.
Only canonical, completed actual/observation/message events with satisfied
preconditions can change current truth or knowledge. Plans, rumors, claims,
attempts, future events, and unsatisfied effects must not be promoted.

Compact record codes, when that representation is supplied:
[ref,effective_t,record_t,kind,authority,status,requires,effects]
kind A=actual P=plan R=rumor C=claim O=observation M=message;
authority K=canonical N=noncanonical; status C=completed P=planned
A=attempted R=reported. requires=[key,operator,value] and
effects=[operator,key,value]. Opaque refs resolve to frozen source events.
In ablation packets an effect atom ["?",key,null] means that exact value is
unknown. Use INSUFFICIENT only when the query or its causal proof depends on
that unknown; ignore an unknown atom on a provably unrelated key.

Allowed reasoning codes and meanings:
- CURRENT_NOT_PLANNED: select current authoritative state over plans/history.
- INFERRED_CONTAINMENT: derive location through the complete containment chain.
- SUPERSEDED_TRANSFORMATION: follow consumed/replaced forms and earned grade.
- EARNED_LEDGER: apply only completed economic/progression/obligation changes.
- TRUTH_VS_KNOWLEDGE: distinguish world truth from an observer's knowledge.
- INSUFFICIENT_EVIDENCE: a visible unknown atom blocks the required proof.

Return exactly one JSON object, with no markdown fence or trailing prose:
{
  "schema_version": 1,
  "answers": [
    {
      "case_id": "...",
      "answer_choice": "A|B|C|D|INSUFFICIENT",
      "ordered_event_refs": ["opaque refs in effective-time order"],
      "rejected_event_refs": ["relevant non-current or non-applying refs"],
      "selected_current_claim_ids": ["claim ids true at query time"],
      "reasoning_code": "one allowed fixed code"
    }
  ]
}

Every supplied case must appear exactly once. Select only task-relevant event
references. ordered_event_refs must contain every causal prerequisite ref and
every relevant planned, noncanonical, blocked, or future ref needed to reject a
false implication, in nondecreasing effective-time order. rejected_event_refs
must contain exactly those cited refs that do not apply at query time. If a
visible unknown ablation atom blocks the proof, use INSUFFICIENT, empty claim
ids, and INSUFFICIENT_EVIDENCE.
"""


def build_solver_prompt(cases: Sequence[BenchmarkCase], condition: str) -> str:
    payload = {
        "condition_representation": condition,
        "cases": [_case_prompt_payload(case, condition) for case in cases],
    }
    return SOLVER_PROMPT_PREFIX + "\nINPUT:\n" + _pretty_json(payload)


def _event_from_compact(record: Sequence[Any]) -> Event:
    """Decode using compact bytes alone; omitted prose/actor have no authority."""

    if len(record) != 8 or not isinstance(record[0], str):
        raise CasePackError("compact record shape/reference mismatch")
    return Event(
        event_id=str(record[0]),
        role="compact-decoded",
        effective_time=int(record[1]),
        record_time=int(record[2]),
        kind={value: key for key, value in _KIND_CODES.items()}[str(record[3])],
        authority={value: key for key, value in _AUTHORITY_CODES.items()}[
            str(record[4])
        ],
        status={value: key for key, value in _STATUS_CODES.items()}[str(record[5])],
        actor="",
        requires=tuple(Requirement(*item) for item in record[6]),
        effects=tuple(Effect(*item) for item in record[7]),
        prose="",
    )


def validate_case_pack(payload: Mapping[str, Any], cases: tuple[BenchmarkCase, ...]) -> None:
    case_ids = {case.case_id for case in cases}
    if len(case_ids) != 20:
        raise CasePackError("case IDs must be unique")
    if Counter(case.family for case in cases) != Counter(
        {
            "temporal_authority": 4,
            "containment": 4,
            "transformation": 4,
            "economics_obligations": 4,
            "intent_knowledge": 4,
        }
    ):
        raise CasePackError("pack must contain four cases in each of five families")
    if Counter(case.correct_choice for case in cases) != Counter(
        {"A": 5, "B": 5, "C": 5, "D": 5}
    ):
        raise CasePackError("correct answer positions must be balanced")
    for case in cases:
        if len(case.events) != case.event_count:
            raise CasePackError(f"{case.case_id} event count mismatch")
        event_ids = [event.event_id for event in case.events]
        if len(event_ids) != len(set(event_ids)):
            raise CasePackError(f"{case.case_id} has duplicate event ids")
        if len(case.required_event_refs) != case.support_depth:
            raise CasePackError(f"{case.case_id} support depth mismatch")
        if not set(case.required_event_refs).issubset(case.allowed_event_refs):
            raise CasePackError(f"{case.case_id} required refs are not allowed")
        if not set(case.rejected_event_refs).issubset(case.allowed_event_refs):
            raise CasePackError(f"{case.case_id} rejected refs are not allowed")
        if _answer_from_replay(case) != case.options[case.correct_choice]:
            raise CasePackError(f"{case.case_id} fixture and replay oracle disagree")
        compact = compressed_packet(case)
        records = compact["records"]
        if any(key in compact for key in ("question", "answer", "gold")):
            raise CasePackError("compressed packet contains query or answer leakage")
        _decoded = tuple(_event_from_compact(record) for record in records)
        # A semantic mismatch is measured as compression loss in PRECHECK and
        # the C condition.  It is not silently repaired or relabeled as a
        # harness defect.  Structural decode errors above still fail closed.
        retrieval = retrieval_packet(case)
        retrieval_budget = min(
            len(_canonical_json(raw_packet(case)).encode()),
            4 * len(_canonical_json(compact).encode()),
        )
        if len(_canonical_json(retrieval).encode()) > retrieval_budget:
            raise CasePackError(f"{case.case_id} retrieval exceeded frozen budget")

    batches = payload.get("batches")
    if not isinstance(batches, list) or len(batches) != 6:
        raise CasePackError("exactly six batches are required")
    seen_in_batches: list[str] = []
    positions: dict[str, Counter[int]] = {name: Counter() for name in CONDITIONS}
    for batch in batches:
        if set(batch) != {"batch_id", "case_ids", "condition_order"}:
            raise CasePackError("batch keys differ from frozen schema")
        ids = batch["case_ids"]
        order = batch["condition_order"]
        if not isinstance(ids, list) or not 3 <= len(ids) <= 4:
            raise CasePackError("batch must contain three or four cases")
        if set(order) != set(CONDITIONS) or len(order) != 3:
            raise CasePackError("each batch must contain each condition once")
        seen_in_batches.extend(map(str, ids))
        for position, condition in enumerate(order):
            positions[str(condition)][position] += 1
    if Counter(seen_in_batches) != Counter({case_id: 1 for case_id in case_ids}):
        raise CasePackError("batches must cover every case exactly once")
    for condition in CONDITIONS:
        if positions[condition] != Counter({0: 2, 1: 2, 2: 2}):
            raise CasePackError("condition order is not fully counterbalanced")

    ablation = payload.get("ablation")
    if not isinstance(ablation, dict) or set(ablation) != {
        "essential_case_ids",
        "control_case_ids",
        "counterbalanced_calls",
    }:
        raise CasePackError("ablation declaration differs from frozen schema")
    essential_ids = list(map(str, ablation["essential_case_ids"]))
    control_ids = list(map(str, ablation["control_case_ids"]))
    if len(essential_ids) != 5 or len(control_ids) != 5:
        raise CasePackError("ablation requires five indispensable cases")
    if set(essential_ids) != set(control_ids):
        raise CasePackError(
            "every indispensable ablation needs a same-case irrelevant control"
        )
    calls = ablation["counterbalanced_calls"]
    if (
        not isinstance(calls, list)
        or len(calls) != ABLATION_CALLS
        or any(not isinstance(call, list) or len(call) != 5 for call in calls)
    ):
        raise CasePackError("ablation requires two five-entry blinded calls")
    expected_roles = Counter(
        [(case_id, "essential") for case_id in essential_ids]
        + [(case_id, "control") for case_id in control_ids]
    )
    observed_roles: Counter[tuple[str, str]] = Counter()
    for call in calls:
        seen_originals: set[str] = set()
        roles: Counter[str] = Counter()
        for entry in call:
            if not isinstance(entry, dict) or set(entry) != {"case_id", "role"}:
                raise CasePackError("ablation call entry differs from frozen schema")
            case_id = str(entry["case_id"])
            role = str(entry["role"])
            if case_id in seen_originals:
                raise CasePackError(
                    "an ablation call cannot expose two versions of the same world"
                )
            seen_originals.add(case_id)
            roles[role] += 1
            observed_roles[(case_id, role)] += 1
        if sorted(roles.values()) != [2, 3] or set(roles) != {"essential", "control"}:
            raise CasePackError("each ablation call must mix essential and control roles")
    if observed_roles != expected_roles:
        raise CasePackError("ablation order/roles do not match declared sets")
    by_case = {case.case_id: case for case in cases}
    for case_id in essential_ids:
        case = by_case[str(case_id)]
        without = _without_last_effect(case.events, case.ablation_event_id)
        mutated = replay_events(without, through_time=case.query_time)
        original = replay_events(case.events, through_time=case.query_time)
        if mutated.state == original.state:
            raise CasePackError(
                f"{case.case_id} declared ablation is not counterfactually necessary"
            )
        counterfactual_answer = _answer_from_replay(
            replace(case, events=without)
        )
        if (
            counterfactual_answer == _answer_from_replay(case)
            or counterfactual_answer not in case.options.values()
        ):
            raise CasePackError(
                f"{case.case_id} ablation does not make the answer non-identifiable"
            )
    for control_id in control_ids:
        control = by_case[control_id]
        without_control = _without_last_effect(
            control.events, control.control_ablation_event_id
        )
        if replay_events(
            without_control, through_time=control.query_time
        ).state != replay_events(control.events, through_time=control.query_time).state:
            raise CasePackError("anti-reflex ablation control changed current truth")


def _ablation_packet(case: BenchmarkCase, *, control: bool) -> dict[str, Any]:
    original = compressed_packet(case)
    target_id = (
        case.control_ablation_event_id if control else case.ablation_event_id
    )
    records = copy.deepcopy(list(original["records"]))
    target = next(record for record in records if record[0] == target_id)
    if not target[7]:
        raise CasePackError("ablation target has no visible effect atom")
    effect = list(target[7][-1])
    target[7][-1] = ["?", effect[1], None]
    return {
        "format": "compact_typed_ledger_v1_ablation",
        "record_columns": original["record_columns"],
        "records": records,
    }


def _ablation_alias(case_id: str, role: str) -> str:
    return "AB-" + hashlib.sha256(f"blind|{case_id}|{role}".encode()).hexdigest()[:10]


def build_ablation_prompt(
    entries: Sequence[tuple[BenchmarkCase, str]],
) -> tuple[str, tuple[tuple[str, BenchmarkCase, str], ...]]:
    payload_cases: list[dict[str, Any]] = []
    blinded: list[tuple[str, BenchmarkCase, str]] = []
    for case, role in entries:
        if role not in {"essential", "control"}:
            raise CasePackError("unknown ablation role")
        alias = _ablation_alias(case.case_id, role)
        item = _case_prompt_payload(case, "compressed")
        item["case_id"] = alias
        item["representation"] = _ablation_packet(case, control=role == "control")
        payload_cases.append(item)
        blinded.append((alias, case, role))
    payload = {
        "condition_representation": "compressed_ablation",
        "cases": payload_cases,
    }
    return (
        SOLVER_PROMPT_PREFIX + "\nINPUT:\n" + _pretty_json(payload),
        tuple(blinded),
    )


def parse_model_output(raw: str, expected_case_ids: Sequence[str]) -> tuple[ParsedAnswer, ...]:
    if not isinstance(raw, str):
        raise ModelOutputRejected("model output must be text")
    if len(raw.encode("utf-8")) > 65_536:
        raise ModelOutputRejected("model output exceeds 65,536 UTF-8 bytes")
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_pairs)
    except (json.JSONDecodeError, ModelOutputRejected) as error:
        raise ModelOutputRejected(f"strict JSON parsing failed: {error}") from error
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "answers"}:
        raise ModelOutputRejected("root must have exactly schema_version and answers")
    if payload["schema_version"] != OUTPUT_SCHEMA_VERSION:
        raise ModelOutputRejected("unsupported output schema version")
    answers = payload["answers"]
    if not isinstance(answers, list) or len(answers) != len(expected_case_ids):
        raise ModelOutputRejected("answers length differs from the batch")
    expected_keys = {
        "case_id",
        "answer_choice",
        "ordered_event_refs",
        "rejected_event_refs",
        "selected_current_claim_ids",
        "reasoning_code",
    }
    parsed: list[ParsedAnswer] = []
    for item in answers:
        if not isinstance(item, dict) or set(item) != expected_keys:
            raise ModelOutputRejected("answer object has missing or unknown fields")
        scalar_fields = ("case_id", "answer_choice", "reasoning_code")
        if any(not isinstance(item[field], str) for field in scalar_fields):
            raise ModelOutputRejected("answer scalar fields must be strings")
        if item["answer_choice"] not in ANSWER_CHOICES:
            raise ModelOutputRejected("unknown answer choice")
        if item["reasoning_code"] not in REASONING_CODES:
            raise ModelOutputRejected("unknown reasoning code")
        list_fields = (
            "ordered_event_refs",
            "rejected_event_refs",
            "selected_current_claim_ids",
        )
        for field in list_fields:
            value = item[field]
            if (
                not isinstance(value, list)
                or len(value) > 16
                or any(not isinstance(entry, str) or not entry for entry in value)
                or len(value) != len(set(value))
            ):
                raise ModelOutputRejected(f"{field} violates strict list bounds")
        parsed.append(
            ParsedAnswer(
                case_id=item["case_id"],
                answer_choice=item["answer_choice"],
                ordered_event_refs=tuple(item["ordered_event_refs"]),
                rejected_event_refs=tuple(item["rejected_event_refs"]),
                selected_current_claim_ids=tuple(item["selected_current_claim_ids"]),
                reasoning_code=item["reasoning_code"],
            )
        )
    if [answer.case_id for answer in parsed] != list(expected_case_ids):
        raise ModelOutputRejected("answers must match batch case order exactly")
    return tuple(parsed)


def _chronological(case: BenchmarkCase, references: Sequence[str]) -> bool:
    by_id = {event.event_id: event for event in case.events}
    if any(reference not in by_id for reference in references):
        return False
    effective_times = [by_id[reference].effective_time for reference in references]
    return effective_times == sorted(effective_times)


def grade_answer(
    case: BenchmarkCase,
    answer: ParsedAnswer,
    *,
    condition: str,
    compression_loss: bool = False,
    ablation_expected_insufficient: bool = False,
) -> CaseScore:
    reasons: list[str] = []
    known_events = {event.event_id for event in case.events}
    known_claims = {claim.claim_id for claim in case.claims}
    if any(reference not in known_events for reference in answer.ordered_event_refs):
        reasons.append("unknown_event_ref")
    if any(reference not in known_events for reference in answer.rejected_event_refs):
        reasons.append("unknown_rejected_ref")
    if any(claim not in known_claims for claim in answer.selected_current_claim_ids):
        reasons.append("unknown_claim_id")
    if ablation_expected_insufficient:
        answer_correct = answer.answer_choice == "INSUFFICIENT"
        claims_correct = answer.selected_current_claim_ids == ()
        reasoning_correct = answer.reasoning_code == "INSUFFICIENT_EVIDENCE"
        chronology_authority = (
            _chronological(case, answer.ordered_event_refs)
            and set(answer.rejected_event_refs).issubset(answer.ordered_event_refs)
        )
        reconstruction_correct = chronology_authority
        required_recall = 0.0
        allowed_precision = 1.0 if not answer.ordered_event_refs else 0.0
    else:
        answer_correct = answer.answer_choice == case.correct_choice
        claims_correct = answer.selected_current_claim_ids == case.current_claim_ids
        reasoning_correct = answer.reasoning_code == case.reasoning_code
        selected = set(answer.ordered_event_refs)
        required = set(case.required_event_refs) | set(case.rejected_event_refs)
        allowed = set(case.allowed_event_refs)
        required_recall = len(selected & required) / max(len(required), 1)
        allowed_precision = len(selected & allowed) / max(len(selected), 1)
        reconstruction_correct = required_recall == 1.0 and allowed_precision == 1.0
        chronology_authority = (
            _chronological(case, answer.ordered_event_refs)
            and set(answer.rejected_event_refs) == set(case.rejected_event_refs)
            and set(answer.rejected_event_refs).issubset(selected)
        )

    noncurrent_claims = {
        claim.claim_id for claim in case.claims if claim.truth_class != "current"
    }
    illegal_promotions = len(
        set(answer.selected_current_claim_ids) & noncurrent_claims
    )
    if not answer_correct:
        reasons.append("answer_incorrect")
    if not reconstruction_correct:
        reasons.append("reconstruction_incorrect")
    if not chronology_authority:
        reasons.append("chronology_or_authority_incorrect")
    if not claims_correct:
        reasons.append("current_claims_incorrect")
    if not reasoning_correct:
        reasons.append("reasoning_code_incorrect")
    if illegal_promotions:
        reasons.append("illegal_state_promotion")
    if compression_loss:
        reasons.append("compression_loss")
    primary = (
        not reasons
        and answer_correct
        and reconstruction_correct
        and chronology_authority
        and claims_correct
        and reasoning_correct
        and illegal_promotions == 0
    )
    return CaseScore(
        case_id=case.case_id,
        condition=condition,
        valid_output=True,
        primary_pass=primary,
        answer_correct=answer_correct,
        chronology_authority_correct=chronology_authority,
        reconstruction_correct=reconstruction_correct,
        current_claims_correct=claims_correct,
        illegal_state_promotions=illegal_promotions,
        required_ref_recall=round(required_recall, 9),
        allowed_ref_precision=round(allowed_precision, 9),
        compression_loss=compression_loss,
        failure_reasons=tuple(reasons),
    )


def rejected_batch_scores(
    cases: Sequence[BenchmarkCase], condition: str, reason: str
) -> tuple[CaseScore, ...]:
    return tuple(
        CaseScore(
            case_id=case.case_id,
            condition=condition,
            valid_output=False,
            primary_pass=False,
            answer_correct=False,
            chronology_authority_correct=False,
            reconstruction_correct=False,
            current_claims_correct=False,
            illegal_state_promotions=0,
            required_ref_recall=0.0,
            allowed_ref_precision=0.0,
            compression_loss=False,
            failure_reasons=(reason,),
        )
        for case in cases
    )


def _git_revision_and_sources(repo_root: Path) -> tuple[str, dict[str, str]]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError("could not bind the experiment to an exact Git revision")
    for args in (
        ["git", "diff", "--quiet", "--", ".", ":(exclude,glob)**/*.pyc"],
        [
            "git",
            "diff",
            "--cached",
            "--quiet",
            "--",
            ".",
            ":(exclude,glob)**/*.pyc",
        ],
    ):
        if subprocess.run(args, cwd=repo_root).returncode != 0:
            raise RuntimeError("experiment refuses tracked or staged source changes")
    observed: dict[str, str] = {}
    for relative in CRITICAL_SOURCE_FILES:
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=repo_root,
            capture_output=True,
        )
        if tracked.returncode != 0:
            raise RuntimeError(f"critical experiment file is not tracked: {relative}")
        head_object = subprocess.run(
            ["git", "rev-parse", f"HEAD:{relative}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        working_object = subprocess.run(
            ["git", "hash-object", "--path", relative, "--", relative],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if head_object != working_object:
            raise RuntimeError(f"critical file differs from HEAD: {relative}")
        head_bytes = subprocess.run(
            ["git", "show", f"HEAD:{relative}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        ).stdout
        observed[relative] = _sha256_bytes(head_bytes)
    return revision, dict(sorted(observed.items()))


def _sealed_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(payload))
    result["payload_sha256"] = _sha256_text(_canonical_json(result))
    return result


def _expanded_pack_payload(cases: Sequence[BenchmarkCase]) -> list[dict[str, Any]]:
    return [asdict(case) for case in cases]


def _representation_stats(case: BenchmarkCase) -> dict[str, Any]:
    packets = {
        condition: representation_packet(case, condition) for condition in CONDITIONS
    }
    retrieval_refs = {
        str(chunk["event_id"]) for chunk in packets["retrieval"]["chunks"]
    }
    relevant_refs = set(case.required_event_refs) | set(case.rejected_event_refs)
    compressed_refs = {str(record[0]) for record in packets["compressed"]["records"]}
    decoded = tuple(
        _event_from_compact(record) for record in packets["compressed"]["records"]
    )
    source_replay = replay_events(case.events, through_time=case.query_time)
    decoded_replay = replay_events(decoded, through_time=case.query_time)
    decoded_case = replace(case, events=decoded)
    relevant = set(case.allowed_event_refs)
    replay_match = (
        decoded_replay.state == source_replay.state
        and _answer_from_replay(decoded_case) == _answer_from_replay(case)
        and tuple(
            event_id for event_id in decoded_replay.applied_event_ids if event_id in relevant
        )
        == tuple(
            event_id for event_id in source_replay.applied_event_ids if event_id in relevant
        )
        and tuple(
            event_id for event_id in decoded_replay.rejected_event_ids if event_id in relevant
        )
        == tuple(
            event_id for event_id in source_replay.rejected_event_ids if event_id in relevant
        )
    )
    source_index = {
        event.event_id: _raw_event(event)["source_sha256"] for event in case.events
    }
    return {
        "case_id": case.case_id,
        "event_count": len(case.events),
        "support_depth": case.support_depth,
        "representation_utf8_bytes": {
            condition: len(_canonical_json(packet).encode("utf-8"))
            for condition, packet in packets.items()
        },
        "raw_source_index": source_index,
        "raw_source_hashes_recomputed": all(
            digest
            == _sha256_text(
                _canonical_json(_event_body(event, include_prose=True))
            )
            for event in case.events
            for digest in (source_index[event.event_id],)
        ),
        "retrieval_selected_refs": sorted(retrieval_refs),
        "retrieval_required_ref_recall": round(
            len(retrieval_refs & set(case.required_event_refs))
            / max(len(case.required_event_refs), 1),
            9,
        ),
        "retrieval_relevant_ref_recall": round(
            len(retrieval_refs & relevant_refs) / max(len(relevant_refs), 1), 9
        ),
        "compressed_required_ref_recall": round(
            len(compressed_refs & set(case.required_event_refs))
            / max(len(case.required_event_refs), 1),
            9,
        ),
        "compressed_task_replay_match": replay_match,
        "compressed_to_raw_byte_ratio": round(
            len(_canonical_json(packets["compressed"]).encode("utf-8"))
            / len(_canonical_json(packets["raw"]).encode("utf-8")),
            9,
        ),
    }


def _score_mapping(score: CaseScore) -> dict[str, Any]:
    return asdict(score)


def _replay_grader(case: BenchmarkCase, answer: ParsedAnswer) -> dict[str, Any]:
    replay_answer = _answer_from_replay(case)
    matching = [slot for slot, value in case.options.items() if value == replay_answer]
    replay_claims = tuple(
        claim.claim_id for claim in case.claims if claim.statement == replay_answer
    )
    return {
        "replay_answer": replay_answer,
        "replay_choice": matching[0] if len(matching) == 1 else None,
        "answer_correct": len(matching) == 1 and answer.answer_choice == matching[0],
        "current_claims_correct": answer.selected_current_claim_ids == replay_claims,
    }


class DecompressionSmokeRunner:
    def __init__(
        self,
        *,
        repo_root: Path,
        output_dir: Path,
        case_pack_payload: Mapping[str, Any],
        cases: Sequence[BenchmarkCase],
        source_revision: str,
        source_file_sha256: Mapping[str, str],
        model_digest: str,
        ask_fn=ask_hive,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.output_dir = output_dir.resolve()
        self.case_pack_payload = copy.deepcopy(dict(case_pack_payload))
        self.cases = tuple(cases)
        self.source_revision = source_revision
        self.source_file_sha256 = dict(source_file_sha256)
        self.model_digest = model_digest
        self.ask_fn = ask_fn
        self.by_case = {case.case_id: case for case in self.cases}
        self.scores: list[CaseScore] = []
        self.ablation_scores: list[CaseScore] = []
        self.decisions_dir = self.output_dir / "decisions"
        self.audit: ProtocolV2AuditStore | None = None

    def _preflight(self) -> dict[str, Any]:
        started = time.monotonic_ns()
        validate_case_pack(self.case_pack_payload, self.cases)
        expanded = _expanded_pack_payload(self.cases)
        stats = [_representation_stats(case) for case in self.cases]
        compression_losses = sum(
            item["compressed_required_ref_recall"] != 1.0
            or item["compressed_task_replay_match"] is not True
            for item in stats
        )
        self.compression_loss_ids = {
            item["case_id"]
            for item in stats
            if item["compressed_required_ref_recall"] != 1.0
            or item["compressed_task_replay_match"] is not True
        }
        if any(item["retrieval_relevant_ref_recall"] != 1.0 for item in stats):
            raise CasePackError(
                "retrieval adequacy gate failed to expose all preregistered relevant refs"
            )
        prompts: dict[str, dict[str, Any]] = {}
        for batch in self.case_pack_payload["batches"]:
            batch_cases = [self.by_case[case_id] for case_id in batch["case_ids"]]
            prompts[str(batch["batch_id"])] = {}
            for condition in CONDITIONS:
                prompt = build_solver_prompt(batch_cases, condition)
                if len(prompt.encode("utf-8")) > 120_000:
                    raise CasePackError("solve prompt exceeds frozen byte safety gate")
                prompts[str(batch["batch_id"])][condition] = {
                    "sha256": _sha256_text(prompt),
                    "chars": len(prompt),
                    "utf8_bytes": len(prompt.encode("utf-8")),
                }
        ablation_prompts: list[dict[str, Any]] = []
        for call_number, call_plan in enumerate(
            self.case_pack_payload["ablation"]["counterbalanced_calls"], start=1
        ):
            ablation_entries = [
                (self.by_case[str(item["case_id"])], str(item["role"]))
                for item in call_plan
            ]
            ablation_prompt, blinded = build_ablation_prompt(ablation_entries)
            if len(ablation_prompt.encode("utf-8")) > 120_000:
                raise CasePackError("ablation prompt exceeds frozen byte safety gate")
            if len({case.case_id for _, case, _ in blinded}) != len(blinded):
                raise CasePackError("ablation prompt contains counterpart world leakage")
            ablation_prompts.append(
                {
                    "call_number": call_number,
                    "sha256": _sha256_text(ablation_prompt),
                    "chars": len(ablation_prompt),
                    "utf8_bytes": len(ablation_prompt.encode("utf-8")),
                    "blinded_aliases": [alias for alias, _, _ in blinded],
                }
            )
        finished = time.monotonic_ns()
        return {
            "schema_version": PROTOCOL_SCHEMA_VERSION,
            "protocol_id": PROTOCOL_ID,
            "case_count": len(self.cases),
            "expanded_case_pack_sha256": _sha256_text(_canonical_json(expanded)),
            "expanded_cases": expanded,
            "representation_stats": stats,
            "compression_loss_count": compression_losses,
            "solver_prompt_template_sha256": _sha256_text(SOLVER_PROMPT_PREFIX),
            "batch_prompts": prompts,
            "ablation_prompts": ablation_prompts,
            "oracle_replay_agreement": True,
            "task_reversibility_passed": compression_losses == 0,
            "preflight_elapsed_ns": finished - started,
            "preflight_elapsed_seconds": round((finished - started) / 1e9, 9),
        }

    def _manifest(self, preflight: Mapping[str, Any]) -> dict[str, Any]:
        assert self.audit is not None
        return _sealed_payload(
            {
                "schema_version": PROTOCOL_SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "source_revision": self.source_revision,
                "source_file_sha256": dict(sorted(self.source_file_sha256.items())),
                "model": MODEL,
                "model_digest": self.model_digest,
                "runtime": {
                    "num_ctx": NUM_CTX,
                    "num_predict": NUM_PREDICT,
                    "temperature": TEMPERATURE,
                    "seed": SEED,
                    "timeout_seconds": TIMEOUT_SECONDS,
                    "physical_attempts_per_call": 1,
                    "max_retries": 1,
                },
                "conditions": list(CONDITIONS),
                "primary_calls": PRIMARY_CALLS,
                "ablation_calls": ABLATION_CALLS,
                "total_calls": TOTAL_CALLS,
                "batch_plan": copy.deepcopy(self.case_pack_payload["batches"]),
                "ablation_plan": copy.deepcopy(self.case_pack_payload["ablation"]),
                "hypothesis_thresholds": {
                    "compressed_primary_passes_min": 16,
                    "compressed_not_worse_than_each_baseline": True,
                    "compressed_support_high_passes_min": 4,
                    "compressed_not_worse_than_each_baseline_support_high": True,
                    "compressed_not_worse_than_each_baseline_distractor_high": True,
                    "compressed_primary_passes_per_family_min": 3,
                    "compressed_illegal_promotions_max": 0,
                    "median_compressed_to_raw_prompt_tokens_max": 0.60,
                    "median_compressed_to_retrieval_prompt_tokens_max": 1.0,
                    "codec_required_ref_recall": 1.0,
                    "essential_ablation_detection_min": 4,
                    "anti_reflex_controls_min": 4,
                },
                "preflight_sha256": _sha256_text(_canonical_json(preflight)),
                "audit_config": self.audit.frozen_config,
                "no_model_judge": True,
                "claim_boundary": (
                    "tests the frozen synthetic representation, not autonomous "
                    "Hive encoder quality"
                ),
            }
        )

    def _write_decision(self, sequence: int, payload: Mapping[str, Any]) -> None:
        _write_exclusive(
            self.decisions_dir / f"decision_{sequence:06d}.json",
            _pretty_json(_sealed_payload(payload)),
        )

    def _run_primary_call(
        self, batch_id: int, condition: str, batch_cases: Sequence[BenchmarkCase]
    ) -> None:
        assert self.audit is not None
        prompt = build_solver_prompt(batch_cases, condition)
        response = self.audit.ask(
            prompt,
            condition=condition,
            chapter=batch_id,
            purpose="decompression solve batch",
            role="default",
            budget_class="generation",
        )
        sequence = len(self.audit.records)
        decision: dict[str, Any] = {
            "schema_version": PROTOCOL_SCHEMA_VERSION,
            "call_id": self.audit.last_call_id,
            "batch_id": batch_id,
            "condition": condition,
            "response_sha256": _sha256_text(response),
        }
        try:
            parsed = parse_model_output(response, [case.case_id for case in batch_cases])
        except ModelOutputRejected as error:
            rejected = rejected_batch_scores(batch_cases, condition, "model_output_rejected")
            self.scores.extend(rejected)
            decision.update(
                {
                    "status": "model_output_rejected",
                    "error": {"type": type(error).__name__, "message": str(error)},
                    "scores": [_score_mapping(score) for score in rejected],
                    "grader_agreement": True,
                }
            )
            self._write_decision(sequence, decision)
            return
        call_scores: list[CaseScore] = []
        replay_grades: list[dict[str, Any]] = []
        grader_agreement = True
        for case, answer in zip(batch_cases, parsed):
            score = grade_answer(
                case,
                answer,
                condition=condition,
                compression_loss=(
                    condition == "compressed"
                    and case.case_id in getattr(self, "compression_loss_ids", set())
                ),
            )
            replay_grade = _replay_grader(case, answer)
            agrees = (
                score.answer_correct == replay_grade["answer_correct"]
                and score.current_claims_correct
                == replay_grade["current_claims_correct"]
            )
            grader_agreement = grader_agreement and agrees
            replay_grades.append({**replay_grade, "agrees_with_fixture": agrees})
            call_scores.append(score)
        if not grader_agreement:
            raise RuntimeError("independent deterministic graders disagreed")
        self.scores.extend(call_scores)
        decision.update(
            {
                "status": "graded",
                "parsed_answers": [asdict(answer) for answer in parsed],
                "fixture_scores": [_score_mapping(score) for score in call_scores],
                "replay_grades": replay_grades,
                "grader_agreement": grader_agreement,
            }
        )
        self._write_decision(sequence, decision)

    def _run_ablation_call(
        self, call_number: int, call_plan: Sequence[Mapping[str, Any]]
    ) -> None:
        assert self.audit is not None
        plan = self.case_pack_payload["ablation"]
        entries = [
            (self.by_case[str(item["case_id"])], str(item["role"]))
            for item in call_plan
        ]
        prompt, blinded = build_ablation_prompt(entries)
        batch_id = 6 + call_number
        response = self.audit.ask(
            prompt,
            condition="compressed_ablation",
            chapter=batch_id,
            purpose=f"minimum sufficient state ablation call {call_number}",
            role="default",
            budget_class="generation",
        )
        sequence = len(self.audit.records)
        decision: dict[str, Any] = {
            "schema_version": PROTOCOL_SCHEMA_VERSION,
            "call_id": self.audit.last_call_id,
            "batch_id": batch_id,
            "ablation_call_number": call_number,
            "condition": "compressed_ablation",
            "response_sha256": _sha256_text(response),
        }
        try:
            parsed = parse_model_output(
                response, [alias for alias, _, _ in blinded]
            )
        except ModelOutputRejected as error:
            rejected = rejected_batch_scores(
                [case for _, case, _ in blinded],
                "compressed_ablation",
                "model_output_rejected",
            )
            self.ablation_scores.extend(rejected)
            decision.update(
                {
                    "status": "model_output_rejected",
                    "error": {"type": type(error).__name__, "message": str(error)},
                    "scores": [_score_mapping(score) for score in rejected],
                }
            )
            self._write_decision(sequence, decision)
            return
        scored: list[CaseScore] = []
        remapped_answers: list[ParsedAnswer] = []
        for (alias, case, role), answer in zip(blinded, parsed):
            is_control = role == "control"
            answer = replace(answer, case_id=case.case_id)
            remapped_answers.append(answer)
            scored.append(
                grade_answer(
                    case,
                    answer,
                    condition="compressed_ablation",
                    ablation_expected_insufficient=not is_control,
                )
            )
        self.ablation_scores.extend(scored)
        decision.update(
            {
                "status": "graded",
                "parsed_answers": [asdict(answer) for answer in remapped_answers],
                "blinded_aliases": [
                    {"alias": alias, "case_id": case.case_id, "role": role}
                    for alias, case, role in blinded
                ],
                "scores": [_score_mapping(score) for score in scored],
                "essential_case_ids": list(plan["essential_case_ids"]),
                "control_case_ids": list(plan["control_case_ids"]),
            }
        )
        self._write_decision(sequence, decision)

    def _call_usage(self) -> dict[str, Any]:
        assert self.audit is not None
        rows: list[dict[str, Any]] = []
        for record in self.audit.records:
            artifact = json.loads(Path(record.artifact_path).read_text(encoding="utf-8"))
            metadata = artifact["transport"]["metadata"]
            rows.append(
                {
                    "call_id": record.call_id,
                    "condition": record.condition,
                    "batch_id": record.chapter,
                    "prompt_tokens": metadata["prompt_eval_count"],
                    "output_tokens": metadata["eval_count"],
                    "latency_seconds": artifact["timing"]["elapsed_seconds"],
                    "server_duration_ns": metadata.get("total_duration_ns"),
                }
            )
        totals: dict[str, Any] = {}
        for condition in (*CONDITIONS, "compressed_ablation"):
            selected = [row for row in rows if row["condition"] == condition]
            totals[condition] = {
                "calls": len(selected),
                "input_tokens": sum(row["prompt_tokens"] for row in selected),
                "output_tokens": sum(row["output_tokens"] for row in selected),
                "latency_seconds": round(
                    sum(row["latency_seconds"] for row in selected), 9
                ),
            }
        raw_ratios: list[float] = []
        retrieval_ratios: list[float] = []
        by_batch_condition = {
            (row["batch_id"], row["condition"]): row for row in rows
        }
        for batch_id in range(1, 7):
            compressed = by_batch_condition[(batch_id, "compressed")]["prompt_tokens"]
            raw = by_batch_condition[(batch_id, "raw")]["prompt_tokens"]
            retrieval = by_batch_condition[(batch_id, "retrieval")]["prompt_tokens"]
            raw_ratios.append(compressed / raw)
            retrieval_ratios.append(compressed / retrieval)
        return {
            "calls": rows,
            "totals": totals,
            "median_compressed_to_raw_prompt_token_ratio": round(
                median(raw_ratios), 9
            ),
            "median_compressed_to_retrieval_prompt_token_ratio": round(
                median(retrieval_ratios), 9
            ),
            "paired_compressed_to_raw_prompt_token_ratios": [
                round(value, 9) for value in raw_ratios
            ],
            "paired_compressed_to_retrieval_prompt_token_ratios": [
                round(value, 9) for value in retrieval_ratios
            ],
        }

    @staticmethod
    def _verify_sealed_json(path: Path, field: str = "payload_sha256") -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        observed = payload.get(field)
        unsigned = dict(payload)
        unsigned.pop(field, None)
        expected = _sha256_text(_canonical_json(unsigned))
        if observed != expected:
            raise RuntimeError(f"sealed JSON payload hash mismatch: {path.name}")
        return payload

    def _verify_evidence(self, preflight: Mapping[str, Any]) -> dict[str, Any]:
        """Reopen and qualify every durable artifact before declaring VALID."""

        assert self.audit is not None
        records = self.audit.records
        if len(records) != TOTAL_CALLS:
            raise RuntimeError("postflight call count mismatch")
        call_files = sorted(self.audit.calls_dir.glob("call_*.json"))
        decision_files = sorted(self.decisions_dir.glob("decision_*.json"))
        if len(call_files) != TOTAL_CALLS or len(decision_files) != TOTAL_CALLS:
            raise RuntimeError("postflight artifact/decision count mismatch")
        event_lines = [
            json.loads(line)
            for line in self.audit.events_path.read_text(encoding="utf-8").splitlines()
        ]
        if len(event_lines) != TOTAL_CALLS * 2:
            raise RuntimeError("postflight audit journal length mismatch")

        call_hashes: dict[str, str] = {}
        decision_hashes: dict[str, str] = {}
        expected_sequence = [
            (int(batch["batch_id"]), str(condition))
            for batch in self.case_pack_payload["batches"]
            for condition in batch["condition_order"]
        ] + [
            (6 + call_number, "compressed_ablation")
            for call_number in range(1, ABLATION_CALLS + 1)
        ]
        for index, (record, call_path, decision_path) in enumerate(
            zip(records, call_files, decision_files), start=1
        ):
            expected_call_id = f"call_{index:06d}"
            if record.call_id != expected_call_id or call_path.stem != expected_call_id:
                raise RuntimeError("postflight call sequence mismatch")
            expected_batch, expected_condition = expected_sequence[index - 1]
            if (record.chapter, record.condition) != (
                expected_batch,
                expected_condition,
            ):
                raise RuntimeError("postflight condition order mismatch")
            call_bytes = call_path.read_bytes()
            call_file_sha = _sha256_bytes(call_bytes)
            if call_file_sha != record.artifact_file_sha256:
                raise RuntimeError("postflight call file hash mismatch")
            artifact = json.loads(call_bytes.decode("utf-8"))
            unsigned_artifact = dict(artifact)
            observed_payload_sha = unsigned_artifact.pop("artifact_payload_sha256", None)
            expected_payload_sha = _sha256_bytes(
                (_canonical_json(unsigned_artifact) + "\n").encode("utf-8")
            )
            if observed_payload_sha != expected_payload_sha:
                raise RuntimeError("postflight call payload hash mismatch")
            if artifact.get("sequence") != index or artifact.get("call_id") != expected_call_id:
                raise RuntimeError("postflight call identity mismatch")
            if artifact.get("status") != "completed" or record.status != "completed":
                raise RuntimeError("postflight includes incomplete physical call")
            request = artifact["request"]
            response = artifact["response"]
            if request["prompt_sha256"] != _sha256_text(request["prompt"]):
                raise RuntimeError("postflight prompt hash mismatch")
            if response["sha256"] != _sha256_text(response["text"]):
                raise RuntimeError("postflight response hash mismatch")
            if (
                request["condition"] != record.condition
                or request["chapter"] != record.chapter
                or request["purpose"] != record.purpose
                or request["runtime"]["model"] != MODEL
                or request["runtime"]["model_digest"] != self.model_digest
                or request["runtime"]["options"]
                != {
                    "num_ctx": NUM_CTX,
                    "num_predict": NUM_PREDICT,
                    "temperature": TEMPERATURE,
                    "seed": SEED,
                }
                or request["runtime"]["max_retries"] != 1
            ):
                raise RuntimeError("postflight request/runtime linkage mismatch")
            metadata = artifact["transport"]["metadata"]
            if (
                artifact["transport"]["reported_physical_attempts"] != 1
                or metadata.get("done") is not True
                or metadata.get("done_reason") != "stop"
                or not isinstance(metadata.get("prompt_eval_count"), int)
                or not isinstance(metadata.get("eval_count"), int)
                or metadata["prompt_eval_count"] >= NUM_CTX - NUM_PREDICT
                or metadata["eval_count"] > NUM_PREDICT
            ):
                raise RuntimeError("postflight transport metadata mismatch")
            expected_prompt_sha = (
                preflight["ablation_prompts"][record.chapter - 7]["sha256"]
                if record.condition == "compressed_ablation"
                else preflight["batch_prompts"][str(record.chapter)][
                    record.condition
                ]["sha256"]
            )
            if request["prompt_sha256"] != expected_prompt_sha:
                raise RuntimeError("postflight prompt differs from frozen preflight")
            started, finished = event_lines[(index - 1) * 2 : index * 2]
            if (
                started.get("event") != "call_started"
                or finished.get("event") != "call_finished"
                or started.get("sequence") != index
                or finished.get("sequence") != index
                or started.get("call_id") != expected_call_id
                or finished.get("call_id") != expected_call_id
                or started["request"] != request
                or finished.get("status") != "completed"
                or finished["artifact_file_sha256"] != call_file_sha
                or finished["response_sha256"] != response["sha256"]
            ):
                raise RuntimeError("postflight journal linkage mismatch")

            decision = self._verify_sealed_json(decision_path)
            if (
                decision.get("call_id") != expected_call_id
                or decision.get("condition") != record.condition
                or decision.get("batch_id") != record.chapter
                or decision.get("response_sha256") != response["sha256"]
            ):
                raise RuntimeError("postflight decision linkage mismatch")
            call_hashes[expected_call_id] = call_file_sha
            decision_hashes[expected_call_id] = _sha256_bytes(decision_path.read_bytes())

        audit_config = json.loads(self.audit.config_path.read_text(encoding="utf-8"))
        config_unsigned = dict(audit_config)
        observed_config_sha = config_unsigned.pop("config_payload_sha256", None)
        expected_config_sha = _sha256_bytes(
            (_canonical_json(config_unsigned) + "\n").encode("utf-8")
        )
        if observed_config_sha != expected_config_sha:
            raise RuntimeError("postflight audit config hash mismatch")
        precheck = self._verify_sealed_json(self.output_dir / "PRECHECK.json")
        manifest = self._verify_sealed_json(self.output_dir / "manifest.json")
        if precheck["protocol_id"] != PROTOCOL_ID or manifest["protocol_id"] != PROTOCOL_ID:
            raise RuntimeError("postflight protocol identity mismatch")
        qualification = {
            "schema_version": PROTOCOL_SCHEMA_VERSION,
            "call_count": TOTAL_CALLS,
            "decision_count": TOTAL_CALLS,
            "call_file_sha256": call_hashes,
            "decision_file_sha256": decision_hashes,
            "events_jsonl_sha256": _sha256_bytes(self.audit.events_path.read_bytes()),
            "audit_config_file_sha256": _sha256_bytes(self.audit.config_path.read_bytes()),
            "precheck_file_sha256": _sha256_bytes(
                (self.output_dir / "PRECHECK.json").read_bytes()
            ),
            "manifest_file_sha256": _sha256_bytes(
                (self.output_dir / "manifest.json").read_bytes()
            ),
            "all_runtime_prompt_response_journal_decision_links_verified": True,
        }
        qualification["aggregate_sha256"] = _sha256_text(
            _canonical_json(qualification)
        )
        return qualification

    def _outcome(
        self,
        usage: Mapping[str, Any],
        preflight: Mapping[str, Any],
        evidence_qualification: Mapping[str, Any],
    ) -> dict[str, Any]:
        summaries: dict[str, Any] = {}
        for condition in CONDITIONS:
            selected = [score for score in self.scores if score.condition == condition]
            summaries[condition] = {
                "cases": len(selected),
                "primary_passes": sum(score.primary_pass for score in selected),
                "answer_correct": sum(score.answer_correct for score in selected),
                "chronology_authority_correct": sum(
                    score.chronology_authority_correct for score in selected
                ),
                "reconstruction_correct": sum(
                    score.reconstruction_correct for score in selected
                ),
                "valid_outputs": sum(score.valid_output for score in selected),
                "illegal_state_promotions": sum(
                    score.illegal_state_promotions for score in selected
                ),
                "mean_required_ref_recall": round(
                    sum(score.required_ref_recall for score in selected)
                    / max(len(selected), 1),
                    9,
                ),
                "mean_allowed_ref_precision": round(
                    sum(score.allowed_ref_precision for score in selected)
                    / max(len(selected), 1),
                    9,
                ),
                "input_tokens": usage["totals"][condition]["input_tokens"],
                "output_tokens": usage["totals"][condition]["output_tokens"],
                "calls": usage["totals"][condition]["calls"],
                "latency_seconds": usage["totals"][condition]["latency_seconds"],
                "state_supplied_utf8_bytes": sum(
                    item["representation_utf8_bytes"][condition]
                    for item in preflight["representation_stats"]
                ),
            }
        families: dict[str, Any] = {}
        for family in sorted({case.family for case in self.cases}):
            family_ids = {case.case_id for case in self.cases if case.family == family}
            families[family] = {}
            for condition in CONDITIONS:
                selected = [
                    score
                    for score in self.scores
                    if score.condition == condition and score.case_id in family_ids
                ]
                families[family][condition] = {
                    "cases": len(selected),
                    "primary_passes": sum(score.primary_pass for score in selected),
                    "answer_correct": sum(score.answer_correct for score in selected),
                    "illegal_state_promotions": sum(
                        score.illegal_state_promotions for score in selected
                    ),
                }
        compressed_scores = [
            score for score in self.scores if score.condition == "compressed"
        ]
        support_high_ids = {
            case.case_id for case in self.cases if case.load == "support_high"
        }
        compressed_support_high = sum(
            score.primary_pass
            for score in compressed_scores
            if score.case_id in support_high_ids
        )
        distractor_high_ids = {
            case.case_id for case in self.cases if case.load == "distractor_high"
        }

        def passes_for(condition: str, case_ids: set[str]) -> int:
            return sum(
                score.primary_pass
                for score in self.scores
                if score.condition == condition and score.case_id in case_ids
            )

        support_high_passes = {
            condition: passes_for(condition, support_high_ids)
            for condition in CONDITIONS
        }
        distractor_high_passes = {
            condition: passes_for(condition, distractor_high_ids)
            for condition in CONDITIONS
        }
        ablation_order = [
            item
            for call_plan in self.case_pack_payload["ablation"]["counterbalanced_calls"]
            for item in call_plan
        ]
        essential_detected = sum(
            score.primary_pass
            for score, item in zip(self.ablation_scores, ablation_order)
            if item["role"] == "essential"
        )
        control_passes = sum(
            score.primary_pass
            for score, item in zip(self.ablation_scores, ablation_order)
            if item["role"] == "control"
        )
        raw_ratio = usage["median_compressed_to_raw_prompt_token_ratio"]
        retrieval_ratio = usage["median_compressed_to_retrieval_prompt_token_ratio"]
        criteria = {
            "compressed_primary_passes_at_least_16": summaries["compressed"][
                "primary_passes"
            ]
            >= 16,
            "compressed_not_worse_than_raw": summaries["compressed"][
                "primary_passes"
            ]
            >= summaries["raw"]["primary_passes"],
            "compressed_not_worse_than_retrieval": summaries["compressed"][
                "primary_passes"
            ]
            >= summaries["retrieval"]["primary_passes"],
            "compressed_support_high_at_least_4_of_5": compressed_support_high
            >= 4,
            "compressed_not_worse_than_each_baseline_support_high": all(
                support_high_passes["compressed"] >= support_high_passes[baseline]
                for baseline in ("raw", "retrieval")
            ),
            "compressed_not_worse_than_each_baseline_distractor_high": all(
                distractor_high_passes["compressed"]
                >= distractor_high_passes[baseline]
                for baseline in ("raw", "retrieval")
            ),
            "compressed_primary_passes_at_least_3_of_4_in_every_family": all(
                family_result["compressed"]["primary_passes"] >= 3
                for family_result in families.values()
            ),
            "compressed_zero_illegal_promotions": summaries["compressed"][
                "illegal_state_promotions"
            ]
            == 0,
            "median_compressed_prompt_tokens_at_most_60_percent_raw": raw_ratio
            <= 0.60,
            "median_compressed_prompt_tokens_not_above_retrieval": retrieval_ratio
            <= 1.0,
            "codec_required_ref_recall_100_percent": preflight[
                "compression_loss_count"
            ]
            == 0,
            "essential_ablation_detection_at_least_4_of_5": essential_detected
            >= 4,
            "anti_reflex_ablation_controls_at_least_4_of_5": control_passes >= 4,
        }
        supported = all(criteria.values())
        evidence_level = "SUPPORTED" if supported else "SPECULATIVE"
        failure_modes = Counter(
            reason
            for score in [*self.scores, *self.ablation_scores]
            for reason in score.failure_reasons
        )
        return {
            "validity": "VALID",
            "hypothesis_result": "SUPPORTED" if supported else "NOT_SUPPORTED",
            "evidence_level": evidence_level,
            "proven": False,
            "condition_summaries": summaries,
            "family_summaries": families,
            "load_summaries": {
                "support_high": support_high_passes,
                "distractor_high": distractor_high_passes,
            },
            "case_scores": [_score_mapping(score) for score in self.scores],
            "ablation": {
                "essential_detected": essential_detected,
                "essential_total": 5,
                "control_passes": control_passes,
                "control_total": 5,
                "scores": [
                    {"role": item["role"], **_score_mapping(score)}
                    for score, item in zip(self.ablation_scores, ablation_order)
                ],
                "calls": usage["totals"]["compressed_ablation"]["calls"],
                "input_tokens": usage["totals"]["compressed_ablation"][
                    "input_tokens"
                ],
                "output_tokens": usage["totals"]["compressed_ablation"][
                    "output_tokens"
                ],
            },
            "criteria": criteria,
            "failure_modes": dict(sorted(failure_modes.items())),
            "compression_loss_failures": preflight["compression_loss_count"],
            "usage": usage,
            "evidence_qualification": copy.deepcopy(dict(evidence_qualification)),
            "interpretation_boundary": (
                "This smoke concerns one synthetic query-blind typed codec and one "
                "model digest. It does not prove autonomous Hive compression or "
                "generalize beyond these five deterministic world templates."
            ),
        }

    @staticmethod
    def _result_markdown(result: Mapping[str, Any]) -> str:
        lines = [
            "# Hive Decompression Test — Smoke 001",
            "",
            f"- Validity: **{result['validity']}**",
            f"- Hypothesis: **{result['hypothesis_result']}**",
            f"- Evidence level: **{result['evidence_level']}**",
            "- PROVEN: **no**",
            "",
            "| Condition | Primary exact | Answers | Chronology/authority | Illegal promotions | Input tokens | Output tokens | Calls |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        summaries = result.get("condition_summaries") or {}
        for condition in CONDITIONS:
            row = summaries.get(condition)
            if row is None:
                lines.append(f"| {condition} | not completed | — | — | — | — | — | — |")
            else:
                lines.append(
                    f"| {condition} | {row['primary_passes']}/{row['cases']} | "
                    f"{row['answer_correct']}/{row['cases']} | "
                    f"{row['chronology_authority_correct']}/{row['cases']} | "
                    f"{row['illegal_state_promotions']} | {row['input_tokens']} | "
                    f"{row['output_tokens']} | {row['calls']} |"
                )
        ablation = result.get("ablation") or {}
        lines.extend(
            [
                "",
                "## Minimum sufficient state ablation",
                "",
                f"- Essential removals detected: {ablation.get('essential_detected', 'not completed')}/{ablation.get('essential_total', '—')}",
                f"- Irrelevant-removal controls passed: {ablation.get('control_passes', 'not completed')}/{ablation.get('control_total', '—')}",
                "",
                "## Preregistered criteria",
                "",
            ]
        )
        for name, passed in (result.get("criteria") or {}).items():
            lines.append(f"- {'PASS' if passed else 'FAIL'} — {name}")
        lines.extend(
            [
                "",
                "## Interpretation boundary",
                "",
                str(result["interpretation_boundary"]),
                "",
            ]
        )
        return "\n".join(lines)

    def _write_terminal(
        self,
        *,
        validity: str,
        result: Mapping[str, Any],
        error: BaseException | None = None,
    ) -> None:
        assert self.audit is not None
        result_payload = _sealed_payload(
            {
                "schema_version": PROTOCOL_SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "source_revision": self.source_revision,
                **copy.deepcopy(dict(result)),
                "audit_index": self.audit.manifest_index(),
            }
        )
        _write_exclusive(self.output_dir / "RESULT.json", _pretty_json(result_payload))
        _write_exclusive(
            self.output_dir / "RESULT.md", self._result_markdown(result_payload)
        )
        status = _sealed_payload(
            {
                "schema_version": PROTOCOL_SCHEMA_VERSION,
                "protocol_id": PROTOCOL_ID,
                "source_revision": self.source_revision,
                "validity": validity,
                "hypothesis_result": result_payload.get("hypothesis_result"),
                "evidence_level": result_payload.get("evidence_level"),
                "call_count": len(self.audit.records),
                "result_file_sha256": _sha256_bytes(
                    (self.output_dir / "RESULT.json").read_bytes()
                ),
                "error": None
                if error is None
                else {"type": type(error).__name__, "message": str(error)},
            }
        )
        _write_exclusive(self.output_dir / "RUN_STATUS.json", _pretty_json(status))

    def run(self) -> Mapping[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=False)
        try:
            self.decisions_dir.mkdir(exist_ok=False)
            preflight = self._preflight()
            _write_exclusive(
                self.output_dir / "PRECHECK.json",
                _pretty_json(_sealed_payload(preflight)),
            )
            self.audit = ProtocolV2AuditStore(
                self.ask_fn,
                self.output_dir / "evidence",
                model=MODEL,
                model_digest=self.model_digest,
                generation_calls_per_chapter=1,
                request_timeout_seconds=TIMEOUT_SECONDS,
                ollama_num_ctx=NUM_CTX,
                ollama_num_predict=NUM_PREDICT,
                ollama_temperature=TEMPERATURE,
                ollama_seed=SEED,
            )
            _write_exclusive(
                self.output_dir / "manifest.json",
                _pretty_json(self._manifest(preflight)),
            )
            for batch in self.case_pack_payload["batches"]:
                batch_id = int(batch["batch_id"])
                batch_cases = [self.by_case[case_id] for case_id in batch["case_ids"]]
                for condition in batch["condition_order"]:
                    self._run_primary_call(batch_id, str(condition), batch_cases)
            for call_number, call_plan in enumerate(
                self.case_pack_payload["ablation"]["counterbalanced_calls"], start=1
            ):
                self._run_ablation_call(call_number, call_plan)
            if len(self.audit.records) != TOTAL_CALLS:
                raise RuntimeError(
                    f"expected {TOTAL_CALLS} physical calls, recorded {len(self.audit.records)}"
                )
            if any(record.status != "completed" for record in self.audit.records):
                raise RuntimeError("one or more physical call artifacts are incomplete")
            evidence_qualification = self._verify_evidence(preflight)
            usage = self._call_usage()
            result = self._outcome(usage, preflight, evidence_qualification)
            self._write_terminal(validity="VALID", result=result)
            return result
        except BaseException as error:
            invalid = {
                "validity": "INVALID",
                "hypothesis_result": "INCONCLUSIVE_INVALID_SMOKE",
                "evidence_level": "SPECULATIVE",
                "proven": False,
                "condition_summaries": {},
                "case_scores": [_score_mapping(score) for score in self.scores],
                "ablation": {
                    "scores": [_score_mapping(score) for score in self.ablation_scores]
                },
                "criteria": {},
                "failure_modes": {"apparatus_failure": 1},
                "interpretation_boundary": (
                    "Harness/runtime evidence is incomplete; no hypothesis result "
                    "and no condition winner may be inferred."
                ),
            }
            if (self.output_dir / "RESULT.json").exists():
                failure = _sealed_payload(
                    {
                        "schema_version": PROTOCOL_SCHEMA_VERSION,
                        "protocol_id": PROTOCOL_ID,
                        "validity": "INVALID",
                        "error": {
                            "type": type(error).__name__,
                            "message": str(error),
                        },
                        "note": "terminal evidence write failed after RESULT creation",
                    }
                )
                if not (self.output_dir / "TERMINAL_FAILURE.json").exists():
                    _write_exclusive(
                        self.output_dir / "TERMINAL_FAILURE.json",
                        _pretty_json(failure),
                    )
            elif self.audit is not None:
                self._write_terminal(validity="INVALID", result=invalid, error=error)
            else:
                minimal = _sealed_payload(
                    {
                        "schema_version": PROTOCOL_SCHEMA_VERSION,
                        "protocol_id": PROTOCOL_ID,
                        "source_revision": self.source_revision,
                        **invalid,
                        "audit_index": None,
                    }
                )
                _write_exclusive(
                    self.output_dir / "RESULT.json", _pretty_json(minimal)
                )
                _write_exclusive(
                    self.output_dir / "RESULT.md", self._result_markdown(minimal)
                )
                _write_exclusive(
                    self.output_dir / "RUN_STATUS.json",
                    _pretty_json(
                        _sealed_payload(
                            {
                                "schema_version": PROTOCOL_SCHEMA_VERSION,
                                "protocol_id": PROTOCOL_ID,
                                "validity": "INVALID",
                                "call_count": 0,
                                "error": {
                                    "type": type(error).__name__,
                                    "message": str(error),
                                },
                            }
                        )
                    ),
                )
            raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen 20-case Hive Decompression Test smoke"
    )
    parser.add_argument(
        "--acknowledge-frozen-smoke",
        action="store_true",
        help="required acknowledgement that the one-shot protocol is frozen",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.acknowledge_frozen_smoke:
        raise SystemExit("refusing live run without --acknowledge-frozen-smoke")
    repo_root = Path(__file__).resolve().parents[1]
    case_pack_path = repo_root / "benchmarks" / "decompression_test" / "CASE_PACK.json"
    output_dir = (
        repo_root
        / ".hive"
        / "benchmarks"
        / "decompression_test"
        / "smoke-v1-001"
    )
    revision, sources = _git_revision_and_sources(repo_root)
    payload, cases = load_case_pack(case_pack_path)
    digest = _ollama_model_digest(MODEL, generate_url=OLLAMA_URL)
    if digest != MODEL_DIGEST:
        raise RuntimeError(
            f"installed model digest {digest!r} differs from frozen digest {MODEL_DIGEST!r}"
        )
    runner = DecompressionSmokeRunner(
        repo_root=repo_root,
        output_dir=output_dir,
        case_pack_payload=payload,
        cases=cases,
        source_revision=revision,
        source_file_sha256=sources,
        model_digest=digest,
    )
    runner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
