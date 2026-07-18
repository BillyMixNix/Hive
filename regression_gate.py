from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class RegressionDefinitionError(ValueError):
    """Raised when a recorded regression case is malformed."""


@dataclass(frozen=True)
class RegressionCase:
    case_id: str
    target_file: str
    callable_path: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    expected: Any = None
    has_expected: bool = False
    expected_exception: str | None = None
    construct: dict[str, Any] | None = None
    preserve_inputs: bool = True
    post_mutations: tuple[dict[str, Any], ...] = ()
    description: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, source: str = "<memory>") -> "RegressionCase":
        if not isinstance(payload, dict):
            raise RegressionDefinitionError(f"{source}: case must be a JSON object")

        required = ("id", "target_file", "callable")
        missing = [name for name in required if not str(payload.get(name) or "").strip()]
        if missing:
            raise RegressionDefinitionError(f"{source}: missing required fields {missing}")

        has_expected = "expected" in payload
        expected_exception = payload.get("expected_exception")
        if has_expected == bool(expected_exception):
            raise RegressionDefinitionError(
                f"{source}: define exactly one of 'expected' or 'expected_exception'"
            )

        args = payload.get("args", [])
        kwargs = payload.get("kwargs", {})
        construct = payload.get("construct")
        post_mutations = payload.get("post_mutations", [])

        if not isinstance(args, list):
            raise RegressionDefinitionError(f"{source}: args must be a JSON list")
        if not isinstance(kwargs, dict):
            raise RegressionDefinitionError(f"{source}: kwargs must be a JSON object")
        if construct is not None and not isinstance(construct, dict):
            raise RegressionDefinitionError(f"{source}: construct must be a JSON object")
        if not isinstance(post_mutations, list) or not all(
            isinstance(item, dict) for item in post_mutations
        ):
            raise RegressionDefinitionError(f"{source}: post_mutations must be a list of objects")

        return cls(
            case_id=str(payload["id"]),
            target_file=_normalize_path(payload["target_file"]),
            callable_path=str(payload["callable"]),
            args=tuple(args),
            kwargs=dict(kwargs),
            expected=payload.get("expected"),
            has_expected=has_expected,
            expected_exception=str(expected_exception) if expected_exception else None,
            construct=dict(construct) if construct is not None else None,
            preserve_inputs=bool(payload.get("preserve_inputs", True)),
            post_mutations=tuple(dict(item) for item in post_mutations),
            description=str(payload.get("description") or ""),
        )

    def fingerprint(self) -> str:
        payload = {
            "id": self.case_id,
            "target_file": self.target_file,
            "callable": self.callable_path,
            "args": self.args,
            "kwargs": self.kwargs,
            "expected": self.expected if self.has_expected else None,
            "expected_exception": self.expected_exception,
            "construct": self.construct,
            "preserve_inputs": self.preserve_inputs,
            "post_mutations": self.post_mutations,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()


def _normalize_path(value: str | Path) -> str:
    return Path(str(value).replace("\\", "/")).as_posix().lstrip("./")


def _case_matches_target(case_target: str, requested_target: str | Path) -> bool:
    requested = _normalize_path(requested_target)
    return case_target == requested or Path(case_target).name == Path(requested).name


def load_regression_cases(
    cases_dir: str | Path = "validation/regressions",
    *,
    target_file: str | Path | None = None,
) -> list[RegressionCase]:
    root = Path(cases_dir)
    if not root.exists():
        return []

    cases: list[RegressionCase] = []
    seen_ids: set[str] = set()
    for path in sorted(root.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload if isinstance(payload, list) else [payload]
        for index, record in enumerate(records):
            source = f"{path}:{index + 1}" if isinstance(payload, list) else str(path)
            case = RegressionCase.from_dict(record, source=source)
            if case.case_id in seen_ids:
                raise RegressionDefinitionError(f"{source}: duplicate case id {case.case_id!r}")
            seen_ids.add(case.case_id)
            if target_file is None or _case_matches_target(case.target_file, target_file):
                cases.append(case)
    return cases


def _load_module(candidate_file: Path):
    module_name = f"_hive_regression_{hashlib.sha1(str(candidate_file).encode()).hexdigest()}"
    spec = importlib.util.spec_from_file_location(module_name, candidate_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module from {candidate_file}")

    module = importlib.util.module_from_spec(spec)
    candidate_parent = str(candidate_file.resolve().parent)
    original_path = list(sys.path)
    try:
        if candidate_parent not in sys.path:
            sys.path.insert(0, candidate_parent)
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_path
    return module


def _construct_instance(cls: type, construct: dict[str, Any] | None):
    config = dict(construct or {})
    mode = config.pop("mode", "call")
    args = config.pop("args", [])
    kwargs = config.pop("kwargs", {})
    if config:
        raise RegressionDefinitionError(f"Unknown construct fields: {sorted(config)}")
    if not isinstance(args, list) or not isinstance(kwargs, dict):
        raise RegressionDefinitionError("construct args/kwargs must be JSON list/object")
    if mode == "new":
        return cls.__new__(cls)
    if mode == "call":
        return cls(*args, **kwargs)
    raise RegressionDefinitionError(f"Unknown construct mode {mode!r}")


def _resolve_callable(module: Any, case: RegressionCase):
    parts = [part for part in case.callable_path.split(".") if part]
    if not parts:
        raise RegressionDefinitionError(f"{case.case_id}: empty callable path")

    first = getattr(module, parts[0])
    if isinstance(first, type) and len(parts) > 1:
        current: Any = _construct_instance(first, case.construct)
        parts = parts[1:]
    else:
        current = first
        parts = parts[1:]

    for part in parts:
        current = getattr(current, part)
    if not callable(current):
        raise TypeError(f"{case.callable_path} is not callable")
    return current


def _set_path(root: Any, path: Iterable[Any], value: Any) -> None:
    pieces = list(path)
    if not pieces:
        raise RegressionDefinitionError("post_mutation path cannot be empty")

    current = root
    for key in pieces[:-1]:
        current = current[key] if isinstance(current, (dict, list, tuple)) else getattr(current, key)

    final = pieces[-1]
    if isinstance(current, (dict, list)):
        current[final] = value
    else:
        setattr(current, final, value)


def run_case(module: Any, case: RegressionCase) -> dict[str, Any]:
    args = copy.deepcopy(list(case.args))
    kwargs = copy.deepcopy(case.kwargs)
    before_args = copy.deepcopy(args)
    before_kwargs = copy.deepcopy(kwargs)

    record: dict[str, Any] = {
        "id": case.case_id,
        "target_file": case.target_file,
        "callable": case.callable_path,
        "passed": False,
        "fingerprint": case.fingerprint(),
        "description": case.description,
        "details": [],
    }

    try:
        target = _resolve_callable(module, case)
        try:
            result = target(*args, **kwargs)
        except Exception as exc:
            if case.expected_exception and (
                type(exc).__name__ == case.expected_exception
                or f"{type(exc).__module__}.{type(exc).__name__}" == case.expected_exception
            ):
                record["passed"] = True
                record["details"].append(f"raised expected {case.expected_exception}")
            else:
                record["details"].append(f"unexpected {type(exc).__name__}: {exc}")
                return record
        else:
            if case.expected_exception:
                record["details"].append(
                    f"expected {case.expected_exception}, but call returned {result!r}"
                )
                return record
            if case.has_expected and result != case.expected:
                record["details"].append(f"expected {case.expected!r}, got {result!r}")
                return record
            record["passed"] = True
            record["details"].append("return value matched")

            for mutation in case.post_mutations:
                path = mutation.get("path")
                if not isinstance(path, list):
                    raise RegressionDefinitionError(
                        f"{case.case_id}: post_mutation path must be a JSON list"
                    )
                _set_path(result, path, copy.deepcopy(mutation.get("value")))
                record["details"].append(f"applied result mutation at {path!r}")

        if case.preserve_inputs and (args != before_args or kwargs != before_kwargs):
            record["passed"] = False
            record["details"].append("input arguments were mutated")
        elif case.preserve_inputs and case.post_mutations:
            record["details"].append("inputs remained detached after result mutation")
    except Exception as exc:
        record["passed"] = False
        record["details"].append(f"gate error {type(exc).__name__}: {exc}")

    return record


class RegressionGate:
    def __init__(self, cases_dir: str | Path = "validation/regressions"):
        self.cases_dir = Path(cases_dir)

    def run_for_file(
        self,
        candidate_file: str | Path,
        *,
        target_file: str | Path | None = None,
    ) -> dict[str, Any]:
        candidate = Path(candidate_file)
        logical_target = target_file or candidate.name
        cases = load_regression_cases(self.cases_dir, target_file=logical_target)
        if not cases:
            return {
                "passed": True,
                "target_file": _normalize_path(logical_target),
                "case_count": 0,
                "passed_count": 0,
                "failed_case_ids": [],
                "cases": [],
            }

        module = _load_module(candidate)
        records = [run_case(module, case) for case in cases]
        failed_ids = [record["id"] for record in records if not record["passed"]]
        return {
            "passed": not failed_ids,
            "target_file": _normalize_path(logical_target),
            "case_count": len(records),
            "passed_count": len(records) - len(failed_ids),
            "failed_case_ids": failed_ids,
            "cases": records,
        }

    def run_all(self, repo_root: str | Path = ".") -> dict[str, Any]:
        root = Path(repo_root)
        cases = load_regression_cases(self.cases_dir)
        targets = sorted({case.target_file for case in cases})
        reports = [self.run_for_file(root / target, target_file=target) for target in targets]
        failed = [case_id for report in reports for case_id in report["failed_case_ids"]]
        return {
            "passed": not failed,
            "target_count": len(reports),
            "case_count": sum(report["case_count"] for report in reports),
            "passed_count": sum(report["passed_count"] for report in reports),
            "failed_case_ids": failed,
            "targets": reports,
        }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Hive's recorded executable regression memory.")
    parser.add_argument("--cases", default="validation/regressions")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--file", dest="target_file")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    gate = RegressionGate(args.cases)
    if args.target_file:
        report = gate.run_for_file(Path(args.repo_root) / args.target_file, target_file=args.target_file)
    else:
        report = gate.run_all(args.repo_root)

    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"regressions: {report['passed_count']}/{report['case_count']} passed")
        for case_id in report["failed_case_ids"]:
            print(f"FAIL {case_id}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
