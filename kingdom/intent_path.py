from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .arena import ArenaExecution, ArenaRegistry, ToolRequest
from .core import HashChainLedger, Seed


_TOOL_CONTRACTS = {
    "repo_read": "operation='read', payload={'path': <repo-relative file>, 'max_chars': optional int}",
    "repo_search": "operation='search', payload={'query': <text>, 'suffixes': optional list, 'limit': optional int}",
    "pytest": "operation='run', payload={'selectors': ['tests/file.py::optional_test']}",
    "simulation": "operation='run', payload={'function': <pre-registered name>, 'args': [], 'kwargs': {}}",
}


@dataclass(frozen=True)
class IntentCapsule:
    """Immutable copy of what the operator asked for before decomposition begins."""

    original_request: str
    context: str
    goal: str
    fingerprint: str

    @classmethod
    def capture(cls, seed: Seed) -> "IntentCapsule":
        payload = {
            "original_request": seed.text,
            "context": seed.context,
            "goal": seed.goal,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return cls(
            original_request=seed.text,
            context=seed.context,
            goal=seed.goal,
            fingerprint=hashlib.sha256(encoded).hexdigest(),
        )


@dataclass(frozen=True)
class IntentStep:
    step_id: str
    description: str
    tool: str
    operation: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    purpose: str = ""
    success_criterion: str = ""

    def request(self) -> ToolRequest:
        return ToolRequest(
            tool=self.tool,
            operation=self.operation,
            payload=dict(self.payload),
            purpose=self.purpose or self.description,
            branch_id="intent-path",
            request_id=f"intent-{self.step_id}",
        ).normalized()


@dataclass(frozen=True)
class IntentStepResult:
    step: IntentStep
    execution: ArenaExecution
    status: str
    reason: str

    def __post_init__(self) -> None:
        if self.status not in {"passed", "failed", "incomplete"}:
            raise ValueError(f"unsupported intent step status: {self.status}")


@dataclass(frozen=True)
class IntentWalkReport:
    capsule: IntentCapsule
    status: str
    reason: str
    steps: tuple[IntentStepResult, ...]
    semantic_verdict: str
    semantic_reason: str
    unresolved_frontier: tuple[str, ...] = ()
    reopened_target_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"passed", "failed", "incomplete"}:
            raise ValueError(f"unsupported intent walk status: {self.status}")
        if self.semantic_verdict not in {"pass", "fail", "incomplete"}:
            raise ValueError(f"unsupported semantic verdict: {self.semantic_verdict}")

    @property
    def passed(self) -> bool:
        return self.status == "passed"


class IntentPathPlanner(Protocol):
    def plan(
        self,
        capsule: IntentCapsule,
        artifact_summary: Mapping[str, Any],
        available_tools: Sequence[str],
    ) -> Sequence[IntentStep]: ...


class IntentPathJudge(Protocol):
    def judge(
        self,
        capsule: IntentCapsule,
        artifact_summary: Mapping[str, Any],
        step_results: Sequence[IntentStepResult],
    ) -> tuple[str, str]: ...


class HiveIntentPathPlanner:
    """Fresh planner that converts original intent into an ordered end-to-end walk.

    It receives the original intent and public finished-state summary, not the
    branch reasoning that produced the candidate. This reduces pressure to
    rationalize Kingdom's own construction history.
    """

    def __init__(self, ask: Callable[..., str] | None = None, *, max_steps: int = 8):
        if ask is None:
            from hive_llm import ask_hive

            ask = ask_hive
        self.ask = ask
        self.max_steps = max_steps

    @staticmethod
    def _parse(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
        return json.loads(cleaned)

    def plan(
        self,
        capsule: IntentCapsule,
        artifact_summary: Mapping[str, Any],
        available_tools: Sequence[str],
    ) -> Sequence[IntentStep]:
        contracts = {
            name: _TOOL_CONTRACTS.get(name, "host-defined operation/payload contract")
            for name in available_tools
        }
        prompt = (
            "KINGDOM / CRITICAL INTENT PATH PLANNER\n\n"
            "You are a fresh end-to-end verifier. Do not defend the construction process. "
            "Walk the ORIGINAL operator intent through the finished candidate the way a real user, request, "
            "or artifact would travel through it. The path itself is the product.\n\n"
            f"ORIGINAL REQUEST: {capsule.original_request}\n"
            f"ORIGINAL CONTEXT: {capsule.context}\n"
            f"ORIGINAL GOAL: {capsule.goal}\n"
            f"FINISHED-STATE SUMMARY: {json.dumps(artifact_summary, default=str)}\n"
            f"AVAILABLE ARENA TOOLS: {json.dumps(contracts)}\n\n"
            "Create an ordered critical path of concrete checks. Prefer checks that exercise composition/end-to-end "
            "behavior over isolated implementation details. Every step must state what success would mean. "
            "If a critical step cannot be verified with an available tool, STILL name the missing capability/tool; "
            "Arena must return it as unavailable rather than silently skipping it. "
            f"Return 1-{self.max_steps} steps as JSON only: {{'steps': [{{'id': '1', 'description': '...', "
            "'tool': '...', 'operation': '...', 'payload': {...}, 'purpose': '...', "
            "'success_criterion': '...'}}]}}."
        )
        payload = self._parse(self.ask(prompt, role="planner"))
        steps: list[IntentStep] = []
        for index, item in enumerate(payload.get("steps", [])[: self.max_steps], 1):
            if not isinstance(item, dict):
                continue
            description = str(item.get("description") or "").strip()
            tool = str(item.get("tool") or "").strip()
            operation = str(item.get("operation") or "").strip()
            raw_payload = item.get("payload")
            if not description or not tool or not operation or not isinstance(raw_payload, dict):
                continue
            step_id = str(item.get("id") or index).strip() or str(index)
            steps.append(
                IntentStep(
                    step_id=step_id,
                    description=description,
                    tool=tool,
                    operation=operation,
                    payload=dict(raw_payload),
                    purpose=str(item.get("purpose") or description),
                    success_criterion=str(item.get("success_criterion") or "").strip(),
                )
            )
        return tuple(steps)


class HiveIntentPathJudge:
    """Independent semantic judge for whether the observed path still matches intent."""

    def __init__(self, ask: Callable[..., str] | None = None):
        if ask is None:
            from hive_llm import ask_hive

            ask = ask_hive
        self.ask = ask

    @staticmethod
    def _parse(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
        return json.loads(cleaned)

    def judge(
        self,
        capsule: IntentCapsule,
        artifact_summary: Mapping[str, Any],
        step_results: Sequence[IntentStepResult],
    ) -> tuple[str, str]:
        observations = [
            {
                "step": result.step.description,
                "success_criterion": result.step.success_criterion,
                "arena_status": result.execution.observation.status,
                "claim": result.execution.observation.claim,
                "detail": result.execution.observation.detail,
                "source": result.execution.observation.source,
            }
            for result in step_results
        ]
        prompt = (
            "KINGDOM / CRITICAL INTENT PATH JUDGE\n\n"
            "You did not build this candidate. Judge whether a person who gave the ORIGINAL request would recognize "
            "the observed end-to-end result as satisfying what they asked for. Do not reward internal effort, branch "
            "count, architecture elegance, or green component tests unless they establish the requested outcome. "
            "A missing observation is not a pass.\n\n"
            f"ORIGINAL REQUEST: {capsule.original_request}\n"
            f"ORIGINAL CONTEXT: {capsule.context}\n"
            f"ORIGINAL GOAL: {capsule.goal}\n"
            f"PUBLIC FINISHED-STATE SUMMARY: {json.dumps(artifact_summary, default=str)}\n"
            f"CRITICAL-PATH OBSERVATIONS: {json.dumps(observations, default=str)}\n\n"
            "Return JSON only: {'verdict': 'pass'|'fail'|'incomplete', 'reason': '...'}. "
            "Use fail when observed behavior contradicts intent; incomplete when evidence cannot establish the path; "
            "pass only when the observed path supports the original intent end-to-end."
        )
        payload = self._parse(self.ask(prompt, role="reflector"))
        verdict = str(payload.get("verdict") or "incomplete").lower()
        if verdict not in {"pass", "fail", "incomplete"}:
            verdict = "incomplete"
        return verdict, str(payload.get("reason") or "semantic judge returned no reason")


def public_artifact_summary(run: Any) -> dict[str, Any]:
    """Expose finished state without branch-by-branch reasoning traces."""

    structure = run.structure
    packet = run.packet
    graph = run.graph
    status_counts: dict[str, int] = {}
    for target in graph.targets.values():
        status_counts[target.status] = status_counts.get(target.status, 0) + 1
    actionable = [
        target.statement
        for target in graph.frontier()
        if target.kind not in {"goal", "branch"}
        and target.status not in {"verified", "rejected"}
    ]
    observations = [
        {
            "status": execution.observation.status,
            "claim": execution.observation.claim,
            "source": execution.observation.source,
        }
        for execution in run.arena_executions[-20:]
    ]
    return {
        "structure": {
            "invariants": list(structure.invariants),
            "disagreements": list(structure.disagreements),
            "hinge_assumptions": list(structure.hinge_assumptions),
            "causal_links": list(structure.causal_links),
            "anomalies": list(structure.anomalies),
            "unknowns": list(structure.unknowns),
        },
        "operator_packet": {
            "title": packet.title,
            "orientation": packet.orientation,
            "load_bearing_insights": list(packet.load_bearing_insights),
            "uncertainty": list(packet.uncertainty),
            "next_moves": list(packet.next_moves),
        },
        "construction": {
            "status_counts": status_counts,
            "actionable_frontier": actionable,
            "missing_capabilities": [
                target.capability for target in run.missing_capabilities
            ],
        },
        "recent_reality_contact": observations,
    }


class IntentPathGate:
    """Terminal critical-path verification and intent-drift gate."""

    def __init__(
        self,
        planner: IntentPathPlanner,
        judge: IntentPathJudge,
    ):
        self.planner = planner
        self.judge = judge

    @staticmethod
    def _step_status(execution: ArenaExecution) -> tuple[str, str]:
        observation = execution.observation
        if observation.status == "verified":
            return "passed", observation.claim
        if observation.status == "failed":
            return "failed", observation.claim
        return "incomplete", observation.claim

    def walk(self, run: Any, arena: ArenaRegistry) -> IntentWalkReport:
        capsule = IntentCapsule.capture(run.base_run.seed)
        summary = public_artifact_summary(run)
        planned = tuple(self.planner.plan(capsule, summary, arena.tool_names))
        results: list[IntentStepResult] = []
        for step in planned:
            execution = arena.execute(step.request())
            status, reason = self._step_status(execution)
            results.append(IntentStepResult(step, execution, status, reason))

        semantic_verdict, semantic_reason = self.judge(capsule, summary, tuple(results))
        actionable_frontier = tuple(summary["construction"]["actionable_frontier"])

        if not results:
            status = "incomplete"
            reason = "No critical-path steps were produced; original intent was not walked."
        elif any(result.status == "failed" for result in results):
            status = "failed"
            reason = "At least one end-to-end critical-path step failed in Arena."
        elif any(result.status == "incomplete" for result in results):
            status = "incomplete"
            reason = "At least one critical-path verification capability or observation is unavailable."
        elif actionable_frontier:
            status = "incomplete"
            reason = "Construction still has unresolved executable/blocking frontier work."
        elif semantic_verdict == "fail":
            status = "failed"
            reason = semantic_reason
        elif semantic_verdict == "incomplete":
            status = "incomplete"
            reason = semantic_reason
        else:
            status = "passed"
            reason = semantic_reason

        return IntentWalkReport(
            capsule=capsule,
            status=status,
            reason=reason,
            steps=tuple(results),
            semantic_verdict=semantic_verdict,
            semantic_reason=semantic_reason,
            unresolved_frontier=actionable_frontier,
        )

    def walk_and_reopen(self, run: Any, arena: ArenaRegistry) -> IntentWalkReport:
        report = self.walk(run, arena)
        graph = run.graph
        roots = [
            target
            for target in graph.targets.values()
            if target.kind == "goal" and target.parent_id is None
        ]
        if not roots:
            return report
        root = sorted(roots, key=lambda target: target.target_id)[0]

        if report.passed:
            graph.set_status(root.target_id, "verified")
            return report

        graph.set_status(root.target_id, "blocked")
        reopened: list[str] = []
        had_step_problem = False
        for result in report.steps:
            if result.status == "passed":
                continue
            had_step_problem = True
            repair = graph.add(
                f"Critical path repair: {result.step.description}",
                kind="experiment",
                parent_id=root.target_id,
                status="blocked",
                reason=(
                    f"Success criterion: {result.step.success_criterion or 'unspecified'}. "
                    f"Observed: {result.reason}"
                ),
                origin_branch_id="intent-path",
            )
            reopened.append(repair.target_id)
            missing = result.execution.missing
            if missing is not None:
                capability = graph.add(
                    (
                        f"Build or acquire critical-path capability '{missing.name}' able to perform "
                        f"'{missing.operation}' for: {missing.purpose or result.step.description}"
                    ),
                    kind="capability",
                    parent_id=repair.target_id,
                    status="blocked",
                    capability=missing.name,
                    reason=missing.purpose or result.step.description,
                    origin_branch_id="intent-path",
                )
                reopened.append(capability.target_id)

        if report.semantic_verdict != "pass" and not had_step_problem:
            semantic = graph.add(
                f"Resolve original-intent mismatch: {report.semantic_reason}",
                kind="experiment",
                parent_id=root.target_id,
                status="blocked",
                reason=(
                    "All executable critical-path checks completed, but the independent semantic judge did not "
                    "recognize the finished result as satisfying the original intent."
                ),
                origin_branch_id="intent-path",
            )
            reopened.append(semantic.target_id)

        return replace(report, reopened_target_ids=tuple(reopened))


@dataclass(frozen=True)
class IntentPathRecord:
    run_id: str
    path: str
    sha256: str
    status: str


class IntentPathRecorder:
    """Persist each critical-path walk as an immutable ledger-anchored artifact."""

    def __init__(
        self,
        root: str | Path = ".hive/kingdom/intent_paths",
        *,
        ledger: HashChainLedger,
    ):
        self.root = Path(root)
        self.ledger = ledger

    def persist(self, run_id: str, report: IntentWalkReport) -> IntentPathRecord:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "run_id": run_id,
            "report": asdict(report),
        }
        encoded = (json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        destination = self.root / f"{run_id}-{digest[:12]}-intent-path.json"
        if not destination.exists():
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=str(self.root),
            )
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(encoded)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, destination)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)

        record = IntentPathRecord(run_id, str(destination), digest, report.status)
        self.ledger.append(
            "intent_path_walk",
            {
                "run_id": run_id,
                "intent_path_file": record.path,
                "sha256": record.sha256,
                "status": report.status,
                "intent_fingerprint": report.capsule.fingerprint,
                "step_count": len(report.steps),
                "reopened_target_count": len(report.reopened_target_ids),
            },
        )
        return record

    @staticmethod
    def verify(record: IntentPathRecord) -> bool:
        path = Path(record.path)
        if not path.is_file():
            return False
        return hashlib.sha256(path.read_bytes()).hexdigest() == record.sha256
