from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .core import BranchResult, BranchSpec, Evidence, Seed


@dataclass(frozen=True)
class ToolRequest:
    tool: str
    operation: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    purpose: str = ""
    branch_id: str = ""
    request_id: str = ""

    def normalized(self) -> "ToolRequest":
        request_id = self.request_id.strip() or uuid.uuid4().hex[:12]
        return ToolRequest(
            tool=self.tool.strip(),
            operation=self.operation.strip(),
            payload=dict(self.payload),
            purpose=self.purpose.strip(),
            branch_id=self.branch_id.strip(),
            request_id=request_id,
        )


@dataclass(frozen=True)
class ArenaObservation:
    request_id: str
    branch_id: str
    tool: str
    operation: str
    status: str
    claim: str
    detail: str = ""
    source: str = ""
    confidence: float = 1.0
    artifacts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"verified", "failed", "unavailable"}:
            raise ValueError(f"unsupported arena status: {self.status}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

    def as_evidence(self) -> Evidence:
        if self.status == "verified":
            stance = "observe"
        elif self.status == "failed":
            stance = "contradict"
        else:
            stance = "uncertain"
        return Evidence(
            claim=self.claim,
            stance=stance,
            confidence=self.confidence,
            source=self.source or f"arena:{self.tool}:{self.operation}",
            detail=self.detail,
        )


@dataclass(frozen=True)
class MissingCapability:
    name: str
    operation: str
    purpose: str
    branch_id: str
    request_id: str


@dataclass(frozen=True)
class ArenaExecution:
    observation: ArenaObservation
    missing: MissingCapability | None = None


class ArenaTool(Protocol):
    name: str

    def execute(self, request: ToolRequest) -> ArenaObservation: ...


class ArenaRegistry:
    """Explicit registry for reality-contact adapters.

    Arena never silently substitutes one tool for another. If a requested
    capability does not exist, the absence is returned as a first-class object
    so the construction layer can turn it into another build target.
    """

    def __init__(self, tools: Sequence[ArenaTool] = ()):
        self._tools: dict[str, ArenaTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: ArenaTool) -> None:
        name = str(tool.name).strip()
        if not name:
            raise ValueError("tool name cannot be empty")
        if name in self._tools:
            raise ValueError(f"arena tool already registered: {name}")
        self._tools[name] = tool

    @property
    def tool_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def execute(self, raw: ToolRequest) -> ArenaExecution:
        request = raw.normalized()
        tool = self._tools.get(request.tool)
        if tool is None:
            observation = ArenaObservation(
                request_id=request.request_id,
                branch_id=request.branch_id,
                tool=request.tool,
                operation=request.operation,
                status="unavailable",
                claim=f"Required capability '{request.tool}' is unavailable.",
                detail=request.purpose,
                source="arena:registry",
                confidence=1.0,
            )
            return ArenaExecution(
                observation=observation,
                missing=MissingCapability(
                    name=request.tool,
                    operation=request.operation,
                    purpose=request.purpose,
                    branch_id=request.branch_id,
                    request_id=request.request_id,
                ),
            )

        try:
            observation = tool.execute(request)
        except Exception as exc:  # adapters must fail closed into evidence
            observation = ArenaObservation(
                request_id=request.request_id,
                branch_id=request.branch_id,
                tool=request.tool,
                operation=request.operation,
                status="failed",
                claim=f"Arena operation {request.tool}.{request.operation} failed.",
                detail=f"{type(exc).__name__}: {exc}",
                source=f"arena:{request.tool}",
                confidence=1.0,
            )
        return ArenaExecution(observation=observation)

    def execute_many(self, requests: Sequence[ToolRequest]) -> tuple[ArenaExecution, ...]:
        return tuple(self.execute(request) for request in requests)


class RepositoryReadTool:
    name = "repo_read"

    def __init__(self, root: str | Path = "."):
        self.root = Path(root).resolve()

    def _resolve(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError("path escapes repository root")
        return candidate

    def execute(self, request: ToolRequest) -> ArenaObservation:
        if request.operation != "read":
            raise ValueError("repo_read supports only operation='read'")
        path = self._resolve(str(request.payload.get("path") or ""))
        if not path.is_file():
            raise FileNotFoundError(path)
        text = path.read_text(encoding="utf-8")
        max_chars = int(request.payload.get("max_chars", 12000))
        clipped = text[: max(1, max_chars)]
        return ArenaObservation(
            request_id=request.request_id,
            branch_id=request.branch_id,
            tool=self.name,
            operation=request.operation,
            status="verified",
            claim=f"Read repository file {path.relative_to(self.root).as_posix()}.",
            detail=clipped,
            source=f"repo:{path.relative_to(self.root).as_posix()}",
            confidence=1.0,
        )


class RepositorySearchTool:
    name = "repo_search"

    def __init__(self, root: str | Path = "."):
        self.root = Path(root).resolve()

    def execute(self, request: ToolRequest) -> ArenaObservation:
        if request.operation != "search":
            raise ValueError("repo_search supports only operation='search'")
        needle = str(request.payload.get("query") or "").strip()
        if not needle:
            raise ValueError("query cannot be empty")
        suffixes = tuple(request.payload.get("suffixes") or (".py", ".md", ".json", ".yml", ".yaml"))
        matches: list[str] = []
        limit = max(1, int(request.payload.get("limit", 25)))
        for path in sorted(self.root.rglob("*")):
            if len(matches) >= limit:
                break
            if not path.is_file() or (suffixes and path.suffix not in suffixes):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for line_no, line in enumerate(text.splitlines(), 1):
                if needle.lower() in line.lower():
                    rel = path.relative_to(self.root).as_posix()
                    matches.append(f"{rel}:{line_no}: {line.strip()[:240]}")
                    if len(matches) >= limit:
                        break
        return ArenaObservation(
            request_id=request.request_id,
            branch_id=request.branch_id,
            tool=self.name,
            operation=request.operation,
            status="verified",
            claim=f"Repository search for {needle!r} produced {len(matches)} match(es).",
            detail="\n".join(matches),
            source="repo:search",
            confidence=1.0,
        )


class SimulationTool:
    """Run named, pre-registered deterministic simulations/functions.

    This deliberately does not expose arbitrary eval/subprocess execution.
    Higher-risk executors can be added later as separately sandboxed adapters.
    """

    name = "simulation"

    def __init__(self, functions: Mapping[str, Callable[..., Any]] | None = None):
        self.functions = dict(functions or {})

    def register(self, name: str, function: Callable[..., Any]) -> None:
        self.functions[name] = function

    def execute(self, request: ToolRequest) -> ArenaObservation:
        if request.operation != "run":
            raise ValueError("simulation supports only operation='run'")
        function_name = str(request.payload.get("function") or "")
        function = self.functions.get(function_name)
        if function is None:
            raise KeyError(f"unknown simulation function {function_name!r}")
        args = list(request.payload.get("args") or [])
        kwargs = dict(request.payload.get("kwargs") or {})
        result = function(*args, **kwargs)
        return ArenaObservation(
            request_id=request.request_id,
            branch_id=request.branch_id,
            tool=self.name,
            operation=request.operation,
            status="verified",
            claim=f"Simulation {function_name!r} executed successfully.",
            detail=json.dumps(result, sort_keys=True, default=str),
            source=f"simulation:{function_name}",
            confidence=1.0,
        )


class ArenaPlanner(Protocol):
    def plan(
        self,
        seed: Seed,
        branch: BranchSpec,
        result: BranchResult,
        available_tools: Sequence[str],
    ) -> Sequence[ToolRequest]: ...


class HiveArenaPlanner:
    """Ask Hive to convert branch uncertainty into explicit reality-contact requests."""

    def __init__(self, ask: Callable[..., str] | None = None, *, max_requests: int = 3):
        if ask is None:
            from hive_llm import ask_hive

            ask = ask_hive
        self.ask = ask
        self.max_requests = max_requests

    @staticmethod
    def _parse(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lstrip().startswith("json"):
                cleaned = cleaned.lstrip()[4:].lstrip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
        return json.loads(cleaned)

    def plan(
        self,
        seed: Seed,
        branch: BranchSpec,
        result: BranchResult,
        available_tools: Sequence[str],
    ) -> Sequence[ToolRequest]:
        prompt = (
            "KINGDOM / ARENA PLANNING\n\n"
            f"Seed: {seed.text}\nBranch: {branch.question}\n"
            f"Findings: {list(result.findings)}\nUncertainties: {list(result.uncertainties)}\n"
            f"Available tools: {list(available_tools)}\n\n"
            "Request only operations that would materially verify, falsify, or constrain this branch. "
            "If the required capability is not available, still request it by a concise capability name; "
            "the construction system will treat that absence as a build target. "
            f"Return at most {self.max_requests} requests as JSON {{'requests': [...]}}. "
            "Each request: tool, operation, payload (object), purpose. JSON only."
        )
        payload = self._parse(self.ask(prompt, role="planner"))
        requests: list[ToolRequest] = []
        for item in payload.get("requests", [])[: self.max_requests]:
            if not isinstance(item, dict):
                continue
            requests.append(
                ToolRequest(
                    tool=str(item.get("tool") or ""),
                    operation=str(item.get("operation") or ""),
                    payload=dict(item.get("payload") or {}),
                    purpose=str(item.get("purpose") or ""),
                    branch_id=branch.branch_id,
                )
            )
        return tuple(requests)
