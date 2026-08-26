from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from .arena import ArenaObservation, ArenaRegistry, ToolRequest


_SAFE_CALLS = {
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "float",
    "int",
    "len",
    "list",
    "max",
    "min",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
}

_ALLOWED_AST = (
    ast.Module,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Return,
    ast.Assign,
    ast.AnnAssign,
    ast.If,
    ast.IfExp,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.Dict,
    ast.List,
    ast.Tuple,
    ast.Set,
    ast.Subscript,
    ast.Slice,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.comprehension,
    ast.Call,
    ast.keyword,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.Pass,
    ast.Expr,
    ast.operator,
    ast.unaryop,
    ast.boolop,
    ast.cmpop,
    ast.expr_context,
)


@dataclass(frozen=True)
class CapabilityCase:
    payload: Mapping[str, Any]
    expected: Any


@dataclass(frozen=True)
class CapabilityCandidate:
    capability: str
    operation: str
    source: str
    cases: tuple[CapabilityCase, ...]
    entrypoint: str = "execute"

    def fingerprint(self) -> str:
        body = {
            "capability": self.capability,
            "operation": self.operation,
            "source": self.source,
            "entrypoint": self.entrypoint,
            "cases": [
                {"payload": dict(case.payload), "expected": case.expected}
                for case in self.cases
            ],
        }
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CandidateValidation:
    passed: bool
    policy_passed: bool
    regression_passed: bool
    detail: str = ""
    regression_report: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ForgeAttempt:
    target_id: str
    capability: str
    operation: str
    status: str
    candidate_fingerprint: str = ""
    detail: str = ""
    registered: bool = False
    validation: CandidateValidation | None = None

    def __post_init__(self) -> None:
        if self.status not in {"accepted", "rejected", "unavailable"}:
            raise ValueError(f"unsupported forge status: {self.status}")


class CapabilityAuthor(Protocol):
    def author(self, target: Any, request: ToolRequest) -> CapabilityCandidate | None: ...


class CapabilityOracle(Protocol):
    def cases(
        self,
        target: Any,
        request: ToolRequest,
        candidate: CapabilityCandidate,
    ) -> Sequence[CapabilityCase]: ...


class CandidatePolicyError(ValueError):
    pass


class HiveCapabilityAuthor:
    """Ask Hive's coding role for a tiny pure-function implementation proposal."""

    def __init__(self, ask: Callable[..., str] | None = None, *, max_cases: int = 8):
        if ask is None:
            from hive_llm import ask_hive

            ask = ask_hive
        self.ask = ask
        self.max_cases = max_cases

    @staticmethod
    def _parse(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
        return json.loads(cleaned)

    def author(self, target: Any, request: ToolRequest) -> CapabilityCandidate | None:
        prompt = (
            "KINGDOM / CAPABILITY FORGE AUTHOR\n\n"
            f"Missing capability: {request.tool}\nOperation: {request.operation}\n"
            f"Purpose: {request.purpose}\nBuild target: {getattr(target, 'statement', '')}\n"
            f"Example payload from blocked request: {json.dumps(dict(request.payload), default=str)}\n\n"
            "Propose the smallest PURE deterministic Python capability that can satisfy this operation. "
            "The source MUST contain exactly one top-level function named execute(payload). "
            "No imports, classes, decorators, attributes, file/network/process access, mutation of the input, "
            "or calls except simple builtins such as len/sum/min/max/sorted/abs/round and primitive constructors. "
            "Use payload['key'] subscripts rather than payload.get(). Return JSON-serializable data. "
            f"Provide 1-{self.max_cases} author examples for development. These are NOT the acceptance oracle. "
            "If this capability cannot honestly be represented as such a pure function, return {\"buildable\": false}. "
            "Otherwise return JSON only: {\"buildable\": true, \"source\": \"...\", "
            "\"cases\": [{\"payload\": {...}, \"expected\": ...}]}."
        )
        payload = self._parse(self.ask(prompt, role="coder"))
        if not payload.get("buildable"):
            return None
        cases: list[CapabilityCase] = []
        for item in payload.get("cases", [])[: self.max_cases]:
            if not isinstance(item, dict) or not isinstance(item.get("payload"), dict):
                continue
            if "expected" not in item:
                continue
            cases.append(CapabilityCase(dict(item["payload"]), item["expected"]))
        return CapabilityCandidate(
            capability=request.tool,
            operation=request.operation,
            source=str(payload.get("source") or ""),
            cases=tuple(cases),
        )


class HiveCapabilityOracle:
    """Separate acceptance-case generator using intended semantics, not author examples."""

    def __init__(self, ask: Callable[..., str] | None = None, *, max_cases: int = 6):
        if ask is None:
            from hive_llm import ask_hive

            ask = ask_hive
        self.ask = ask
        self.max_cases = max_cases

    @staticmethod
    def _parse(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]
        return json.loads(cleaned)

    def cases(
        self,
        target: Any,
        request: ToolRequest,
        candidate: CapabilityCandidate,
    ) -> Sequence[CapabilityCase]:
        prompt = (
            "KINGDOM / CAPABILITY ACCEPTANCE ORACLE\n\n"
            f"Capability: {request.tool}\nOperation: {request.operation}\n"
            f"Purpose: {request.purpose}\nBuild target: {getattr(target, 'statement', '')}\n"
            f"Original blocked payload: {json.dumps(dict(request.payload), default=str)}\n"
            f"Candidate source under review:\n{candidate.source}\n\n"
            "You are the acceptance oracle, not the implementation author. Derive independent executable cases from "
            "the intended contract. Do not copy the author's examples. Include boundary or adversarial cases when the "
            "contract supports them. Expected outputs must be justified by the requested semantics, not by whatever "
            "the candidate happens to return. If the intended behavior is too ambiguous to assign objective expected "
            "outputs, return {\"testable\": false}. "
            f"Otherwise return 1-{self.max_cases} cases as JSON only: "
            "{\"testable\": true, \"cases\": [{\"payload\": {...}, \"expected\": ...}]}."
        )
        payload = self._parse(self.ask(prompt, role="reflector"))
        if not payload.get("testable"):
            return ()
        cases: list[CapabilityCase] = []
        for item in payload.get("cases", [])[: self.max_cases]:
            if not isinstance(item, dict) or not isinstance(item.get("payload"), dict):
                continue
            if "expected" not in item:
                continue
            cases.append(CapabilityCase(dict(item["payload"]), item["expected"]))
        return tuple(cases)


def _merge_cases(*groups: Sequence[CapabilityCase]) -> tuple[CapabilityCase, ...]:
    merged: list[CapabilityCase] = []
    seen: set[str] = set()
    for group in groups:
        for case in group:
            key = json.dumps(
                {"payload": dict(case.payload), "expected": case.expected},
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(case)
    return tuple(merged)


class SafeCapabilityValidator:
    """Policy + Hive RegressionGate validation for restricted generated functions.

    This is defense in depth for a deliberately tiny capability class; it is
    not a general-purpose security sandbox for arbitrary Python programs.
    """

    def __init__(
        self,
        *,
        repo_root: str | Path | None = None,
        max_source_chars: int = 12000,
        regression_timeout: float = 4.0,
    ):
        self.repo_root = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
        self.max_source_chars = max_source_chars
        self.regression_timeout = regression_timeout

    def _validate_policy(self, candidate: CapabilityCandidate) -> None:
        if not candidate.capability.strip() or not candidate.operation.strip():
            raise CandidatePolicyError("capability and operation are required")
        if not candidate.entrypoint.isidentifier() or candidate.entrypoint.startswith("_"):
            raise CandidatePolicyError("entrypoint must be a public identifier")
        if not candidate.source.strip():
            raise CandidatePolicyError("candidate source is empty")
        if len(candidate.source) > self.max_source_chars:
            raise CandidatePolicyError("candidate source exceeds size limit")
        if not 1 <= len(candidate.cases) <= 12:
            raise CandidatePolicyError("candidate must provide 1-12 executable cases")

        try:
            tree = ast.parse(candidate.source)
        except SyntaxError as exc:
            raise CandidatePolicyError(f"syntax error: {exc}") from exc

        top_level = [node for node in tree.body if not self._is_docstring(node)]
        if len(top_level) != 1 or not isinstance(top_level[0], ast.FunctionDef):
            raise CandidatePolicyError("source must contain exactly one top-level function")
        function = top_level[0]
        if function.name != candidate.entrypoint:
            raise CandidatePolicyError(f"function must be named {candidate.entrypoint}")
        if function.decorator_list:
            raise CandidatePolicyError("decorators are not allowed")
        args = function.args
        if (
            len(args.posonlyargs) != 0
            or len(args.args) != 1
            or args.args[0].arg != "payload"
            or args.vararg is not None
            or args.kwarg is not None
            or args.kwonlyargs
            or args.defaults
            or args.kw_defaults
        ):
            raise CandidatePolicyError("execute must accept exactly one argument named payload")

        for node in ast.walk(tree):
            if not isinstance(node, _ALLOWED_AST):
                raise CandidatePolicyError(f"AST node {type(node).__name__} is not allowed")
            if isinstance(node, ast.Name) and node.id.startswith("__"):
                raise CandidatePolicyError("dunder names are not allowed")
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_CALLS:
                    raise CandidatePolicyError("only approved simple builtin calls are allowed")
            if isinstance(node, ast.Expr) and not self._is_docstring(node):
                raise CandidatePolicyError("standalone expressions are not allowed")

        for index, case in enumerate(candidate.cases, 1):
            try:
                json.dumps(dict(case.payload))
                json.dumps(case.expected)
            except (TypeError, ValueError) as exc:
                raise CandidatePolicyError(f"case {index} is not JSON serializable") from exc

    @staticmethod
    def _is_docstring(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )

    def _run_regression_gate(self, candidate: CapabilityCandidate) -> Mapping[str, Any]:
        helper = (
            "import json,sys\n"
            "from pathlib import Path\n"
            "repo,cases,candidate,target=sys.argv[1:]\n"
            "sys.path.insert(0,repo)\n"
            "from regression_gate import RegressionGate\n"
            "report=RegressionGate(cases).run_for_file(Path(candidate),target_file=target)\n"
            "print(json.dumps(report,sort_keys=True))\n"
        )
        with tempfile.TemporaryDirectory(prefix="kingdom-forge-") as temp:
            root = Path(temp)
            filename = "generated_capability.py"
            candidate_path = root / filename
            candidate_path.write_text(candidate.source.rstrip() + "\n", encoding="utf-8")
            cases_dir = root / "cases"
            cases_dir.mkdir()
            records = []
            for index, case in enumerate(candidate.cases, 1):
                records.append(
                    {
                        "id": f"forge-{candidate.fingerprint()[:12]}-{index}",
                        "target_file": filename,
                        "callable": candidate.entrypoint,
                        "args": [dict(case.payload)],
                        "expected": case.expected,
                        "preserve_inputs": True,
                    }
                )
            (cases_dir / "candidate.json").write_text(
                json.dumps(records, sort_keys=True), encoding="utf-8"
            )
            try:
                process = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        "-S",
                        "-c",
                        helper,
                        str(self.repo_root),
                        str(cases_dir),
                        str(candidate_path),
                        filename,
                    ],
                    text=True,
                    capture_output=True,
                    timeout=self.regression_timeout,
                    env={},
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise CandidatePolicyError("RegressionGate timed out") from exc
            if process.returncode != 0:
                detail = (process.stderr or process.stdout or "RegressionGate failed").strip()
                raise CandidatePolicyError(detail[:2000])
            try:
                return json.loads(process.stdout.strip().splitlines()[-1])
            except (json.JSONDecodeError, IndexError) as exc:
                raise CandidatePolicyError("RegressionGate returned invalid JSON") from exc

    def validate(self, candidate: CapabilityCandidate) -> CandidateValidation:
        try:
            self._validate_policy(candidate)
        except CandidatePolicyError as exc:
            return CandidateValidation(False, False, False, str(exc), {})

        try:
            report = self._run_regression_gate(candidate)
        except CandidatePolicyError as exc:
            return CandidateValidation(False, True, False, str(exc), {})
        regression_passed = bool(report.get("passed"))
        detail = "RegressionGate passed" if regression_passed else (
            "RegressionGate rejected: " + ", ".join(report.get("failed_case_ids", []))
        )
        return CandidateValidation(
            regression_passed,
            True,
            regression_passed,
            detail,
            report,
        )


_RUNNER = r'''
import json,sys
SAFE = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "float": float, "int": int, "len": len, "list": list, "max": max,
    "min": min, "round": round, "set": set, "sorted": sorted, "str": str,
    "sum": sum, "tuple": tuple,
}
envelope = json.loads(sys.stdin.read())
namespace = {"__builtins__": SAFE}
exec(compile(envelope["source"], "<kingdom-generated>", "exec"), namespace, namespace)
result = namespace[envelope["entrypoint"]](envelope["payload"])
print(json.dumps(result, sort_keys=True))
'''.strip()


class GeneratedCapabilityTool:
    """Runtime adapter for a candidate that already passed forge validation."""

    def __init__(
        self,
        candidate: CapabilityCandidate,
        *,
        timeout: float = 2.0,
        max_payload_bytes: int = 65536,
    ):
        self.candidate = candidate
        self.name = candidate.capability
        self.timeout = timeout
        self.max_payload_bytes = max_payload_bytes

    def _invoke(self, payload: Mapping[str, Any]) -> Any:
        envelope = {
            "source": self.candidate.source,
            "entrypoint": self.candidate.entrypoint,
            "payload": dict(payload),
        }
        serialized = json.dumps(envelope, sort_keys=True)
        if len(serialized.encode("utf-8")) > self.max_payload_bytes:
            raise ValueError("generated capability payload exceeds size limit")
        process = subprocess.run(
            [sys.executable, "-I", "-S", "-c", _RUNNER],
            input=serialized,
            text=True,
            capture_output=True,
            timeout=self.timeout,
            env={},
            check=False,
        )
        if process.returncode != 0:
            raise RuntimeError((process.stderr or process.stdout or "generated capability failed")[:2000])
        return json.loads(process.stdout.strip())

    def verify_cases(self) -> tuple[bool, str]:
        for index, case in enumerate(self.candidate.cases, 1):
            try:
                actual = self._invoke(case.payload)
            except Exception as exc:
                return False, f"isolated runtime case {index} failed: {type(exc).__name__}: {exc}"
            if actual != case.expected:
                return False, f"isolated runtime case {index} expected {case.expected!r}, got {actual!r}"
        return True, "isolated runtime cases passed"

    def execute(self, request: ToolRequest) -> ArenaObservation:
        if request.operation != self.candidate.operation:
            raise ValueError(
                f"{self.name} supports only operation={self.candidate.operation!r}"
            )
        result = self._invoke(request.payload)
        return ArenaObservation(
            request_id=request.request_id,
            branch_id=request.branch_id,
            tool=self.name,
            operation=request.operation,
            status="verified",
            claim=f"Forged capability '{self.name}' executed '{request.operation}'.",
            detail=json.dumps(result, sort_keys=True, default=str),
            source=f"forge:{self.candidate.fingerprint()}",
            confidence=1.0,
        )


class CapabilityForge:
    """Author -> independent oracle -> policy -> RegressionGate -> isolated runtime -> Arena."""

    def __init__(
        self,
        arena: ArenaRegistry,
        author: CapabilityAuthor,
        validator: SafeCapabilityValidator | None = None,
        *,
        oracle: CapabilityOracle | None = None,
    ):
        self.arena = arena
        self.author = author
        self.validator = validator or SafeCapabilityValidator()
        self.oracle = oracle

    def attempt(self, target: Any, request: ToolRequest) -> ForgeAttempt:
        request = request.normalized()
        try:
            candidate = self.author.author(target, request)
        except Exception as exc:
            return ForgeAttempt(
                target_id=str(getattr(target, "target_id", "")),
                capability=request.tool,
                operation=request.operation,
                status="unavailable",
                detail=f"capability author failed closed: {type(exc).__name__}: {exc}",
            )
        if candidate is None:
            return ForgeAttempt(
                target_id=str(getattr(target, "target_id", "")),
                capability=request.tool,
                operation=request.operation,
                status="unavailable",
                detail="author could not represent the missing capability as a restricted pure function",
            )
        if candidate.capability != request.tool or candidate.operation != request.operation:
            return ForgeAttempt(
                target_id=str(getattr(target, "target_id", "")),
                capability=request.tool,
                operation=request.operation,
                status="rejected",
                candidate_fingerprint=candidate.fingerprint(),
                detail="candidate capability/operation does not match the blocked request",
            )

        if self.oracle is not None:
            try:
                oracle_cases = tuple(self.oracle.cases(target, request, candidate))
            except Exception as exc:
                return ForgeAttempt(
                    target_id=str(getattr(target, "target_id", "")),
                    capability=request.tool,
                    operation=request.operation,
                    status="rejected",
                    candidate_fingerprint=candidate.fingerprint(),
                    detail=f"acceptance oracle failed closed: {type(exc).__name__}: {exc}",
                )
            if not oracle_cases:
                return ForgeAttempt(
                    target_id=str(getattr(target, "target_id", "")),
                    capability=request.tool,
                    operation=request.operation,
                    status="rejected",
                    candidate_fingerprint=candidate.fingerprint(),
                    detail="acceptance oracle could not define objective independent cases",
                )
            candidate = replace(candidate, cases=_merge_cases(candidate.cases, oracle_cases))

        fingerprint = candidate.fingerprint()
        if candidate.capability in self.arena.tool_names:
            return ForgeAttempt(
                target_id=str(getattr(target, "target_id", "")),
                capability=request.tool,
                operation=request.operation,
                status="rejected",
                candidate_fingerprint=fingerprint,
                detail="Arena already contains a tool with this name",
            )

        validation = self.validator.validate(candidate)
        if not validation.passed:
            return ForgeAttempt(
                target_id=str(getattr(target, "target_id", "")),
                capability=request.tool,
                operation=request.operation,
                status="rejected",
                candidate_fingerprint=fingerprint,
                detail=validation.detail,
                validation=validation,
            )

        tool = GeneratedCapabilityTool(candidate)
        runtime_ok, runtime_detail = tool.verify_cases()
        if not runtime_ok:
            return ForgeAttempt(
                target_id=str(getattr(target, "target_id", "")),
                capability=request.tool,
                operation=request.operation,
                status="rejected",
                candidate_fingerprint=fingerprint,
                detail=runtime_detail,
                validation=validation,
            )

        self.arena.register(tool)
        return ForgeAttempt(
            target_id=str(getattr(target, "target_id", "")),
            capability=request.tool,
            operation=request.operation,
            status="accepted",
            candidate_fingerprint=fingerprint,
            detail=f"{validation.detail}; {runtime_detail}",
            registered=True,
            validation=validation,
        )
