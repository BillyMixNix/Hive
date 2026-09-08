"""Bounded, persistent orchestration for the small local Hive agent.

The module intentionally leaves :mod:`local_agent` intact: it reuses its repository
fingerprinting and Ollama transport, while keeping executive state, worker authority,
and acceptance decisions outside worker conversations.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import inspect
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import tokenize
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable

from local_agent import normalize, ollama_chat, repository_diff, revision_id, snapshot_repository


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _leaf_choice_fingerprint(
        location_id: str, old_expression: str, replace_reference: str,
        with_in_scope_value: str, resulting_expression: str) -> str:
    """Bind one opaque Repair choice to its locked location and exact AST-preserving edit."""
    return _fingerprint({
        "kind": "leaf_substitution",
        "location_id": location_id,
        "old_expression": old_expression,
        "replace_reference": replace_reference,
        "with_in_scope_value": with_in_scope_value,
        "resulting_expression": resulting_expression,
    })


def _code_line_identity(line: str) -> tuple[tuple[int, str], ...]:
    """Normalize one selected code line without erasing strings or operators."""
    ignored = {
        tokenize.ENCODING, tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
        tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER,
    }
    tokens: list[tuple[int, str]] = []
    try:
        generated = tokenize.generate_tokens(io.StringIO(line).readline)
        for token in generated:
            if token.type not in ignored:
                tokens.append((token.type, token.string))
    except (tokenize.TokenError, IndentationError):
        # A single physical line can legitimately open a multiline expression.
        # Tokens emitted before EOF are still a precise identity for that line.
        pass
    return tuple(tokens)


_RUNTIME_CAPTURE_SCRIPT = r"""
import json
import os
import sys

import pytest

target = os.path.normcase(os.path.abspath(sys.argv[1]))
target_line = int(sys.argv[2])
nodes = json.loads(sys.argv[3])
local_names = set(json.loads(sys.argv[4]))
attribute_names = set(json.loads(sys.argv[5]))
captures_before = []
captures_after = []
pending_frames = set()

def safe(value, depth=0):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth >= 4:
        return {"type": type(value).__name__, "truncated": True}
    if isinstance(value, (list, tuple)):
        return [safe(item, depth + 1) for item in list(value)[:12]]
    if isinstance(value, dict):
        return {
            str(key): safe(item, depth + 1)
            for key, item in list(value.items())[:12]
        }
    values = getattr(value, "__dict__", None)
    if isinstance(values, dict):
        selected = {
            str(key): item for key, item in values.items()
            if not attribute_names or str(key) in attribute_names
        }
        return {
            "type": type(value).__name__,
            "attributes": {
                key: safe(item, depth + 1)
                for key, item in list(selected.items())[:12]
            },
        }
    return {"type": type(value).__name__}

def local_trace(frame, event, arg):
    if event != "line":
        return local_trace
    frame_id = id(frame)
    if frame_id in pending_frames and len(captures_after) < 3:
        captures_after.append({
            key: safe(value)
            for key, value in frame.f_locals.items()
            if key in local_names
        })
        pending_frames.discard(frame_id)
    if frame.f_lineno == target_line and len(captures_before) < 3:
        captures_before.append({
            key: safe(value)
            for key, value in frame.f_locals.items()
            if key in local_names
        })
        pending_frames.add(frame_id)
    return local_trace

def global_trace(frame, event, arg):
    if (event == "call"
            and os.path.normcase(os.path.abspath(frame.f_code.co_filename)) == target):
        return local_trace
    return None

sys.settrace(global_trace)
pytest_exit = int(pytest.main(["-q", "-p", "no:cacheprovider", *nodes]))
sys.settrace(None)
print("HIVE_RUNTIME_CAPTURE=" + json.dumps({
    "pytest_exit": pytest_exit,
    "frames_before": captures_before,
    "frames_after": captures_after,
}, sort_keys=True, default=str))
"""


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class WorkerStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"


class EvidenceKind(str, Enum):
    OBSERVATION = "OBSERVATION"
    TEST_RESULT = "TEST_RESULT"
    DIFF = "DIFF"
    CLAIM = "CLAIM"
    INFERENCE = "INFERENCE"


class EvidenceLifecycle(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    CONTRADICTED = "CONTRADICTED"
    UNVERIFIED = "UNVERIFIED"


class ContinuationDecision(str, Enum):
    SATISFIED = "SATISFIED"
    EXECUTABLE_WORK_REMAINS = "EXECUTABLE_WORK_REMAINS"
    GENUINELY_BLOCKED = "GENUINELY_BLOCKED"


@dataclass
class TaskState:
    """Controller-owned definition of done for an atomic repair trajectory.

    Workers may contribute evidence, but only deterministic controller gates mutate
    these fields.  The snapshots and node ids make red/green attribution durable
    across retries and process resumes.
    """

    original_failure_reproduced: bool = False
    root_cause_identified: bool = False
    callable_location_grounded: bool = False
    callable_location: dict[str, Any] = field(default_factory=dict)
    rejected_callable_locations: list[dict[str, Any]] = field(default_factory=list)
    invalid_callable_location_submissions: list[dict[str, Any]] = field(default_factory=list)
    source_location_grounded: bool = False
    source_location: dict[str, Any] = field(default_factory=dict)
    cause_location_grounded: bool = False
    candidate_source_location: dict[str, Any] = field(default_factory=dict)
    rejected_cause_locations: list[dict[str, Any]] = field(default_factory=list)
    operationally_deferred_cause_locations: list[dict[str, Any]] = field(
        default_factory=list)
    rejected_source_locations: list[dict[str, Any]] = field(default_factory=list)
    operationally_deferred_source_locations: list[dict[str, Any]] = field(
        default_factory=list)
    invalid_source_location_submissions: list[dict[str, Any]] = field(default_factory=list)
    location_repair_failures: dict[str, int] = field(default_factory=dict)
    location_repair_stagnations: dict[str, int] = field(default_factory=dict)
    diagnosis_grounded: bool = False
    investigator_diagnosis: dict[str, Any] = field(default_factory=dict)
    source_runtime_evidence: dict[str, Any] = field(default_factory=dict)
    rejected_investigator_diagnoses: list[dict[str, Any]] = field(default_factory=list)
    atomic_source_files: list[str] = field(default_factory=list)
    atomic_test_files: list[str] = field(default_factory=list)
    regression_established: bool = False
    regression_created: bool = False
    regression_fails_on_broken_revision: bool = False
    source_repaired: bool = False
    regression_passes_after_repair: bool = False
    original_tests_pass: bool = False
    acceptance_oracle_pass: bool = False
    review_pass: bool = False
    reproduced_failure_nodes: list[str] = field(default_factory=list)
    regression_nodes: list[str] = field(default_factory=list)
    regression_origin: str = ""
    regression_baseline_snapshot: dict[str, str] = field(default_factory=dict)
    accepted_regression_snapshot: dict[str, str] = field(default_factory=dict)
    regression_target: dict[str, Any] = field(default_factory=dict)
    repair_oracle_target: dict[str, Any] = field(default_factory=dict)
    last_failed_gate: str = ""
    last_gate_feedback: str = ""
    gate_failures: dict[str, int] = field(default_factory=dict)
    rejected_repair_actions: list[dict[str, Any]] = field(default_factory=list)
    rejected_repair_action_locations: dict[str, list[str]] = field(default_factory=dict)
    invalid_repair_submissions: list[dict[str, Any]] = field(default_factory=list)
    atomic_cycle: int = 1
    cycle_history: list[dict[str, Any]] = field(default_factory=list)
    oracle_feedback: str = ""
    reproduction_origin: str = ""

    @property
    def complete(self) -> bool:
        return all((
            self.original_failure_reproduced,
            self.callable_location_grounded,
            self.source_location_grounded,
            self.cause_location_grounded,
            self.diagnosis_grounded,
            self.root_cause_identified,
            self.regression_established or self.regression_created,
            self.regression_fails_on_broken_revision,
            self.source_repaired,
            self.regression_passes_after_repair,
            self.original_tests_pass,
            self.acceptance_oracle_pass,
            self.review_pass,
        ))

    def reset_for_residual(self, oracle_feedback: str) -> None:
        self.cycle_history.append({
            "cycle": self.atomic_cycle,
            "regression_nodes": list(self.regression_nodes),
            "regression_established": self.regression_established,
            "regression_origin": self.regression_origin,
            "callable_location": dict(self.callable_location),
            "rejected_callable_locations": list(self.rejected_callable_locations),
            "source_location": dict(self.source_location),
            "cause_location_grounded": self.cause_location_grounded,
            "candidate_source_location": dict(self.candidate_source_location),
            "rejected_cause_locations": list(self.rejected_cause_locations),
            "operationally_deferred_cause_locations": list(
                self.operationally_deferred_cause_locations),
            "rejected_source_locations": list(self.rejected_source_locations),
            "operationally_deferred_source_locations": list(
                self.operationally_deferred_source_locations),
            "rejected_investigator_diagnoses": list(
                self.rejected_investigator_diagnoses),
            "source_repaired": self.source_repaired,
            "original_tests_pass": self.original_tests_pass,
            "review_pass": self.review_pass,
            "oracle_feedback": oracle_feedback,
            "reproduction_origin": self.reproduction_origin,
        })
        failures = dict(self.gate_failures)
        history = list(self.cycle_history)
        cycle = self.atomic_cycle + 1
        self.__dict__.update(TaskState().__dict__)
        self.gate_failures = failures
        self.cycle_history = history
        self.atomic_cycle = cycle
        self.oracle_feedback = oracle_feedback


@dataclass
class Authority:
    allowed_tools: list[str] = field(default_factory=lambda: ["list_files", "read_file"])
    read_scopes: list[str] = field(default_factory=lambda: ["."])
    write_scopes: list[str] = field(default_factory=list)
    allowed_commands: list[str] = field(default_factory=lambda: ["pytest", "pytest -v", "pytest --verbose"])

    @property
    def read_only(self) -> bool:
        return (not self.write_scopes
                and "replace_in_file" not in self.allowed_tools
                and "replace_selected_line" not in self.allowed_tools
                and "replace_selected_leaf" not in self.allowed_tools
                and "replace_selected_expression" not in self.allowed_tools
                and "append_to_file" not in self.allowed_tools
                and "run_command" not in self.allowed_tools)


@dataclass
class Evidence:
    evidence_id: str
    kind: EvidenceKind
    summary: str
    source_worker_run_id: str
    task_id: str
    revision: str
    payload: Any = None
    created_at: str = field(default_factory=utc_now)
    verified: bool = False
    lifecycle: EvidenceLifecycle = EvidenceLifecycle.UNVERIFIED


@dataclass
class Artifact:
    artifact_id: str
    path: str
    revision: str
    source_worker_run_id: str
    task_id: str
    description: str = ""
    created_at: str = field(default_factory=utc_now)


@dataclass
class ValidationResult:
    validation_id: str
    revision: str
    command: str
    exit_code: int
    output: str
    accepted: bool
    conformance_decision: str = "REVISE"
    reasons: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)


@dataclass
class WorkerRun:
    run_id: str
    objective_id: str
    task_id: str
    capability: str
    status: WorkerStatus
    authority: Authority
    input_fingerprint: str
    model: str
    lease_id: str
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    inference_calls: int = 0
    error: str = ""
    summary: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    start_revision: str = ""
    end_revision: str = ""
    edited_files: list[str] = field(default_factory=list)
    commands_executed: list[str] = field(default_factory=list)
    action_fingerprints: list[str] = field(default_factory=list)
    start_snapshot: dict[str, str] = field(default_factory=dict)


@dataclass
class Task:
    task_id: str
    objective_id: str
    description: str
    capability: str
    acceptance_conditions: list[str]
    authority: Authority
    dependencies: list[str] = field(default_factory=list)
    required_context: list[str] = field(default_factory=list)
    expected_output: str = "structured findings"
    status: TaskStatus = TaskStatus.PENDING
    assigned_worker_run_id: str | None = None
    lease_id: str | None = None
    lease_expires_at: float = 0.0
    retry_count: int = 0
    last_failure_fingerprint: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    failure_reason: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass
class GraphRevision:
    revision_id: str
    repository_revision: str
    validation_id: str
    category: str
    reasoning: str
    triggering_evidence_ids: list[str]
    evidence_fingerprint: str
    before_graph: list[dict[str, Any]]
    after_graph: list[dict[str, Any]]
    inserted_task_ids: list[str]
    inserted_dependencies: dict[str, list[str]]
    result: str = "APPLIED"
    created_at: str = field(default_factory=utc_now)


@dataclass
class Objective:
    objective_id: str
    original_request: str
    success_criteria: list[str]
    baseline_revision: str
    baseline_snapshot: dict[str, str]
    state: str = "ACTIVE"
    priority: int = 0
    parent_objective_id: str | None = None
    blocker: str = ""
    task_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    validation: ValidationResult | None = None
    graph_revisions: list[GraphRevision] = field(default_factory=list)
    task_state: TaskState = field(default_factory=TaskState)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


@dataclass
class HiveConfig:
    default_model: str = "qwen2.5-coder:7b"
    capability_models: dict[str, str] = field(default_factory=dict)
    ollama_url: str = "http://localhost:11434/api/chat"
    max_active_workers: int = 2
    max_queued_workers: int = 24
    max_model_concurrency: int = 1
    max_worker_steps: int = 8
    max_worker_retries: int = 2
    max_graph_revisions: int = 4
    max_tasks_per_revision: int = 4
    max_objective_worker_runs: int = 32
    max_inference_calls: int = 128
    worker_timeout_seconds: float = 180.0
    command_timeout_seconds: float = 60.0
    lease_seconds: float = 300.0
    max_context_chars: int = 40_000
    test_command: str = "pytest"
    max_identical_actions: int = 2
    max_applied_repairs_per_location: int = 2
    retire_superseded_evidence: bool = True
    regression_first: bool = True
    independent_review: bool = True
    protected_tail_inference_calls: int = 14
    responsibility_call_budgets: dict[str, int] = field(default_factory=dict)
    recovery_reserve_calls: int = 0
    capability_step_limits: dict[str, int] = field(default_factory=lambda: {
        "REPRODUCER": 3,
        "SCOUT": 4,
        "CALLABLE_LOCATOR": 6,
        "SOURCE_LOCATOR": 2,
        "INVESTIGATOR": 4,
        "CAUSE_LOCATOR": 2,
        "REGRESSION_DESIGNER": 4,
        "REPAIR": 6,
        "BUILDER": 6,
        "REVIEWER": 4,
        "VALIDATOR": 4,
    })

    @classmethod
    def atomic(cls, call_budget: int = 36, **overrides: Any) -> "HiveConfig":
        """Return the initial responsibility-reserved experiment configuration."""
        if call_budget != 36 and "responsibility_call_budgets" not in overrides:
            raise ValueError("nonstandard atomic call budgets require explicit allocations")
        values: dict[str, Any] = {
            "max_inference_calls": call_budget,
            "protected_tail_inference_calls": 0,
            "responsibility_call_budgets": {
                "REPRODUCER": 2,
                "CALLABLE_LOCATOR": 6,
                "SOURCE_LOCATOR": 4,
                "INVESTIGATOR": 3,
                "CAUSE_LOCATOR": 3,
                "REGRESSION_DESIGNER": 5,
                "REPAIR": 6,
                "REVIEWER": 3,
            },
            "recovery_reserve_calls": 4,
            "max_applied_repairs_per_location": 3,
            "capability_step_limits": {
                "REPRODUCER": 3,
                "SCOUT": 4,
                "CALLABLE_LOCATOR": 6,
                "SOURCE_LOCATOR": 2,
                "INVESTIGATOR": 2,
                "CAUSE_LOCATOR": 2,
                "REGRESSION_DESIGNER": 4,
                "REPAIR": 6,
                "BUILDER": 6,
                "REVIEWER": 4,
                "VALIDATOR": 4,
            },
        }
        values.update(overrides)
        return cls(**values)


@dataclass(frozen=True)
class CapabilitySpec:
    capability: str
    allowed_tools: tuple[str, ...]
    may_write: bool = False


CAPABILITIES = {
    "REPRODUCER": CapabilitySpec("REPRODUCER", ("list_files", "read_file", "run_command")),
    "SCOUT": CapabilitySpec("SCOUT", ("list_files", "read_file")),
    "CALLABLE_LOCATOR": CapabilitySpec(
        "CALLABLE_LOCATOR", ("read_source_lines", "submit_callable")),
    "SOURCE_LOCATOR": CapabilitySpec(
        "SOURCE_LOCATOR", ("submit_location",)),
    "CAUSE_LOCATOR": CapabilitySpec(
        "CAUSE_LOCATOR", ("submit_cause", "confirm_candidate", "reject_cause_frontier")),
    "INVESTIGATOR": CapabilitySpec("INVESTIGATOR", ("list_files", "read_file", "run_command")),
    "REGRESSION_DESIGNER": CapabilitySpec(
        "REGRESSION_DESIGNER", ("read_file", "run_command", "replace_in_file"), True),
    "REPAIR": CapabilitySpec(
        "REPAIR", ("replace_selected_leaf", "replace_selected_expression"), True),
    "BUILDER": CapabilitySpec("BUILDER", ("list_files", "read_file", "run_command", "replace_in_file"), True),
    "REVIEWER": CapabilitySpec("REVIEWER", ("list_files", "read_file", "run_command")),
    "VALIDATOR": CapabilitySpec("VALIDATOR", ("list_files", "read_file", "run_command")),
}


PLANNER_SYSTEM = """You are Hive's executive task decomposer. Build the smallest useful
evidence-driven task graph for the original objective. Choose only capabilities from
SCOUT, INVESTIGATOR, REGRESSION_DESIGNER, BUILDER, REVIEWER, VALIDATOR. Do not use a fixed pipeline when a
smaller graph is enough. A BUILDER must list exact write_scopes. Prefer read-only work
before writes and independent review for consequential edits. Return JSON only:
{"tasks":[{"key":"short-local-key","description":"bounded objective",
"capability":"SCOUT","dependencies":["earlier-key"],
"required_context":["relative/path"],"write_scopes":[],
"acceptance_conditions":["observable condition"]}]}"""

REVISION_PLANNER_SYSTEM = """You are Hive's evidence-bound graph revision planner.
Validation disproved the completeness of the current plan. Distinguish an incomplete
plan from an implementation defect, and add only the smallest novel work justified by
verified evidence. Speculation may justify an INVESTIGATOR, never a write. Do not retry
or paraphrase an existing completed task. Use only SCOUT, INVESTIGATOR, BUILDER,
REGRESSION_DESIGNER, REVIEWER, VALIDATOR. A BUILDER must have exact existing-file write_scopes. An
INVESTIGATOR must request diagnosis using read/test evidence only; never ask it to add,
edit, fix, or write regression coverage. Dependencies may name an existing task id or
an earlier local key. If a graph-added INVESTIGATOR has completed since the preceding
revision and its verified evidence establishes an actionable defect, cite both the
current validation evidence and that INVESTIGATOR evidence; propose the narrowly
scoped BUILDER (and independent REVIEWER when warranted), rather than another
investigation of unchanged evidence. When regression coverage is required, schedule a
test-only REGRESSION_DESIGNER before the BUILDER; it must write only existing test files
and demonstrate the new test failing before the repair. Return JSON only:
{"category":"PLAN_INCOMPLETE|IMPLEMENTATION_DEFECT|BLOCKED","reasoning":"...",
"triggering_evidence_ids":["evidence_id"],"tasks":[{"key":"novel-key",
"description":"bounded objective","capability":"INVESTIGATOR",
"dependencies":["existing-task-id-or-earlier-key"],"required_context":["path"],
"write_scopes":[],"acceptance_conditions":["observable condition"]}]}"""


_ENUM_FIELDS = {
    "status": {"Task": TaskStatus, "WorkerRun": WorkerStatus},
    "kind": {"Evidence": EvidenceKind},
    "lifecycle": {"Evidence": EvidenceLifecycle},
}


class StateStore:
    """Atomic snapshot plus append-only, per-objective event trace."""

    def __init__(self, root: Path, objective_id: str):
        if not re.fullmatch(r"objective_[0-9a-f]{12}", objective_id):
            raise ValueError("invalid objective id")
        state_root = (root / ".agent_runs" / "hive").resolve()
        self.directory = (state_root / objective_id).resolve()
        if os.path.commonpath([str(state_root), str(self.directory)]) != str(state_root):
            raise ValueError("objective state path escapes state root")
        self.state_path = self.directory / "state.json"
        self.trace_path = self.directory / "trace.jsonl"
        self._lock = threading.RLock()
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, payload: dict[str, Any]) -> None:
        with self._lock:
            temporary = self.state_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            for attempt in range(6):
                try:
                    os.replace(temporary, self.state_path)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.01 * (attempt + 1))

    def load(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(self.state_path.read_text(encoding="utf-8"))

    def trace(self, event: str, **details: Any) -> None:
        record = {"timestamp": utc_now(), "event": event, **details}
        line = json.dumps(record, sort_keys=True, default=str) + "\n"
        with self._lock, self.trace_path.open("a", encoding="utf-8") as stream:
            stream.write(line)
            stream.flush()


class AuthorityError(PermissionError):
    pass


class WorkerSession:
    """Central broker; workers never receive filesystem or subprocess objects."""

    _write_lock = threading.RLock()

    def __init__(self, root: Path, authority: Authority, command_timeout: float = 60.0,
                 fixed_review: str | None = None,
                 rejected_replacements: list[dict[str, Any]] | None = None,
                 fixed_line_repair: dict[str, Any] | None = None):
        self.root = root.resolve()
        self.authority = authority
        self.command_timeout = command_timeout
        self.fixed_review = fixed_review
        self.rejected_replacements = rejected_replacements or []
        self.fixed_line_repair = dict(fixed_line_repair or {})

    def _require_tool(self, name: str) -> None:
        if name not in self.authority.allowed_tools:
            raise AuthorityError(f"tool not allowed: {name}")

    def _path(self, relative: str, scopes: Iterable[str]) -> Path:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise AuthorityError("path must be repository-relative without traversal")
        candidate = (self.root / relative).resolve()
        if os.path.commonpath([str(self.root), str(candidate)]) != str(self.root):
            raise AuthorityError("path escapes repository root")
        allowed = False
        for scope in scopes:
            scope_path = Path(scope)
            if scope_path.is_absolute() or ".." in scope_path.parts:
                raise AuthorityError("authority scope must remain inside repository")
            boundary = (self.root / scope).resolve()
            if os.path.commonpath([str(self.root), str(boundary)]) != str(self.root):
                raise AuthorityError("authority scope escapes repository root")
            if os.path.commonpath([str(boundary), str(candidate)]) == str(boundary):
                allowed = True
                break
        if not allowed:
            raise AuthorityError(f"path outside assigned scope: {relative}")
        return candidate

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        self._require_tool(name)
        if name == "list_files":
            visible = []
            for relative in sorted(snapshot_repository(self.root)):
                try:
                    self._path(relative, self.authority.read_scopes + self.authority.write_scopes)
                except AuthorityError:
                    continue
                visible.append(relative)
            return "\n".join(visible)
        if name == "read_file":
            scopes = self.authority.read_scopes + self.authority.write_scopes
            return self._path(str(arguments.get("path", "")), scopes).read_text(encoding="utf-8")
        if name == "read_source_lines":
            scopes = self.authority.read_scopes + self.authority.write_scopes
            target = self._path(str(arguments.get("path", "")), scopes)
            content = target.read_text(encoding="utf-8")
            numbered = "\n".join(
                f"{line_number} | {line}"
                for line_number, line in enumerate(content.splitlines(), 1)
            )
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            return (
                f"SOURCE FILE: {target.relative_to(self.root).as_posix()}\n"
                f"SOURCE SHA256: {digest}\n{numbered}"
            )
        if name == "run_command":
            command = str(arguments.get("command", ""))
            if command not in self.authority.allowed_commands:
                raise AuthorityError(f"command not allowed: {command}")
            result = _run_pytest(command, self.root, self.command_timeout)
            return f"EXIT CODE: {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        if name == "submit_diagnosis":
            required = {
                "source_file": str,
                "symbol": str,
                "line": int,
                "source_line": str,
                "mechanism": str,
            }
            missing = [key for key in (*required, "actual", "expected")
                       if key not in arguments]
            invalid = [key for key, expected_type in required.items()
                       if key in arguments
                       and (not isinstance(arguments[key], expected_type)
                            or (expected_type is str and not arguments[key].strip()))]
            if missing or invalid or isinstance(arguments.get("line"), bool):
                raise ValueError(
                    f"diagnosis requires structured fields; missing={missing}, invalid={invalid}")
            return "SUCCESS: Structured diagnosis submitted for controller verification"
        if name == "submit_mechanism":
            required = {"location_id": str, "mechanism": str}
            if set(arguments) != set(required):
                raise ValueError(
                    "mechanism requires exactly location_id and mechanism fields")
            invalid = [key for key, expected_type in required.items()
                       if not isinstance(arguments[key], expected_type)
                       or not arguments[key].strip()]
            if invalid:
                raise ValueError(f"mechanism fields must be nonempty strings: {invalid}")
            return "SUCCESS: Causal mechanism submitted for controller verification"
        if name == "submit_callable":
            required = {"source_file": str, "definition_line": int}
            if set(arguments) != set(required):
                raise ValueError(
                    "callable requires exactly source_file and definition_line")
            invalid = [key for key, expected_type in required.items()
                       if (not isinstance(arguments[key], expected_type)
                           or (expected_type is str and not arguments[key].strip()))]
            if invalid or isinstance(arguments.get("definition_line"), bool):
                raise ValueError(
                    f"callable fields have invalid types or values: {invalid}")
            return "SUCCESS: Structured callable submitted for controller verification"
        if name == "submit_location":
            required = {
                "callable_id": str,
                "choice_id": str,
            }
            if set(arguments) != set(required):
                raise ValueError(
                    "location requires exactly callable_id and choice_id")
            missing = [key for key in required if key not in arguments]
            invalid = [key for key, expected_type in required.items()
                       if key in arguments
                       and (not isinstance(arguments[key], expected_type)
                            or (expected_type is str and not arguments[key].strip()))]
            if missing or invalid:
                raise ValueError(
                    f"location requires structured fields; missing={missing}, invalid={invalid}")
            return "SUCCESS: Structured source location submitted for controller verification"
        if name == "submit_cause":
            required = {"candidate_location_id": str, "cause_choice_id": str}
            if set(arguments) != set(required):
                raise ValueError(
                    "cause location requires exactly candidate_location_id and cause_choice_id")
            invalid = [key for key, expected_type in required.items()
                       if not isinstance(arguments[key], expected_type)
                       or not arguments[key].strip()]
            if invalid:
                raise ValueError(f"cause location fields must be nonempty strings: {invalid}")
            return "SUCCESS: Structured causal source location submitted for controller verification"
        if name == "confirm_candidate":
            if set(arguments) != {"candidate_location_id"}:
                raise ValueError(
                    "candidate confirmation requires exactly candidate_location_id")
            if (not isinstance(arguments.get("candidate_location_id"), str)
                    or not arguments["candidate_location_id"].strip()):
                raise ValueError("candidate_location_id must be a nonempty string")
            return "SUCCESS: Direct candidate cause submitted for controller verification"
        if name == "reject_cause_frontier":
            if set(arguments) != {"candidate_location_id"}:
                raise ValueError(
                    "cause-frontier rejection requires exactly candidate_location_id")
            if (not isinstance(arguments.get("candidate_location_id"), str)
                    or not arguments["candidate_location_id"].strip()):
                raise ValueError("candidate_location_id must be a nonempty string")
            return "SUCCESS: Exhausted cause frontier submitted for controller verification"
        if name in {"replace_selected_line", "replace_selected_leaf",
                    "replace_selected_expression"}:
            if name == "replace_selected_leaf":
                if (set(arguments) != {"choice_id"}
                        or not isinstance(arguments.get("choice_id"), str)
                        or not str(arguments["choice_id"]).strip()):
                    raise ValueError(
                        "selected leaf repair requires exactly one nonempty string field: choice_id")
            elif set(arguments) != {"new"} or not isinstance(arguments.get("new"), str):
                raise ValueError("selected repair requires exactly one string field: new")
            if not self.fixed_line_repair:
                raise AuthorityError("no controller-locked source line is available")
            source_file = str(self.fixed_line_repair.get("source_file", ""))
            line_number = self.fixed_line_repair.get("line")
            expected_line = str(self.fixed_line_repair.get("source_line", "")).strip()
            expected_digest = str(self.fixed_line_repair.get("source_sha256", ""))
            if (not isinstance(line_number, int) or isinstance(line_number, bool)
                    or line_number < 1 or not source_file or not expected_line):
                raise AuthorityError("controller-locked source line is invalid")
            model_new = str(arguments.get("new", ""))
            if name == "replace_selected_leaf":
                frame = self.fixed_line_repair.get("expression_frame", {})
                if not isinstance(frame, dict) or frame.get("mode") != "expression":
                    raise AuthorityError(
                        "controller could not lock an expression-only repair frame")
                choice_id = str(arguments["choice_id"]).strip()
                choices = self.fixed_line_repair.get("leaf_replacement_choices", [])
                matches = [choice for choice in choices
                           if isinstance(choice, dict)
                           and choice.get("choice_id") == choice_id]
                if len(matches) != 1:
                    raise ValueError(
                        "choice_id is not one current controller-generated leaf edit")
                choice = matches[0]
                required_choice_fields = {
                    "choice_id", "replace_reference", "with_in_scope_value",
                    "resulting_expression",
                }
                if set(choice) != required_choice_fields:
                    raise AuthorityError("controller-generated leaf edit is malformed")
                model_new = str(choice.get("resulting_expression", "")).strip()
                expected_choice_id = _leaf_choice_fingerprint(
                    str(self.fixed_line_repair.get("location_id", "")),
                    str(frame.get("old_expression", "")),
                    str(choice.get("replace_reference", "")),
                    str(choice.get("with_in_scope_value", "")),
                    model_new,
                )
                if choice_id != expected_choice_id:
                    raise AuthorityError("controller-generated leaf edit identity is stale")
            if (not model_new.strip() or "\n" in model_new or "\r" in model_new):
                raise ValueError("new must contain exactly one nonempty physical source line")
            if name in {"replace_selected_leaf", "replace_selected_expression"}:
                frame = self.fixed_line_repair.get("expression_frame", {})
                if not isinstance(frame, dict) or frame.get("mode") != "expression":
                    raise AuthorityError(
                        "controller could not lock an expression-only repair frame")
                expression = (
                    model_new if name == "replace_selected_leaf"
                    else HiveExecutive._normalize_model_expression(model_new, frame)
                )
                try:
                    ast.parse(expression, mode="eval")
                except SyntaxError as exc:
                    raise AuthorityError(
                        "controller-generated leaf edit is not one valid expression") from exc
                new_line = (
                    str(frame.get("prefix", "")) + expression
                    + str(frame.get("suffix", ""))
                )
            else:
                new_line = model_new
            target = self._path(source_file, self.authority.write_scopes)
            with self._write_lock:
                content = target.read_text(encoding="utf-8")
                current_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                if expected_digest and current_digest != expected_digest:
                    raise ValueError("controller-locked source revision is stale")
                physical_lines = content.splitlines(keepends=True)
                if line_number > len(physical_lines):
                    raise ValueError("controller-locked source line no longer exists")
                physical = physical_lines[line_number - 1]
                line_ending = ("\r\n" if physical.endswith("\r\n") else
                               "\n" if physical.endswith("\n") else
                               "\r" if physical.endswith("\r") else "")
                existing = physical[:-len(line_ending)] if line_ending else physical
                if existing.strip() != expected_line:
                    raise ValueError("controller-locked source line no longer matches")
                replacement = new_line.strip()
                if _code_line_identity(replacement) == _code_line_identity(existing):
                    raise ValueError("new must materially change the locked source line")
                action = {
                    "path": source_file,
                    "old": expected_line,
                    "new": model_new.strip(),
                }
                if action in self.rejected_replacements:
                    raise ValueError(
                        "replacement was already rejected by the focused regression; "
                        "choose a materially different source change"
                    )
                indentation = existing[:len(existing) - len(existing.lstrip())]
                physical_lines[line_number - 1] = indentation + replacement + line_ending
                try:
                    ast.parse("".join(physical_lines))
                except SyntaxError as exc:
                    raise ValueError(
                        f"replacement makes the source syntactically invalid: {exc.msg}") from exc
                target.write_text("".join(physical_lines), encoding="utf-8")
            return f"SUCCESS: Updated locked line in {source_file}"
        if name == "replace_in_file":
            replacement = {
                "path": str(arguments.get("path", "")),
                "old": str(arguments.get("old", "")),
                "new": str(arguments.get("new", "")),
            }
            if replacement in self.rejected_replacements:
                raise ValueError(
                    "replacement was already rejected by the focused regression; "
                    "choose a materially different source change"
                )
            target = self._path(str(arguments.get("path", "")), self.authority.write_scopes)
            old, new = str(arguments.get("old", "")), str(arguments.get("new", ""))
            with self._write_lock:
                content = target.read_text(encoding="utf-8")
                if not old or content.count(old) != 1:
                    raise ValueError("replacement must match exactly once")
                target.write_text(content.replace(old, new, 1), encoding="utf-8")
            return f"SUCCESS: Updated {target.relative_to(self.root).as_posix()}"
        if name == "append_to_file":
            target = self._path(str(arguments.get("path", "")), self.authority.write_scopes)
            addition = str(arguments.get("content", ""))
            if not addition.strip():
                raise ValueError("append content must be nonempty")
            with self._write_lock, target.open("a", encoding="utf-8") as stream:
                stream.write(addition)
            return f"SUCCESS: Appended to {target.relative_to(self.root).as_posix()}"
        if name == "review_snapshot":
            if self.fixed_review is None:
                raise AuthorityError("no controller-compiled review snapshot is available")
            return self.fixed_review
        if name == "submit_review":
            if set(arguments) != {"verdict", "findings"}:
                raise ValueError("review requires exactly verdict and findings")
            verdict = str(arguments.get("verdict", "")).strip().upper()
            findings = arguments.get("findings")
            if verdict not in {"PASS", "FINDINGS"}:
                raise ValueError("review verdict must be PASS or FINDINGS")
            if (not isinstance(findings, list)
                    or any(not isinstance(item, str) or not item.strip()
                           for item in findings)):
                raise ValueError("review findings must be a list of nonempty strings")
            if verdict == "PASS" and findings:
                raise ValueError("PASS review must have no findings")
            if verdict == "FINDINGS" and not findings:
                raise ValueError("FINDINGS review must include at least one finding")
            return "SUCCESS: Advisory review submitted for controller verification"
        raise AuthorityError(f"unknown tool: {name}")


def _run_pytest(command: str, root: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    """Map the small command allowlist to argv and isolate pytest's writable state."""
    verbosity = ["-v"] if command in {"pytest -v", "pytest --verbose"} else []
    temp_parent = root / ".agent_runs"
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pytest_", dir=temp_parent) as temporary:
        temp_root = Path(temporary) / "basetemp"
        bytecode_root = Path(temporary) / "pycache"
        argv = [sys.executable, "-m", "pytest", *verbosity, "-p", "no:cacheprovider",
                f"--basetemp={temp_root}"]
        environment = os.environ.copy()
        environment["PYTHONPYCACHEPREFIX"] = str(bytecode_root)
        return subprocess.run(argv, shell=False, cwd=root, capture_output=True, text=True,
                              timeout=timeout, env=environment)


def _run_pytest_nodes(nodes: list[str], root: Path,
                      timeout: float) -> subprocess.CompletedProcess[str]:
    """Run controller-selected pytest nodes without widening worker command authority."""
    if not nodes or any(not re.fullmatch(r"[^\s:]+\.py::[A-Za-z_][A-Za-z0-9_]*", node)
                        for node in nodes):
        raise ValueError("focused regression nodes must be simple repository test functions")
    temp_parent = root / ".agent_runs"
    temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pytest_nodes_", dir=temp_parent) as temporary:
        temp_root = Path(temporary) / "basetemp"
        bytecode_root = Path(temporary) / "pycache"
        argv = [sys.executable, "-m", "pytest", "-q", *nodes, "-p", "no:cacheprovider",
                f"--basetemp={temp_root}"]
        environment = os.environ.copy()
        environment["PYTHONPYCACHEPREFIX"] = str(bytecode_root)
        return subprocess.run(argv, shell=False, cwd=root, capture_output=True, text=True,
                              timeout=timeout, env=environment)


WORKER_SYSTEM = """You are a bounded Hive worker. Use only the JSON tools in your
task packet. Return exactly one JSON object per turn. For a tool action, copy the
exact tool name and argument keys from task_packet.tool_contracts. Never return the
literal placeholder name TOOL. When done use:
{"name":"finish","arguments":{"status":"COMPLETED|BLOCKED","summary":"...",
"evidence":[{"kind":"OBSERVATION|TEST_RESULT|DIFF|CLAIM|INFERENCE","summary":"...","payload":null}],
"artifacts":[{"path":"relative/path","description":"..."}],
"discovered_tasks":[]}}. CLAIM, OBSERVATION, INFERENCE, and DIFF are evidence kinds,
not tool names. Put them inside finish.evidence. When the assigned task is complete,
finish immediately; do not attempt work outside your authority. Claims are not proof;
cite tool observations. Never exceed authority."""


REPRODUCER_SYSTEM = WORKER_SYSTEM + """
You are only the Reproducer. Run the allowed failing test command once. Do not diagnose,
edit, plan, or finish the global task. Hive closes this responsibility from command evidence."""

INVESTIGATOR_SYSTEM = WORKER_SYSTEM + """
You are only the Investigator. A separate Cause Locator already selected one exact producer line.
Call submit_mechanism exactly once, keeping the prefilled location_id unchanged. State only
how that selected line can produce the supplied observable mismatch. Treat the
controller-captured locals immediately before the line as facts: do not claim an object is absent,
a branch is not executing, or a value differs when the runtime evidence shows otherwise. Compare
the selected expression's operands with the callable inputs and observable mismatch. Distinguish
stored values established by earlier calls from current-call parameters. Do not claim a stored
value should change unless visible source assigns it. Name which operand the selected computation
uses and which in-scope value the local requirement needs; do not turn an upstream producer into a
downstream difference or delta merely because a later output reports one. Evaluate the literal
selected RHS from the captured operands, state the value assigned after it executes, and identify
any current-call parameter omitted by that RHS. Do not label internal intermediate values expected
or actual; those labels belong only to the public observable counterexample.
This remains a hypothesis until Repair flips the locked regression red to green. Do not read,
edit, add tests, choose another line, plan a repair, or finish the global task."""

CALLABLE_LOCATOR_SYSTEM = WORKER_SYSTEM + """
You are only the Callable Locator. Read only the allowed numbered source files, then submit
one callable by source_file and its exact def/async-def definition_line. You may inspect more
than one allowed file so helper callables remain reachable. When the observable counterexample
names a callable that exists in the allowed source, inspect that public operation first; choose a
helper instead only when the public callable merely delegates the failing computation. Do not
substitute a constructor or unrelated initializer for a named runtime operation. Do not choose a
statement inside the callable, explain a mechanism, diagnose, repair, edit, test, review, or
finish the task. Hive parses the current source and locks the callable name, span, digest, and
identity."""

SOURCE_LOCATOR_SYSTEM = WORKER_SYSTEM + """
You are only the line-level Source Locator. You have no filesystem tools. Hive supplies one
controller-locked callable context and opaque choices with already-disproven lines removed.
Select the first line where the runtime value becomes wrong, not initialization, storage, or
a downstream use of an already-wrong value. Use callable_context to preserve branch structure.
Keep callable_id unchanged and copy exactly one choice_id. Hive owns the file, line number,
and source text. Submit no source code, file, symbol, explanation, or diagnosis. Do not read,
repair, edit, test, review, or finish the task."""

CAUSE_LOCATOR_SYSTEM = WORKER_SYSTEM + """
You are only the Cause Locator. A line scout selected a symptom. Hive has mechanically reduced
the choices to untried reaching definitions of
values consumed by that symptom. Select the first line that creates the wrong upstream value.
If the locked candidate itself is the first wrong computation, call confirm_candidate instead;
otherwise call submit_cause with one cause_choice_id from the separate upstream list. Call
reject_cause_frontier only when it is explicitly offered and neither the remaining upstream
choices nor the locked candidate can explain every mismatched observable field. Call exactly one
offered tool once. Hive owns all source text, file paths, line numbers, and choice identities.
Do not invent a choice id, explain, diagnose, edit, test, review, or finish the global task."""

REGRESSION_SYSTEM = WORKER_SYSTEM + """
You are only the Regression worker. Source is unavailable and must never be read or
edited. Read the assigned test file, append exactly one new top-level test_* function
without changing any existing line, run pytest once to demonstrate red, then stop.
When oracle_counterexample is available, use its observable input, expected value, and
actual value to write the smallest test yourself. Hive does not supply test code. Existing
test bytes are physically immutable. Do not add coverage for a function the residual
output shows is already passing."""

REPAIR_SYSTEM = WORKER_SYSTEM + """
You are only the Repair worker. Tests are immutable. The exact current source is already
in repair_handoff. Call exactly the one controller-authorized replacement tool, then stop.
For replace_selected_leaf, copy exactly one controller-generated choice_id; Hive preserves the
entire expression tree and substitutes only that one existing data reference. For
replace_selected_expression, supply only the new Python expression: no assignment target, return
keyword, indentation, or other statement wrapper. For the explicit statement fallback, supply
exactly one replacement source line without indentation. Hive preserves all locked bytes around
an expression and runs the focused regression and full suite itself. Do not read, test,
add tests, review, clean up, or finish the global task. Do not compensate in callers, formatting,
or presentation layers. Use the exact accepted regression, expected/actual values, root cause,
and focused red output in repair_handoff. Hive independently checks red-to-green behavior."""

REVIEWER_SYSTEM = WORKER_SYSTEM + """
You are only the read-only Reviewer. First call review_snapshot exactly once. It returns
the controller-computed diff and fresh test result. Then call submit_review exactly once
with PASS or FINDINGS and a short list supported only by that snapshot. Look for hardcoded
examples, weakened behavior, nearby defects, or unnecessary changes. Claims are advisory;
Hive independently verifies mechanical gates and owns completion. The diff contains the only
changed code: do not report unchanged APIs, deprecations, style, or nearby source that is absent
from its added/removed lines. Every finding must cite an exact changed token visible in the diff."""

TOOL_CONTRACTS = {
    "list_files": {"name": "list_files", "arguments": {}},
    "read_file": {"name": "read_file", "arguments": {"path": "relative/path"}},
    "read_source_lines": {
        "name": "read_source_lines", "arguments": {"path": "assigned/source.py"}},
    "run_command": {"name": "run_command", "arguments": {"command": "pytest"}},
    "submit_diagnosis": {
        "name": "submit_diagnosis",
        "arguments": {
            "source_file": "assigned/source.py",
            "symbol": "containing_function_or_method",
            "line": 1,
            "source_line": "exact stripped source line",
            "actual": None,
            "expected": None,
            "mechanism": "one causal hypothesis",
        },
    },
    "submit_mechanism": {
        "name": "submit_mechanism",
        "arguments": {
            "location_id": "controller-locked-location-id",
            "mechanism": "one causal explanation only",
        },
    },
    "submit_callable": {
        "name": "submit_callable",
        "arguments": {
            "source_file": "assigned/source.py",
            "definition_line": 1,
        },
    },
    "submit_location": {
        "name": "submit_location",
        "arguments": {
            "callable_id": "controller-locked-callable-id",
            "choice_id": "controller-generated-line-choice-id",
        },
    },
    "submit_cause": {
        "name": "submit_cause",
        "arguments": {
            "candidate_location_id": "controller-locked-symptom-location-id",
            "cause_choice_id": "controller-generated-cause-choice-id",
        },
    },
    "confirm_candidate": {
        "name": "confirm_candidate",
        "arguments": {
            "candidate_location_id": "controller-locked-symptom-location-id",
        },
    },
    "reject_cause_frontier": {
        "name": "reject_cause_frontier",
        "arguments": {
            "candidate_location_id": "controller-locked-symptom-location-id",
        },
    },
    "replace_in_file": {
        "name": "replace_in_file",
        "arguments": {"path": "relative/path", "old": "exact existing text", "new": "replacement"},
    },
    "replace_selected_line": {
        "name": "replace_selected_line",
        "arguments": {"new": "one replacement source line without indentation"},
    },
    "replace_selected_leaf": {
        "name": "replace_selected_leaf",
        "arguments": {"choice_id": "controller-generated-leaf-edit-choice-id"},
    },
    "replace_selected_expression": {
        "name": "replace_selected_expression",
        "arguments": {"new": "one model-authored Python expression only"},
    },
    "append_to_file": {
        "name": "append_to_file",
        "arguments": {"path": "assigned_test.py", "content": "\\n\\ndef test_new_case():\\n    ...\\n"},
    },
    "review_snapshot": {"name": "review_snapshot", "arguments": {}},
    "submit_review": {
        "name": "submit_review",
        "arguments": {"verdict": "PASS or FINDINGS", "findings": ["short finding"]},
    },
}


class AtomicAgent:
    """One independently invoked model responsibility in an atomic Hive cycle."""

    capability = ""
    system_prompt = WORKER_SYSTEM
    allowed_tools: tuple[str, ...] = ()

    def create_task(self, hive: "HiveExecutive", source_files: list[str],
                    test_files: list[str], dependency: Task | None = None) -> Task:
        raise NotImplementedError

    def compile_packet(self, hive: "HiveExecutive", task: Task) -> dict[str, Any]:
        return hive._atomic_base_packet(task)

    def run(self, hive: "HiveExecutive", task: Task) -> WorkerRun:
        return hive._execute_task(
            task, self.system_prompt, self.compile_packet(hive, task), self,
        )

    def apply_gate(self, hive: "HiveExecutive", task: Task, run: WorkerRun,
                   status: str, summary: str, observations: list[dict[str, Any]],
                   current_snapshot: dict[str, str]) -> None:
        raise NotImplementedError

    def retry_feedback(self, hive: "HiveExecutive", task: Task) -> str:
        state = hive.objective.task_state
        return state.last_gate_feedback or task.failure_reason

    def grounded_completion(self, task: Task,
                            observations: list[dict[str, Any]]) -> dict[str, Any] | None:
        return None

    @staticmethod
    def completed_from_evidence() -> dict[str, Any]:
        return {
            "status": "COMPLETED",
            "summary": "Atomic responsibility satisfied by brokered evidence.",
            "evidence": [{"kind": "OBSERVATION",
                          "summary": "Required atomic tools completed with broker provenance."}],
            "artifacts": [], "discovered_tasks": [],
        }


class ReproducerAgent(AtomicAgent):
    capability = "REPRODUCER"
    system_prompt = REPRODUCER_SYSTEM
    allowed_tools = ("list_files", "read_file", "run_command")

    def run(self, hive: "HiveExecutive", task: Task) -> WorkerRun:
        return hive._execute_task(task, self.system_prompt,
                                  self.compile_packet(hive, task), self)

    def compile_packet(self, hive: "HiveExecutive", task: Task) -> dict[str, Any]:
        task.authority.allowed_tools = ["run_command"]
        oracle_residual = (
            hive.objective.task_state.atomic_cycle > 1
            and bool(hive.objective.task_state.oracle_feedback)
        )
        packet = {
            "task": {
                "id": task.task_id,
                "capability": "reproducer",
                "description": (
                    "Confirm the controller-recorded external-oracle counterexample."
                    if oracle_residual else
                    "Capture the controller's exact failing test command and output."
                ),
            },
            "authority": asdict(task.authority),
            "tool_contracts": [TOOL_CONTRACTS["run_command"]],
            "instruction": (
                f"Call run_command exactly once with command={hive.config.test_command!r}. "
                "Do not add a path, flags, or another command; Hive records the output. "
                + (
                    "The visible suite may be green; Hive independently owns the recorded "
                    "external-oracle failure below."
                    if oracle_residual else ""
                )
            ),
        }
        if oracle_residual:
            packet["deterministic_oracle_failure"] = hive.objective.task_state.oracle_feedback
        return packet

    def create_task(self, hive: "HiveExecutive", source_files: list[str],
                    test_files: list[str], dependency: Task | None = None) -> Task:
        context = source_files + test_files
        return hive.add_task(
            "Reproduce the reported problem and return the exact failing command and output.",
            "reproducer", ["A controller-observed command exits nonzero"],
            Authority(list(self.allowed_tools), context, []),
            dependencies=[dependency.task_id] if dependency else [], required_context=test_files,
            expected_output="Exact failing command, observed result, expected result, and relevant files",
        )

    def apply_gate(self, hive: "HiveExecutive", task: Task, run: WorkerRun,
                   status: str, summary: str, observations: list[dict[str, Any]],
                   current_snapshot: dict[str, str]) -> None:
        state = hive.objective.task_state
        command_observed = any(item["tool"] == "run_command" for item in observations)
        pytest_failed = any(
            item["tool"] == "run_command" and "EXIT CODE: 0" not in item["output"]
            for item in observations
        )
        oracle_residual = (
            state.atomic_cycle > 1 and bool(state.oracle_feedback)
            and bool(hive._smallest_oracle_counterexample())
        )
        if not command_observed or not (pytest_failed or oracle_residual):
            hive._gate_failure("original_failure_reproduced",
                               "reproducer captured neither a failing command nor a "
                               "controller-recorded external-oracle counterexample")
        state.original_failure_reproduced = True
        state.reproduction_origin = "oracle_residual" if oracle_residual else "pytest"
        if pytest_failed:
            hive._adopt_existing_failing_regression(task, observations, current_snapshot)

    def grounded_completion(self, task: Task,
                            observations: list[dict[str, Any]]) -> dict[str, Any] | None:
        return (self.completed_from_evidence()
                if any(item["tool"] == "run_command" for item in observations) else None)


class CallableLocatorAgent(AtomicAgent):
    capability = "CALLABLE_LOCATOR"
    system_prompt = CALLABLE_LOCATOR_SYSTEM
    allowed_tools = ("read_source_lines", "submit_callable")

    def compile_packet(self, hive: "HiveExecutive", task: Task) -> dict[str, Any]:
        state = hive.objective.task_state
        counterexample = hive._smallest_oracle_counterexample()
        if counterexample:
            state.regression_target = dict(counterexample)
        source_candidates = list(state.atomic_source_files)
        operation = (str(counterexample.get("operation", "")).strip()
                     if isinstance(counterexample, dict) else "")
        operation_symbol = operation.rsplit(".", 1)[-1] if operation else ""
        current_snapshot = snapshot_repository(hive.root)
        operation_candidates: list[dict[str, Any]] = []
        if operation_symbol:
            for path in source_candidates:
                source = current_snapshot.get(path)
                if not isinstance(source, str):
                    continue
                try:
                    tree = ast.parse(source)
                except (SyntaxError, ValueError):
                    continue
                operation_candidates.extend({
                    "source_file": path,
                    "symbol": node.name,
                    "definition_line": node.lineno,
                } for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == operation_symbol)
        task.authority.allowed_tools = list(self.allowed_tools)
        task.authority.read_scopes = source_candidates
        task.authority.write_scopes = []
        source_field = (source_candidates[0] if len(source_candidates) == 1
                        else "COPY ONE PATH FROM source_candidates")
        failure_outputs = [
            str(evidence.payload.get("output", ""))
            for dependency_id in task.dependencies
            for evidence_id in hive.tasks[dependency_id].evidence_ids
            if (evidence := hive.evidence[evidence_id]).verified
            and evidence.kind == EvidenceKind.TEST_RESULT
            and isinstance(evidence.payload, dict)
            and evidence.payload.get("output")
        ]
        packet = {
            "task": {
                "id": task.task_id,
                "capability": "callable_locator",
                "description": "Select one callable only; do not choose a statement.",
            },
            "authority": asdict(task.authority),
            "source_candidates": source_candidates,
            "observable_counterexample": counterexample or "unavailable",
            "reported_operation_hint": operation or "unavailable",
            "reported_operation_candidates": operation_candidates,
            "observed_failure": failure_outputs[-1][-3_000:] if failure_outputs else "unavailable",
            "retry_feedback": (
                state.last_gate_feedback if state.last_failed_gate == "callable_location_grounded"
                else "No prior rejected callable in this responsibility."
            ),
            "tool_contracts": [{
                "name": "read_source_lines",
                "arguments": {"path": source_field},
            }, {
                "name": "submit_callable",
                "arguments": {"source_file": source_field, "definition_line": 0},
            }],
            "instruction": (
                "Read any allowed source files needed to trace into a helper, then call "
                "submit_callable exactly once. Copy source_file from source_candidates and "
                "definition_line from the numbered def or async def line. When "
                "reported_operation_candidates is nonempty, inspect that callable first and "
                "prefer it over constructors or unrelated initializers. A helper remains legal "
                "when the named operation delegates the failing computation. Do not choose a "
                "statement inside the callable."
            ),
            "assigned_feedback": task.expected_output[-3_000:],
        }
        if state.rejected_callable_locations:
            packet["rejected_callables_do_not_repeat"] = list(
                state.rejected_callable_locations)
        return packet

    def create_task(self, hive: "HiveExecutive", source_files: list[str],
                    test_files: list[str], dependency: Task | None = None) -> Task:
        if dependency is None:
            raise ValueError("CallableLocatorAgent requires an upstream dependency")
        return hive.add_task(
            "Locate only the callable that can produce the observed wrong value.",
            "callable_locator", ["Submit one exact callable definition line"],
            Authority(list(self.allowed_tools), source_files, []),
            dependencies=[dependency.task_id], required_context=source_files,
            expected_output="Source file and exact callable definition line only",
        )

    def apply_gate(self, hive: "HiveExecutive", task: Task, run: WorkerRun,
                   status: str, summary: str, observations: list[dict[str, Any]],
                   current_snapshot: dict[str, str]) -> None:
        hive._apply_callable_locator_gate(task, observations, current_snapshot)

    def grounded_completion(self, task: Task,
                            observations: list[dict[str, Any]]) -> dict[str, Any] | None:
        submission = next((item for item in reversed(observations)
                           if item["tool"] == "submit_callable"), None)
        if submission is None:
            return None
        return {
            "status": "COMPLETED",
            "summary": json.dumps(submission["arguments"], sort_keys=True, default=str),
            "evidence": [{"kind": "INFERENCE",
                          "summary": "Structured callable-location hypothesis",
                          "payload": submission["arguments"]}],
            "artifacts": [], "discovered_tasks": [],
        }


class SourceLocatorAgent(AtomicAgent):
    capability = "SOURCE_LOCATOR"
    system_prompt = SOURCE_LOCATOR_SYSTEM
    allowed_tools = ("submit_location",)

    def compile_packet(self, hive: "HiveExecutive", task: Task) -> dict[str, Any]:
        state = hive.objective.task_state
        task.authority.allowed_tools = list(self.allowed_tools)
        task.authority.read_scopes = []
        task.authority.write_scopes = []
        locked = dict(state.callable_location)
        source = snapshot_repository(hive.root).get(str(locked.get("source_file", "")))
        lines = source.splitlines() if isinstance(source, str) else []
        first = int(locked.get("definition_line", 0) or 0)
        last = int(locked.get("end_line", 0) or 0)
        choices = hive._source_line_choices(source, locked)
        choice_lines = {int(choice["line"]) for choice in choices}
        context_lines = [
            lines[number - 1]
            for number in range(first, last + 1)
            if 1 <= number <= len(lines)
            and (number == first or number in choice_lines or not lines[number - 1].strip())
        ]
        ancestor_ids = set(task.dependencies)
        frontier = list(task.dependencies)
        while frontier:
            ancestor = hive.tasks[frontier.pop()]
            for dependency_id in ancestor.dependencies:
                if dependency_id not in ancestor_ids:
                    ancestor_ids.add(dependency_id)
                    frontier.append(dependency_id)
        failure_outputs = [
            str(evidence.payload.get("output", ""))
            for evidence in hive.evidence.values()
            if evidence.task_id in ancestor_ids and evidence.verified
            and evidence.kind == EvidenceKind.TEST_RESULT
            and isinstance(evidence.payload, dict) and evidence.payload.get("output")
        ]
        callable_id = str(locked.get("callable_id", ""))
        return {
            "task": {
                "id": task.task_id,
                "capability": "source_locator",
                "description": "Select one source line from the locked callable window.",
            },
            "authority": asdict(task.authority),
            "observable_counterexample": (
                hive._smallest_oracle_counterexample() or "unavailable"),
            "observed_failure": failure_outputs[-1][-3_000:] if failure_outputs else "unavailable",
            "locked_callable_id": callable_id,
            "callable_context": "\n".join(context_lines),
            "source_line_choices": [
                {"choice_id": choice["choice_id"], "source_line": choice["source_line"]}
                for choice in choices
            ],
            "retry_feedback": (
                state.last_gate_feedback if state.last_failed_gate == "source_location_grounded"
                else "No prior rejected exact line in this responsibility."
            ),
            "tool_contracts": [{
                "name": "submit_location",
                "arguments": {
                    "callable_id": callable_id,
                    "choice_id": "COPY ONE choice_id FROM source_line_choices",
                },
            }],
            "instruction": (
                "Call submit_location exactly once. Keep callable_id unchanged and copy one "
                "choice_id from source_line_choices. Choose the first line where the value "
                "becomes wrong, not initialization, storage, or a downstream use. Hive owns "
                "the source text and line number."
            ),
            "assigned_feedback": task.expected_output[-3_000:],
        }

    def create_task(self, hive: "HiveExecutive", source_files: list[str],
                    test_files: list[str], dependency: Task | None = None) -> Task:
        if dependency is None:
            raise ValueError("SourceLocatorAgent requires a Callable Locator dependency")
        return hive.add_task(
            "Select only one causal line from the controller-locked callable.",
            "source_locator", ["Submit one exact line from the locked callable window"],
            Authority(list(self.allowed_tools), [], []),
            dependencies=[dependency.task_id], required_context=[],
            expected_output="Locked callable id and one exact source line only",
        )

    def apply_gate(self, hive: "HiveExecutive", task: Task, run: WorkerRun,
                   status: str, summary: str, observations: list[dict[str, Any]],
                   current_snapshot: dict[str, str]) -> None:
        hive._apply_source_locator_gate(task, observations, current_snapshot)

    def grounded_completion(self, task: Task,
                            observations: list[dict[str, Any]]) -> dict[str, Any] | None:
        location = next((item for item in reversed(observations)
                         if item["tool"] == "submit_location"), None)
        if location is None:
            return None
        return {
            "status": "COMPLETED",
            "summary": json.dumps(location["arguments"], sort_keys=True, default=str),
            "evidence": [{"kind": "INFERENCE",
                          "summary": "Structured line-location hypothesis",
                          "payload": location["arguments"]}],
            "artifacts": [], "discovered_tasks": [],
        }


class InvestigatorAgent(AtomicAgent):
    capability = "INVESTIGATOR"
    system_prompt = INVESTIGATOR_SYSTEM
    allowed_tools = ("submit_mechanism",)

    def compile_packet(self, hive: "HiveExecutive", task: Task) -> dict[str, Any]:
        state = hive.objective.task_state
        counterexample = hive._smallest_oracle_counterexample()
        if counterexample:
            state.regression_target = dict(counterexample)
        task.authority.allowed_tools = list(self.allowed_tools)
        task.authority.read_scopes = []
        task.authority.write_scopes = []
        location = dict(state.source_location)
        source = snapshot_repository(hive.root).get(str(location.get("source_file", "")))
        bounded = hive._bounded_callable_window(
            source, state.callable_location, location.get("line"))
        runtime_evidence = dict(state.source_runtime_evidence)
        if (runtime_evidence.get("location_id") != location.get("location_id")
                or not runtime_evidence.get("captured")):
            runtime_evidence = hive._capture_runtime_at_source_location(location)
            state.source_runtime_evidence = dict(runtime_evidence)
        packet = {
            "task": {
                "id": task.task_id,
                "capability": "investigator",
                "description": "Explain only the controller-accepted source location.",
            },
            "authority": asdict(task.authority),
            "accepted_red_regression_nodes": list(state.regression_nodes),
            "local_requirement": hive.objective.original_request[-3_000:],
            "oracle_counterexample": counterexample or "unavailable",
            "accepted_source_location": location or "unavailable",
            "callable_signature": bounded["callable_signature"],
            "selected_symbol_source": bounded["selected_source_window"],
            "controller_runtime_evidence": runtime_evidence,
            "retry_feedback": (
                state.last_gate_feedback if state.last_failed_gate == "diagnosis_grounded"
                else "No prior rejected diagnosis in this responsibility."
            ),
            "tool_contracts": [{
                "name": "submit_mechanism",
                "arguments": {
                    "location_id": location.get("location_id", "NO ACCEPTED LOCATION"),
                    "mechanism": "EXPLAIN HOW THE CITED LINE CAUSES ACTUAL NOT EXPECTED",
                },
            }],
        }
        if state.rejected_investigator_diagnoses:
            # Rejected prose is controller-only state. Showing it to a small model
            # anchors the next hypothesis to the very mechanism Hive rejected.
            packet["prior_diagnoses_rejected"] = len(
                state.rejected_investigator_diagnoses)
        packet["instruction"] = (
            "Call submit_mechanism exactly once. Keep location_id exactly as prefilled. Replace "
            "only mechanism with one causal explanation of how the locked line and its operands "
            "produce actual instead of expected. The runtime frame is controller-observed state "
            "immediately before the selected line and must not be contradicted. Use only the "
            "local requirement, public counterexample, source window, and runtime evidence. "
            "Evaluate the literal selected expression from frames_before_line, state the assigned "
            "target visible in frames_after_line, and identify a relevant current-call parameter "
            "listed as not loaded by the RHS. Describe the resulting insensitivity. Do not call an "
            "internal value expected or actual, and do not describe a downstream delta or repair."
        )
        if task.expected_output:
            packet["assigned_feedback"] = task.expected_output[-2_000:]
        return packet

    def run(self, hive: "HiveExecutive", task: Task) -> WorkerRun:
        return hive._execute_task(task, self.system_prompt,
                                  self.compile_packet(hive, task), self)

    def create_task(self, hive: "HiveExecutive", source_files: list[str],
                    test_files: list[str], dependency: Task | None = None) -> Task:
        if dependency is None:
            raise ValueError("InvestigatorAgent requires a Cause Locator dependency")
        return hive.add_task(
            "Explain only how the accepted source location produces actual instead of expected.",
            "investigator", ["Submit one mechanism for the accepted source location"],
            Authority(list(self.allowed_tools), [], []),
            dependencies=[dependency.task_id], required_context=[],
            expected_output="One causal mechanism only; no source selection or repair",
        )

    def apply_gate(self, hive: "HiveExecutive", task: Task, run: WorkerRun,
                   status: str, summary: str, observations: list[dict[str, Any]],
                   current_snapshot: dict[str, str]) -> None:
        hive._apply_investigator_gate(task, summary, observations, current_snapshot)

    def grounded_completion(self, task: Task,
                            observations: list[dict[str, Any]]) -> dict[str, Any] | None:
        mechanism = next((item for item in reversed(observations)
                          if item["tool"] == "submit_mechanism"), None)
        if mechanism is None:
            return None
        return {
            "status": "COMPLETED",
            "summary": json.dumps(mechanism["arguments"], sort_keys=True, default=str),
            "evidence": [{"kind": "INFERENCE",
                          "summary": "Structured source-grounded diagnosis hypothesis",
                          "payload": mechanism["arguments"]}],
            "artifacts": [], "discovered_tasks": [],
        }


class CauseLocatorAgent(AtomicAgent):
    capability = "CAUSE_LOCATOR"
    system_prompt = CAUSE_LOCATOR_SYSTEM
    allowed_tools = ("submit_cause", "confirm_candidate", "reject_cause_frontier")

    def compile_packet(self, hive: "HiveExecutive", task: Task) -> dict[str, Any]:
        state = hive.objective.task_state
        task.authority.read_scopes = []
        task.authority.write_scopes = []
        locked = dict(state.callable_location)
        candidate = dict(state.candidate_source_location or state.source_location)
        source = snapshot_repository(hive.root).get(str(locked.get("source_file", "")))
        choices = hive._cause_line_choices(source, locked, candidate)
        candidate_id = str(candidate.get("location_id", ""))
        lines = source.splitlines() if isinstance(source, str) else []
        first = int(locked.get("definition_line", 0) or 0)
        last = int(locked.get("end_line", 0) or 0)
        callable_context = "\n".join(
            f"{number} | {lines[number - 1]}"
            for number in range(first, last + 1)
            if 1 <= number <= len(lines)
        )
        candidate_available = hive._cause_candidate_available(candidate)
        tool_contracts: list[dict[str, Any]] = []
        if choices:
            tool_contracts.append({
                "name": "submit_cause",
                "arguments": {
                    "candidate_location_id": candidate_id,
                    "cause_choice_id": (
                        "COPY ONE cause_choice_id FROM cause_source_line_choices"),
                },
            })
        if candidate_available:
            tool_contracts.append({
                "name": "confirm_candidate",
                "arguments": {"candidate_location_id": candidate_id},
            })
        if not choices and candidate_id:
            tool_contracts.append({
                "name": "reject_cause_frontier",
                "arguments": {"candidate_location_id": candidate_id},
            })
        task.authority.allowed_tools = [
            str(contract["name"]) for contract in tool_contracts]
        available_names = task.authority.allowed_tools
        if available_names == ["submit_cause"]:
            instruction = (
                "Call submit_cause exactly once with the unchanged candidate_location_id and "
                "one exact cause_choice_id from cause_source_line_choices."
            )
        elif available_names == ["confirm_candidate", "reject_cause_frontier"]:
            instruction = (
                "No upstream producer choices remain. Call confirm_candidate exactly once only "
                "if the locked candidate itself is the first wrong computation and explains every "
                "mismatched observable field; otherwise call reject_cause_frontier exactly once."
            )
        else:
            instruction = (
                "Call exactly one offered tool once. If candidate_direct_cause is itself the first "
                "wrong computation and explains every mismatched observable field, call "
                "confirm_candidate with its unchanged id. Otherwise call submit_cause with the "
                "unchanged candidate_location_id and copy one cause_choice_id from "
                "cause_source_line_choices. Prefer the earliest producer that explains every "
                "mismatched observable field."
            )
        return {
            "task": {
                "id": task.task_id,
                "capability": "cause_locator",
                "description": "Map the causal trace to one upstream producer choice.",
            },
            "authority": asdict(task.authority),
            "observable_counterexample": (
                hive._smallest_oracle_counterexample() or "unavailable"),
            "candidate_source_location": {
                key: candidate.get(key) for key in (
                    "location_id", "symbol", "line", "source_line")
            },
            "candidate_direct_cause": ({
                "candidate_location_id": candidate_id,
                "source_line": candidate.get("source_line", ""),
            } if candidate_available else "unavailable"),
            "callable_context": callable_context,
            "cause_source_line_choices": [
                {
                    "cause_choice_id": choice["cause_choice_id"],
                    "source_line": choice["source_line"],
                    "relation": choice["relation"],
                }
                for choice in choices
            ],
            "prior_cause_choices_deferred": len(
                state.operationally_deferred_cause_locations),
            "tool_contracts": tool_contracts,
            "instruction": instruction + " Submit no source text or explanation.",
            "assigned_feedback": task.expected_output[-3_000:],
        }

    def create_task(self, hive: "HiveExecutive", source_files: list[str],
                    test_files: list[str], dependency: Task | None = None) -> Task:
        if dependency is None:
            raise ValueError("CauseLocatorAgent requires a Source Locator dependency")
        return hive.add_task(
            "Confirm the selected computation, choose one upstream producer, or reject an "
            "exhausted causal frontier.",
            "cause_locator", ["Submit one controller-owned cause or frontier decision"],
            Authority(list(self.allowed_tools), [], []),
            dependencies=[dependency.task_id], required_context=[],
            expected_output="Locked candidate id and one direct or upstream cause choice only",
        )

    def apply_gate(self, hive: "HiveExecutive", task: Task, run: WorkerRun,
                   status: str, summary: str, observations: list[dict[str, Any]],
                   current_snapshot: dict[str, str]) -> None:
        hive._apply_cause_locator_gate(task, observations, current_snapshot)

    def grounded_completion(self, task: Task,
                            observations: list[dict[str, Any]]) -> dict[str, Any] | None:
        location = next((item for item in reversed(observations)
                         if item["tool"] in {
                             "submit_cause", "confirm_candidate", "reject_cause_frontier"}),
                        None)
        if location is None:
            return None
        return {
            "status": "COMPLETED",
            "summary": json.dumps(location["arguments"], sort_keys=True, default=str),
            "evidence": [{"kind": "INFERENCE",
                          "summary": "Structured upstream-cause location hypothesis",
                          "payload": location["arguments"]}],
            "artifacts": [], "discovered_tasks": [],
        }


class RegressionAgent(AtomicAgent):
    capability = "REGRESSION_DESIGNER"
    system_prompt = REGRESSION_SYSTEM
    allowed_tools = ("read_file", "run_command", "append_to_file")

    def run(self, hive: "HiveExecutive", task: Task) -> WorkerRun:
        return hive._execute_task(task, self.system_prompt,
                                  self.compile_packet(hive, task), self)

    def create_task(self, hive: "HiveExecutive", source_files: list[str],
                    test_files: list[str], dependency: Task | None = None) -> Task:
        if dependency is None:
            raise ValueError("RegressionAgent requires an Investigator dependency")
        return hive.add_task(
            "Add the smallest new regression test demonstrating the observed defect. Do not modify source or existing tests.",
            "regression_designer", ["A new test node fails on the broken revision"],
            Authority(list(self.allowed_tools), test_files, test_files),
            dependencies=[dependency.task_id], required_context=source_files + test_files,
            expected_output="One new focused test and its red-phase result",
        )

    def compile_packet(self, hive: "HiveExecutive", task: Task) -> dict[str, Any]:
        return hive._compile_regression_packet(task, hive._atomic_base_packet(task))

    def apply_gate(self, hive: "HiveExecutive", task: Task, run: WorkerRun,
                   status: str, summary: str, observations: list[dict[str, Any]],
                   current_snapshot: dict[str, str]) -> None:
        nodes = hive._verify_new_regression(current_snapshot)
        state = hive.objective.task_state
        state.regression_nodes = nodes
        state.accepted_regression_snapshot = dict(current_snapshot)
        state.regression_established = True
        state.regression_created = True
        state.regression_fails_on_broken_revision = True
        state.regression_origin = "created"

    def grounded_completion(self, task: Task,
                            observations: list[dict[str, Any]]) -> dict[str, Any] | None:
        edited = any(item["tool"] == "append_to_file" for item in observations)
        tested = any(item["tool"] == "run_command" for item in observations)
        return self.completed_from_evidence() if edited and tested else None


class RepairAgent(AtomicAgent):
    capability = "REPAIR"
    system_prompt = REPAIR_SYSTEM
    allowed_tools = ("replace_selected_leaf", "replace_selected_expression")

    def run(self, hive: "HiveExecutive", task: Task) -> WorkerRun:
        return hive._execute_task(task, self.system_prompt,
                                  self.compile_packet(hive, task), self)

    def create_task(self, hive: "HiveExecutive", source_files: list[str],
                    test_files: list[str], dependency: Task | None = None) -> Task:
        if dependency is None:
            raise ValueError("RepairAgent requires a Regression dependency")
        return hive.add_task(
            "Repair only the source defect exposed by the accepted regression. Do not modify tests.",
            "repair", ["The accepted regression and original suite pass"],
            Authority(list(self.allowed_tools), source_files, source_files),
            dependencies=[dependency.task_id], required_context=source_files + test_files,
            expected_output="Minimal source repair and exact green-phase result",
        )

    def compile_packet(self, hive: "HiveExecutive", task: Task) -> dict[str, Any]:
        return hive._compile_repair_packet(task)

    def retry_feedback(self, hive: "HiveExecutive", task: Task) -> str:
        state = hive.objective.task_state
        target = state.repair_oracle_target or state.regression_target
        locked_line = state.source_location.get("source_line", "")
        frame = state.source_location.get("expression_frame", {})
        replacement = (
            "choose a different controller-generated leaf substitution"
            if state.source_location.get("leaf_replacement_choices") else
            "submit only a materially different Python expression for "
            f"template={frame.get('template')!r}"
            if isinstance(frame, dict) and frame.get("mode") == "expression"
            else "submit only one materially different replacement source line"
        )
        return (
            "The prior proposal was rejected and rolled back. Use only the current source in "
            f"repair_handoff. Counterexample expected={target.get('expected')!r}, "
            f"actual={target.get('actual')!r}. Hive has locked old={locked_line!r}; "
            f"{replacement}. Do not reuse a prior proposal."
        )

    def apply_gate(self, hive: "HiveExecutive", task: Task, run: WorkerRun,
                   status: str, summary: str, observations: list[dict[str, Any]],
                   current_snapshot: dict[str, str]) -> None:
        state = hive.objective.task_state
        applied_selected_line_edit = False
        try:
            diagnosis = state.source_location
            replacements = [item.get("arguments", {}) for item in observations
                            if item.get("tool") in {
                                "replace_selected_line", "replace_selected_leaf",
                                "replace_selected_expression"}]
            if diagnosis:
                cited_line = str(diagnosis.get("source_line", "")).strip()
                source_file = str(diagnosis.get("source_file", ""))
                line_number = diagnosis.get("line")
                repaired_source = current_snapshot.get(source_file, "")
                repaired_lines = repaired_source.splitlines()
                changes_only_cited_line = bool(
                    cited_line and replacements
                    and isinstance(line_number, int) and not isinstance(line_number, bool)
                    and 1 <= line_number <= len(repaired_lines)
                    and repaired_lines[line_number - 1].strip() != cited_line
                )
                applied_selected_line_edit = changes_only_cited_line and bool(replacements)
                if not changes_only_cited_line:
                    hive._gate_failure(
                        "source_repaired",
                        "repair must replace exactly the Investigator's one cited source line "
                        "with one materially different source line",
                    )
            suite_passed, suite_output = hive._verify_repair(current_snapshot, run)
            if suite_passed and hive.acceptance_oracle is not None:
                try:
                    oracle_result = hive.acceptance_oracle(hive.root)
                except Exception as oracle_error:
                    oracle_result = None
                    hive.store.trace(
                        "repair_candidate_oracle_unavailable",
                        task_id=task.task_id,
                        error=f"{type(oracle_error).__name__}: {oracle_error}",
                    )
                if isinstance(oracle_result, dict) and not oracle_result.get("accepted"):
                    residual_packet = hive._public_oracle_residual(oracle_result)
                    residual = residual_packet.get("smallest_counterexample", {})
                    prior_operation = (
                        state.regression_target.get("operation")
                        if isinstance(state.regression_target, dict) else None)
                    residual_operation = (
                        residual.get("operation") if isinstance(residual, dict) else None)
                    if (prior_operation and residual_operation
                            and prior_operation == residual_operation):
                        state.repair_oracle_target = dict(residual)
                        state.oracle_feedback = json.dumps(
                            residual_packet, sort_keys=True, default=str)
                        hive._gate_failure(
                            "acceptance_oracle_pass",
                            "repair candidate passed the focused and visible suites but still "
                            "failed the same observable operation. The exact public residual is "
                            f"{state.oracle_feedback}. Roll back only this Repair proposal and "
                            "retry the remaining bounded edit choice.",
                        )
                elif isinstance(oracle_result, dict) and oracle_result.get("accepted"):
                    state.repair_oracle_target = {}
                    state.oracle_feedback = ""
        except Exception as exc:
            rejected = [hive._repair_action_from_arguments(
                item.get("arguments", {})) for item in observations if item["tool"] in {
                    "replace_selected_line", "replace_selected_leaf",
                    "replace_selected_expression"}]
            for action in rejected:
                if action not in state.rejected_repair_actions:
                    state.rejected_repair_actions.append(action)
                hive._bind_rejected_repair_action(
                    state, action, str(state.source_location.get("location_id", "")))
            if applied_selected_line_edit:
                location_id = str(state.source_location.get("location_id", ""))
                failures = state.location_repair_failures.get(location_id, 0) + 1
                state.location_repair_failures[location_id] = failures
                runtime_evidence = dict(state.source_runtime_evidence)
                all_leaf_choices = hive._leaf_replacement_choices(
                    state.source_location, runtime_evidence, [])
                rejected_for_location = [
                    str(action.get("new", "")) for action in state.rejected_repair_actions
                    if action.get("path") == state.source_location.get("source_file")
                    and action.get("old") == state.source_location.get("source_line")
                    and hive._repair_action_applies_to_location(
                        state, action, location_id)
                ]
                remaining_leaf_choices = hive._leaf_replacement_choices(
                    state.source_location, runtime_evidence, rejected_for_location)
                if all_leaf_choices and not remaining_leaf_choices:
                    feedback = (
                        "Every controller-generated one-reference substitution for the locked "
                        "expression remained red. Keep the failed edit family frozen and move "
                        "only to the next causal hypothesis; unrestricted expression editing is "
                        f"not authorized. Last gate: {exc}"
                    )
                    if not hive._schedule_cause_retry_after_failed_repair(
                            task, feedback, reason="leaf_repair_frontier_exhausted"):
                        hive._schedule_reinvestigation_after_failed_repair(task, feedback)
                elif failures >= hive.config.max_applied_repairs_per_location:
                    hive._schedule_next_cause_or_relocation(task, str(exc))
            raise
        state.root_cause_identified = True
        state.source_repaired = True
        state.regression_passes_after_repair = True
        state.original_tests_pass = suite_passed
        if not suite_passed:
            hive._extend_atomic_residual_after_repair(task, suite_output[-4_000:])

    def grounded_completion(self, task: Task,
                            observations: list[dict[str, Any]]) -> dict[str, Any] | None:
        edited = any(item["tool"] in {
            "replace_selected_line", "replace_selected_leaf",
            "replace_selected_expression"}
                     for item in observations)
        return self.completed_from_evidence() if edited else None


class ReviewerAgent(AtomicAgent):
    capability = "REVIEWER"
    system_prompt = REVIEWER_SYSTEM
    allowed_tools = ("review_snapshot", "submit_review")

    def run(self, hive: "HiveExecutive", task: Task) -> WorkerRun:
        return hive._execute_task(task, self.system_prompt,
                                  self.compile_packet(hive, task), self)

    def create_task(self, hive: "HiveExecutive", source_files: list[str],
                    test_files: list[str], dependency: Task | None = None) -> Task:
        if dependency is None:
            raise ValueError("ReviewerAgent requires a Repair dependency")
        context = source_files + test_files
        return hive.add_task(
            "Read only: look for cheating, weakened behavior, obvious nearby defects, or unnecessary modifications.",
            "reviewer", ["Report advisory findings supported by reads and tests"],
            Authority(list(self.allowed_tools), context, []),
            dependencies=[dependency.task_id], required_context=context,
            expected_output="Advisory findings only; Hive mechanically verifies every approval claim",
        )

    def compile_packet(self, hive: "HiveExecutive", task: Task) -> dict[str, Any]:
        return hive._compile_reviewer_packet(task, hive._atomic_base_packet(task))

    def apply_gate(self, hive: "HiveExecutive", task: Task, run: WorkerRun,
                   status: str, summary: str, observations: list[dict[str, Any]],
                   current_snapshot: dict[str, str]) -> None:
        hive.objective.task_state.review_pass = False
        if task.authority.write_scopes:
            hive._gate_failure("review_pass", "reviewer has write authority")
        snapshot_indexes = [index for index, item in enumerate(observations)
                            if item.get("tool") == "review_snapshot"]
        review_indexes = [index for index, item in enumerate(observations)
                          if item.get("tool") == "submit_review"]
        if (len(snapshot_indexes) != 1 or len(review_indexes) != 1
                or snapshot_indexes[0] > review_indexes[0]):
            hive._gate_failure(
                "review_pass",
                "Reviewer must inspect exactly one controller snapshot before submitting "
                "exactly one advisory review",
            )
        suite_passed, suite_output = hive._verify_repair(
            current_snapshot, run, require_source_edit=False)
        if not suite_passed:
            hive._gate_failure("review_pass", suite_output[-2_000:])
        advisory = dict(observations[review_indexes[0]].get("arguments", {}))
        hive.store.trace(
            "review_advisory_recorded", task_id=task.task_id,
            verdict=advisory.get("verdict", ""), findings=advisory.get("findings", []),
        )
        findings = [str(item) for item in advisory.get("findings", [])]
        verified, dismissed, boundary_error = hive._mechanically_verify_review_findings(
            findings, current_snapshot)
        if boundary_error:
            hive._gate_failure(
                "review_pass",
                boundary_error,
            )
        if dismissed:
            hive.store.trace(
                "review_advisory_dismissed", task_id=task.task_id,
                findings=dismissed,
                reason=(
                    "finding was not mechanically reproduced by the locked one-line diff, "
                    "immutable tests, fresh green suite, or literal-only repair check"
                ),
            )
        if verified:
            hive._gate_failure(
                "review_pass",
                "mechanically verified Reviewer findings remain: "
                + json.dumps(verified, default=str),
            )
        hive.objective.task_state.review_pass = True

    def grounded_completion(self, task: Task,
                            observations: list[dict[str, Any]]) -> dict[str, Any] | None:
        snapshot_index = next((index for index, item in enumerate(observations)
                               if item.get("tool") == "review_snapshot"), None)
        review_index = next((index for index in range(len(observations) - 1, -1, -1)
                             if observations[index].get("tool") == "submit_review"), None)
        if (snapshot_index is None or review_index is None
                or snapshot_index > review_index):
            return None
        advisory = dict(observations[review_index].get("arguments", {}))
        return {
            "status": "COMPLETED",
            "summary": json.dumps(advisory, sort_keys=True, default=str),
            "evidence": [{
                "kind": "INFERENCE",
                "summary": "Read-only advisory review after controller snapshot inspection",
                "payload": advisory,
            }],
            "artifacts": [], "discovered_tasks": [],
        }


class HiveExecutive:
    """Persistent executive with bounded worker scheduling and revision gates."""

    def __init__(self, root: str | Path | None = None, objective: str | None = None,
                 success_criteria: list[str] | None = None,
                 worker_chat: Callable[..., str] = ollama_chat,
                 judge_chat: Callable[..., str] = ollama_chat,
                 config: HiveConfig | None = None, objective_id: str | None = None,
                 acceptance_oracle: Callable[[Path], bool | dict[str, Any]] | None = None):
        self.root = Path(root or os.getcwd()).resolve()
        self.config = config or HiveConfig()
        self.worker_chat, self.judge_chat = worker_chat, judge_chat
        self.acceptance_oracle = acceptance_oracle
        self._lock = threading.RLock()
        self._model_slots = threading.BoundedSemaphore(self.config.max_model_concurrency)
        self._model_call_count = 0
        self._responsibility_call_counts: dict[str, int] = {}
        self._oracle_probe_cache: dict[str, dict[str, Any]] = {}
        agents = [ReproducerAgent(), CallableLocatorAgent(), SourceLocatorAgent(),
                  InvestigatorAgent(), CauseLocatorAgent(), RegressionAgent(),
                  RepairAgent(), ReviewerAgent()]
        self.atomic_agents: dict[str, AtomicAgent] = {
            agent.capability: agent for agent in agents
        }
        self._cancel_events: dict[str, threading.Event] = {}
        self.tasks: dict[str, Task] = {}
        self.worker_runs: dict[str, WorkerRun] = {}
        self.evidence: dict[str, Evidence] = {}
        self.artifacts: dict[str, Artifact] = {}
        if objective_id and not objective:
            self.store = StateStore(self.root, objective_id)
            self._restore(self.store.load())
        else:
            if not objective:
                raise ValueError("objective is required for a new HiveExecutive")
            baseline = snapshot_repository(self.root)
            oid = objective_id or stable_id("objective")
            self.objective = Objective(oid, objective.strip(), success_criteria or [objective.strip()],
                                       revision_id(baseline), baseline)
            self.store = StateStore(self.root, oid)
            self._persist()
            self.store.trace("objective_created", objective_id=oid,
                             baseline_revision=self.objective.baseline_revision)

    @classmethod
    def resume(cls, root: str | Path, objective_id: str,
               worker_chat: Callable[..., str] = ollama_chat,
               judge_chat: Callable[..., str] = ollama_chat,
               config: HiveConfig | None = None,
               acceptance_oracle: Callable[[Path], bool | dict[str, Any]] | None = None) -> "HiveExecutive":
        return cls(root=root, objective_id=objective_id, worker_chat=worker_chat,
                   judge_chat=judge_chat, config=config, acceptance_oracle=acceptance_oracle)

    def _payload(self) -> dict[str, Any]:
        return {"objective": asdict(self.objective),
                "tasks": {k: asdict(v) for k, v in self.tasks.items()},
                "worker_runs": {k: asdict(v) for k, v in self.worker_runs.items()},
                "evidence": {k: asdict(v) for k, v in self.evidence.items()},
                "artifacts": {k: asdict(v) for k, v in self.artifacts.items()},
                "controller_usage": {
                    "model_calls": self._model_call_count,
                    "responsibility_calls": dict(self._responsibility_call_counts),
                }}

    def _persist(self) -> None:
        self.objective.updated_at = utc_now()
        self.store.save(self._payload())

    def _restore(self, payload: dict[str, Any]) -> None:
        o = payload["objective"]
        if o.get("validation"):
            o["validation"] = ValidationResult(**o["validation"])
        o["graph_revisions"] = [
            item if isinstance(item, GraphRevision) else GraphRevision(**item)
            for item in o.get("graph_revisions", [])
        ]
        raw_task_state = o.get("task_state", {})
        if isinstance(raw_task_state, dict):
            raw_task_state.setdefault(
                "regression_established", raw_task_state.get("regression_created", False))
            raw_task_state.setdefault(
                "regression_origin", "created" if raw_task_state.get("regression_created") else "")
            # States written before the Source Locator / Investigator split already
            # used root_cause_identified only after a mechanically green repair. Keep
            # those completed trajectories resumable without inventing new evidence.
            legacy_confirmed = bool(raw_task_state.get("root_cause_identified", False))
            raw_task_state.setdefault("callable_location_grounded", legacy_confirmed)
            raw_task_state.setdefault("source_location_grounded", legacy_confirmed)
            raw_task_state.setdefault("cause_location_grounded", legacy_confirmed)
            raw_task_state.setdefault("diagnosis_grounded", legacy_confirmed)
        o["task_state"] = (raw_task_state if isinstance(raw_task_state, TaskState)
                           else TaskState(**raw_task_state))
        self.objective = Objective(**o)
        for key, raw in payload.get("tasks", {}).items():
            raw["status"] = TaskStatus(raw["status"])
            raw["authority"] = Authority(**raw["authority"])
            self.tasks[key] = Task(**raw)
        for key, raw in payload.get("worker_runs", {}).items():
            raw["status"] = WorkerStatus(raw["status"])
            raw["authority"] = Authority(**raw["authority"])
            self.worker_runs[key] = WorkerRun(**raw)
        for key, raw in payload.get("evidence", {}).items():
            raw["kind"] = EvidenceKind(raw["kind"])
            raw["lifecycle"] = EvidenceLifecycle(
                raw.get("lifecycle", "CURRENT" if raw.get("verified") else "UNVERIFIED"))
            self.evidence[key] = Evidence(**raw)
        self.artifacts = {k: Artifact(**v) for k, v in payload.get("artifacts", {}).items()}
        controller_usage = payload.get("controller_usage", {})
        if isinstance(controller_usage, dict):
            self._model_call_count = max(
                0, int(controller_usage.get("model_calls", self._model_call_count)))
            restored_counts = controller_usage.get("responsibility_calls", {})
            if isinstance(restored_counts, dict):
                self._responsibility_call_counts = {
                    str(key).upper(): max(0, int(value))
                    for key, value in restored_counts.items()
                }

    def add_task(self, description: str, capability: str,
                 acceptance_conditions: list[str], authority: Authority | None = None,
                 dependencies: list[str] | None = None, required_context: list[str] | None = None,
                 expected_output: str = "structured findings") -> Task:
        with self._lock:
            if len(self.tasks) >= self.config.max_queued_workers:
                raise RuntimeError("task queue budget exhausted")
            task = Task(stable_id("task"), self.objective.objective_id, description, capability,
                        acceptance_conditions, authority or Authority(), dependencies or [],
                        required_context or [], expected_output)
            self.tasks[task.task_id] = task
            self.objective.task_ids.append(task.task_id)
            try:
                self.validate_graph()
            except Exception:
                self.tasks.pop(task.task_id, None)
                self.objective.task_ids.remove(task.task_id)
                raise
            self._persist()
            self.store.trace("task_added", task_id=task.task_id, capability=capability,
                             dependencies=task.dependencies)
            return task

    def add_atomic_cycle(self, source_files: list[str], test_files: list[str]) -> list[Task]:
        """Create the eight-worker atomic graph with code-enforced authority boundaries."""
        if not self.config.responsibility_call_budgets:
            raise ValueError("atomic cycle requires HiveConfig.atomic()")
        snapshot = snapshot_repository(self.root)
        source_files = sorted(set(source_files))
        test_files = sorted(set(test_files))
        if (not source_files or not test_files
                or any(path not in snapshot for path in source_files + test_files)):
            raise ValueError("atomic scopes must name existing source and test files")
        if any(Path(path).name.startswith("test_") for path in source_files):
            raise ValueError("repair authority cannot include tests")
        if any(not Path(path).name.startswith("test_") for path in test_files):
            raise ValueError("regression authority can include tests only")
        if len(self.tasks) + 8 > self.config.max_queued_workers:
            raise RuntimeError("eight-worker atomic cycle exceeds task queue capacity")
        self.objective.task_state.atomic_source_files = list(source_files)
        self.objective.task_state.atomic_test_files = list(test_files)
        reproducer = self.atomic_agents["REPRODUCER"].create_task(
            self, source_files, test_files)
        callable_locator = self.atomic_agents["CALLABLE_LOCATOR"].create_task(
            self, source_files, test_files, reproducer)
        locator = self.atomic_agents["SOURCE_LOCATOR"].create_task(
            self, source_files, test_files, callable_locator)
        cause_locator = self.atomic_agents["CAUSE_LOCATOR"].create_task(
            self, source_files, test_files, locator)
        investigator = self.atomic_agents["INVESTIGATOR"].create_task(
            self, source_files, test_files, cause_locator)
        regression = self.atomic_agents["REGRESSION_DESIGNER"].create_task(
            self, source_files, test_files, investigator)
        repair = self.atomic_agents["REPAIR"].create_task(
            self, source_files, test_files, regression)
        reviewer = self.atomic_agents["REVIEWER"].create_task(
            self, source_files, test_files, repair)
        # Preserve the original five role positions for callers while exposing the
        # three locator roles at the end of the returned list.
        return [reproducer, investigator, regression, repair, reviewer,
                locator, callable_locator, cause_locator]

    def accept_task_proposal(self, evidence_id: str,
                             authority: Authority | None = None) -> Task:
        """Let the Executive turn an untrusted worker discovery into graph state."""
        proposal = self.evidence[evidence_id]
        if (proposal.kind != EvidenceKind.INFERENCE
                or proposal.summary != "Worker proposed a follow-up task for executive review"
                or not isinstance(proposal.payload, dict)):
            raise ValueError("evidence is not a worker task proposal")
        capability = str(proposal.payload.get("capability", "investigator")).upper()
        if capability not in CAPABILITIES:
            raise ValueError("proposed capability is not registered")
        spec = CAPABILITIES[capability]
        if spec.may_write and authority is None:
            raise ValueError("Builder proposal requires explicit Executive write authority")
        bounded_authority = authority or Authority(list(spec.allowed_tools), ["."], [])
        task = self.add_task(
            str(proposal.payload["description"]), capability.lower(),
            [str(item) for item in proposal.payload.get(
                "acceptance_conditions", ["Return grounded evidence"])],
            bounded_authority, dependencies=[proposal.task_id],
        )
        proposal.verified = True
        self._persist()
        self.store.trace("task_proposal_accepted", evidence_id=evidence_id,
                         task_id=task.task_id)
        return task

    def plan_tasks(self, planner_chat: Callable[..., str] | None = None) -> list[Task]:
        """Compile a model proposal into trusted task and authority state.

        The planner never supplies tools directly: capability templates and exact
        write scopes are validated by the executive before tasks enter the graph.
        """
        with self._lock:
            if self.tasks:
                return list(self.tasks.values())
        files = sorted(snapshot_repository(self.root))
        packet = {
            "original_objective": self.objective.original_request,
            "success_criteria": self.objective.success_criteria,
            "repository_files": files,
            "limits": {"max_tasks": self.config.max_queued_workers,
                       "max_worker_steps": self.config.max_worker_steps},
        }
        if len(json.dumps(packet)) > self.config.max_context_chars:
            packet["repository_files"] = files[:200]
        raw = self._call_model(planner_chat or self.worker_chat, [
            {"role": "system", "content": PLANNER_SYSTEM},
            {"role": "user", "content": json.dumps(packet)},
        ], self.config.default_model, responsibility="RECOVERY")
        parsed = json.loads(normalize(raw))
        proposals = parsed.get("tasks", []) if isinstance(parsed, dict) else []
        if not proposals or len(proposals) > self.config.max_queued_workers:
            raise ValueError("planner must return a nonempty task list within queue budget")
        keys = [str(item.get("key", "")) for item in proposals]
        if any(not key for key in keys) or len(keys) != len(set(keys)):
            raise ValueError("planner task keys must be nonempty and unique")
        known_files = set(files)
        normalized = []
        seen_keys: set[str] = set()
        for proposal, key in zip(proposals, keys):
            capability = str(proposal.get("capability", "")).upper()
            if capability not in CAPABILITIES:
                raise ValueError(f"unknown planned capability: {capability}")
            spec = CAPABILITIES[capability]
            write_scopes = [str(path) for path in proposal.get("write_scopes", [])]
            if spec.may_write != bool(write_scopes):
                raise ValueError("BUILDER requires write_scopes and read-only capabilities forbid them")
            for path in write_scopes:
                if path not in known_files or path == "." or Path(path).suffix == "":
                    raise ValueError("planned write scopes must be existing concrete files")
                WorkerSession(self.root, Authority(read_scopes=["."], write_scopes=[path]))._path(path, [path])
            required_context = [str(path) for path in proposal.get("required_context", [])]
            required_context = [path for path in required_context if path in known_files]
            dependency_keys = [str(item) for item in proposal.get("dependencies", [])]
            unknown = set(dependency_keys) - seen_keys
            if unknown:
                raise ValueError(f"planned dependencies must reference earlier tasks: {sorted(unknown)}")
            description = str(proposal.get("description", "")).strip()
            if not description:
                raise ValueError("planned task description is required")
            read_scopes = sorted(set(required_context + write_scopes)) or ["."]
            authority = Authority(list(spec.allowed_tools), read_scopes, write_scopes)
            normalized.append((key, description, capability, authority, dependency_keys,
                               required_context,
                               [str(item) for item in proposal.get("acceptance_conditions", [])]
                               or ["Return grounded evidence"]))
            seen_keys.add(key)
        # All untrusted proposals are normalized before the first durable mutation.
        created: dict[str, Task] = {}
        for key, description, capability, authority, dependency_keys, required_context, criteria in normalized:
            created[key] = self.add_task(
                description, capability.lower(), criteria,
                authority, [created[item].task_id for item in dependency_keys], required_context,
            )
        self.store.trace("objective_decomposed", task_ids=[task.task_id for task in created.values()])
        return list(created.values())

    def validate_graph(self) -> None:
        for task in self.tasks.values():
            missing = set(task.dependencies) - set(self.tasks)
            if missing:
                raise ValueError(f"task {task.task_id} has missing dependencies: {sorted(missing)}")
        visiting, visited = set(), set()
        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError(f"task dependency cycle at {task_id}")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in self.tasks[task_id].dependencies:
                visit(dependency)
            visiting.remove(task_id); visited.add(task_id)
        for task_id in self.tasks:
            visit(task_id)

    def ready_tasks(self) -> list[Task]:
        with self._lock:
            self.validate_graph()
            now = time.time()
            for task in self.tasks.values():
                if task.status == TaskStatus.RUNNING and task.lease_expires_at <= now:
                    task.status, task.lease_id = TaskStatus.FAILED, None
                    task.failure_reason = "worker lease expired"
                if task.status in {TaskStatus.PENDING, TaskStatus.WAITING, TaskStatus.READY}:
                    deps = [self.tasks[item].status for item in task.dependencies]
                    if any(status in {TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.REJECTED,
                                      TaskStatus.CANCELLED} for status in deps):
                        task.status = TaskStatus.WAITING
                    elif all(status == TaskStatus.COMPLETED for status in deps):
                        task.status = TaskStatus.READY
            self._persist()
            return [task for task in self.tasks.values() if task.status == TaskStatus.READY]

    def cancel_task(self, task_id: str, reason: str = "cancelled by executive") -> None:
        with self._lock:
            task = self.tasks[task_id]
            if task.status == TaskStatus.COMPLETED:
                raise ValueError("completed task cannot be cancelled")
            task.status, task.failure_reason, task.lease_id = TaskStatus.CANCELLED, reason, None
            if task.assigned_worker_run_id in self._cancel_events:
                self._cancel_events[task.assigned_worker_run_id].set()
            self._persist(); self.store.trace("task_cancelled", task_id=task_id, reason=reason)

    def retry_task(self, task_id: str) -> None:
        """Requeue a failed task only after its effective input has changed."""
        with self._lock:
            task = self.tasks[task_id]
            if task.status not in {TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.REJECTED}:
                raise ValueError("only failed, blocked, or rejected tasks may be retried")
            if (not self.config.responsibility_call_budgets
                    and task.retry_count > self.config.max_worker_retries):
                raise RuntimeError("worker retry budget exhausted")
            if task.last_failure_fingerprint == self._task_fingerprint(task):
                raise RuntimeError("retry denied until task input or repository fingerprint changes")
            task.status, task.failure_reason = TaskStatus.PENDING, ""
            task.updated_at = utc_now()
            self._persist(); self.store.trace("task_requeued", task_id=task_id,
                                              retry_count=task.retry_count)

    def _task_fingerprint(self, task: Task) -> str:
        dependency_evidence = {
            item: [asdict(self.evidence[eid]) for eid in self.tasks[item].evidence_ids]
            for item in task.dependencies
        }
        return _fingerprint({"description": task.description, "capability": task.capability,
                             "acceptance_conditions": task.acceptance_conditions,
                             "expected_output": task.expected_output,
                             "authority": asdict(task.authority),
                             "context": task.required_context, "dependencies": dependency_evidence,
                             "model": self.config.capability_models.get(
                                 task.capability, self.config.default_model),
                             "revision": revision_id(snapshot_repository(self.root))})

    def _acquire(self, task: Task) -> WorkerRun:
        with self._lock:
            if len(self.worker_runs) >= self.config.max_objective_worker_runs:
                raise RuntimeError("objective worker-run budget exhausted")
            if task.status != TaskStatus.READY:
                raise RuntimeError(f"task is not READY: {task.status.value}")
            if task.lease_id and task.lease_expires_at > time.time():
                raise RuntimeError("duplicate execution lease denied")
            fingerprint = self._task_fingerprint(task)
            if task.last_failure_fingerprint == fingerprint:
                raise RuntimeError("retry denied until task input or repository fingerprint changes")
            if (not self.config.responsibility_call_budgets
                    and task.retry_count > self.config.max_worker_retries):
                raise RuntimeError("worker retry budget exhausted")
            lease, run_id = stable_id("lease"), stable_id("worker")
            start_snapshot = snapshot_repository(self.root)
            run = WorkerRun(run_id, self.objective.objective_id, task.task_id, task.capability,
                            WorkerStatus.RUNNING, task.authority, fingerprint,
                            self.config.capability_models.get(task.capability, self.config.default_model), lease,
                            start_revision=revision_id(start_snapshot), start_snapshot=start_snapshot)
            if (task.capability.upper() == "REGRESSION_DESIGNER"
                    and not self.objective.task_state.regression_baseline_snapshot):
                self.objective.task_state.regression_baseline_snapshot = dict(start_snapshot)
            task.status, task.lease_id = TaskStatus.RUNNING, lease
            task.lease_expires_at, task.assigned_worker_run_id = time.time() + self.config.lease_seconds, run_id
            self.worker_runs[run_id] = run; self._cancel_events[run_id] = threading.Event()
            self._persist(); self.store.trace("worker_started", worker_run_id=run_id,
                                              task_id=task.task_id, fingerprint=fingerprint)
            return run

    def _responsibility_allowance(self, responsibility: str) -> int:
        """Return the durable role allowance, reclaiming only proven-skipped work."""
        responsibility = responsibility.upper()
        if responsibility == "RECOVERY":
            return self.config.recovery_reserve_calls
        allowance = self.config.responsibility_call_budgets.get(responsibility, 0)
        state = self.objective.task_state
        if state.regression_origin == "existing" and state.regression_established:
            # The deterministic adoption gate cancelled Regression, so its
            # reserved calls can no longer be consumed there. Redistribute that
            # exact reservation across the remaining diagnostic/repair roles.
            released = self.config.responsibility_call_budgets.get(
                "REGRESSION_DESIGNER", 0)
            if responsibility == "REGRESSION_DESIGNER":
                return 0
            investigator_bonus = min(1, released)
            cause_bonus = min(1, max(0, released - investigator_bonus))
            repair_bonus = max(0, released - investigator_bonus - cause_bonus)
            allowance += {
                "INVESTIGATOR": investigator_bonus,
                "CAUSE_LOCATOR": cause_bonus,
                "REPAIR": repair_bonus,
            }.get(responsibility, 0)
        return allowance

    def _recovery_reserve_unlocked(self) -> bool:
        """Reserve calls become available only after a late deterministic gate fails."""
        state = self.objective.task_state
        late_gates = {
            "source_repaired", "regression_passes_after_repair", "original_tests_pass",
            "acceptance_oracle_pass", "review_pass",
        }
        return (state.atomic_cycle > 1
                or any(state.gate_failures.get(gate, 0) > 0 for gate in late_gates))

    def _call_model(self, chat: Callable[..., str], messages: list[dict[str, str]], model: str,
                    responsibility: str = "RECOVERY") -> str:
        outcome: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        with self._lock:
            if self._model_call_count >= self.config.max_inference_calls:
                raise RuntimeError("objective inference budget exhausted")
            responsibility = responsibility.upper()
            allocations = self.config.responsibility_call_budgets
            if allocations:
                allowance = self._responsibility_allowance(responsibility)
                used = self._responsibility_call_counts.get(responsibility, 0)
                if used >= allowance:
                    recovery_used = self._responsibility_call_counts.get("RECOVERY", 0)
                    if (responsibility != "RECOVERY"
                            and self._recovery_reserve_unlocked()
                            and recovery_used < self.config.recovery_reserve_calls):
                        self._responsibility_call_counts["RECOVERY"] = recovery_used + 1
                    else:
                        raise RuntimeError(
                            f"{responsibility.lower()} responsibility inference budget exhausted")
                else:
                    self._responsibility_call_counts[responsibility] = used + 1
            self._model_call_count += 1

        def invoke() -> None:
            try:
                with self._model_slots:
                    parameters = inspect.signature(chat).parameters
                    kwargs = {}
                    if "model" in parameters: kwargs["model"] = model
                    if "url" in parameters: kwargs["url"] = self.config.ollama_url
                    outcome.put((True, chat(messages, **kwargs)))
            except BaseException as exc:  # contain model transport failures in the run
                outcome.put((False, exc))

        threading.Thread(target=invoke, daemon=True, name="hive-model-call").start()
        try:
            succeeded, value = outcome.get(timeout=self.config.worker_timeout_seconds)
        except queue.Empty as exc:
            raise TimeoutError("model call exceeded worker timeout") from exc
        if not succeeded:
            raise value
        return str(value)

    def _is_tail_task(self, task: Task) -> bool:
        revised_ids = {task_id for revision in self.objective.graph_revisions
                       for task_id in revision.inserted_task_ids}
        return (task.capability.upper() in {"REGRESSION_DESIGNER", "REVIEWER"}
                or (task.task_id in revised_ids and task.capability.upper() == "BUILDER"))

    def _worker_step_limit(self, task: Task) -> int:
        capability_limit = self.config.capability_step_limits.get(
            task.capability.upper(), self.config.max_worker_steps)
        limit = min(self.config.max_worker_steps, capability_limit)
        if not self._is_tail_task(task) and self.config.protected_tail_inference_calls:
            unreserved = (self.config.max_inference_calls
                          - self.config.protected_tail_inference_calls
                          - self._model_call_count)
            limit = min(limit, max(0, unreserved))
        return limit

    def _refresh_evidence_lifecycle(self, current_revision: str | None = None) -> None:
        """Keep stale observations out of active worker context without deleting history."""
        current_revision = current_revision or revision_id(snapshot_repository(self.root))
        for evidence in self.evidence.values():
            if evidence.lifecycle == EvidenceLifecycle.CONTRADICTED:
                continue
            if not evidence.verified:
                evidence.lifecycle = EvidenceLifecycle.UNVERIFIED
            elif evidence.revision == current_revision or not self.config.retire_superseded_evidence:
                evidence.lifecycle = EvidenceLifecycle.CURRENT
            else:
                evidence.lifecycle = EvidenceLifecycle.SUPERSEDED

    def _smallest_oracle_counterexample(self) -> dict[str, Any]:
        """Return only the smallest deterministic oracle failure for Regression."""
        if not self.config.responsibility_call_budgets or self.acceptance_oracle is None:
            return {}
        current_revision = revision_id(snapshot_repository(self.root))
        if current_revision not in self._oracle_probe_cache:
            result = self.acceptance_oracle(self.root)
            self._oracle_probe_cache[current_revision] = (
                result if isinstance(result, dict) else {})
        result = self._oracle_probe_cache[current_revision]
        behavior = result.get("behavior", {})
        example = (behavior.get("smallest_counterexample", {})
                   if isinstance(behavior, dict) else {})
        if not isinstance(example, dict):
            return {}
        # Evaluation oracles may reveal observable behavior, never test bodies,
        # source targets, repair contracts, or controller-authored code.
        public_fields = {
            "operation", "input_values", "payload", "expected", "actual", "error",
        }
        return {key: value for key, value in example.items() if key in public_fields}

    def _public_oracle_residual(
            self, oracle_result: dict[str, Any] | None = None) -> dict[str, Any]:
        """Expose observable residual behavior without leaking evaluator internals."""
        if oracle_result is None:
            counterexample = self._smallest_oracle_counterexample()
        else:
            behavior = oracle_result.get("behavior", {})
            example = (behavior.get("smallest_counterexample", {})
                       if isinstance(behavior, dict) else {})
            public_fields = {
                "operation", "input_values", "payload", "expected", "actual", "error",
            }
            counterexample = ({key: value for key, value in example.items()
                               if key in public_fields}
                              if isinstance(example, dict) else {})
        return {
            "accepted": False,
            "smallest_counterexample": counterexample,
        } if counterexample else {"accepted": False}

    def _atomic_base_packet(self, task: Task) -> dict[str, Any]:
        """Compile common immutable envelope; concrete agents add their own payload."""
        compiled = self._worker_packet(task)
        return {key: value for key, value in compiled.items() if key not in {
            "bounded_regression_protocol", "repair_handoff", "independent_review",
        }}

    def _compile_regression_packet(self, task: Task,
                                   packet: dict[str, Any]) -> dict[str, Any]:
        role_packet = self._worker_packet(task)
        packet["bounded_regression_protocol"] = role_packet["bounded_regression_protocol"]
        packet["dependency_evidence"] = []
        return packet

    def _compile_repair_packet(self, task: Task) -> dict[str, Any]:
        """Compile only the facts required by one concrete RepairAgent."""
        state = self.objective.task_state
        counterexample = (
            state.repair_oracle_target or state.regression_target
            or self._smallest_oracle_counterexample())
        if counterexample and not state.regression_target:
            state.regression_target = dict(counterexample)
        snapshot = snapshot_repository(self.root)
        source_context = {path: snapshot[path] for path in task.authority.write_scopes
                          if path in snapshot}
        if len(source_context) != 1:
            raise RuntimeError(
                "RepairAgent requires exactly one controller-selected source file")
        focused = _run_pytest_nodes(
            state.regression_nodes, self.root, self.config.command_timeout_seconds)
        focused_output = (
            f"EXIT CODE: {focused.returncode}\nSTDOUT:\n{focused.stdout}\nSTDERR:\n{focused.stderr}"
        )
        selected = dict(state.source_location)
        expression_frame = dict(selected.get("expression_frame", {}))
        if not expression_frame:
            expression_frame = self._source_expression_frame(
                str(selected.get("source_line", "")))
            selected["expression_frame"] = dict(expression_frame)
            state.source_location["expression_frame"] = dict(expression_frame)
        expression_only = expression_frame.get("mode") == "expression"
        candidate = dict(state.candidate_source_location)
        source_file = next(iter(source_context))
        source_text = next(iter(source_context.values()))
        bounded = self._bounded_callable_window(
            source_text, state.callable_location, selected.get("line"))
        diagnosis_matches_cause = (
            selected.get("line") == state.investigator_diagnosis.get("line")
            and selected.get("source_line")
            == state.investigator_diagnosis.get("source_line")
        )
        repair_diagnosis = {
            "location_id": selected.get("location_id", ""),
            "source_file": selected.get("source_file", ""),
            "symbol": selected.get("symbol", ""),
            "line": selected.get("line", 0),
            "source_line": selected.get("source_line", ""),
            "cause_relation": selected.get("cause_relation", ""),
            "actual": counterexample.get("actual") if isinstance(counterexample, dict) else None,
            "expected": (
                counterexample.get("expected") if isinstance(counterexample, dict) else None),
            "investigator_hypothesis_verified": False,
        }
        if diagnosis_matches_cause:
            repair_diagnosis["mechanism_advisory"] = (
                state.investigator_diagnosis.get("mechanism", ""))
        elif candidate:
            repair_diagnosis["candidate_hypothesis_withheld"] = True
        rejected_expressions = [
            str(action.get("new", ""))
            for action in state.rejected_repair_actions
            if action.get("path") == selected.get("source_file")
            and action.get("old") == selected.get("source_line")
            and self._repair_action_applies_to_location(
                state, action, str(selected.get("location_id", "")))
            and str(action.get("new", "")).strip()
        ]
        normalized_rejected: list[str] = []
        for rejected in rejected_expressions:
            if expression_only:
                try:
                    rejected = self._normalize_model_expression(
                        rejected, expression_frame)
                except ValueError:
                    pass
            if rejected.strip() and rejected.strip() not in normalized_rejected:
                normalized_rejected.append(rejected.strip())
        runtime_evidence = (
            dict(state.source_runtime_evidence)
            if state.source_runtime_evidence.get("location_id")
            == selected.get("location_id") else {}
        )
        all_leaf_choices = (
            self._leaf_replacement_choices(selected, runtime_evidence, [])
            if expression_only else []
        )
        leaf_choices = (
            self._leaf_replacement_choices(
                selected, runtime_evidence, normalized_rejected)
            if all_leaf_choices else []
        )
        if all_leaf_choices and not leaf_choices:
            state.source_location["leaf_replacement_choices"] = []
            task.authority.allowed_tools = ["replace_selected_leaf"]
            raise RuntimeError(
                "controller-generated leaf repair frontier is exhausted; unrestricted "
                "expression fallback is denied until Hive selects a new causal responsibility")
        selected["leaf_replacement_choices"] = list(leaf_choices)
        state.source_location["leaf_replacement_choices"] = list(leaf_choices)
        repair_tool = (
            "replace_selected_leaf" if leaf_choices else
            "replace_selected_expression" if expression_only else
            "replace_selected_line"
        )
        task.authority.allowed_tools = [repair_tool]
        return {
            "task": {
                "id": task.task_id,
                "capability": "repair",
                "description": "Make the accepted focused regression green by editing one causal source file.",
                "expected_output": (
                    "One controller-bounded leaf substitution for the locked source line"
                    if leaf_choices else
                    "One model-authored replacement for the locked source line"),
            },
            "authority": asdict(task.authority),
            "tool_contracts": [TOOL_CONTRACTS[repair_tool]],
            "repair_handoff": {
                "source_file": source_file,
                "callable_signature": bounded["callable_signature"],
                "selected_source_window": bounded["selected_source_window"],
                "investigator_diagnosis": (
                    repair_diagnosis
                    if state.investigator_diagnosis and selected else "unavailable"
                ),
                "controller_runtime_evidence": (
                    runtime_evidence if runtime_evidence else "unavailable"
                ),
                "accepted_regression_counterexample": (
                    dict(state.regression_target) if state.regression_target else "unavailable"),
                "same_operation_oracle_residual": (
                    dict(state.repair_oracle_target)
                    if state.repair_oracle_target else "unavailable"),
                "observable_counterexample": counterexample or "unavailable",
                "locked_statement_frame": {
                    "mode": expression_frame.get("mode", "statement"),
                    "template": expression_frame.get("template", "<MODEL_STATEMENT>"),
                    "old_expression": expression_frame.get("old_expression", ""),
                    "assigned_targets": list(
                        expression_frame.get("assigned_targets", [])),
                },
                "leaf_replacement_choices": leaf_choices,
                "focused_red_output": focused_output[-1_500:],
                "prior_proposals_rejected": len(state.rejected_repair_actions),
                "rejected_expressions_for_locked_line": normalized_rejected,
                "retry_feedback": (
                    task.expected_output[-2_000:]
                    if task.retry_count else "No prior Repair proposal in this handoff."
                ),
                "instruction": (
                    "Edit only source_file. Make the exact accepted regression pass. "
                    "Use the controller-selected causal statement, observable counterexample, "
                    "controller-observed runtime frame, bounded callable context, and focused red "
                    "output. Investigator mechanism text is advisory, not proof; reconcile it with "
                    "the controller runtime evidence. Only red-to-green execution can confirm it. "
                    "Preserve the data-flow stages shown in selected_source_window: do not fold a "
                    "later subtraction, delta, aggregation, or presentation operation into this "
                    "producer's RHS when that operation already remains downstream. "
                    "Do not reuse any expression listed for the locked line. "
                    "Do not change tests, callers, formatting layers, or unrelated behavior. "
                     + ("Hive has preserved the entire selected RHS operator tree and generated "
                        "the only allowed one-reference substitutions from captured in-scope data. "
                        "Compare the choices with the runtime evidence, copy exactly one choice_id, "
                        "and do not author source text. " if leaf_choices else
                        "Hive owns every byte shown around <MODEL_EXPRESSION>. Supply only the "
                        "replacement expression: no assignment target, return keyword, indentation, "
                        "or statement wrapper. " if expression_only else
                       "Supply exactly one replacement source line without indentation. ")
                    + f"Call {repair_tool} exactly once, then stop; "
                    "Hive runs all tests."
                ),
            },
        }

    def _repair_action_from_arguments(
            self, arguments: Any) -> dict[str, str]:
        """Resolve an opaque Repair choice back to the exact controller-owned edit."""
        selected = self.objective.task_state.source_location
        malformed = not isinstance(arguments, dict)
        safe_arguments = arguments if isinstance(arguments, dict) else {}
        proposed = (
            f"<malformed-arguments:{type(arguments).__name__}>" if malformed
            else str(safe_arguments.get("new", ""))
        )
        choice_id = str(safe_arguments.get("choice_id", "")).strip()
        if choice_id:
            matches = [
                choice for choice in selected.get("leaf_replacement_choices", [])
                if isinstance(choice, dict) and choice.get("choice_id") == choice_id
            ]
            proposed = (
                str(matches[0].get("resulting_expression", ""))
                if len(matches) == 1 else f"<unknown-leaf-choice:{choice_id}>"
            )
        return {
            "path": str(selected.get("source_file", "")),
            "old": str(selected.get("source_line", "")),
            "new": proposed.strip(),
        }

    @staticmethod
    def _repair_action_applies_to_location(
            state: TaskState, action: dict[str, Any], location_id: str) -> bool:
        """Honor new multi-location bindings and legacy unbound/string state."""
        recorded = state.rejected_repair_action_locations.get(_fingerprint(action))
        if not recorded:
            return True
        if isinstance(recorded, str):
            return recorded == location_id
        return location_id in recorded

    @staticmethod
    def _bind_rejected_repair_action(
            state: TaskState, action: dict[str, Any], location_id: str) -> None:
        if not location_id:
            return
        fingerprint = _fingerprint(action)
        recorded = state.rejected_repair_action_locations.get(fingerprint, [])
        locations = [recorded] if isinstance(recorded, str) else list(recorded)
        if location_id not in locations:
            locations.append(location_id)
        state.rejected_repair_action_locations[fingerprint] = locations

    def _record_rejected_repair_action(
            self, task: Task, arguments: Any, error: Exception,
            session: WorkerSession) -> None:
        selected = self.objective.task_state.source_location
        action = self._repair_action_from_arguments(arguments)
        state = self.objective.task_state
        prior_invalid_actions = [
            item.get("action", {}) for item in state.invalid_repair_submissions
            if isinstance(item, dict)
            and (not item.get("location_id")
                 or item.get("location_id") == selected.get("location_id"))
        ]
        repeated = (
            (action in state.rejected_repair_actions
             and self._repair_action_applies_to_location(
                 state, action, str(selected.get("location_id", ""))))
            or action in prior_invalid_actions)
        invalid_submission = {
            "action": dict(action),
            "location_id": str(selected.get("location_id", "")),
            "error_type": type(error).__name__,
            "error": str(error)[:1_000],
        }
        if invalid_submission not in state.invalid_repair_submissions:
            state.invalid_repair_submissions.append(invalid_submission)
        if action not in session.rejected_replacements:
            session.rejected_replacements.append(action)
        feedback = (
            f"selected-line repair rejected for {action['path']!r}: "
            f"{type(error).__name__}: {error}. Hive still owns the locked old line; "
            "submit a materially different replacement through the authorized tool."
        )
        state.last_failed_gate = "source_repaired"
        state.last_gate_feedback = feedback
        state.gate_failures["source_repaired"] = (
            state.gate_failures.get("source_repaired", 0) + 1)
        self.store.trace(
            "repair_action_rejected", task_id=task.task_id,
            action=action, error=f"{type(error).__name__}: {error}",
        )
        selected_line_action = (
            repeated
            and bool(action["new"])
        )
        location_id = str(selected.get("location_id", ""))
        if selected_line_action and location_id:
            stagnations = state.location_repair_stagnations.get(location_id, 0) + 1
            state.location_repair_stagnations[location_id] = stagnations
            # A broker rejection proves only that this proposal violated the locked
            # repair contract. It is not evidence against the Cause-selected line.
            self.store.trace(
                "repair_action_stagnated_same_location", task_id=task.task_id,
                location_id=location_id, stagnations=stagnations,
                feedback=feedback[-2_000:],
            )
            self._schedule_next_cause_or_relocation(
                task,
                "Repair responsibility repeated an exact broker-rejected action at the "
                "locked hypothesis. The action is disproven; move to another unconfirmed "
                f"cause/location without treating this as causal proof.\n{feedback}",
                reason="broker_rejected_action_stagnation",
            )

    def _schedule_next_cause_or_relocation(
            self, repair_task: Task, feedback: str,
            reason: str = "bounded_applied_repair_attempts_exhausted") -> None:
        """Retry the narrowest unconfirmed responsibility before wider relocation."""
        if self._schedule_investigator_retry_after_failed_repair(
                repair_task, feedback, reason=reason):
            return
        if self._schedule_cause_retry_after_failed_repair(
                repair_task, feedback, reason=reason):
            return
        self._schedule_reinvestigation_after_failed_repair(repair_task, feedback)

    def _schedule_investigator_retry_after_failed_repair(
            self, repair_task: Task, feedback: str,
            reason: str = "repair_hypothesis_stagnated") -> bool:
        """Retry only the unverified mechanism once while keeping Cause frozen.

        A red or broker-invalid repair proposal disproves that proposal, not the
        controller-selected source line.  One fresh Investigator call gets a chance to
        replace the advisory mechanism before Hive rotates to another cause edge.
        """
        state = self.objective.task_state
        selected = dict(state.source_location)
        location_id = str(selected.get("location_id", ""))
        if (not state.cause_location_grounded or not state.diagnosis_grounded
                or not location_id or not state.investigator_diagnosis):
            return False
        prior_for_location = [
            item for item in state.rejected_investigator_diagnoses
            if str(item.get("location_id", "")) == location_id
        ]
        if prior_for_location:
            return False
        ancestor_ids = set(repair_task.dependencies)
        frontier = list(repair_task.dependencies)
        while frontier:
            ancestor = self.tasks[frontier.pop()]
            for dependency_id in ancestor.dependencies:
                if dependency_id not in ancestor_ids:
                    ancestor_ids.add(dependency_id)
                    frontier.append(dependency_id)
        investigators = [
            candidate for candidate in self.tasks.values()
            if candidate.task_id in ancestor_ids
            and candidate.capability.upper() == "INVESTIGATOR"
            and candidate.status == TaskStatus.COMPLETED
        ]
        if not investigators or len(self.tasks) + 1 > self.config.max_queued_workers:
            return False
        prior_investigator = investigators[-1]
        causes = [
            self.tasks[dependency_id]
            for dependency_id in prior_investigator.dependencies
            if self.tasks[dependency_id].capability.upper() == "CAUSE_LOCATOR"
            and self.tasks[dependency_id].status == TaskStatus.COMPLETED
        ]
        if len(causes) != 1:
            return False
        fresh = self.atomic_agents["INVESTIGATOR"].create_task(
            self, list(state.atomic_source_files), list(state.atomic_test_files), causes[0])
        fresh.description = (
            "Re-explain only the same frozen Cause-selected line after the prior mechanism-led "
            "repair proposals failed."
        )
        fresh.expected_output = (
            "The prior advisory mechanism did not lead to a green focused regression. Produce "
            "one materially different mechanism for the same locked line without changing "
            "Callable, Source, Cause, tests, or source:\n" + feedback[-2_000:]
        )
        direct_investigators = {
            dependency_id for dependency_id in repair_task.dependencies
            if self.tasks[dependency_id].capability.upper() == "INVESTIGATOR"
        }
        repair_task.dependencies = [
            dependency_id for dependency_id in repair_task.dependencies
            if dependency_id not in direct_investigators
        ]
        repair_task.dependencies.append(fresh.task_id)
        repair_task.dependencies = list(dict.fromkeys(repair_task.dependencies))
        prior_diagnosis = dict(state.investigator_diagnosis)
        if prior_diagnosis not in state.rejected_investigator_diagnoses:
            state.rejected_investigator_diagnoses.append(prior_diagnosis)
        state.diagnosis_grounded = False
        state.investigator_diagnosis = {}
        state.root_cause_identified = False
        self.validate_graph()
        self.store.trace(
            "investigator_retry_same_cause_scheduled",
            repair_task_id=repair_task.task_id,
            prior_investigator_task_id=prior_investigator.task_id,
            fresh_investigator_task_id=fresh.task_id,
            cause_locator_task_id=causes[0].task_id,
            location_id=location_id,
            reason=reason,
            feedback=feedback[-2_000:],
        )
        return True

    def _schedule_cause_retry_after_failed_repair(
            self, repair_task: Task, feedback: str,
            reason: str = "bounded_applied_repair_attempts_exhausted") -> bool:
        """Retire one unconfirmed cause edge after bounded applied repair attempts.

        Cause now precedes Investigator.  A different producer therefore needs its
        own fresh, producer-scoped mechanism before Repair may run again.
        """
        state = self.objective.task_state
        candidate = dict(state.candidate_source_location)
        selected = dict(state.source_location)
        candidate_id = str(candidate.get("location_id", ""))
        if (not state.cause_location_grounded or not state.diagnosis_grounded
                or not candidate_id
                or selected.get("candidate_location_id") != candidate_id):
            return False
        rejection = {
            "candidate_location_id": candidate_id,
            "source_file": selected.get("source_file", ""),
            "symbol": selected.get("symbol", ""),
            "line": selected.get("line", 0),
            "source_line": selected.get("source_line", ""),
            "cause_relation": selected.get("cause_relation", ""),
            "reason": reason,
        }
        if rejection not in state.operationally_deferred_cause_locations:
            state.operationally_deferred_cause_locations.append(rejection)

        snapshot = snapshot_repository(self.root)
        source = snapshot.get(str(state.callable_location.get("source_file", "")))
        remaining = self._cause_line_choices(
            source, state.callable_location, candidate)
        candidate_remaining = self._cause_candidate_available(candidate)
        if not remaining and not candidate_remaining:
            # The symptom's complete syntactic cause frontier is exhausted. Restore
            # that candidate before the full relocation path records it as disproven.
            state.source_location = dict(candidate)
            state.source_location_grounded = True
            state.cause_location_grounded = False
            return False

        ancestor_ids = set(repair_task.dependencies)
        frontier = list(repair_task.dependencies)
        while frontier:
            ancestor = self.tasks[frontier.pop()]
            for dependency_id in ancestor.dependencies:
                if dependency_id not in ancestor_ids:
                    ancestor_ids.add(dependency_id)
                    frontier.append(dependency_id)
        causes = [candidate_task for candidate_task in self.tasks.values()
                  if candidate_task.task_id in ancestor_ids
                  and candidate_task.capability.upper() == "CAUSE_LOCATOR"]
        if not causes or len(self.tasks) + 2 > self.config.max_queued_workers:
            state.source_location = dict(candidate)
            state.source_location_grounded = True
            state.cause_location_grounded = False
            return False
        prior_cause = causes[-1]
        source_locator = next((
            self.tasks[dependency_id]
            for dependency_id in prior_cause.dependencies
            if self.tasks[dependency_id].capability.upper() == "SOURCE_LOCATOR"
        ), None)
        if source_locator is None:
            return False
        created: list[Task] = []
        try:
            new_cause = self.atomic_agents["CAUSE_LOCATOR"].create_task(
                self, list(state.atomic_source_files), list(state.atomic_test_files),
                source_locator)
            created.append(new_cause)
            new_investigator = self.atomic_agents["INVESTIGATOR"].create_task(
                self, list(state.atomic_source_files), list(state.atomic_test_files),
                new_cause)
            created.append(new_investigator)
        except Exception:
            for created_task in reversed(created):
                self.tasks.pop(created_task.task_id, None)
                if created_task.task_id in self.objective.task_ids:
                    self.objective.task_ids.remove(created_task.task_id)
            self._persist()
            raise
        new_cause.description = (
            "Retry only upstream cause selection; Callable and symptom are frozen."
        )
        new_cause.expected_output = (
            "The prior cause-selected repair did not make the locked regression green. "
            "Choose one remaining cause-only producer:\n" + feedback[-2_000:]
        )
        new_investigator.description = (
            "Explain only how the newly selected producer causes the observable mismatch."
        )
        new_investigator.expected_output = (
            "A prior producer hypothesis was mechanically rejected. Explain the fresh locked "
            "producer without reusing the symptom-bound mechanism:\n" + feedback[-2_000:]
        )
        direct_investigators = {
            dependency_id for dependency_id in repair_task.dependencies
            if self.tasks[dependency_id].capability.upper() == "INVESTIGATOR"
        }
        repair_task.dependencies = [
            dependency_id for dependency_id in repair_task.dependencies
            if dependency_id not in direct_investigators
        ]
        repair_task.dependencies.append(new_investigator.task_id)
        repair_task.dependencies = list(dict.fromkeys(repair_task.dependencies))
        if (state.investigator_diagnosis
                and state.investigator_diagnosis
                not in state.rejected_investigator_diagnoses):
            state.rejected_investigator_diagnoses.append(
                dict(state.investigator_diagnosis))
        state.source_location = dict(candidate)
        state.source_location_grounded = True
        state.cause_location_grounded = False
        state.diagnosis_grounded = False
        state.investigator_diagnosis = {}
        state.source_runtime_evidence = {}
        state.root_cause_identified = False
        self.validate_graph()
        self.store.trace(
            "cause_choice_rejected_retry_scheduled",
            repair_task_id=repair_task.task_id,
            prior_cause_task_id=prior_cause.task_id,
            cause_locator_task_id=new_cause.task_id,
            investigator_task_id=new_investigator.task_id,
            candidate_location_id=candidate_id,
            rejected_cause=rejection,
            remaining_cause_choices=len(remaining) + int(candidate_remaining),
            feedback=feedback[-2_000:],
        )
        return True

    def _schedule_reinvestigation_after_failed_repair(
            self, repair_task: Task, feedback: str,
            dependency: Task | None = None,
            superseded_dependency_id: str = "") -> None:
        """Return a disproven line to fresh callable, line, and mechanism roles."""
        ancestor_ids = set(repair_task.dependencies)
        frontier = list(repair_task.dependencies)
        while frontier:
            ancestor = self.tasks[frontier.pop()]
            for dependency_id in ancestor.dependencies:
                if dependency_id not in ancestor_ids:
                    ancestor_ids.add(dependency_id)
                    frontier.append(dependency_id)
        investigators = [candidate for candidate in self.tasks.values()
                         if candidate.task_id in ancestor_ids
                         and candidate.capability.upper() == "INVESTIGATOR"]
        if not investigators:
            return
        prior = dependency or investigators[-1]
        state = self.objective.task_state
        if len(self.tasks) + 4 > self.config.max_queued_workers:
            state.last_failed_gate = "source_repaired"
            state.last_gate_feedback = (
                "cannot schedule Callable Locator, Source Locator, Investigator, and "
                "Cause Locator: "
                "task queue capacity exhausted"
            )
            return
        source_files = sorted({
            path for path in state.atomic_source_files
            if Path(path).suffix == ".py" and not Path(path).name.startswith("test_")
        })
        test_files = list(state.atomic_test_files)
        if not source_files:
            return
        created: list[Task] = []
        try:
            callable_locator = self.atomic_agents["CALLABLE_LOCATOR"].create_task(
                self, source_files, test_files, prior)
            created.append(callable_locator)
            callable_locator.description = (
                "Relocate only the callable: the prior exact source line exhausted its "
                "bounded repair hypotheses without making the locked regression green."
            )
            callable_locator.expected_output = (
                "Mechanically disproven exact source line; select a callable that contains "
                "another upstream producer:\n" + feedback[-3_000:]
            )
            relocalizer = self.atomic_agents["SOURCE_LOCATOR"].create_task(
                self, source_files, test_files, callable_locator)
            created.append(relocalizer)
            relocalizer.description = (
                "Relocate only: the prior exact source line produced an edit that did not make "
                "the locked regression green. Select a different upstream producer."
            )
            relocalizer.expected_output = (
                "Mechanically disproven source location; choose another:\n" + feedback[-3_000:]
            )
            cause_locator = self.atomic_agents["CAUSE_LOCATOR"].create_task(
                self, source_files, test_files, relocalizer)
            created.append(cause_locator)
            reinvestigator = self.atomic_agents["INVESTIGATOR"].create_task(
                self, source_files, test_files, cause_locator)
            created.append(reinvestigator)
        except Exception:
            # add_task is durable. Remove every partial member so an orphaned
            # locator chain cannot enter the queue.
            for created_task in reversed(created):
                self.tasks.pop(created_task.task_id, None)
                if created_task.task_id in self.objective.task_ids:
                    self.objective.task_ids.remove(created_task.task_id)
            self._persist()
            raise
        reinvestigator.description = (
            "Re-investigate only: the prior source hypothesis produced an edit that did not "
            "make the locked regression green. Submit a materially different diagnosis."
        )
        reinvestigator.expected_output = (
            "Mechanically rejected prior repair hypothesis:\n" + feedback[-3_000:]
        )
        retained_dependencies = [
            dependency_id for dependency_id in repair_task.dependencies
            if dependency_id != superseded_dependency_id
        ]
        repair_task.dependencies = list(dict.fromkeys([
            *retained_dependencies, reinvestigator.task_id,
        ]))
        if (state.investigator_diagnosis
                and state.investigator_diagnosis
                not in state.rejected_investigator_diagnoses):
            state.rejected_investigator_diagnoses.append(
                dict(state.investigator_diagnosis))
        if state.source_location:
            identity = {key: state.source_location.get(key) for key in (
                "source_file", "symbol", "line", "source_line")}
            identity["reason"] = "bounded_repair_hypotheses_exhausted"
            if identity not in state.operationally_deferred_source_locations:
                state.operationally_deferred_source_locations.append(identity)
        # Failed edit proposals do not prove the line or enclosing callable false.
        # Operationally defer the exact line so the bounded trajectory can explore
        # another hypothesis without overstating what the test evidence established.
        state.callable_location_grounded = False
        state.callable_location = {}
        state.source_location_grounded = False
        state.source_location = {}
        state.candidate_source_location = {}
        state.cause_location_grounded = False
        state.source_runtime_evidence = {}
        state.diagnosis_grounded = False
        state.investigator_diagnosis = {}
        state.root_cause_identified = False
        self.validate_graph()
        self.store.trace(
            "repair_hypothesis_rejected_relocation_scheduled",
            repair_task_id=repair_task.task_id,
            prior_investigator_task_id=prior.task_id,
            callable_locator_task_id=callable_locator.task_id,
            source_locator_task_id=relocalizer.task_id,
            reinvestigator_task_id=reinvestigator.task_id,
            cause_locator_task_id=cause_locator.task_id,
            feedback=feedback[-3_000:],
        )

    def _schedule_after_rejected_cause_frontier(
            self, cause_task: Task, feedback: str) -> None:
        """Relocate a symptom whose remaining causal frontier was explicitly rejected.

        This is an operational model decision, not proof that a source line is wrong or
        causally irrelevant.  Keep it in a separate deferred ledger and leave every
        completion boolean false until a later repair flips the regression red to green.
        """
        state = self.objective.task_state
        waiting_investigators = [
            candidate for candidate in self.tasks.values()
            if candidate.capability.upper() == "INVESTIGATOR"
            and cause_task.task_id in candidate.dependencies
            and candidate.status != TaskStatus.COMPLETED
        ]
        if len(waiting_investigators) != 1:
            raise RuntimeError(
                "cause-frontier rejection requires exactly one waiting Investigator")
        prior_investigator = waiting_investigators[0]
        consumers = [
            candidate for candidate in self.tasks.values()
            if prior_investigator.task_id in candidate.dependencies
            and candidate.status != TaskStatus.CANCELLED
        ]
        if not consumers:
            raise RuntimeError(
                "cause-frontier rejection has no downstream responsibility to rewire")
        if len(self.tasks) + 4 > self.config.max_queued_workers:
            raise RuntimeError(
                "cannot schedule cause-frontier relocation: task queue capacity exhausted")
        source_files = sorted({
            path for path in state.atomic_source_files
            if Path(path).suffix == ".py" and not Path(path).name.startswith("test_")
        })
        test_files = list(state.atomic_test_files)
        if not source_files:
            raise RuntimeError("cause-frontier relocation has no source authority")
        created: list[Task] = []
        try:
            callable_locator = self.atomic_agents["CALLABLE_LOCATOR"].create_task(
                self, source_files, test_files, cause_task)
            created.append(callable_locator)
            source_locator = self.atomic_agents["SOURCE_LOCATOR"].create_task(
                self, source_files, test_files, callable_locator)
            created.append(source_locator)
            new_cause = self.atomic_agents["CAUSE_LOCATOR"].create_task(
                self, source_files, test_files, source_locator)
            created.append(new_cause)
            new_investigator = self.atomic_agents["INVESTIGATOR"].create_task(
                self, source_files, test_files, new_cause)
            created.append(new_investigator)
        except Exception:
            for created_task in reversed(created):
                self.tasks.pop(created_task.task_id, None)
                if created_task.task_id in self.objective.task_ids:
                    self.objective.task_ids.remove(created_task.task_id)
            self._persist()
            raise
        callable_locator.description = (
            "Relocate only the callable after the current symptom's causal frontier was "
            "explicitly exhausted.")
        callable_locator.expected_output = feedback[-3_000:]
        source_locator.description = (
            "Select a different symptom/producer after an exhausted causal frontier.")
        source_locator.expected_output = feedback[-3_000:]
        new_cause.expected_output = feedback[-3_000:]
        new_investigator.expected_output = feedback[-3_000:]
        for consumer in consumers:
            consumer.dependencies = [
                new_investigator.task_id
                if dependency_id == prior_investigator.task_id else dependency_id
                for dependency_id in consumer.dependencies
            ]
            consumer.dependencies = list(dict.fromkeys(consumer.dependencies))
        self.cancel_task(
            prior_investigator.task_id,
            "NONRETRYABLE: superseded after Cause Locator rejected the exhausted frontier",
        )
        candidate = dict(state.candidate_source_location or state.source_location)
        if candidate:
            deferred = {
                "source_file": candidate.get("source_file", ""),
                "symbol": candidate.get("symbol", ""),
                "line": candidate.get("line", 0),
                "source_line": candidate.get("source_line", ""),
                "reason": "cause_frontier_rejected",
            }
            if deferred not in state.operationally_deferred_source_locations:
                state.operationally_deferred_source_locations.append(deferred)
        state.callable_location_grounded = False
        state.callable_location = {}
        state.source_location_grounded = False
        state.source_location = {}
        state.candidate_source_location = {}
        state.cause_location_grounded = False
        state.diagnosis_grounded = False
        state.investigator_diagnosis = {}
        state.source_runtime_evidence = {}
        state.root_cause_identified = False
        self.validate_graph()
        self.store.trace(
            "cause_frontier_rejected_relocation_scheduled",
            cause_locator_task_id=cause_task.task_id,
            prior_investigator_task_id=prior_investigator.task_id,
            callable_locator_task_id=callable_locator.task_id,
            source_locator_task_id=source_locator.task_id,
            new_cause_task_id=new_cause.task_id,
            new_investigator_task_id=new_investigator.task_id,
            feedback=feedback[-3_000:],
        )

    def _compile_reviewer_packet(self, task: Task,
                                 packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "task": {
                "id": task.task_id,
                "capability": "reviewer",
                "description": "Inspect the controller-brokered final diff and test result.",
            },
            "authority": asdict(task.authority),
            "tool_contracts": [
                TOOL_CONTRACTS["review_snapshot"], TOOL_CONTRACTS["submit_review"]],
            "instruction": (
                "Call review_snapshot exactly once. Inspect only its diff and fresh test "
                "result, then call submit_review exactly once. Use PASS with [] only when "
                "the snapshot supports no concrete concern; otherwise use FINDINGS and short "
                "snapshot-grounded findings that cite an exact added/removed token. The diff "
                "is the complete change boundary: ignore unchanged code not shown there. Do "
                "not edit or decide task completion."
            ),
        }

    @classmethod
    def _literal_only_repair_expression(cls, source_line: str) -> bool:
        frame = cls._source_expression_frame(source_line)
        expression = str(frame.get("old_expression", ""))
        if not expression:
            return False
        try:
            node = ast.parse(expression, mode="eval").body
        except SyntaxError:
            return False

        def literal(item: ast.AST | None) -> bool:
            if item is None:
                return True
            if isinstance(item, ast.Constant):
                return True
            if isinstance(item, ast.UnaryOp) and isinstance(
                    item.op, (ast.UAdd, ast.USub, ast.Invert)):
                return literal(item.operand)
            if isinstance(item, (ast.List, ast.Tuple, ast.Set)):
                return all(literal(element) for element in item.elts)
            if isinstance(item, ast.Dict):
                return all(literal(key) and literal(value)
                           for key, value in zip(item.keys, item.values))
            if isinstance(item, ast.JoinedStr):
                return all(isinstance(value, ast.Constant) for value in item.values)
            return False

        return literal(node)

    def _mechanically_verify_review_findings(
            self, findings: list[str], current_snapshot: dict[str, str]
    ) -> tuple[list[str], list[str], str]:
        """Verify only properties Hive can prove from the locked one-line change.

        Reviewer prose is advisory.  Fresh tests, immutable regression bytes, the
        acceptance oracle, and the exact Repair boundary own behavioral completion.
        """
        state = self.objective.task_state
        selected = state.source_location
        source_file = str(selected.get("source_file", ""))
        line_number = selected.get("line")
        before = state.accepted_regression_snapshot.get(source_file)
        after = current_snapshot.get(source_file)
        if (not source_file or not isinstance(line_number, int)
                or isinstance(line_number, bool)
                or not isinstance(before, str) or not isinstance(after, str)):
            return [], list(findings), "locked Repair change boundary is unavailable"
        before_lines, after_lines = before.splitlines(), after.splitlines()
        if len(before_lines) != len(after_lines) or not 1 <= line_number <= len(after_lines):
            return [], list(findings), "Repair changed the source line structure"
        changed_lines = [
            index for index, (old, new) in enumerate(zip(before_lines, after_lines), 1)
            if old != new
        ]
        changed_paths = sorted({
            path for path in set(state.accepted_regression_snapshot) | set(current_snapshot)
            if state.accepted_regression_snapshot.get(path) != current_snapshot.get(path)
        })
        if changed_lines != [line_number] or changed_paths != [source_file]:
            return [], list(findings), (
                "final diff exceeds the controller-locked one-line Repair boundary: "
                f"paths={changed_paths}, lines={changed_lines}"
            )
        changed_line = after_lines[line_number - 1].strip()
        literal_only = self._literal_only_repair_expression(changed_line)
        verified: list[str] = []
        dismissed: list[str] = []
        for finding in findings:
            normalized = finding.lower()
            alleges_hardcode = any(term in normalized for term in (
                "hardcod", "literal-only", "literal only", "fixed constant",
                "constant value", "example-specific", "example specific",
            ))
            if alleges_hardcode and literal_only:
                verified.append(finding)
            else:
                dismissed.append(finding)
        return verified, dismissed, ""

    def _review_snapshot(self) -> str:
        current = snapshot_repository(self.root)
        result = _run_pytest(
            self.config.test_command, self.root, self.config.command_timeout_seconds)
        diff = repository_diff(self.objective.baseline_snapshot, current)
        # Reviewer scope is the final patch.  Pytest output can quote arbitrary
        # unchanged source in warnings and tracebacks, which makes that source look
        # reviewable even though it is outside the locked change boundary.  The
        # controller and apply_gate retain the complete brokered test result; the
        # read-only Reviewer needs only its fresh pass/fail status.
        return (
            f"FINAL DIFF:\n{diff[-6_000:]}\n\n"
            f"TEST EXIT CODE: {result.returncode}\n"
            f"TEST STATUS: {'PASSED' if result.returncode == 0 else 'FAILED'}"
        )

    def _worker_packet(self, task: Task) -> dict[str, Any]:
        self._refresh_evidence_lifecycle()
        context = {}
        session = WorkerSession(self.root, task.authority, self.config.command_timeout_seconds)
        context_paths = list(task.required_context)
        if task.capability.upper() == "REGRESSION_DESIGNER":
            context_paths = [path for path in context_paths
                             if Path(path).name.startswith("test_")]
        for path in context_paths:
            try: context[path] = session.execute("read_file", {"path": path})
            except Exception as exc: context[path] = f"UNAVAILABLE: {exc}"
        revised_task_ids = {task_id for revision in self.objective.graph_revisions
                            for task_id in revision.inserted_task_ids}
        objective_text = self.objective.original_request
        if task.task_id in revised_task_ids and "Initial empirical evidence:" in objective_text:
            objective_text = objective_text.split("Initial empirical evidence:", 1)[0].rstrip()
        if self.config.responsibility_call_budgets:
            objective_text = (
                "Hive owns global completion. Perform only the atomic responsibility "
                "described in this packet."
            )
        dependency_evidence = [asdict(self.evidence[eid]) for dep in task.dependencies
                               for eid in self.tasks[dep].evidence_ids
                               if self.evidence[eid].lifecycle
                               in {EvidenceLifecycle.CURRENT,
                                   EvidenceLifecycle.UNVERIFIED}]
        packet = {"original_objective": objective_text,
                  "task": {"id": task.task_id, "description": task.description,
                           "capability": task.capability, "acceptance_conditions": task.acceptance_conditions,
                           "expected_output": task.expected_output},
                  "authority": asdict(task.authority),
                  "tool_contracts": [TOOL_CONTRACTS[name] for name in task.authority.allowed_tools
                                     if name in TOOL_CONTRACTS],
                  "context": context,
                  "dependency_evidence": dependency_evidence}
        if task.capability.upper() == "REGRESSION_DESIGNER":
            oracle_counterexample = self._smallest_oracle_counterexample()
            if oracle_counterexample:
                self.objective.task_state.regression_target = oracle_counterexample
                self._persist()
                self.store.trace(
                    "regression_oracle_target_selected",
                    cycle=self.objective.task_state.atomic_cycle,
                    counterexample=oracle_counterexample,
                )
            source_signatures: dict[str, list[str]] = {}
            snapshot = snapshot_repository(self.root)
            for path in task.required_context:
                if path not in snapshot or Path(path).name.startswith("test_"):
                    continue
                try:
                    tree = ast.parse(snapshot[path])
                    source_signatures[path] = [
                        f"{type(node).__name__} {node.name}"
                        for node in tree.body
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    ]
                except (SyntaxError, ValueError):
                    source_signatures[path] = ["unparseable source"]
            validation_payloads = [
                item.payload for item in self.evidence.values()
                if item.task_id == "controller" and item.kind == EvidenceKind.TEST_RESULT
                and isinstance(item.payload, dict) and item.payload.get("output")
            ]
            dependency_ids = set(task.dependencies)
            frontier = list(task.dependencies)
            while frontier:
                dependency = self.tasks[frontier.pop()]
                for ancestor_id in dependency.dependencies:
                    if ancestor_id not in dependency_ids:
                        dependency_ids.add(ancestor_id)
                        frontier.append(ancestor_id)
            dependency_test_evidence = [
                item.payload for item in self.evidence.values()
                if item.task_id in dependency_ids and item.verified
                and item.kind == EvidenceKind.TEST_RESULT and isinstance(item.payload, dict)
            ]
            dependency_summaries = [
                self.worker_runs[dependency.assigned_worker_run_id].summary
                for dependency_id in task.dependencies
                if (dependency := self.tasks[dependency_id]).assigned_worker_run_id
                in self.worker_runs
            ]
            packet["bounded_regression_protocol"] = {
                "allowed_sequence": [
                    "read the assigned test file",
                    "edit exactly one assigned test file",
                    "run pytest once and demonstrate a nonzero red-phase exit",
                    "finish immediately",
                ],
                "residual_validation": (validation_payloads[-1]["output"][-2_000:]
                                        if validation_payloads else "unavailable"),
                "observed_failure": (
                    dependency_test_evidence[-1].get("output", "")[-2_000:]
                    if dependency_test_evidence else "unavailable"
                ),
                "investigator_conclusion": dependency_summaries[-1] if dependency_summaries else "unavailable",
                "exact_residual_requirement": (
                    self.objective.task_state.oracle_feedback[-2_000:]
                    if self.objective.task_state.oracle_feedback else "initial reported failure"
                ),
                "oracle_counterexample": oracle_counterexample or "unavailable",
                "source_signatures": source_signatures,
                "instruction": (
                    f"Append one new function named test_atomic_regression_cycle_"
                    f"{self.objective.task_state.atomic_cycle} using append_to_file, then run "
                    "pytest once. Write the test yourself from the observable evidence."
                ),
            }
            packet["dependency_evidence"] = []
        regression_dependencies = [
            self.tasks[dep] for dep in task.dependencies
            if self.tasks[dep].capability.upper() == "REGRESSION_DESIGNER"
        ]
        if task.capability.upper() in {"BUILDER", "REPAIR"} and regression_dependencies:
            red_observations = []
            for dependency in regression_dependencies:
                for evidence_id in dependency.evidence_ids:
                    evidence = self.evidence[evidence_id]
                    if (evidence.verified and isinstance(evidence.payload, dict)
                            and evidence.payload.get("tool") in {
                                "replace_in_file", "append_to_file", "run_command"}):
                        red_observations.append(evidence.payload)
            ancestor_ids = {dependency.task_id for dependency in regression_dependencies}
            frontier = list(ancestor_ids)
            while frontier:
                ancestor = self.tasks[frontier.pop()]
                for dependency_id in ancestor.dependencies:
                    if dependency_id not in ancestor_ids:
                        ancestor_ids.add(dependency_id)
                        frontier.append(dependency_id)
            root_cause_summaries = [
                run.summary for run in self.worker_runs.values()
                if run.task_id in ancestor_ids
                and run.capability.upper() == "INVESTIGATOR" and run.summary
            ]
            packet["repair_handoff"] = {
                "current_diff": repository_diff(
                    self.objective.baseline_snapshot, snapshot_repository(self.root)),
                "red_phase_observations": red_observations,
                "target_source_files": list(task.authority.write_scopes),
                "focused_regression_nodes": list(self.objective.task_state.regression_nodes),
                "root_cause": (root_cause_summaries[-1]
                               if root_cause_summaries else "unavailable"),
                "instruction": (
                    "Repair only the source defect exposed by the red test. Do not edit tests. "
                    "Run pytest once after the source edit, then finish."
                ),
            }
            packet["dependency_evidence"] = []
        if task.capability.upper() == "REVIEWER":
            packet["independent_review"] = {
                "baseline_revision": self.objective.baseline_revision,
                "current_revision": revision_id(snapshot_repository(self.root)),
                "current_diff": repository_diff(
                    self.objective.baseline_snapshot, snapshot_repository(self.root)),
                "dependency_runs": [
                    asdict(run) for dependency in task.dependencies
                    for run in self.worker_runs.values() if run.task_id == dependency
                ],
                "instruction": (
                    "Look for unmet acceptance conditions and unsupported claims. "
                    "Do not trust the Builder summary; inspect the exact diff and run tests."
                ),
            }
        encoded = json.dumps(packet, default=str)
        if len(encoded) > self.config.max_context_chars:
            raise RuntimeError("compiled worker context exceeds configured budget")
        return packet

    @staticmethod
    def _test_trees(snapshot: dict[str, str]) -> dict[str, ast.Module]:
        trees: dict[str, ast.Module] = {}
        for path, source in snapshot.items():
            if Path(path).suffix != ".py" or not Path(path).name.startswith("test_"):
                continue
            try:
                trees[path] = ast.parse(source)
            except SyntaxError as exc:
                raise ValueError(f"test module is not parseable: {path}: {exc}") from exc
        return trees

    @staticmethod
    def _oracle_value_leaves(value: Any) -> list[Any]:
        if isinstance(value, dict):
            return [leaf for item in value.values()
                    for leaf in HiveExecutive._oracle_value_leaves(item)]
        if isinstance(value, list):
            return [leaf for item in value
                    for leaf in HiveExecutive._oracle_value_leaves(item)]
        return [value]

    @classmethod
    def _differing_expected_leaves(cls, expected: Any, actual: Any) -> list[Any]:
        if isinstance(expected, dict) and isinstance(actual, dict):
            leaves: list[Any] = []
            for key, expected_value in expected.items():
                if key not in actual:
                    leaves.extend(cls._oracle_value_leaves(expected_value))
                else:
                    leaves.extend(cls._differing_expected_leaves(
                        expected_value, actual[key]))
            return leaves
        if isinstance(expected, list) and isinstance(actual, list):
            leaves = []
            for index, expected_value in enumerate(expected):
                if index >= len(actual):
                    leaves.extend(cls._oracle_value_leaves(expected_value))
                else:
                    leaves.extend(cls._differing_expected_leaves(
                        expected_value, actual[index]))
            return leaves
        return [] if expected == actual else cls._oracle_value_leaves(expected)

    @staticmethod
    def _literal_present(constants: list[Any], required: Any) -> bool:
        return (any(type(item) is type(required) and item == required for item in constants)
                or any(isinstance(item, str) and str(required) in item
                       for item in constants))

    def _existing_test_targets_oracle(
            self, node: str, snapshot: dict[str, str], target: dict[str, Any]) -> bool:
        """Require an adoptable red node to encode the oracle's public example."""
        path, _, function_name = node.partition("::")
        try:
            tree = self._test_trees(snapshot)[path]
        except (KeyError, ValueError):
            return False
        function = next((item for item in tree.body
                         if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and item.name == function_name), None)
        if function is None:
            return False
        operation = str(target.get("operation", ""))
        operation_call = operation.rsplit(".", 1)[-1]
        called = {
            (call.func.id if isinstance(call.func, ast.Name) else call.func.attr)
            for call in ast.walk(function) if isinstance(call, ast.Call)
            and isinstance(call.func, (ast.Name, ast.Attribute))
        }
        constants = [item.value for item in ast.walk(function)
                     if isinstance(item, ast.Constant)]
        required_inputs = list(target.get("input_values", []))
        if target.get("payload") is not None:
            required_inputs.append(target["payload"])
        differing_expected = self._differing_expected_leaves(
            target.get("expected"), target.get("actual"))
        return bool(
            operation and operation_call in called
            and all(self._literal_present(constants, item) for item in required_inputs)
            and differing_expected
            and any(self._literal_present(constants, item)
                    for item in differing_expected)
        )

    def _gate_failure(self, gate: str, feedback: str) -> None:
        state = self.objective.task_state
        state.last_failed_gate = gate
        state.last_gate_feedback = feedback
        state.gate_failures[gate] = state.gate_failures.get(gate, 0) + 1
        if gate in {"regression_created", "regression_fails_on_broken_revision"}:
            for path, source in state.regression_baseline_snapshot.items():
                if Path(path).name.startswith("test_"):
                    target = (self.root / path).resolve()
                    if os.path.commonpath([str(self.root), str(target)]) == str(self.root):
                        target.write_text(source, encoding="utf-8")
        if gate in {"source_repaired", "regression_passes_after_repair", "original_tests_pass",
                    "acceptance_oracle_pass"}:
            for path, source in state.accepted_regression_snapshot.items():
                target = (self.root / path).resolve()
                if os.path.commonpath([str(self.root), str(target)]) == str(self.root):
                    target.write_text(source, encoding="utf-8")
        raise ValueError(f"ATOMIC GATE {gate} FAILED: {feedback}")

    def _adopt_existing_failing_regression(
            self, reproducer_task: Task, observations: list[dict[str, Any]],
            current_snapshot: dict[str, str]) -> bool:
        """Lock one existing assertion failure and bypass unnecessary test creation."""
        allowed_tests = {
            path.replace("\\", "/") for path in reproducer_task.authority.read_scopes
            if Path(path).name.startswith("test_") and path in current_snapshot
        }
        candidates: set[str] = set()
        patterns = (
            re.compile(r"(?m)^FAILED\s+(\S+\.py(?:::\S+)+)(?:\s+-.*)?$"),
            re.compile(r"(?m)^(\S+\.py(?:::\S+)+)\s+FAILED(?:\s|$)"),
        )
        for observation in observations:
            if observation.get("tool") != "run_command":
                continue
            output = str(observation.get("output", ""))
            for pattern in patterns:
                for match in pattern.finditer(output):
                    raw_node = match.group(1).replace("\\", "/")
                    raw_file, separator, suffix = raw_node.partition("::")
                    if not separator:
                        continue
                    if not re.fullmatch(
                            r"[^\s:]+\.py::[A-Za-z_][A-Za-z0-9_]*", raw_node):
                        continue
                    matched_file = next(
                        (path for path in allowed_tests
                         if raw_file == path or raw_file.endswith("/" + path)),
                        "",
                    )
                    if matched_file:
                        candidates.add(f"{matched_file}::{suffix}")
        state = self.objective.task_state
        state.reproduced_failure_nodes = sorted(candidates)
        if len(candidates) != 1:
            return False
        node = next(iter(candidates))
        target = self._smallest_oracle_counterexample()
        if target:
            if not self._existing_test_targets_oracle(node, current_snapshot, target):
                self.store.trace(
                    "existing_regression_rejected_as_oracle_unrelated",
                    reproducer_task_id=reproducer_task.task_id,
                    regression_node=node,
                    oracle_counterexample=target,
                )
                return False
            self.objective.task_state.regression_target = dict(target)
        try:
            focused = _run_pytest_nodes(
                [node], self.root, self.config.command_timeout_seconds)
        except ValueError:
            return False
        focused_output = f"{focused.stdout}\n{focused.stderr}".lower()
        if focused.returncode != 1 or "1 failed" not in focused_output:
            return False

        callable_locators = [candidate for candidate in self.tasks.values()
                             if reproducer_task.task_id in candidate.dependencies
                             and candidate.capability.upper() == "CALLABLE_LOCATOR"]
        if len(callable_locators) != 1:
            return False
        callable_locator = callable_locators[0]
        locators = [candidate for candidate in self.tasks.values()
                    if callable_locator.task_id in candidate.dependencies
                    and candidate.capability.upper() == "SOURCE_LOCATOR"]
        if len(locators) != 1:
            return False
        locator = locators[0]
        cause_locators = [candidate for candidate in self.tasks.values()
                          if locator.task_id in candidate.dependencies
                          and candidate.capability.upper() == "CAUSE_LOCATOR"]
        if len(cause_locators) != 1:
            return False
        cause_locator = cause_locators[0]
        investigators = [candidate for candidate in self.tasks.values()
                         if cause_locator.task_id in candidate.dependencies
                         and candidate.capability.upper() == "INVESTIGATOR"]
        if len(investigators) != 1:
            return False
        investigator = investigators[0]
        regressions = [candidate for candidate in self.tasks.values()
                       if investigator.task_id in candidate.dependencies
                       and candidate.capability.upper() == "REGRESSION_DESIGNER"]
        if len(regressions) != 1:
            return False
        regression = regressions[0]
        repairs = [candidate for candidate in self.tasks.values()
                   if regression.task_id in candidate.dependencies
                   and candidate.capability.upper() == "REPAIR"]
        if len(repairs) != 1:
            return False
        repair = repairs[0]

        state.regression_established = True
        state.regression_created = False
        state.regression_fails_on_broken_revision = True
        state.regression_nodes = [node]
        state.regression_origin = "existing"
        state.regression_baseline_snapshot = dict(current_snapshot)
        state.accepted_regression_snapshot = dict(current_snapshot)
        regression.status = TaskStatus.CANCELLED
        regression.failure_reason = (
            f"SKIPPED: existing focused failing test adopted as regression: {node}")
        regression.updated_at = utc_now()
        repair.dependencies = list(dict.fromkeys(
            investigator.task_id if dependency == regression.task_id else dependency
            for dependency in repair.dependencies
        ))
        repair.updated_at = utc_now()
        self.validate_graph()
        self.store.trace(
            "existing_regression_adopted",
            reproducer_task_id=reproducer_task.task_id,
            callable_locator_task_id=callable_locator.task_id,
            source_locator_task_id=locator.task_id,
            investigator_task_id=investigator.task_id,
            cause_locator_task_id=cause_locator.task_id,
            skipped_regression_task_id=regression.task_id,
            repair_task_id=repair.task_id,
            regression_node=node,
        )
        return True

    def _verify_new_regression(self, current_snapshot: dict[str, str]) -> list[str]:
        """Prove a new, non-weakening test fails on the still-broken source revision."""
        state = self.objective.task_state
        baseline = state.regression_baseline_snapshot
        if not baseline:
            self._gate_failure("regression_created", "controller lacks the pre-regression snapshot")
        changed = sorted(
            path for path in set(baseline) | set(current_snapshot)
            if baseline.get(path) != current_snapshot.get(path)
        )
        non_tests = [path for path in changed if not Path(path).name.startswith("test_")]
        if non_tests:
            self._gate_failure(
                "regression_created",
                f"regression responsibility changed non-test files: {', '.join(non_tests)}",
            )
        baseline_trees = self._test_trees(baseline)
        current_trees = self._test_trees(current_snapshot)
        if set(baseline_trees) != set(current_trees):
            self._gate_failure("regression_created", "test modules were added or removed")
        nodes: list[str] = []
        new_function_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        for path, baseline_tree in baseline_trees.items():
            current_tree = current_trees[path]
            old_names = {
                node.name for node in baseline_tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            new_functions = [
                node for node in current_tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test_") and node.name not in old_names
            ]
            new_names = {node.name for node in new_functions}
            current_without_new = ast.Module(
                body=[node for node in current_tree.body
                      if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                              and node.name in new_names)],
                type_ignores=current_tree.type_ignores,
            )
            if ast.dump(baseline_tree, include_attributes=False) != ast.dump(
                    current_without_new, include_attributes=False):
                self._gate_failure(
                    "regression_created",
                    f"existing test behavior was modified in {path}; add a new test only",
                )
            nodes.extend(f"{path}::{node.name}" for node in new_functions)
            new_function_nodes.extend(new_functions)
        if not nodes:
            self._gate_failure(
                "regression_created",
                "no newly added top-level test function was found",
            )
        target = state.regression_target
        if target:
            if len(new_function_nodes) != 1:
                self._gate_failure(
                    "regression_created",
                    "oracle-targeted regression must add exactly one new test function",
                )
            function = new_function_nodes[0]
            operation = str(target.get("operation", ""))
            operation_call = operation.rsplit(".", 1)[-1]
            called = {
                (call.func.id if isinstance(call.func, ast.Name) else call.func.attr)
                for call in ast.walk(function) if isinstance(call, ast.Call)
                and isinstance(call.func, (ast.Name, ast.Attribute))
            }
            constants = [node.value for node in ast.walk(function)
                         if isinstance(node, ast.Constant)]

            def expected_leaves(value: Any) -> list[Any]:
                if isinstance(value, dict):
                    return [leaf for item in value.values() for leaf in expected_leaves(item)]
                if isinstance(value, list):
                    return [leaf for item in value for leaf in expected_leaves(item)]
                return [value]

            required_literals = [*target.get("input_values", []),
                                 *expected_leaves(target.get("expected"))]
            if target.get("payload") is not None:
                required_literals.append(target["payload"])

            def literal_present(required: Any) -> bool:
                return (required in constants
                        or any(isinstance(item, str) and str(required) in item
                               for item in constants))

            missing_literals = [item for item in required_literals
                                if not literal_present(item)]
            if not operation or operation_call not in called or missing_literals:
                self._gate_failure(
                    "regression_created",
                    "new test must directly encode the selected oracle counterexample: "
                    f"operation={operation}, input_values={target.get('input_values')}, "
                    f"expected={target.get('expected')}; missing_literals={missing_literals}",
                )
        for node in nodes:
            result = _run_pytest_nodes([node], self.root, self.config.command_timeout_seconds)
            output = f"{result.stdout}\n{result.stderr}".lower()
            if result.returncode != 1 or "1 failed" not in output:
                self._gate_failure(
                    "regression_fails_on_broken_revision",
                    f"new regression {node} did not produce one attributed assertion failure "
                    f"on the broken revision (exit={result.returncode})",
                )
        return nodes

    def _verify_repair(self, current_snapshot: dict[str, str], run: WorkerRun,
                       require_source_edit: bool = True) -> tuple[bool, str]:
        state = self.objective.task_state
        if not state.regression_nodes or not state.accepted_regression_snapshot:
            self._gate_failure("source_repaired", "no mechanically accepted red regression exists")
        accepted_tests = {
            path: source for path, source in state.accepted_regression_snapshot.items()
            if Path(path).name.startswith("test_")
        }
        current_tests = {
            path: source for path, source in current_snapshot.items()
            if Path(path).name.startswith("test_")
        }
        if accepted_tests != current_tests:
            self._gate_failure("source_repaired", "the accepted regression changed during repair")
        edited_source = [path for path in run.edited_files
                         if not Path(path).name.startswith("test_")]
        if require_source_edit and not edited_source:
            self._gate_failure("source_repaired", "repair responsibility made no source edit")
        focused = _run_pytest_nodes(
            state.regression_nodes, self.root, self.config.command_timeout_seconds)
        if focused.returncode != 0:
            focused_output = (
                f"EXIT CODE: {focused.returncode}\nSTDOUT:\n{focused.stdout}\n"
                f"STDERR:\n{focused.stderr}"
            )
            self._gate_failure(
                "regression_passes_after_repair",
                "accepted regression still fails after repair:\n"
                + focused_output[-3_000:],
            )
        suite = _run_pytest(self.config.test_command, self.root,
                            self.config.command_timeout_seconds)
        output = f"EXIT CODE: {suite.returncode}\nSTDOUT:\n{suite.stdout}\nSTDERR:\n{suite.stderr}"
        return suite.returncode == 0, output

    def _extend_atomic_residual_after_repair(self, repair_task: Task, feedback: str) -> None:
        """Freeze a focused green repair and turn a distinct suite residual into a new cycle."""
        state = self.objective.task_state
        downstream = next(
            (candidate for candidate in self.tasks.values()
             if repair_task.task_id in candidate.dependencies
             and candidate.capability.upper() == "REVIEWER"
             and candidate.status in {TaskStatus.PENDING, TaskStatus.WAITING}),
            None,
        )
        if downstream is None or len(self.tasks) + 8 > self.config.max_queued_workers:
            self._gate_failure("original_tests_pass", feedback)
        snapshot = snapshot_repository(self.root)
        source_files = sorted(
            path for path in snapshot
            if Path(path).suffix == ".py" and not Path(path).name.startswith("test_")
        )
        test_files = sorted(
            path for path in snapshot
            if Path(path).suffix == ".py" and Path(path).name.startswith("test_")
        )
        state.reset_for_residual(feedback)
        state.atomic_source_files = list(source_files)
        state.atomic_test_files = list(test_files)
        downstream.status = TaskStatus.CANCELLED
        downstream.failure_reason = "superseded by the next concrete atomic-agent cycle"
        reproducer = self.atomic_agents["REPRODUCER"].create_task(
            self, source_files, test_files, repair_task)
        reproducer.description = "Reproduce only the exact residual left after the accepted focused repair."
        reproducer.expected_output = feedback
        callable_locator = self.atomic_agents["CALLABLE_LOCATOR"].create_task(
            self, source_files, test_files, reproducer)
        locator = self.atomic_agents["SOURCE_LOCATOR"].create_task(
            self, source_files, test_files, callable_locator)
        cause_locator = self.atomic_agents["CAUSE_LOCATOR"].create_task(
            self, source_files, test_files, locator)
        investigator = self.atomic_agents["INVESTIGATOR"].create_task(
            self, source_files, test_files, cause_locator)
        regression = self.atomic_agents["REGRESSION_DESIGNER"].create_task(
            self, source_files, test_files, investigator)
        repair = self.atomic_agents["REPAIR"].create_task(
            self, source_files, test_files, regression)
        self.atomic_agents["REVIEWER"].create_task(
            self, source_files, test_files, repair)
        self.store.trace(
            "atomic_suite_residual_scheduled", cycle=state.atomic_cycle,
            prior_repair_task_id=repair_task.task_id, feedback=feedback[-4_000:],
        )

    @staticmethod
    def _callable_node_at_definition(
            source: str, definition_line: Any
    ) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        """Resolve one callable by a controller-observed definition line."""
        if (not isinstance(definition_line, int)
                or isinstance(definition_line, bool)):
            return None
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            return None
        matches = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.lineno == definition_line
        ]
        return matches[0] if len(matches) == 1 else None

    @classmethod
    def _eligible_callable_lines(cls, source: str,
                                 locked: dict[str, Any]) -> list[int]:
        """Return lines owned by the locked callable, excluding nested definitions."""
        selected = cls._callable_node_at_definition(
            source, locked.get("definition_line"))
        if selected is None or selected.name != locked.get("symbol"):
            return []
        end_line = selected.end_lineno or selected.lineno
        eligible = set(range(selected.lineno, end_line + 1))
        # The callable header establishes a scope; it does not compute a runtime
        # value and cannot be changed by the one-line Repair responsibility.
        if not any(getattr(statement, "lineno", 0) == selected.lineno
                   for statement in selected.body):
            eligible.discard(selected.lineno)
        for nested in ast.walk(selected):
            if nested is selected:
                continue
            if isinstance(nested, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nested_first = min(
                    [nested.lineno]
                    + [decorator.lineno for decorator in getattr(nested, "decorator_list", [])]
                )
                nested_last = nested.end_lineno or nested.lineno
                eligible.difference_update(range(nested_first, nested_last + 1))
        return sorted(eligible)

    @staticmethod
    def _ast_value_key(node: ast.AST) -> str:
        """Return a stable local data-flow key for a name, attribute, or subscript."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = HiveExecutive._ast_value_key(node.value)
            return f"{prefix}.{node.attr}" if prefix else node.attr
        if isinstance(node, ast.Subscript):
            prefix = HiveExecutive._ast_value_key(node.value)
            try:
                suffix = ast.unparse(node.slice)
            except (AttributeError, ValueError):
                suffix = "?"
            return f"{prefix}[{suffix}]" if prefix else ""
        return ""

    @classmethod
    def _source_expression_frame(cls, source_line: str) -> dict[str, Any]:
        """Lock the unchanged statement bytes surrounding one editable expression."""
        stripped = str(source_line).strip()
        try:
            tree = ast.parse(stripped)
        except SyntaxError:
            tree = None
        if tree is None or len(tree.body) != 1:
            return {"mode": "statement", "template": "<MODEL_STATEMENT>"}
        statement = tree.body[0]
        value: ast.AST | None = None
        kind = type(statement).__name__
        targets: list[str] = []
        if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            value = statement.value
            targets = sorted(cls._statement_store_keys(statement))
            kind = "assignment"
        elif isinstance(statement, ast.Return):
            value = statement.value
            kind = "return"
        elif isinstance(statement, ast.Expr):
            value = statement.value
            kind = "expression_statement"
        elif isinstance(statement, ast.Assert):
            value = statement.test
            kind = "assert"
        elif isinstance(statement, ast.Raise):
            value = statement.exc
            kind = "raise"
        if (value is None or not isinstance(getattr(value, "col_offset", None), int)
                or not isinstance(getattr(value, "end_col_offset", None), int)):
            return {"mode": "statement", "template": "<MODEL_STATEMENT>"}
        first = int(value.col_offset)
        last = int(value.end_col_offset)
        prefix, suffix = stripped[:first], stripped[last:]
        return {
            "mode": "expression",
            "statement_kind": kind,
            "assigned_targets": targets,
            "prefix": prefix,
            "suffix": suffix,
            "template": prefix + "<MODEL_EXPRESSION>" + suffix,
            "old_expression": stripped[first:last],
        }

    @staticmethod
    def _runtime_value_category(value: Any) -> str:
        """Return a coarse runtime type used only to rule out implausible leaf swaps."""
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, str):
            return "string"
        if value is None:
            return "none"
        if isinstance(value, list):
            return "sequence"
        if isinstance(value, dict) and "type" not in value:
            return "mapping"
        return ""

    @classmethod
    def _resolve_runtime_reference(
            cls, node: ast.AST, frame: dict[str, Any]) -> tuple[bool, Any]:
        """Resolve a call-free Name/Attribute/Subscript from serialized trace locals."""
        if isinstance(node, ast.Name):
            return ((True, frame[node.id]) if node.id in frame else (False, None))
        if isinstance(node, ast.Attribute):
            available, base = cls._resolve_runtime_reference(node.value, frame)
            if not available or not isinstance(base, dict):
                return False, None
            attributes = base.get("attributes")
            if isinstance(attributes, dict) and node.attr in attributes:
                return True, attributes[node.attr]
            if node.attr in base:
                return True, base[node.attr]
            return False, None
        if isinstance(node, ast.Subscript):
            available, base = cls._resolve_runtime_reference(node.value, frame)
            if not available:
                return False, None
            slice_node = node.slice
            if not isinstance(slice_node, ast.Constant):
                return False, None
            key = slice_node.value
            if isinstance(base, dict) and key in base:
                return True, base[key]
            if isinstance(base, list) and isinstance(key, int) and not isinstance(key, bool):
                if -len(base) <= key < len(base):
                    return True, base[key]
            return False, None
        return False, None

    @staticmethod
    def _maximal_expression_references(expression: str) -> list[dict[str, Any]]:
        """Return non-overlapping, call-free load references in one expression.

        AST columns are UTF-8 byte offsets.  Keeping byte spans lets the controller
        substitute exactly one reference while preserving every other expression byte.
        """
        try:
            root = ast.parse(expression, mode="eval")
        except SyntaxError:
            return []
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(root):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        candidates: list[dict[str, Any]] = []
        encoded = expression.encode("utf-8")
        for node in ast.walk(root):
            if (not isinstance(node, (ast.Name, ast.Attribute, ast.Subscript))
                    or not isinstance(getattr(node, "ctx", None), ast.Load)):
                continue
            ancestor = parents.get(node)
            wrapped = False
            while ancestor is not None:
                if (isinstance(ancestor, (ast.Attribute, ast.Subscript))
                        and isinstance(getattr(ancestor, "ctx", None), ast.Load)):
                    wrapped = True
                    break
                ancestor = parents.get(ancestor)
            if wrapped:
                continue
            parent = parents.get(node)
            if isinstance(parent, ast.Call) and parent.func is node:
                continue
            first = getattr(node, "col_offset", None)
            last = getattr(node, "end_col_offset", None)
            if (not isinstance(first, int) or not isinstance(last, int)
                    or first < 0 or last <= first or last > len(encoded)):
                continue
            try:
                source = encoded[first:last].decode("utf-8")
            except UnicodeDecodeError:
                continue
            if not source.strip():
                continue
            candidates.append({
                "node": node,
                "first_byte": first,
                "last_byte": last,
                "source": source,
            })
        return sorted(candidates, key=lambda item: (
            int(item["first_byte"]), int(item["last_byte"]), str(item["source"])))

    @classmethod
    def _branch_control_parameters(
            cls, selected_callable: ast.FunctionDef | ast.AsyncFunctionDef,
            selected_line: int, parameter_names: set[str]) -> list[str]:
        """Identify current-call parameters used only to reach the selected statement."""
        controls: set[str] = set()

        def owns_line(statements: list[ast.stmt]) -> bool:
            return any(
                statement.lineno <= selected_line
                <= (statement.end_lineno or statement.lineno)
                for statement in statements
            )

        for node in ast.walk(selected_callable):
            expression: ast.AST | None = None
            controlled: list[ast.stmt] = []
            if isinstance(node, (ast.If, ast.While)):
                expression = node.test
                controlled = [*node.body, *node.orelse]
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                expression = node.iter
                controlled = [*node.body, *node.orelse]
            elif isinstance(node, ast.Match):
                expression = node.subject
                controlled = [statement for case in node.cases for statement in case.body]
            if expression is None or not owns_line(controlled):
                continue
            controls.update(
                child.id for child in ast.walk(expression)
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
                and child.id in parameter_names
            )
        return sorted(controls)

    @classmethod
    def _leaf_replacement_choices(
            cls, location: dict[str, Any], runtime_evidence: dict[str, Any],
            rejected_expressions: Iterable[str]) -> list[dict[str, str]]:
        """Generate bounded edits that replace one RHS reference and preserve its AST tree."""
        frame = location.get("expression_frame", {})
        if (not isinstance(frame, dict) or frame.get("mode") != "expression"
                or runtime_evidence.get("location_id") != location.get("location_id")
                or not runtime_evidence.get("captured")):
            return []
        old_expression = str(frame.get("old_expression", ""))
        references = cls._maximal_expression_references(old_expression)
        frames = [item for item in runtime_evidence.get("frames_before_line", [])
                  if isinstance(item, dict)]
        parameter_names = runtime_evidence.get(
            "omitted_data_parameters",
            runtime_evidence.get("current_call_parameters_not_loaded", []),
        )
        parameters = sorted({
            str(name) for name in parameter_names
            if isinstance(name, str)
            and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
        })
        if not old_expression or not references or not frames or not parameters:
            return []
        rejected = {str(item).strip() for item in rejected_expressions if str(item).strip()}
        encoded = old_expression.encode("utf-8")
        choices: list[dict[str, str]] = []
        seen_results: set[str] = set()
        for reference in references:
            reference_values: list[Any] = []
            resolvable = True
            for runtime_frame in frames:
                available, value = cls._resolve_runtime_reference(
                    reference["node"], runtime_frame)
                if not available or not cls._runtime_value_category(value):
                    resolvable = False
                    break
                reference_values.append(value)
            if not resolvable:
                continue
            for parameter in parameters:
                if any(parameter not in runtime_frame for runtime_frame in frames):
                    continue
                parameter_values = [runtime_frame[parameter] for runtime_frame in frames]
                if any(
                    cls._runtime_value_category(reference_value)
                    != cls._runtime_value_category(parameter_value)
                    for reference_value, parameter_value
                    in zip(reference_values, parameter_values)
                ):
                    continue
                replacement_bytes = parameter.encode("utf-8")
                result = (
                    encoded[:int(reference["first_byte"])] + replacement_bytes
                    + encoded[int(reference["last_byte"]):]
                ).decode("utf-8")
                try:
                    ast.parse(result, mode="eval")
                except SyntaxError:
                    continue
                if result == old_expression or result.strip() in rejected or result in seen_results:
                    continue
                seen_results.add(result)
                replace_reference = str(reference["source"])
                choice_id = _leaf_choice_fingerprint(
                    str(location.get("location_id", "")), old_expression,
                    replace_reference, parameter, result,
                )
                choices.append({
                    "choice_id": choice_id,
                    "replace_reference": replace_reference,
                    "with_in_scope_value": parameter,
                    "resulting_expression": result,
                })
        return choices[:12]

    @classmethod
    def _bounded_callable_window(
            cls, source: str | None, locked: dict[str, Any],
            selected_line: int | None) -> dict[str, str]:
        """Return a microscopic source window around one controller-locked line."""
        if not isinstance(source, str) or not isinstance(selected_line, int):
            return {"callable_signature": "unavailable", "selected_source_window": "unavailable"}
        lines = source.splitlines()
        selected_callable = cls._callable_node_at_definition(
            source, locked.get("definition_line"))
        if (selected_callable is None or not 1 <= selected_line <= len(lines)):
            return {"callable_signature": "unavailable", "selected_source_window": "unavailable"}
        first = max(selected_callable.lineno, selected_line - 1)
        last = min(selected_callable.end_lineno or selected_callable.lineno,
                   selected_line + 3)
        return {
            "callable_signature": (
                f"{selected_callable.lineno} | {lines[selected_callable.lineno - 1]}"),
            "selected_source_window": "\n".join(
                f"{number} | {lines[number - 1]}"
                for number in range(first, last + 1)
            ),
        }

    def _capture_runtime_at_source_location(
            self, location: dict[str, Any]) -> dict[str, Any]:
        """Capture bounded locals before the locked line during the red regression.

        The trace is controller-owned evidence.  It runs the already accepted focused
        regression without editing repository bytes and serializes only function arguments,
        nearby loaded locals, and nearby object attributes.
        """
        source_file = str(location.get("source_file", ""))
        line_number = location.get("line")
        location_id = str(location.get("location_id", ""))
        trace_nodes = (
            list(self.objective.task_state.regression_nodes)
            or list(self.objective.task_state.reproduced_failure_nodes)
        )
        if (not source_file or not isinstance(line_number, int)
                or isinstance(line_number, bool) or not location_id
                or not trace_nodes):
            return {"captured": False, "reason": "locked location or regression unavailable"}
        source = snapshot_repository(self.root).get(source_file)
        if not isinstance(source, str):
            return {"captured": False, "reason": "locked source unavailable"}
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if digest != str(location.get("source_sha256", digest)):
            return {"captured": False, "reason": "locked source is stale"}
        callable_location = self.objective.task_state.callable_location
        selected_callable = self._callable_node_at_definition(
            source, callable_location.get("definition_line"))
        if selected_callable is None:
            return {"captured": False, "reason": "locked callable unavailable"}
        arguments = [
            argument.arg
            for argument in [
                *selected_callable.args.posonlyargs,
                *selected_callable.args.args,
                *selected_callable.args.kwonlyargs,
            ]
        ]
        if selected_callable.args.vararg is not None:
            arguments.append(selected_callable.args.vararg.arg)
        if selected_callable.args.kwarg is not None:
            arguments.append(selected_callable.args.kwarg.arg)
        candidate_line = self.objective.task_state.candidate_source_location.get(
            "line", line_number)
        relevant_first = min(
            line_number,
            candidate_line if isinstance(candidate_line, int) else line_number,
        ) - 1
        relevant_last = max(
            line_number,
            candidate_line if isinstance(candidate_line, int) else line_number,
        ) + 2
        local_names = set(arguments)
        attribute_names: set[str] = set()
        selected_statement = self._candidate_statement(
            source, callable_location, line_number)
        selected_loads = (
            sorted(self._statement_load_keys(selected_statement))
            if selected_statement is not None else [])
        selected_stores = (
            sorted(self._statement_store_keys(selected_statement))
            if selected_statement is not None else [])
        for key in [*selected_loads, *selected_stores]:
            root = re.split(r"[.\[]", key, maxsplit=1)[0]
            if root:
                local_names.add(root)
        for node in ast.walk(selected_callable):
            node_line = getattr(node, "lineno", 0)
            if not relevant_first <= node_line <= relevant_last:
                continue
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                local_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                attribute_names.add(node.attr)
        target_path = (self.root / source_file).resolve()
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            result = subprocess.run(
                [
                    sys.executable, "-c", _RUNTIME_CAPTURE_SCRIPT,
                    str(target_path), str(line_number),
                    json.dumps(trace_nodes),
                    json.dumps(sorted(local_names)),
                    json.dumps(sorted(attribute_names)),
                ],
                cwd=self.root, capture_output=True, text=True,
                timeout=self.config.command_timeout_seconds, env=environment,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"captured": False, "reason": f"{type(exc).__name__}: {exc}"}
        marker = "HIVE_RUNTIME_CAPTURE="
        if marker not in result.stdout:
            return {
                "captured": False,
                "reason": "focused runtime trace produced no structured capture",
            }
        try:
            payload = json.loads(result.stdout.rsplit(marker, 1)[1].strip().splitlines()[0])
        except (json.JSONDecodeError, IndexError, AttributeError):
            return {"captured": False, "reason": "focused runtime trace was malformed"}
        frames_before = payload.get("frames_before", []) if isinstance(payload, dict) else []
        frames_after = payload.get("frames_after", []) if isinstance(payload, dict) else []
        loaded_roots = {
            re.split(r"[.\[]", key, maxsplit=1)[0]
            for key in selected_loads
        }
        omitted_parameters = [
            name for name in arguments
            if name != "self" and name not in loaded_roots
        ]
        branch_control_parameters = self._branch_control_parameters(
            selected_callable, line_number, set(arguments) - {"self"})
        omitted_data_parameters = [
            name for name in omitted_parameters
            if name not in branch_control_parameters
        ]
        evidence = {
            "captured": bool(frames_before),
            "location_id": location_id,
            "source_file": source_file,
            "line": line_number,
            "test_nodes": trace_nodes,
            "pytest_exit": payload.get("pytest_exit") if isinstance(payload, dict) else None,
            "selected_expression": self._source_expression_frame(
                str(location.get("source_line", ""))).get("old_expression", ""),
            "selected_loads": selected_loads,
            "assigned_targets": selected_stores,
            "current_call_parameters_not_loaded": omitted_parameters,
            "branch_control_parameters": branch_control_parameters,
            "omitted_data_parameters": omitted_data_parameters,
            "frames_before_line": (
                frames_before[:3] if isinstance(frames_before, list) else []),
            "frames_after_line": (
                frames_after[:3] if isinstance(frames_after, list) else []),
        }
        evidence["runtime_evidence_id"] = _fingerprint(evidence)
        return evidence

    @classmethod
    def _normalize_model_expression(
            cls, model_text: str, frame: dict[str, Any]) -> str:
        """Accept an expression, or unwrap a redundant matching statement wrapper."""
        proposed = str(model_text).strip()
        try:
            ast.parse(proposed, mode="eval")
            return proposed
        except SyntaxError:
            pass
        try:
            tree = ast.parse(proposed)
        except SyntaxError as exc:
            raise ValueError("new must be one valid Python expression") from exc
        if len(tree.body) != 1:
            raise ValueError("new must contain exactly one Python expression")
        statement = tree.body[0]
        kind = str(frame.get("statement_kind", ""))
        value: ast.AST | None = None
        if kind == "assignment" and isinstance(
                statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = sorted(cls._statement_store_keys(statement))
            if targets != sorted(str(item) for item in frame.get("assigned_targets", [])):
                raise ValueError(
                    "redundant assignment wrapper must preserve the controller-locked target")
            value = statement.value
        elif kind == "return" and isinstance(statement, ast.Return):
            value = statement.value
        elif kind == "expression_statement" and isinstance(statement, ast.Expr):
            value = statement.value
        elif kind == "assert" and isinstance(statement, ast.Assert):
            value = statement.test
        elif kind == "raise" and isinstance(statement, ast.Raise):
            value = statement.exc
        if value is None:
            raise ValueError(
                "new included a statement wrapper that does not match the locked syntax frame")
        segment = ast.get_source_segment(proposed, value)
        if not segment or not segment.strip():
            raise ValueError("could not isolate one model-authored expression")
        ast.parse(segment.strip(), mode="eval")
        return segment.strip()

    @classmethod
    def _statement_load_keys(cls, statement: ast.stmt) -> set[str]:
        """Collect values consumed by one statement without treating its body as input."""
        nodes: list[ast.AST] = []
        if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            value = getattr(statement, "value", None)
            if value is not None:
                nodes.append(value)
        elif isinstance(statement, ast.AugAssign):
            nodes.extend([statement.target, statement.value])
        elif isinstance(statement, (ast.If, ast.While, ast.Assert)):
            nodes.append(statement.test)
            if isinstance(statement, ast.Assert) and statement.msg is not None:
                nodes.append(statement.msg)
        elif isinstance(statement, (ast.For, ast.AsyncFor)):
            nodes.append(statement.iter)
        elif isinstance(statement, (ast.Return, ast.Expr, ast.Raise)):
            value = getattr(statement, "value", None)
            if value is None:
                value = getattr(statement, "exc", None)
            if value is not None:
                nodes.append(value)
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            nodes.extend(item.context_expr for item in statement.items)
        else:
            nodes.append(statement)
        keys: set[str] = set()
        for root in nodes:
            for node in ast.walk(root):
                if isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)):
                    context = getattr(node, "ctx", ast.Load())
                    if isinstance(context, ast.Load):
                        key = cls._ast_value_key(node)
                        if key:
                            keys.add(key)
        return keys

    @classmethod
    def _statement_store_keys(cls, statement: ast.stmt) -> set[str]:
        """Collect values defined by one assignment-like statement."""
        targets: list[ast.AST] = []
        if isinstance(statement, ast.Assign):
            targets.extend(statement.targets)
        elif isinstance(statement, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets.append(statement.target)
        elif isinstance(statement, (ast.For, ast.AsyncFor)):
            targets.append(statement.target)

        keys: set[str] = set()

        def collect(target: ast.AST) -> None:
            if isinstance(target, (ast.Tuple, ast.List)):
                for item in target.elts:
                    collect(item)
                return
            key = cls._ast_value_key(target)
            if key:
                keys.add(key)

        for target in targets:
            collect(target)
        return keys

    @classmethod
    def _candidate_statement(
            cls, source: str, locked: dict[str, Any], line: Any) -> ast.stmt | None:
        """Resolve the smallest statement containing one controller-locked source line."""
        if not isinstance(line, int) or isinstance(line, bool):
            return None
        selected = cls._callable_node_at_definition(source, locked.get("definition_line"))
        if selected is None or selected.name != locked.get("symbol"):
            return None
        eligible = set(cls._eligible_callable_lines(source, locked))
        matches = [
            node for node in ast.walk(selected)
            if isinstance(node, ast.stmt)
            and not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.lineno in eligible
            and node.lineno <= line <= (node.end_lineno or node.lineno)
        ]
        if not matches:
            return None
        return min(matches, key=lambda node: (
            (node.end_lineno or node.lineno) - node.lineno,
            abs(node.lineno - line),
        ))

    def _cause_line_choices(
            self, source: str | None, locked: dict[str, Any],
            candidate: dict[str, Any]) -> list[dict[str, Any]]:
        """Build cause-only choices from reaching definitions of the symptom inputs.

        The controller performs only syntactic def-use reduction. It never chooses a
        repair or asserts semantic causality; the locked regression remains the judge.
        """
        if not isinstance(source, str):
            return []
        lines = source.splitlines()
        candidate_line = candidate.get("line")
        candidate_id = str(candidate.get("location_id", ""))
        statement = self._candidate_statement(source, locked, candidate_line)
        if statement is None or not candidate_id:
            return []
        eligible = set(self._eligible_callable_lines(source, locked))
        load_keys = self._statement_load_keys(statement)
        selected_callable = self._callable_node_at_definition(
            source, locked.get("definition_line"))
        definitions: dict[str, list[ast.stmt]] = {key: [] for key in load_keys}
        if selected_callable is not None:
            for prior in ast.walk(selected_callable):
                if (not isinstance(prior, ast.stmt)
                        or isinstance(prior, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                        or prior.lineno not in eligible
                        or not isinstance(candidate_line, int)
                        or prior.lineno >= candidate_line):
                    continue
                stores = self._statement_store_keys(prior)
                for load_key in load_keys:
                    if any(
                            load_key == store
                            or load_key.startswith(store + ".")
                            or load_key.startswith(store + "[")
                            for store in stores):
                        definitions[load_key].append(prior)
        # Preserve every lexically possible reaching definition for control-flow
        # alternatives, but never include unrelated callable statements.
        upstream_lines = sorted({
            prior.lineno
            for candidates in definitions.values()
            for prior in candidates
        })
        rejected = {
            (str(item.get("candidate_location_id", "")),
             int(item.get("line", 0) or 0),
             str(item.get("source_line", "")).strip())
            for item in [
                *self.objective.task_state.rejected_cause_locations,
                *self.objective.task_state.operationally_deferred_cause_locations,
            ]
        }

        def compile_choice(number: int, relation: str) -> dict[str, Any] | None:
            if not 1 <= number <= len(lines):
                return None
            source_line = lines[number - 1].strip()
            if (not source_line
                    or (candidate_id, number, source_line) in rejected):
                return None
            cause_choice_id = _fingerprint({
                "choice_domain": "cause",
                "candidate_location_id": candidate_id,
                "source_sha256": locked.get("source_sha256", ""),
                "line": number,
                "source_line": source_line,
                "relation": relation,
            })
            return {
                "cause_choice_id": cause_choice_id,
                "line": number,
                "source_line": source_line,
                "relation": relation,
            }

        upstream = [choice for number in upstream_lines
                    if (choice := compile_choice(number, "upstream_reaching_definition"))]
        return upstream

    def _cause_candidate_available(self, candidate: dict[str, Any]) -> bool:
        """Keep direct-candidate confirmation distinct from upstream Cause identities."""
        candidate_id = str(candidate.get("location_id", ""))
        line = candidate.get("line")
        source_line = str(candidate.get("source_line", "")).strip()
        if (not candidate_id or not isinstance(line, int) or isinstance(line, bool)
                or not source_line):
            return False
        rejected = {
            (str(item.get("candidate_location_id", "")),
             int(item.get("line", 0) or 0),
             str(item.get("source_line", "")).strip())
            for item in [
                *self.objective.task_state.rejected_cause_locations,
                *self.objective.task_state.operationally_deferred_cause_locations,
            ]
        }
        return (candidate_id, line, source_line) not in rejected

    def _source_line_choices(self, source: str | None,
                             locked: dict[str, Any]) -> list[dict[str, Any]]:
        """Compile opaque, current-revision choices for one locked callable."""
        if not isinstance(source, str):
            return []
        lines = source.splitlines()
        rejected = {
            (int(item.get("line", 0) or 0), str(item.get("source_line", "")).strip())
            for item in [
                *self.objective.task_state.rejected_source_locations,
                *self.objective.task_state.operationally_deferred_source_locations,
            ]
            if item.get("source_file") == locked.get("source_file")
            and item.get("symbol") == locked.get("symbol")
        }
        choices: list[dict[str, Any]] = []
        for number in self._eligible_callable_lines(source, locked):
            if not 1 <= number <= len(lines):
                continue
            source_line = lines[number - 1].strip()
            if not source_line or (number, source_line) in rejected:
                continue
            choice_id = _fingerprint({
                "callable_id": locked.get("callable_id", ""),
                "source_sha256": locked.get("source_sha256", ""),
                "line": number,
                "source_line": source_line,
            })
            choices.append({
                "choice_id": choice_id,
                "line": number,
                "source_line": source_line,
            })
        return choices

    def _apply_callable_locator_gate(
            self, task: Task, observations: list[dict[str, Any]],
            current_snapshot: dict[str, str]) -> None:
        """Lock one current non-test callable; do not accept a statement or diagnosis."""
        state = self.objective.task_state
        submissions = [item for item in observations
                       if item.get("tool") == "submit_callable"]
        if len(submissions) != 1:
            self._gate_failure(
                "callable_location_grounded",
                "Callable Locator must submit exactly one structured callable",
            )
        submitted = dict(submissions[0].get("arguments", {}))
        schema_valid = set(submitted) == {"source_file", "definition_line"}
        source_file = str(submitted.get("source_file", "")).replace("\\", "/")
        definition_line = submitted.get("definition_line")
        source = current_snapshot.get(source_file)
        source_digest = (hashlib.sha256(source.encode("utf-8")).hexdigest()
                         if isinstance(source, str) else "")
        source_scope_valid = (
            source_file in state.atomic_source_files
            and Path(source_file).suffix == ".py"
            and not Path(source_file).name.startswith("test_")
        )
        reads = [item for item in observations
                 if item.get("tool") == "read_source_lines"]
        matching_reads = [
            item for item in reads
            if str(item.get("arguments", {}).get("path", "")).replace("\\", "/")
            == source_file
            and f"SOURCE SHA256: {source_digest}" in str(item.get("output", ""))
        ]
        selected = (self._callable_node_at_definition(source, definition_line)
                    if isinstance(source, str) else None)
        symbol = selected.name if selected is not None else ""
        end_line = ((selected.end_lineno or selected.lineno)
                    if selected is not None else 0)
        callable_location = {
            "source_file": source_file,
            "symbol": symbol,
            "definition_line": definition_line,
            "end_line": end_line,
            "source_sha256": source_digest,
        }
        identity_keys = ("source_file", "symbol", "definition_line", "end_line")
        identity = {key: callable_location.get(key) for key in identity_keys}
        rejected = [
            {key: item.get(key) for key in identity_keys}
            for item in state.rejected_callable_locations
        ]
        novel = identity not in rejected
        if not (state.original_failure_reproduced and schema_valid
                and source_scope_valid and len(matching_reads) >= 1
                and selected is not None and novel):
            reasons: list[str] = []
            if not state.original_failure_reproduced:
                reasons.append("the original failure is not mechanically reproduced")
            if not schema_valid:
                reasons.append(
                    "submission must contain exactly source_file and definition_line")
            if not source_scope_valid:
                reasons.append(f"{source_file!r} is not an original non-test source scope")
            if not matching_reads:
                reasons.append(
                    f"a current-revision numbered read of {source_file!r} is required")
            if selected is None:
                reasons.append(
                    f"definition_line={definition_line!r} is not an exact function or method definition")
            if not novel:
                reasons.append("callable was mechanically exhausted")
            invalid = {
                "source_file": source_file,
                "definition_line": definition_line,
            }
            if invalid not in state.invalid_callable_location_submissions:
                state.invalid_callable_location_submissions.append(invalid)
            self._gate_failure(
                "callable_location_grounded",
                "callable location rejected: " + "; ".join(reasons),
            )
        callable_location["callable_id"] = _fingerprint(callable_location)
        state.callable_location_grounded = True
        state.callable_location = callable_location
        state.source_location_grounded = False
        state.source_location = {}
        state.candidate_source_location = {}
        state.cause_location_grounded = False
        state.source_runtime_evidence = {}

    def _apply_source_locator_gate(
            self, task: Task, observations: list[dict[str, Any]],
            current_snapshot: dict[str, str]) -> None:
        """Lock one exact current line inside the controller-locked callable."""
        state = self.objective.task_state
        submissions = [item for item in observations
                       if item.get("tool") == "submit_location"]
        if len(submissions) != 1:
            self._gate_failure(
                "source_location_grounded",
                "Source Locator must submit exactly one structured source line",
            )
        submitted = dict(submissions[0].get("arguments", {}))
        schema_valid = set(submitted) == {"callable_id", "choice_id"}
        callable_id = str(submitted.get("callable_id", "")).strip()
        choice_id = str(submitted.get("choice_id", "")).strip()
        locked = dict(state.callable_location)
        source_file = str(locked.get("source_file", ""))
        source = current_snapshot.get(source_file)
        source_digest = (hashlib.sha256(source.encode("utf-8")).hexdigest()
                         if isinstance(source, str) else "")
        callable_valid = (
            state.callable_location_grounded
            and callable_id == locked.get("callable_id")
            and bool(callable_id)
        )
        source_current = (
            isinstance(source, str)
            and source_digest == locked.get("source_sha256")
        )
        choices = self._source_line_choices(source, locked)
        matching_choices = [choice for choice in choices
                            if choice["choice_id"] == choice_id]
        identity_keys = ("source_file", "symbol", "line", "source_line")
        rejected = [
            {key: item.get(key) for key in identity_keys}
            for item in state.rejected_source_locations
        ]
        line_valid = len(matching_choices) == 1
        selected_choice = matching_choices[0] if line_valid else {}
        line_number = selected_choice.get("line")
        locked_source_line = str(selected_choice.get("source_line", ""))
        location = {
            "callable_id": callable_id,
            "source_file": source_file,
            "symbol": locked.get("symbol", ""),
            "line": line_number,
            "source_line": locked_source_line,
        }
        identity = {key: location.get(key) for key in identity_keys}
        novel = identity not in rejected
        if not (state.original_failure_reproduced and schema_valid and callable_valid
                and source_current and line_valid and novel):
            reasons: list[str] = []
            if not state.original_failure_reproduced:
                reasons.append("the original failure is not mechanically reproduced")
            if not schema_valid:
                reasons.append(
                    "submission must contain exactly callable_id and choice_id")
            if not callable_valid:
                reasons.append("callable_id does not match the locked callable")
            if not source_current:
                reasons.append("locked callable source is stale at the current revision")
            if not line_valid:
                reasons.append(
                    f"choice_id={choice_id!r} is not one current visible line choice "
                    "inside the locked callable")
            if not novel:
                reasons.append("exact source location was mechanically disproven")
            invalid = {
                "callable_id": callable_id,
                "choice_id": choice_id,
            }
            if invalid not in state.invalid_source_location_submissions:
                state.invalid_source_location_submissions.append(invalid)
            self._gate_failure(
                "source_location_grounded",
                "source location rejected: " + "; ".join(reasons),
            )
        location["source_sha256"] = source_digest
        location["location_id"] = _fingerprint({
            "callable_id": callable_id,
            "source_file": source_file,
            "symbol": locked.get("symbol", ""),
            "line": line_number,
            "source_line": locked_source_line,
            "source_sha256": source_digest,
        })
        state.source_location_grounded = True
        state.source_location = location
        state.candidate_source_location = dict(location)
        state.cause_location_grounded = False
        state.source_runtime_evidence = {}

    def _apply_cause_locator_gate(
            self, task: Task, observations: list[dict[str, Any]],
            current_snapshot: dict[str, str]) -> None:
        """Lock the upstream producer chosen from controller-owned line identities."""
        state = self.objective.task_state
        submissions = [item for item in observations
                       if item.get("tool") in {
                           "submit_cause", "confirm_candidate", "reject_cause_frontier"}]
        if len(submissions) != 1:
            self._gate_failure(
                "cause_location_grounded",
                "Cause Locator must submit exactly one upstream choice or direct-candidate "
                "confirmation",
            )
        submission_tool = str(submissions[0].get("tool", ""))
        submitted = dict(submissions[0].get("arguments", {}))
        schema_valid = (
            (submission_tool == "submit_cause"
             and set(submitted) == {"candidate_location_id", "cause_choice_id"})
            or (submission_tool == "confirm_candidate"
                and set(submitted) == {"candidate_location_id"})
            or (submission_tool == "reject_cause_frontier"
                and set(submitted) == {"candidate_location_id"})
        )
        candidate_location_id = str(
            submitted.get("candidate_location_id", "")).strip()
        cause_choice_id = str(submitted.get("cause_choice_id", "")).strip()
        locked = dict(state.callable_location)
        candidate = dict(state.candidate_source_location)
        source_file = str(locked.get("source_file", ""))
        source = current_snapshot.get(source_file)
        source_digest = (hashlib.sha256(source.encode("utf-8")).hexdigest()
                         if isinstance(source, str) else "")
        candidate_valid = (
            state.callable_location_grounded
            and state.source_location_grounded
            and candidate_location_id == candidate.get("location_id")
            and bool(candidate_location_id)
        )
        source_current = (
            isinstance(source, str)
            and source_digest == locked.get("source_sha256")
        )
        cause_choices = self._cause_line_choices(source, locked, candidate)
        if submission_tool == "confirm_candidate":
            line_valid = self._cause_candidate_available(candidate)
            selected = ({
                "line": candidate.get("line"),
                "source_line": candidate.get("source_line", ""),
                "relation": "direct_candidate_confirmation",
            } if line_valid else {})
        elif submission_tool == "reject_cause_frontier":
            line_valid = not cause_choices
            selected = {}
        else:
            matching = [
                choice for choice in cause_choices
                if choice["cause_choice_id"] == cause_choice_id
            ]
            line_valid = len(matching) == 1
            selected = matching[0] if line_valid else {}
        line_number = selected.get("line")
        source_line = str(selected.get("source_line", ""))
        if not (state.original_failure_reproduced and schema_valid and candidate_valid
                and source_current and line_valid):
            reasons: list[str] = []
            if not state.original_failure_reproduced:
                reasons.append("the original failure is not mechanically reproduced")
            if not schema_valid:
                reasons.append(
                    "submit_cause requires candidate_location_id and cause_choice_id; "
                    "confirm_candidate and reject_cause_frontier require only "
                    "candidate_location_id")
            if not candidate_valid:
                reasons.append(
                    "candidate_location_id does not match the locked Source Locator symptom")
            if not source_current:
                reasons.append("locked callable source is stale at the current revision")
            if not line_valid:
                if submission_tool == "confirm_candidate":
                    reasons.append("the direct candidate is not a current untried cause choice")
                elif submission_tool == "reject_cause_frontier":
                    reasons.append(
                        "the cause frontier cannot be rejected while upstream choices remain")
                else:
                    reasons.append(
                        f"cause_choice_id={cause_choice_id!r} is not one current "
                        "upstream cause-only choice")
            self._gate_failure(
                "cause_location_grounded",
                "cause location rejected: " + "; ".join(reasons),
            )
        if submission_tool == "reject_cause_frontier":
            self._schedule_after_rejected_cause_frontier(
                task,
                "Cause Locator found that the remaining locked symptom cannot explain every "
                "mismatched observable field after its upstream frontier was exhausted.",
            )
            return
        location = {
            "callable_id": locked.get("callable_id", ""),
            "candidate_location_id": candidate_location_id,
            "source_file": source_file,
            "symbol": locked.get("symbol", ""),
            "line": line_number,
            "source_line": source_line,
            "source_sha256": source_digest,
            "cause_relation": selected.get("relation", ""),
            "expression_frame": self._source_expression_frame(source_line),
        }
        location["location_id"] = _fingerprint(location)
        state.source_location_grounded = True
        state.source_location = location
        state.cause_location_grounded = True
        state.diagnosis_grounded = False
        state.investigator_diagnosis = {}
        state.source_runtime_evidence = {}

    def _apply_investigator_gate(self, task: Task, summary: str,
                                 observations: list[dict[str, Any]],
                                 current_snapshot: dict[str, str]) -> None:
        """Attach one causal mechanism to the controller-locked source location."""
        state = self.objective.task_state
        submissions = [item for item in observations
                       if item.get("tool") == "submit_mechanism"]
        if len(submissions) != 1:
            self._gate_failure(
                "diagnosis_grounded",
                "Investigator must submit exactly one causal mechanism",
            )
        counterexample = state.regression_target or self._smallest_oracle_counterexample()
        locked_location = dict(state.source_location)
        submitted = dict(submissions[0].get("arguments", {}))
        location_id = str(submitted.get("location_id", "")).strip()
        mechanism = str(submitted.get("mechanism", "")).strip()
        location_valid = (
            state.source_location_grounded
            and location_id == locked_location.get("location_id")
        )
        locked_source = current_snapshot.get(str(locked_location.get("source_file", "")))
        locked_line_number = locked_location.get("line")
        locked_lines = locked_source.splitlines() if isinstance(locked_source, str) else []
        source_still_locked = (
            isinstance(locked_source, str)
            and hashlib.sha256(locked_source.encode("utf-8")).hexdigest()
            == locked_location.get("source_sha256")
            and isinstance(locked_line_number, int)
            and not isinstance(locked_line_number, bool)
            and 1 <= locked_line_number <= len(locked_lines)
            and locked_lines[locked_line_number - 1].strip()
            == str(locked_location.get("source_line", "")).strip()
        )
        diagnosis = {
            "location_id": location_id,
            "source_file": locked_location.get("source_file", ""),
            "symbol": locked_location.get("symbol", ""),
            "line": locked_location.get("line", 0),
            "source_line": locked_location.get("source_line", ""),
            "actual": (counterexample.get("actual")
                       if isinstance(counterexample, dict) else None),
            "expected": (counterexample.get("expected")
                         if isinstance(counterexample, dict) else None),
            "mechanism": mechanism,
        }
        novel_hypothesis = diagnosis not in state.rejected_investigator_diagnoses
        if not (state.original_failure_reproduced and state.cause_location_grounded
                and location_valid and source_still_locked
                and mechanism and novel_hypothesis):
            failure_reasons = []
            if not state.original_failure_reproduced:
                failure_reasons.append("the original failure is not mechanically reproduced")
            if not state.cause_location_grounded:
                failure_reasons.append("no controller-grounded Cause Locator result is available")
            if not location_valid:
                failure_reasons.append(
                    "submitted location_id does not match the locked Source Locator result")
            if not source_still_locked:
                failure_reasons.append("locked source location is stale at the current revision")
            if not mechanism:
                failure_reasons.append("mechanism is empty")
            if not novel_hypothesis:
                failure_reasons.append(
                    "diagnosis must differ from rejected hypotheses; exact repeat detected")
            if diagnosis not in state.rejected_investigator_diagnoses:
                state.rejected_investigator_diagnoses.append(dict(diagnosis))
            upstream_investigator = next((
                self.tasks[dependency_id]
                for dependency_id in task.dependencies
                if self.tasks[dependency_id].capability.upper() == "INVESTIGATOR"
            ), None)
            downstream_repairs = [
                candidate for candidate in self.tasks.values()
                if candidate.capability.upper() == "REPAIR"
                and task.task_id in candidate.dependencies
            ]
            if (not novel_hypothesis and upstream_investigator is not None
                    and len(downstream_repairs) == 1):
                self._schedule_reinvestigation_after_failed_repair(
                    downstream_repairs[0],
                    "Same-line Investigator repeated an already rejected mechanism; "
                    "the locked line is operationally exhausted for this fixed model.",
                    dependency=upstream_investigator,
                    superseded_dependency_id=task.task_id,
                )
                self.cancel_task(
                    task.task_id,
                    "NONRETRYABLE: duplicate same-line diagnosis superseded by relocation",
                )
            self._gate_failure(
                "diagnosis_grounded",
                "structured diagnosis rejected: " + "; ".join(failure_reasons),
            )
        state.diagnosis_grounded = True
        state.investigator_diagnosis = diagnosis
        state.root_cause_identified = False
        regression_tasks = [candidate for candidate in self.tasks.values()
                            if task.task_id in candidate.dependencies
                            and candidate.capability.upper() == "REGRESSION_DESIGNER"]
        regression_ids = {regression.task_id for regression in regression_tasks}
        repairs = [candidate for candidate in self.tasks.values()
                   if candidate.capability.upper() == "REPAIR"
                   and (task.task_id in candidate.dependencies
                        or bool(regression_ids.intersection(candidate.dependencies)))]
        source_file = str(locked_location.get("source_file", ""))
        for repair in repairs:
            scopes = [source_file]
            repair.authority.read_scopes = scopes
            repair.authority.write_scopes = scopes
            repair.required_context = scopes

    def _grounded_completion(self, task: Task,
                             observations: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Close a bounded task from broker evidence when a local model misses finish."""
        capability = task.capability.upper()
        reads = [item for item in observations if item["tool"] == "read_file"]
        tests = [item for item in observations if item["tool"] == "run_command"]
        passing = any("EXIT CODE: 0" in item["output"] for item in tests)
        edits = [item for item in observations
                 if item["tool"] in {"replace_in_file", "append_to_file"}]
        inspected = bool(reads or task.required_context)
        complete = (
            (capability == "REPRODUCER" and bool(tests))
            or (capability == "SCOUT" and inspected and bool(observations))
            or (capability in {"REVIEWER", "VALIDATOR"} and inspected and passing)
            or (capability == "REGRESSION_DESIGNER"
                and any(item["tool"] in {"replace_in_file", "append_to_file"}
                        and Path(str(item["arguments"].get("path", ""))).name.startswith("test_")
                        for item in observations)
                and bool(tests))
            # A bounded Builder may correctly complete its scoped repair while the
            # full objective still fails for a newly exposed cause. Objective-level
            # validation and graph revision own that residual failure.
            or (capability in {"BUILDER", "REPAIR"} and bool(edits and tests))
        )
        if not complete:
            return None
        return {
            "status": "COMPLETED",
            "summary": "Capability acceptance satisfied by brokered evidence; final envelope normalized by executive.",
            "evidence": [{"kind": "OBSERVATION",
                          "summary": "Required capability tools completed with broker provenance."}],
            "artifacts": [],
            "discovered_tasks": [],
        }

    def run_task(self, task_id: str) -> WorkerRun:
        task = self.tasks[task_id]
        if self.config.responsibility_call_budgets:
            agent = self.atomic_agents.get(task.capability.upper())
            if agent is None:
                raise RuntimeError(
                    f"atomic task has no concrete agent: {task.capability}")
            return agent.run(self, task)
        return self._execute_task(task, WORKER_SYSTEM, self._worker_packet(task), None)

    def _execute_task(self, task: Task, system_prompt: str, packet: dict[str, Any],
                      atomic_agent: AtomicAgent | None) -> WorkerRun:
        try:
            run = self._acquire(task)
        except RuntimeError as exc:
            # A rejected duplicate is observable to the caller but is not persisted as
            # another run, preserving the exactly-one lease invariant.
            return WorkerRun(stable_id("denied"), self.objective.objective_id, task.task_id,
                             task.capability, WorkerStatus.FAILED, task.authority,
                             self._task_fingerprint(task),
                             self.config.capability_models.get(task.capability, self.config.default_model),
                             "", finished_at=utc_now(), error=str(exc))
        fixed_review = (self._review_snapshot()
                        if isinstance(atomic_agent, ReviewerAgent) else None)
        rejected_replacements = None
        if isinstance(atomic_agent, RepairAgent):
            state = self.objective.task_state
            location_id = str(state.source_location.get("location_id", ""))
            rejected_replacements = [
                action for action in state.rejected_repair_actions
                if self._repair_action_applies_to_location(
                    state, action, location_id)
            ]
        fixed_line_repair = (
            dict(self.objective.task_state.source_location)
            if isinstance(atomic_agent, RepairAgent) else None
        )
        session = WorkerSession(
            self.root, task.authority, self.config.command_timeout_seconds,
            fixed_review=fixed_review,
            rejected_replacements=rejected_replacements,
            fixed_line_repair=fixed_line_repair,
        )
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(packet, default=str)}]
        grounded_observations: list[dict[str, Any]] = []
        def grounded_finish() -> dict[str, Any] | None:
            return (atomic_agent.grounded_completion(task, grounded_observations)
                    if atomic_agent is not None
                    else self._grounded_completion(task, grounded_observations))
        try:
            finish: dict[str, Any] | None = None
            step_limit = self._worker_step_limit(task)
            if step_limit <= 0:
                raise RuntimeError("protected tail inference reserve reached")
            for step_index in range(step_limit):
                if self._cancel_events[run.run_id].is_set():
                    raise InterruptedError("worker cancelled")
                if step_index == step_limit - 1 and grounded_observations:
                    messages.append({
                        "role": "user",
                        "content": (
                            "FINAL ALLOWED TURN: Do not call another tool. Return the finish JSON "
                            "now, summarizing the exact conclusion supported by the brokered observations."
                        ),
                    })
                raw = self._call_model(
                    self.worker_chat, messages, run.model,
                    responsibility=(atomic_agent.capability if atomic_agent is not None
                                    else task.capability.upper()),
                ); run.inference_calls += 1
                try:
                    action = json.loads(normalize(raw))
                    if not isinstance(action, dict) or "name" not in action:
                        raise ValueError("action must be an object with a name")
                except (json.JSONDecodeError, ValueError) as exc:
                    self.store.trace("worker_protocol_error", worker_run_id=run.run_id,
                                     task_id=task.task_id, error=str(exc), raw=raw[:2_000])
                    finish = grounded_finish()
                    if finish:
                        break
                    messages += [
                        {"role": "assistant", "content": normalize(raw)},
                        {"role": "user", "content":
                         "PROTOCOL ERROR: Return exactly one JSON tool action and no prose. Retry now."},
                    ]
                    continue
                name, arguments = action["name"], action.get("arguments", {})
                if name == "finish" and not grounded_observations:
                    messages += [
                        {"role": "assistant", "content": normalize(raw)},
                        {"role": "user", "content":
                         "COMPLETION REJECTED: use at least one allowed tool successfully before finish."},
                    ]
                    continue
                if name == "finish": finish = arguments; break
                action_fingerprint = _fingerprint({"name": name, "arguments": arguments})
                run.action_fingerprints.append(action_fingerprint)
                consecutive = 0
                for fingerprint in reversed(run.action_fingerprints):
                    if fingerprint != action_fingerprint:
                        break
                    consecutive += 1
                if consecutive > self.config.max_identical_actions:
                    raise RuntimeError("identical action loop detected after strategy-change warning")
                if consecutive == self.config.max_identical_actions:
                    self.store.trace("worker_repeated_action", worker_run_id=run.run_id,
                                     task_id=task.task_id, action_fingerprint=action_fingerprint)
                    messages += [
                        {"role": "assistant", "content": normalize(raw)},
                        {"role": "user", "content": (
                            "REPEATED ACTION REJECTED: repository state and arguments are unchanged. "
                            "Choose a materially different action or finish with the evidence already gathered."
                        )},
                    ]
                    continue
                try:
                    observation = session.execute(name, arguments)
                    bounded_observation = (
                        observation if len(observation) <= 8_000 else
                        observation[:4_000]
                        + "\n...[controller retained tail after truncation]...\n"
                        + observation[-4_000:]
                    )
                    observation_record = {
                        "tool": name, "arguments": arguments, "output": bounded_observation,
                    }
                    if name == "read_file":
                        observation_record["full_output_sha256"] = hashlib.sha256(
                            observation.encode("utf-8")).hexdigest()
                        observation_record["full_output_chars"] = len(observation)
                    grounded_observations.append(observation_record)
                    if name in {"replace_in_file", "append_to_file", "replace_selected_line",
                                "replace_selected_leaf", "replace_selected_expression"}:
                        path = (str(self.objective.task_state.source_location.get(
                            "source_file", "")) if name in {
                                "replace_selected_line", "replace_selected_leaf",
                                "replace_selected_expression"}
                                else str(arguments.get("path", "")))
                        if path and path not in run.edited_files:
                            run.edited_files.append(path)
                    elif name == "run_command":
                        command = str(arguments.get("command", ""))
                        if command:
                            run.commands_executed.append(command)
                    if atomic_agent is not None:
                        evidence_finish = grounded_finish()
                        if evidence_finish is not None:
                            finish = evidence_finish
                            break
                except Exception as exc:
                    observation = f"TOOL ERROR: {type(exc).__name__}: {exc}"
                    if (isinstance(atomic_agent, RepairAgent)
                            and name in {"replace_selected_line",
                                         "replace_selected_leaf",
                                         "replace_selected_expression"}):
                        self._record_rejected_repair_action(
                            task, arguments, exc, session)
                        raise ValueError(
                            "repair action rejected; Hive requires a fresh one-action "
                            "Repair worker with the current source packet"
                        ) from exc
                    finish = grounded_finish()
                    if finish:
                        break
                remaining = step_limit - step_index - 1
                messages += [{"role": "assistant", "content": normalize(raw)},
                             {"role": "user", "content": (
                                 f"TOOL RESULT:\n{observation}\nChoose next action. "
                                 f"{remaining} inference turn(s) remain; finish immediately once the "
                                 "acceptance conditions are evidenced."
                             )}]
            if finish is None:
                finish = grounded_finish()
            if finish is None:
                raise RuntimeError("worker step budget exhausted without structured finish")
            self._ingest(run, task, finish, grounded_observations, atomic_agent)
        except InterruptedError as exc:
            self._fail_run(run, task, WorkerStatus.CANCELLED, TaskStatus.CANCELLED, str(exc))
        except Exception as exc:
            cancelled = self._cancel_events.get(run.run_id)
            if task.status == TaskStatus.CANCELLED or (cancelled and cancelled.is_set()):
                self._fail_run(run, task, WorkerStatus.CANCELLED, TaskStatus.CANCELLED, str(exc))
            else:
                self._fail_run(run, task, WorkerStatus.FAILED, TaskStatus.FAILED,
                               f"{type(exc).__name__}: {exc}")
        return run

    def _ingest(self, run: WorkerRun, task: Task, result: dict[str, Any],
                grounded_observations: list[dict[str, Any]],
                atomic_agent: AtomicAgent | None = None) -> None:
        with self._lock:
            self._ingest_locked(run, task, result, grounded_observations, atomic_agent)

    def _ingest_locked(self, run: WorkerRun, task: Task, result: dict[str, Any],
                       grounded_observations: list[dict[str, Any]],
                       atomic_agent: AtomicAgent | None = None) -> None:
        cancelled = self._cancel_events.get(run.run_id)
        if (task.status != TaskStatus.RUNNING or task.lease_id != run.lease_id
                or task.assigned_worker_run_id != run.run_id
                or (cancelled and cancelled.is_set())):
            raise RuntimeError("stale or cancelled worker result rejected")
        status = str(result.get("status", "FAILED")).upper()
        if status not in {"COMPLETED", "BLOCKED"}:
            raise ValueError("finish status must be COMPLETED or BLOCKED")
        # A read-only investigator may describe an actionable source defect as
        # "blocked" merely because it correctly lacks edit authority.  When it
        # has actually reproduced the failure, inspected repository evidence,
        # and returned an explicit evidenced conclusion, the diagnostic task is
        # complete; remediation remains a separate Builder responsibility.
        if (status == "BLOCKED" and task.capability.upper() == "INVESTIGATOR"
                and str(result.get("summary", "")).strip()
                and (task.required_context
                     or any(item["tool"] == "read_file" for item in grounded_observations))
                and (any(item["tool"] == "run_command" for item in grounded_observations)
                     or (task.expected_output.startswith("Controller-targeted source: ")
                         and any(item["tool"] == "read_file"
                                 for item in grounded_observations)))):
            status = "COMPLETED"
            self.store.trace("worker_status_normalized", worker_run_id=run.run_id,
                             task_id=task.task_id,
                             reason="read-only investigation returned an evidenced diagnosis")
        if (status == "BLOCKED" and task.capability.upper() == "REPRODUCER"
                and (any(item["tool"] == "run_command"
                         and "EXIT CODE: 0" not in item["output"]
                         for item in grounded_observations)
                     or (self.objective.task_state.atomic_cycle > 1
                         and bool(self.objective.task_state.oracle_feedback)
                         and any(item["tool"] == "run_command"
                                 for item in grounded_observations)))):
            status = "COMPLETED"
            self.store.trace(
                "worker_status_normalized", worker_run_id=run.run_id,
                task_id=task.task_id,
                reason="reproducer captured the required failing command",
            )
        if status == "COMPLETED" and not grounded_observations:
            raise ValueError("COMPLETED requires evidence grounded in a successful brokered tool call")
        current_snapshot = snapshot_repository(self.root)
        tools_used = {item["tool"] for item in grounded_observations}
        if (status == "COMPLETED" and task.capability.upper() in {"BUILDER", "REPAIR"}
                and atomic_agent is None):
            test_executed = any(item["tool"] == "run_command" for item in grounded_observations)
            if "replace_in_file" not in tools_used or not test_executed:
                raise ValueError("BUILDER completion requires a brokered edit and test execution")
            task_contract = " ".join([task.description, *task.acceptance_conditions]).lower()
            requires_regression = bool(re.search(
                r"\b(?:add|create|write)\b.{0,40}\bregression\b", task_contract))
            edited_test = any(
                item["tool"] in {"replace_in_file", "append_to_file"}
                and Path(str(item["arguments"].get("path", ""))).name.startswith("test_")
                for item in grounded_observations
            )
            if requires_regression and not edited_test:
                raise ValueError("regression-bearing Builder requires its own brokered test-file edit")
        if status == "COMPLETED" and task.capability.upper() == "REGRESSION_DESIGNER":
            edited_test = any(
                item["tool"] in {"replace_in_file", "append_to_file"}
                and Path(str(item["arguments"].get("path", ""))).name.startswith("test_")
                for item in grounded_observations
            )
            red_test = any(item["tool"] == "run_command" and "EXIT CODE: 0" not in item["output"]
                           for item in grounded_observations)
            if not edited_test or not red_test:
                raise ValueError(
                    "REGRESSION_DESIGNER completion requires a brokered test edit and failing red-phase test")
        if status == "COMPLETED" and task.capability.upper() == "VALIDATOR":
            if not any(item["tool"] == "run_command" and "EXIT CODE: 0" in item["output"]
                       for item in grounded_observations):
                raise ValueError("VALIDATOR completion requires a passing brokered test")
        if (atomic_agent is None and task.capability.upper() == "REVIEWER"
                and "regression" in self.objective.original_request.lower()):
            changed_tests = [
                path for path in current_snapshot
                if Path(path).name.startswith("test_")
                and self.objective.baseline_snapshot.get(path) != current_snapshot.get(path)
            ]
            passing_test = any(
                item["tool"] == "run_command" and "EXIT CODE: 0" in item["output"]
                for item in grounded_observations
            )
            if not changed_tests:
                raise RuntimeError(
                    "NONRETRYABLE: reviewer cannot approve regression coverage; no test changed")
            if status == "COMPLETED" and not passing_test:
                raise RuntimeError(
                    "NONRETRYABLE: reviewer cannot approve; no passing brokered test result")
        current_revision = revision_id(current_snapshot)
        reported_evidence = result.get("evidence", [])
        if not reported_evidence and grounded_observations:
            reported_evidence = [{"kind": "OBSERVATION", "summary": "Brokered tool evidence",
                                  "payload": None}]
        staged_evidence = []
        for item in reported_evidence:
            kind = EvidenceKind(str(item.get("kind", "CLAIM")).upper())
            staged_evidence.append((kind, str(item.get("summary", "")), item.get("payload")))
        staged_artifacts = []
        for item in result.get("artifacts", []):
            path = str(item.get("path", ""))
            artifact_path = WorkerSession(self.root, task.authority)._path(
                path, task.authority.read_scopes + task.authority.write_scopes)
            if not artifact_path.is_file():
                raise ValueError(f"reported artifact does not exist: {path}")
            staged_artifacts.append((path, str(item.get("description", ""))))
        if atomic_agent is not None and status == "COMPLETED":
            atomic_agent.apply_gate(
                self, task, run, status, str(result.get("summary", "")),
                grounded_observations, current_snapshot,
            )
            self.objective.task_state.last_failed_gate = ""
            self.objective.task_state.last_gate_feedback = ""
        for kind, summary, payload in staged_evidence:
            evidence = Evidence(stable_id("evidence"), kind, summary,
                                run.run_id, task.task_id, current_revision,
                                {"reported_payload": payload,
                                 "broker_observations": grounded_observations},
                                verified=False)
            self.evidence[evidence.evidence_id] = evidence
            task.evidence_ids.append(evidence.evidence_id); run.evidence_ids.append(evidence.evidence_id)
            self.objective.evidence_ids.append(evidence.evidence_id)
        for observation in grounded_observations:
            broker_kind = (EvidenceKind.TEST_RESULT if observation["tool"] == "run_command"
                           else EvidenceKind.DIFF if observation["tool"]
                           in {"replace_in_file", "replace_selected_line",
                               "replace_selected_leaf", "replace_selected_expression",
                               "append_to_file"}
                           else EvidenceKind.OBSERVATION)
            broker_evidence = Evidence(
                stable_id("evidence"), broker_kind,
                f"Broker executed {observation['tool']}", run.run_id, task.task_id,
                current_revision, observation, verified=True,
                lifecycle=EvidenceLifecycle.CURRENT,
            )
            self.evidence[broker_evidence.evidence_id] = broker_evidence
            task.evidence_ids.append(broker_evidence.evidence_id)
            run.evidence_ids.append(broker_evidence.evidence_id)
            self.objective.evidence_ids.append(broker_evidence.evidence_id)
        for path, description in staged_artifacts:
            artifact = Artifact(stable_id("artifact"), path, current_revision, run.run_id, task.task_id,
                                description)
            self.artifacts[artifact.artifact_id] = artifact
            task.artifact_ids.append(artifact.artifact_id); run.artifact_ids.append(artifact.artifact_id)
            self.objective.artifact_ids.append(artifact.artifact_id)
        for discovered in result.get("discovered_tasks", []):
            if not isinstance(discovered, dict) or not discovered.get("description"):
                continue
            proposal = Evidence(stable_id("evidence"), EvidenceKind.INFERENCE,
                                "Worker proposed a follow-up task for executive review",
                                run.run_id, task.task_id, current_revision, discovered, verified=False)
            self.evidence[proposal.evidence_id] = proposal
            task.evidence_ids.append(proposal.evidence_id); run.evidence_ids.append(proposal.evidence_id)
            self.objective.evidence_ids.append(proposal.evidence_id)
        run.status = WorkerStatus.COMPLETED; run.finished_at = utc_now(); run.summary = str(result.get("summary", ""))
        run.end_revision = current_revision
        task.status = TaskStatus.COMPLETED if status == "COMPLETED" else TaskStatus.BLOCKED
        task.failure_reason = "" if status == "COMPLETED" else run.summary
        if status == "BLOCKED":
            task.retry_count += 1
            task.last_failure_fingerprint = run.input_fingerprint
        task.lease_id = None; task.updated_at = utc_now()
        self._persist(); self.store.trace("worker_finished", worker_run_id=run.run_id,
                                          task_id=task.task_id, status=task.status.value)

    def _fail_run(self, run: WorkerRun, task: Task, worker_status: WorkerStatus,
                  task_status: TaskStatus, error: str) -> None:
        with self._lock:
            run.status, run.error, run.finished_at = worker_status, error, utc_now()
            run.end_revision = revision_id(snapshot_repository(self.root))
            if task.assigned_worker_run_id == run.run_id:
                task.status, task.failure_reason, task.lease_id = task_status, error, None
                if task_status != TaskStatus.CANCELLED:
                    task.retry_count += 1
                    task.last_failure_fingerprint = run.input_fingerprint
            self._persist(); self.store.trace("worker_failed", worker_run_id=run.run_id,
                                              task_id=task.task_id, error=error)

    def run_ready(self) -> list[WorkerRun]:
        ready = self.ready_tasks()
        read_only, writers = [t for t in ready if t.authority.read_only], [t for t in ready if not t.authority.read_only]
        results: list[WorkerRun] = []
        with ThreadPoolExecutor(max_workers=max(1, self.config.max_active_workers)) as pool:
            futures = {pool.submit(self.run_task, task.task_id): task.task_id for task in read_only}
            for future in as_completed(futures): results.append(future.result())
        for task in writers: results.append(self.run_task(task.task_id))
        return results

    def validate_objective(self) -> ValidationResult:
        with WorkerSession._write_lock:
            return self._validate_objective_locked()

    def _validate_objective_locked(self) -> ValidationResult:
        command = self.config.test_command
        if command not in {"pytest", "pytest -v", "pytest --verbose"}:
            raise ValueError("validation command is not in the controller allowlist")
        before = revision_id(snapshot_repository(self.root))
        result = _run_pytest(command, self.root, self.config.command_timeout_seconds)
        output = f"EXIT CODE: {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        after_snapshot = snapshot_repository(self.root); after = revision_id(after_snapshot)
        reasons: list[str] = []
        decision = "REVISE"
        if result.returncode != 0: reasons.append("mechanical validation failed")
        elif before != after: reasons.append("repository changed during validation")
        elif "regression" in self.objective.original_request.lower():
            changed_tests = [path for path in after_snapshot
                             if Path(path).name.startswith("test_")
                             and self.objective.baseline_snapshot.get(path) != after_snapshot.get(path)]
            regression_runs = [run for run in self.worker_runs.values()
                               if run.capability.upper() == "REGRESSION_DESIGNER"
                               and run.status == WorkerStatus.COMPLETED
                               and any(Path(path).name.startswith("test_") for path in run.edited_files)]
            state = self.objective.task_state
            existing_regression = bool(
                self.config.responsibility_call_budgets
                and state.regression_established
                and state.regression_origin == "existing"
                and state.regression_nodes
            )
            if (not existing_regression
                    and (not changed_tests
                         or (self.config.regression_first and not regression_runs))):
                reasons.append("mechanical regression evidence missing")
            else:
                decision = "PENDING_JUDGE"
        if result.returncode == 0 and before == after and not reasons:
            decision = "PENDING_JUDGE"
        atomic_oracle_used = bool(
            self.config.responsibility_call_budgets and self.acceptance_oracle is not None)
        if decision == "PENDING_JUDGE" and atomic_oracle_used:
            try:
                oracle_result = self.acceptance_oracle(self.root)
                oracle_pass = (bool(oracle_result.get("accepted"))
                               if isinstance(oracle_result, dict) else bool(oracle_result))
                self.objective.task_state.acceptance_oracle_pass = oracle_pass
                public_oracle = self._public_oracle_residual(
                    oracle_result if isinstance(oracle_result, dict) else {})
                self.objective.task_state.oracle_feedback = json.dumps(
                    public_oracle, sort_keys=True, default=str)
                decision = "ACCEPT" if oracle_pass else "REVISE"
                reasons = (["deterministic acceptance oracle passed"] if oracle_pass else
                           ["deterministic acceptance oracle failed: "
                            + json.dumps(public_oracle, sort_keys=True, default=str)])
            except Exception as exc:
                self.objective.task_state.acceptance_oracle_pass = False
                decision, reasons = "REVISE", [f"acceptance oracle failed closed: {exc}"]
        if decision == "PENDING_JUDGE":
            packet = {"original_objective": self.objective.original_request,
                      "success_criteria": self.objective.success_criteria,
                      "task_results": [{"description": task.description,
                                        "acceptance_conditions": task.acceptance_conditions,
                                        "status": task.status.value,
                                        "evidence": [asdict(self.evidence[eid]) for eid in task.evidence_ids]}
                                       for task in self.tasks.values()],
                      "baseline_revision": self.objective.baseline_revision,
                      "validated_revision": after,
                      "proposed_diff": repository_diff(self.objective.baseline_snapshot, after_snapshot),
                      "test_result": output,
                      "instruction": "Return JSON: decision ACCEPT or REVISE, and nonempty reasons list."}
            try:
                raw = self._call_model(self.judge_chat, [
                    {"role": "system", "content": "Independently judge objective conformance. Tests alone are insufficient. Return JSON only."},
                    {"role": "user", "content": json.dumps(packet)}], self.config.default_model,
                    responsibility="REVIEWER")
                parsed = json.loads(normalize(raw)); decision = str(parsed.get("decision", "REVISE")).upper()
                reasons = [str(item) for item in parsed.get("reasons", [])]
                if decision not in {"ACCEPT", "REVISE"} or not reasons: raise ValueError("invalid judgment")
            except Exception as exc:
                decision, reasons = "REVISE", [f"conformance judge failed closed: {exc}"]
        final_revision = revision_id(snapshot_repository(self.root))
        if final_revision != after:
            reasons.append("repository changed during conformance judgment")
        accepted = (result.returncode == 0 and before == after == final_revision
                    and decision == "ACCEPT")
        if self.config.responsibility_call_budgets:
            accepted = accepted and self.objective.task_state.complete
        validation = ValidationResult(stable_id("validation"), after, command, result.returncode,
                                      output, accepted, decision, reasons)
        bounded_output = output[:self.config.max_context_chars]
        validation_evidence = Evidence(
            stable_id("evidence"), EvidenceKind.TEST_RESULT,
            "Controller objective validation", "controller", "controller", after,
            {"validation_id": validation.validation_id, "command": command,
            "exit_code": result.returncode, "output": bounded_output,
             "output_truncated": len(output) > len(bounded_output),
             "accepted": accepted, "decision": decision, "reasons": reasons},
            verified=True, lifecycle=EvidenceLifecycle.CURRENT,
        )
        self.evidence[validation_evidence.evidence_id] = validation_evidence
        self.objective.evidence_ids.append(validation_evidence.evidence_id)
        self.objective.validation = validation
        self.objective.state = "SATISFIED" if accepted else "ACTIVE"
        self._persist(); self.store.trace("objective_validated", revision=after, accepted=accepted,
                                          decision=decision, reasons=reasons)
        return validation

    def continuation_judgment(self) -> ContinuationDecision:
        if self.objective.state == "BLOCKED":
            return ContinuationDecision.GENUINELY_BLOCKED
        current = revision_id(snapshot_repository(self.root))
        validation = self.objective.validation
        if validation and validation.accepted and validation.revision == current:
            return ContinuationDecision.SATISFIED
        if self.ready_tasks() or any(t.status == TaskStatus.RUNNING for t in self.tasks.values()):
            return ContinuationDecision.EXECUTABLE_WORK_REMAINS
        pending = [t for t in self.tasks.values() if t.status not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}]
        if not self.tasks or any(t.status in {TaskStatus.PENDING, TaskStatus.WAITING} for t in pending):
            return ContinuationDecision.EXECUTABLE_WORK_REMAINS
        packet = {"original_objective": self.objective.original_request,
                  "current_revision": current,
                  "validation": asdict(validation) if validation else None,
                  "unfinished_tasks": [{"description": t.description, "status": t.status.value,
                                        "reason": t.failure_reason} for t in pending],
                  "instruction": "Return JSON decision EXECUTABLE_WORK_REMAINS or GENUINELY_BLOCKED and reasons."}
        try:
            raw = self._call_model(self.judge_chat, [
                {"role": "system", "content": "Judge continuation from the original objective. Failure of one approach is not a genuine blocker. JSON only."},
                {"role": "user", "content": json.dumps(packet, default=str)}], self.config.default_model,
                responsibility="RECOVERY")
            parsed = json.loads(normalize(raw)); proposed = ContinuationDecision(parsed["decision"])
        except Exception:
            proposed = ContinuationDecision.EXECUTABLE_WORK_REMAINS
        # Guardrail: only terminal blocked/failed/rejected tasks can establish a genuine block.
        terminal_blocks = {TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.REJECTED, TaskStatus.CANCELLED}
        if proposed == ContinuationDecision.GENUINELY_BLOCKED and pending and all(t.status in terminal_blocks for t in pending):
            self.objective.state = "BLOCKED"; self.objective.blocker = "No executable task remains after independent continuation review."
            self._persist(); return proposed
        return ContinuationDecision.EXECUTABLE_WORK_REMAINS

    def _graph_snapshot(self, tasks: dict[str, Task] | None = None) -> list[dict[str, Any]]:
        source = tasks or self.tasks
        return [
            {"task_id": task.task_id, "description": task.description,
             "capability": task.capability.upper(), "status": task.status.value,
             "dependencies": list(task.dependencies),
             "acceptance_conditions": list(task.acceptance_conditions),
             "required_context": list(task.required_context),
             "write_scopes": list(task.authority.write_scopes)}
            for task in source.values()
        ]

    def _block_replanning(self, reason: str) -> bool:
        self.objective.state = "BLOCKED"
        self.objective.blocker = reason
        self._persist()
        self.store.trace("graph_revision_blocked", reason=reason,
                         graph_revision_count=len(self.objective.graph_revisions))
        return False

    @staticmethod
    def _proposal_signature(capability: str, description: str,
                            acceptance: list[str], write_scopes: list[str]) -> str:
        normalized_description = " ".join(description.lower().split())
        return _fingerprint({"capability": capability, "description": normalized_description,
                             "acceptance": sorted(" ".join(item.lower().split())
                                                  for item in acceptance),
                             "write_scopes": sorted(write_scopes)})

    def _revise_graph_from_validation(self, validation: ValidationResult,
                                      planner_chat: Callable[..., str] | None = None) -> bool:
        """Compile one evidence-driven graph extension after rejected validation.

        Validation failure is not attributed to the last writer. The first ambiguous
        post-fix mechanical failure can create only read-only diagnostic work; a later
        Builder requires verified evidence produced by an Investigator.
        """
        with self._lock:
            current_snapshot = snapshot_repository(self.root)
            current_revision = revision_id(current_snapshot)
            if validation.accepted or validation.revision != current_revision:
                return self._block_replanning("replanning requires rejected validation for the exact current revision")
            if len(self.objective.graph_revisions) >= self.config.max_graph_revisions:
                return self._block_replanning("graph revision budget exhausted")
            validation_evidence = next((item for item in reversed(list(self.evidence.values()))
                                        if item.verified and item.kind == EvidenceKind.TEST_RESULT
                                        and isinstance(item.payload, dict)
                                        and item.payload.get("validation_id") == validation.validation_id), None)
            if validation_evidence is None:
                return self._block_replanning("replanning lacks controller-verified validation evidence")
            verified = [item for item in self.evidence.values()
                        if item.verified and item.revision == current_revision]
            files = sorted(current_snapshot)
            packet = {
                "original_objective": self.objective.original_request,
                "success_criteria": self.objective.success_criteria,
                "repository_revision": current_revision,
                "current_graph": self._graph_snapshot(),
                "baseline_diff": repository_diff(self.objective.baseline_snapshot, current_snapshot),
                "repository_files": files,
                "validation": {**asdict(validation),
                               "output": validation.output[:self.config.max_context_chars],
                               "output_truncated": (len(validation.output)
                                                    > self.config.max_context_chars)},
                "validation_evidence_id": validation_evidence.evidence_id,
                "verified_evidence": [asdict(item) for item in verified],
                "limits": {"max_new_tasks": self.config.max_tasks_per_revision,
                           "remaining_graph_revisions": (self.config.max_graph_revisions
                                                         - len(self.objective.graph_revisions))},
            }
            encoded = json.dumps(packet, default=str)
            if len(encoded) > self.config.max_context_chars:
                # Never truncate the triggering validation. Reduce only auxiliary context.
                packet["verified_evidence"] = [asdict(validation_evidence)] + [
                    asdict(item) for item in verified
                    if item.evidence_id != validation_evidence.evidence_id
                ][-12:]
                packet["repository_files"] = files[:200]
            planned_revision = current_revision

        try:
            raw = self._call_model(planner_chat or self.judge_chat, [
                {"role": "system", "content": REVISION_PLANNER_SYSTEM},
                {"role": "user", "content": json.dumps(packet, default=str)},
            ], self.config.default_model, responsibility="RECOVERY")
            parsed = json.loads(normalize(raw))
            if not isinstance(parsed, dict):
                raise ValueError("revision plan must be an object")
        except Exception as exc:
            with self._lock:
                return self._block_replanning(f"graph revision planner failed closed: {exc}")

        with self._lock:
            if revision_id(snapshot_repository(self.root)) != planned_revision:
                return self._block_replanning("repository changed during graph revision planning")
            category = str(parsed.get("category", "")).upper()
            if category not in {"PLAN_INCOMPLETE", "IMPLEMENTATION_DEFECT", "BLOCKED"}:
                return self._block_replanning("revision planner returned an invalid reasoning category")
            reasoning = str(parsed.get("reasoning", "")).strip()
            if not reasoning:
                return self._block_replanning("revision planner omitted reasoning")
            proposed_trigger_ids = [str(item) for item in parsed.get("triggering_evidence_ids", [])]
            if not proposed_trigger_ids:
                return self._block_replanning("revision must cite triggering evidence")
            # Planner-copied IDs are advisory. Retain only exact, current,
            # broker-verified evidence; the controller adds the canonical
            # validation and recent Investigator evidence below.
            trigger_ids = []
            for evidence_id in proposed_trigger_ids:
                evidence = self.evidence.get(evidence_id)
                if (evidence is not None and evidence.verified
                        and evidence.revision == planned_revision
                        and evidence_id not in trigger_ids):
                    trigger_ids.append(evidence_id)
            # The controller owns the validation event and canonically binds it
            # to every revision. Preserve the planner's verified citations, but
            # do not depend on a small model copying this bookkeeping ID from a
            # large evidence packet without error.
            if validation_evidence.evidence_id not in trigger_ids:
                trigger_ids.append(validation_evidence.evidence_id)
            recent_investigator: Task | None = None
            if self.objective.graph_revisions:
                inserted = self.objective.graph_revisions[-1].inserted_task_ids
                recent_investigator = next((self.tasks[task_id] for task_id in inserted
                                            if task_id in self.tasks
                                            and self.tasks[task_id].capability.upper() == "INVESTIGATOR"
                                            and self.tasks[task_id].status == TaskStatus.COMPLETED), None)
            # Canonically carry forward broker-verified evidence from the
            # diagnostic task that this validation follows. This makes the
            # causal handoff durable even if the planner copies only one ID.
            if recent_investigator is not None:
                for evidence_id in recent_investigator.evidence_ids:
                    evidence = self.evidence.get(evidence_id)
                    if (evidence is not None and evidence.verified
                            and evidence.revision == planned_revision
                            and evidence_id not in trigger_ids):
                        trigger_ids.append(evidence_id)
            triggers = [self.evidence.get(item) for item in trigger_ids]
            if any(item is None or not item.verified or item.revision != planned_revision
                   for item in triggers):
                return self._block_replanning("revision cited unverified, missing, or stale evidence")
            evidence_fingerprint = _fingerprint([
                {"kind": item.kind.value, "summary": item.summary,
                 "revision": item.revision,
                 "payload": ({key: value for key, value in item.payload.items()
                              if key != "validation_id"}
                             if isinstance(item.payload, dict) else item.payload)}
                for item in triggers if item is not None
            ])
            if any(item.evidence_fingerprint == evidence_fingerprint
                   for item in self.objective.graph_revisions):
                return self._block_replanning("unchanged evidence cannot rewrite the graph")

            proposals = parsed.get("tasks", [])
            if category == "BLOCKED":
                if proposals:
                    return self._block_replanning("BLOCKED revision cannot also propose tasks")
                return self._block_replanning(reasoning)
            if (not isinstance(proposals, list) or not proposals
                    or len(proposals) > self.config.max_tasks_per_revision):
                return self._block_replanning("revision task list is empty or exceeds its bound")
            # If the planner merely repeats the just-completed Investigator,
            # convert that no-op into the narrow evidence-to-action handoff it
            # failed to express. Exact source scopes must be named in the
            # Investigator's conclusion; regression scopes are existing tests.
            if recent_investigator is not None:
                run = self.worker_runs.get(recent_investigator.assigned_worker_run_id or "")
                conclusion = run.summary if run is not None else ""
                mentioned_sources = sorted(
                    path for path in current_snapshot
                    if path in conclusion and Path(path).suffix == ".py"
                    and not Path(path).name.startswith("test_")
                )
                symbol_sources: set[str] = set()
                for path, source in current_snapshot.items():
                    if Path(path).suffix != ".py" or Path(path).name.startswith("test_"):
                        continue
                    try:
                        tree = ast.parse(source)
                    except (SyntaxError, ValueError):
                        continue
                    definitions = [node.name for node in ast.walk(tree)
                                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                                        ast.ClassDef))]
                    if any(re.search(rf"\b{re.escape(name)}\b", conclusion)
                           for name in definitions):
                        symbol_sources.add(path)
                mentioned_sources = sorted(set(mentioned_sources) | symbol_sources)
                dependency_sources: set[str] = set()
                for path in mentioned_sources:
                    try:
                        tree = ast.parse(current_snapshot[path])
                    except (SyntaxError, ValueError):
                        continue
                    for node in ast.walk(tree):
                        modules: list[str] = []
                        if isinstance(node, ast.Import):
                            modules = [alias.name for alias in node.names]
                        elif isinstance(node, ast.ImportFrom) and node.module:
                            modules = [node.module]
                        for module in modules:
                            candidate = module.replace(".", "/") + ".py"
                            if candidate in current_snapshot:
                                dependency_sources.add(candidate)
                mentioned_sources = sorted(set(mentioned_sources) | dependency_sources)
                regression_files = sorted(
                    path for path in current_snapshot
                    if Path(path).suffix == ".py" and Path(path).name.startswith("test_")
                )
                if mentioned_sources:
                    builder_key = "evidence_bound_repair"
                    regression_required = (
                        "regression" in self.objective.original_request.lower()
                        and bool(regression_files)
                        and self.config.regression_first
                    )
                    repair_dependencies = [recent_investigator.task_id]
                    proposals = []
                    if regression_required:
                        regression_key = "red_phase_regression"
                        proposals.append({
                            "key": regression_key,
                            "description": (
                                "Add a focused regression that demonstrates the completed "
                                "Investigator's failure mode before any source repair."
                            ),
                            "capability": "REGRESSION_DESIGNER",
                            "dependencies": [recent_investigator.task_id],
                            "required_context": sorted(set(mentioned_sources + regression_files)),
                            "write_scopes": regression_files,
                            "acceptance_conditions": [
                                "A focused test-file edit is brokered",
                                "The new regression is demonstrated failing before the repair",
                            ],
                        })
                        repair_dependencies = [regression_key]
                    proposals.append(
                        {
                            "key": builder_key,
                            "description": "Repair only the defect established by the completed Investigator.",
                            "capability": "BUILDER",
                            "dependencies": repair_dependencies,
                            "required_context": sorted(set(mentioned_sources + regression_files)),
                            "write_scopes": mentioned_sources,
                            "acceptance_conditions": ["The full suite passes without weakening the regression"],
                        })
                    if self.config.independent_review:
                        proposals.append({
                            "key": "independent_evidence_review",
                            "description": "Independently review the evidence-bound repair and its regression.",
                            "capability": "REVIEWER",
                            "dependencies": [builder_key],
                            "required_context": sorted(set(mentioned_sources + regression_files)),
                            "write_scopes": [],
                            "acceptance_conditions": ["The full suite and focused regression pass"],
                        })
                    reasoning += (
                        " Controller normalized a repeated diagnosis into a regression-first, "
                        "evidence-scoped repair and independent review."
                    )
            if len(self.tasks) + len(proposals) > self.config.max_queued_workers:
                return self._block_replanning("task graph budget exhausted")

            first_ambiguous_failure = (
                validation.exit_code != 0 and not self.objective.graph_revisions
                and any(task.capability.upper() == "BUILDER" and task.status == TaskStatus.COMPLETED
                        for task in self.tasks.values())
            )
            known_files = set(current_snapshot)
            if first_ambiguous_failure:
                completed_builder = next(
                    task for task in reversed(list(self.tasks.values()))
                    if task.capability.upper() == "BUILDER"
                    and task.status == TaskStatus.COMPLETED
                )
                proposals = [{
                    "key": "controller_residual_investigation",
                    "description": (
                        "Investigate the residual validation failure using repository reads "
                        "and test execution only. Establish its root cause and minimum fix "
                        "surface with exact evidence; do not edit files."
                    ),
                    "capability": "INVESTIGATOR",
                    "dependencies": [completed_builder.task_id],
                    "required_context": sorted(known_files),
                    "write_scopes": [],
                    "acceptance_conditions": [
                        "Return an explicit evidence-backed root cause and minimum fix surface",
                        "Run the failing validation or an equally focused reproducer without editing files",
                    ],
                }]
                reasoning += (
                    " Controller compiled the first ambiguous residual into a mandatory "
                    "read-only investigation before permitting another write."
                )
            keys = [str(item.get("key", "")) for item in proposals if isinstance(item, dict)]
            if len(keys) != len(proposals) or any(not key for key in keys) or len(keys) != len(set(keys)):
                return self._block_replanning("revision task keys must be nonempty and unique")
            existing_signatures = {
                self._proposal_signature(task.capability.upper(), task.description,
                                         task.acceptance_conditions, task.authority.write_scopes)
                for task in self.tasks.values()
            }
            normalized: list[dict[str, Any]] = []
            seen_keys: set[str] = set()
            has_investigator = False
            has_builder = False
            for proposal, key in zip(proposals, keys):
                capability = str(proposal.get("capability", "")).upper()
                if capability not in CAPABILITIES:
                    return self._block_replanning(f"unknown revised capability: {capability}")
                spec = CAPABILITIES[capability]
                description = str(proposal.get("description", "")).strip()
                if not description:
                    return self._block_replanning("revised task description is required")
                acceptance = [str(item) for item in proposal.get("acceptance_conditions", [])]
                acceptance = acceptance or ["Return grounded evidence"]
                write_scopes = [str(item) for item in proposal.get("write_scopes", [])]
                if spec.may_write != bool(write_scopes):
                    return self._block_replanning("BUILDER requires write scopes and read-only tasks forbid them")
                for path in write_scopes:
                    if path not in known_files or path == "." or Path(path).suffix == "":
                        return self._block_replanning("revised write scopes must be existing concrete files")
                    WorkerSession(self.root, Authority(read_scopes=["."], write_scopes=[path]))._path(path, [path])
                required_context = [str(item) for item in proposal.get("required_context", [])]
                if any(path not in known_files for path in required_context):
                    return self._block_replanning("revised task context must name existing files")
                dependencies = [str(item) for item in proposal.get("dependencies", [])]
                allowed_dependencies = set(self.tasks) | seen_keys
                if set(dependencies) - allowed_dependencies:
                    return self._block_replanning("revised dependencies must name existing tasks or earlier local keys")
                # The first residual failure is deliberately treated as ambiguous.
                # Small local models sometimes echo the objective's request for a
                # regression test into a read-only Investigator proposal.  Preserve
                # the model's category, causal reasoning, dependency choice, and
                # evidence citation, but make the capability contract executable:
                # this task diagnoses only and must return an explicit conclusion.
                if first_ambiguous_failure and capability == "INVESTIGATOR":
                    residual_output = validation.output[:2_000]
                    description = (
                        "Investigate the residual validation failure using repository reads "
                        "and test execution only. Establish its root cause and minimum fix "
                        "surface with exact evidence; do not edit files. Do not re-attribute "
                        "the residual to a completed repair unless current evidence proves "
                        "that repair regressed. The following is the current controller "
                        f"validation after the completed repair:\n{residual_output}"
                    )
                    acceptance = [
                        "Return an explicit evidence-backed root cause and minimum fix surface",
                        "Run the failing validation or an equally focused reproducer without editing files",
                    ]
                    # The cause is unknown by definition at this boundary. Do
                    # not let the planner's speculative file guess hide a small
                    # repository file from the read-only diagnostic worker.
                    required_context = sorted(known_files)
                signature = self._proposal_signature(capability, description, acceptance, write_scopes)
                if signature in existing_signatures or any(item["signature"] == signature for item in normalized):
                    return self._block_replanning("duplicate or no-op graph revision rejected")
                has_investigator |= capability == "INVESTIGATOR"
                has_builder |= capability == "BUILDER"
                normalized.append({"key": key, "description": description,
                                   "capability": capability, "acceptance": acceptance,
                                   "write_scopes": write_scopes,
                                   "required_context": required_context,
                                   "dependencies": dependencies, "signature": signature})
                seen_keys.add(key)
            if first_ambiguous_failure and (not has_investigator or has_builder):
                return self._block_replanning(
                    "first ambiguous post-fix failure requires new investigation, not a Builder retry")
            if has_builder:
                investigator_evidence = {
                    item.evidence_id for item in triggers if item is not None
                    and item.task_id in self.tasks
                    and self.tasks[item.task_id].capability.upper() == "INVESTIGATOR"
                }
                if not investigator_evidence:
                    return self._block_replanning("new Builder lacks cited verified Investigator evidence")

            before_graph = self._graph_snapshot()
            created_by_key: dict[str, Task] = {}
            prospective = dict(self.tasks)
            for item in normalized:
                dependencies = [created_by_key[value].task_id if value in created_by_key else value
                                for value in item["dependencies"]]
                spec = CAPABILITIES[item["capability"]]
                read_scopes = (["."] if item["capability"] == "INVESTIGATOR"
                               else sorted(set(item["required_context"] + item["write_scopes"])) or ["."])
                authority = Authority(list(spec.allowed_tools), read_scopes, item["write_scopes"])
                task = Task(stable_id("task"), self.objective.objective_id,
                            item["description"], item["capability"].lower(), item["acceptance"],
                            authority, dependencies, item["required_context"])
                created_by_key[item["key"]] = task
                prospective[task.task_id] = task
            # Validate the entire prospective graph before the first durable mutation.
            original_tasks = self.tasks
            try:
                self.tasks = prospective
                self.validate_graph()
            finally:
                self.tasks = original_tasks
            for task in created_by_key.values():
                self.tasks[task.task_id] = task
                self.objective.task_ids.append(task.task_id)
            after_graph = self._graph_snapshot()
            graph_revision = GraphRevision(
                stable_id("graph_revision"), planned_revision, validation.validation_id,
                category, reasoning, trigger_ids, evidence_fingerprint,
                before_graph, after_graph, [task.task_id for task in created_by_key.values()],
                {task.task_id: list(task.dependencies) for task in created_by_key.values()},
            )
            self.objective.graph_revisions.append(graph_revision)
            self.objective.validation = None
            self.objective.state = "ACTIVE"
            self.objective.blocker = ""
            self._persist()
            self.store.trace("graph_revised", **asdict(graph_revision))
            return True

    def _schedule_validation_revision(self, validation: ValidationResult) -> bool:
        """Compatibility wrapper for evidence-driven graph extension."""
        return self._revise_graph_from_validation(validation)

    def _schedule_atomic_residual(self, validation: ValidationResult) -> bool:
        """Turn one exact failed oracle packet into the next eight bounded obligations."""
        if validation.accepted or not self.config.responsibility_call_budgets:
            return False
        state = self.objective.task_state
        public_residual = self._public_oracle_residual()
        if not public_residual.get("smallest_counterexample"):
            return self._block_replanning(
                "deterministic acceptance oracle failed without an observable behavioral "
                "counterexample; a source-repair cycle would be unsupported")
        feedback = json.dumps(public_residual, sort_keys=True, default=str)
        snapshot = snapshot_repository(self.root)
        source_files = sorted(
            path for path in snapshot
            if Path(path).suffix == ".py" and not Path(path).name.startswith("test_")
        )
        test_files = sorted(
            path for path in snapshot
            if Path(path).suffix == ".py" and Path(path).name.startswith("test_")
        )
        if len(self.tasks) + 8 > self.config.max_queued_workers:
            return self._block_replanning(
                f"atomic residual remains after {state.atomic_cycle} cycles: {feedback}")
        state.reset_for_residual(feedback)
        tasks = self.add_atomic_cycle(source_files, test_files)
        tasks[0].expected_output = (
            "Reproduce only this exact failed acceptance-oracle requirement: " + feedback
        )
        self.objective.validation = None
        self.objective.state = "ACTIVE"
        self._persist()
        self.store.trace(
            "atomic_residual_scheduled", cycle=state.atomic_cycle,
            oracle_feedback=feedback, task_ids=[task.task_id for task in tasks],
        )
        return True

    def _retry_budget_available(self, task: Task) -> bool:
        if not self.config.responsibility_call_budgets:
            return task.retry_count <= self.config.max_worker_retries
        capability = task.capability.upper()
        used = self._responsibility_call_counts.get(capability, 0)
        allocated = self._responsibility_allowance(capability)
        recovery_used = self._responsibility_call_counts.get("RECOVERY", 0)
        return (self._model_call_count < self.config.max_inference_calls
                and (used < allocated
                     or (self._recovery_reserve_unlocked()
                          and recovery_used < self.config.recovery_reserve_calls)))

    def run_until_stable(self) -> ContinuationDecision:
        """Continue ready work; never equate worker completion with objective success."""
        if not self.tasks:
            self.plan_tasks()
        while True:

            current = revision_id(snapshot_repository(self.root))
            validation = self.objective.validation
            terminal_success = ({TaskStatus.COMPLETED, TaskStatus.CANCELLED}
                                if self.config.responsibility_call_budgets
                                else {TaskStatus.COMPLETED})
            if (self.tasks and all(task.status in terminal_success for task in self.tasks.values())
                    and (not validation or validation.revision != current or not validation.accepted)):
                validation = self.validate_objective()
                if validation.accepted:
                    return ContinuationDecision.SATISFIED
                if self.config.responsibility_call_budgets:
                    if self._schedule_atomic_residual(validation):
                        continue
                    return ContinuationDecision.GENUINELY_BLOCKED
                if self._schedule_validation_revision(validation):
                    continue
                if self.objective.state == "BLOCKED":
                    return ContinuationDecision.GENUINELY_BLOCKED
            ready = self.ready_tasks()
            if self.config.responsibility_call_budgets and ready:
                runnable = []
                for task in ready:
                    if self._retry_budget_available(task):
                        runnable.append(task)
                    else:
                        task.status = TaskStatus.FAILED
                        task.failure_reason = (
                            "NONRETRYABLE: responsibility and recovery inference budgets exhausted"
                        )
                if len(runnable) != len(ready):
                    self._persist()
                ready = runnable
            if not ready:
                retryable = [task for task in self.tasks.values()
                             if task.status in {TaskStatus.FAILED, TaskStatus.BLOCKED}
                             and self._retry_budget_available(task)
                             and "NONRETRYABLE:" not in task.failure_reason]
                if retryable:
                    for task in retryable:
                        prior_failure = task.failure_reason
                        if self.config.responsibility_call_budgets:
                            agent = self.atomic_agents.get(task.capability.upper())
                            if agent is None:
                                raise RuntimeError(
                                    f"atomic retry has no concrete agent: {task.capability}")
                            correction = agent.retry_feedback(self, task)
                        elif task.capability.upper() == "REGRESSION_DESIGNER":
                            correction = (
                                "Edit one assigned test file, run pytest and capture a nonzero exit, "
                                "then finish. Do not inspect or edit source."
                            )
                        elif task.capability.upper() in {"BUILDER", "REPAIR"}:
                            correction = (
                                "Edit one assigned source file, run pytest once, then finish. "
                                "Do not edit the regression."
                            )
                        elif task.capability.upper() == "REVIEWER":
                            correction = (
                                "Run pytest and report only mechanically supported findings; "
                                "do not claim a regression exists without changed-test provenance."
                            )
                        else:
                            correction = "Use the minimum successful tools needed by the task contract, then finish."
                        task.expected_output = (
                            f"Exact failed-gate retry attempt {task.retry_count + 1}: {correction} "
                            f"Prior failure: {prior_failure}"
                        )
                        self.retry_task(task.task_id)
                    continue
                return self.continuation_judgment()
            self.run_ready()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run or resume the bounded Hive executive")
    parser.add_argument("objective", nargs="?")
    parser.add_argument("--root", default=os.getcwd())
    parser.add_argument("--resume", metavar="OBJECTIVE_ID")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.resume and not args.objective:
        parser.error("objective is required unless --resume is used")
    executive = (HiveExecutive.resume(args.root, args.resume) if args.resume
                 else HiveExecutive(args.root, args.objective))
    if args.plan_only:
        if not executive.tasks:
            executive.plan_tasks()
        decision = executive.continuation_judgment()
    else:
        decision = executive.run_until_stable()
    print(json.dumps({"objective_id": executive.objective.objective_id,
                      "continuation": decision.value,
                      "tasks": {task.task_id: task.status.value
                                for task in executive.tasks.values()}}, indent=2))
    return 0 if decision == ContinuationDecision.SATISFIED or args.plan_only else 2


if __name__ == "__main__":
    raise SystemExit(main())
