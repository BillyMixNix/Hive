"""Observe explicit input-preservation contracts during existing public tests.

This is a bounded development checker, not an adversarial Python sandbox. It
checks final values of supported arguments on observed synchronous calls; it
does not prove behavior on unseen inputs, object identity, or other threads.
No model supplies policy and no protected evaluator is read by this module.
"""
from dataclasses import asdict, dataclass
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from hive_learning.evaluate import candidate_snapshot, strict_json, validate_files, write_files
from hive_learning.ledger import canonical, digest


@dataclass(frozen=True)
class InputPreservation:
    source_file: str
    symbol: str
    arguments: tuple[str, ...]

    def __post_init__(self):
        if (not re.fullmatch(r"[A-Za-z_]\w*\.py", self.source_file)
                or self.source_file.startswith("test_")
                or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", self.symbol)
                or not isinstance(self.arguments, (list, tuple)) or not self.arguments
                or any(not isinstance(a, str) or not a.isidentifier() for a in self.arguments)
                or len(set(self.arguments)) != len(self.arguments)):
            raise ValueError("invalid public input-preservation declaration")
        object.__setattr__(self, "arguments", tuple(self.arguments))

    def public(self):
        return {"kind": "preserve_argument_values", **asdict(self),
                "scope": "After each observed public-test call, including exceptions."}


def _value_snapshot(value):
    """Use exact built-in types; never invoke candidate equality or copy hooks."""
    active, nodes = set(), 0

    def walk(item, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > 10000 or depth > 32:
            raise ValueError("argument snapshot exceeds bounds")
        kind = type(item)
        if kind in (type(None), bool, int, str):
            return [kind.__name__, item]
        if kind is float and math.isfinite(item):
            return ["float", item.hex()]
        if kind not in (list, tuple, dict):
            raise ValueError("unsupported argument type")
        if id(item) in active:
            raise ValueError("cyclic argument is outside this checker")
        active.add(id(item))
        try:
            if kind is dict:
                return ["dict", [[walk(k, depth+1), walk(v, depth+1)] for k, v in item.items()]]
            return [kind.__name__, [walk(v, depth+1) for v in item]]
        finally:
            active.remove(id(item))

    encoded = canonical(walk(value))
    if len(encoded.encode()) > 64000:
        raise ValueError("argument snapshot exceeds byte limit")
    return encoded


def _validate_target(source, contract):
    body = ast.parse(source).body
    node = None
    for name in contract.symbol.split("."):
        matches = [n for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name]
        if len(matches) != 1:
            raise ValueError("contract target is absent or ambiguous")
        node = matches[0]
        body = node.body
    def suspends(item):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return False
        return isinstance(item, (ast.Yield, ast.YieldFrom, ast.Await)) or any(suspends(child) for child in ast.iter_child_nodes(item))

    if not isinstance(node, ast.FunctionDef) or any(suspends(item) for item in node.body):
        raise ValueError("contract requires a synchronous non-generator function")
    args = node.args
    names = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    names.update(a.arg for a in (args.vararg, args.kwarg) if a is not None)
    if not set(contract.arguments) <= names:
        raise ValueError("contract argument is missing from the callable")


class PublicContractGate:
    def __init__(self, public_files, contracts, *, timeout=10):
        validate_files(public_files)
        self._baseline = dict(public_files)
        self.contracts = tuple(contracts)
        if (not self.contracts or len(self.contracts) > 8
                or any(type(c) is not InputPreservation for c in self.contracts)
                or len({(c.source_file, c.symbol) for c in self.contracts}) != len(self.contracts)
                or not 0 < timeout <= 30):
            raise ValueError("invalid public contract policy")
        self.timeout = timeout
        self.tests = tuple(p for p in public_files if Path(p).name.startswith("test_"))
        if not self.tests:
            raise ValueError("public contract checks require existing public tests")
        for contract in self.contracts:
            _validate_target(self._baseline[contract.source_file], contract)
        self._policy = json.loads(canonical({"schema": "hive.public-contract-policy.v1", "contracts": [c.public() for c in self.contracts],
                       "baseline_sha256": digest(self._baseline), "timeout_seconds": timeout,
                       "maximum_observed_calls": 1000}))
        self.policy_sha256 = digest(self._policy)

    @property
    def policy(self):
        return json.loads(canonical(self._policy))

    @property
    def baseline(self):
        return dict(self._baseline)

    def _error(self, code, candidate_sha256=None):
        return {"schema": "hive.public-contract-result.v1", "status": "ERROR", "accepted": False,
                "valid": False, "error_code": code, "candidate_sha256": candidate_sha256,
                "policy_sha256": self.policy_sha256, "observed_calls": 0, "checks": []}

    def check(self, workspace):
        try:
            before = candidate_snapshot(Path(workspace), self._baseline)
            result = self.evaluate(before)
            if candidate_snapshot(Path(workspace), self._baseline) != before:
                return self._error("workspace_changed_during_check", digest(before))
            return result
        except (ValueError, OSError):
            return self._error("workspace_integrity_failure")

    def evaluate(self, candidate):
        sha = digest(candidate)
        actual_policy = {"schema": "hive.public-contract-policy.v1", "contracts": [c.public() for c in self.contracts],
                         "baseline_sha256": digest(self._baseline), "timeout_seconds": self.timeout,
                         "maximum_observed_calls": 1000}
        if digest(actual_policy) != self.policy_sha256:
            return self._error("public_contract_policy_changed", sha)
        try:
            validate_files(candidate)
            if set(candidate) != set(self._baseline) or any(candidate[p] != self._baseline[p] for p in self.tests):
                raise ValueError("public fixture set or tests changed")
            for contract in self.contracts:
                _validate_target(candidate[contract.source_file], contract)
        except (ValueError, KeyError, SyntaxError, TypeError):
            return self._error("candidate_or_contract_invalid", sha)
        with tempfile.TemporaryDirectory(prefix="hive-public-contract-") as temp:
            directory = Path(temp)
            workspace = directory/"workspace"
            workspace.mkdir()
            write_files(workspace, candidate)
            request, response = directory/"request.json", directory/"response.json"
            request.write_text(canonical({"contracts": [asdict(c) for c in self.contracts], "tests": self.tests}))
            log = directory/"public-test.log"
            # A copied public workspace and a secret-free child environment.
            # This is process isolation for ordinary fixtures, not a hostile-code boundary.
            env = {"PATH": os.defpath, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
            try:
                with log.open("wb") as output:
                    process = subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).resolve()),
                        "--worker", str(request), str(response)], cwd=workspace, env=env,
                        stdout=output, stderr=subprocess.STDOUT, timeout=self.timeout)
                if process.returncode != 0 or not response.exists() or response.stat().st_size > 200000:
                    return self._error("checker_process_failure", sha)
                measured = strict_json(response.read_bytes())
                if candidate_snapshot(workspace, self._baseline) != candidate:
                    return self._error("copied_workspace_changed_during_check", sha)
            except subprocess.TimeoutExpired:
                return self._error("checker_timeout", sha)
            except (ValueError, OSError):
                return self._error("invalid_checker_evidence", sha)
            checks = measured["checks"]
            expected = [asdict(c) for c in self.contracts]
            if ([c["contract"] for c in checks] != json.loads(canonical(expected))
                    or type(measured["public_test_exit_code"]) is not int):
                return self._error("checker_policy_mismatch", sha)
            valid = measured["public_test_exit_code"] in (0, 1) and all(
                c["observed_calls"] > 0 and c["completed_calls"] == c["observed_calls"] and not c["errors"] for c in checks)
            accepted = valid and measured["public_test_exit_code"] == 0 and not any(c["violations"] for c in checks)
            return {"schema": "hive.public-contract-result.v1", "status": "PASSED" if accepted else "FAILED" if valid else "ERROR",
                    "accepted": accepted, "valid": valid, "candidate_sha256": sha,
                    "policy_sha256": self.policy_sha256, "observed_calls": sum(c["observed_calls"] for c in checks),
                    "public_test_exit_code": measured["public_test_exit_code"], "checks": checks,
                    "output_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}


def _worker(request_path, response_path):
    import pytest
    request = strict_json(Path(request_path).read_bytes())
    checks, targets, active = [], {}, {}
    for declaration in request["contracts"]:
        contract = InputPreservation(**declaration)
        item = {"contract": asdict(contract), "observed_calls": 0, "completed_calls": 0, "violations": [], "errors": []}
        checks.append(item)
        targets[(str((Path.cwd()/contract.source_file).resolve()), contract.symbol)] = item

    def error(item, code):
        if code not in item["errors"] and len(item["errors"]) < 8:
            item["errors"].append(code)

    def observe(frame, event, arg):
        if event == "call":
            item = targets.get((frame.f_code.co_filename, frame.f_code.co_qualname))
            if item is None:
                return
            item["observed_calls"] += 1
            if item["observed_calls"] > 1000:
                error(item, "call_limit_exceeded")
                return
            try:
                # Retain the originally bound objects even if a parameter is rebound.
                bound = {name: frame.f_locals[name] for name in item["contract"]["arguments"]}
                before = {name: _value_snapshot(value) for name, value in bound.items()}
                active[id(frame)] = (item, item["observed_calls"], bound, before)
            except (ValueError, KeyError):
                error(item, "argument_snapshot_unavailable")
        elif event == "return" and id(frame) in active:
            item, number, bound, before = active.pop(id(frame))
            item["completed_calls"] += 1
            for name, original in bound.items():
                try:
                    after = _value_snapshot(original)
                    if after != before[name] and len(item["violations"]) < 8:
                        item["violations"].append({"call": number, "argument": name,
                            "before_sha256": digest(before[name]), "after_sha256": digest(after),
                            "before": before[name][:1500], "after": after[:1500]})
                except ValueError:
                    error(item, "argument_snapshot_unavailable")

    sys.path.insert(0, str(Path.cwd()))
    sys.setprofile(observe)
    try:
        code = int(pytest.main([*request["tests"], "-q", "-p", "no:cacheprovider"]))
    finally:
        sys.setprofile(None)
    for item, *_ in active.values():
        error(item, "observed_call_did_not_complete")
    Path(response_path).write_text(canonical({"public_test_exit_code": code, "checks": checks}))


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--worker":
        raise SystemExit("This worker is launched by PublicContractGate.")
    _worker(sys.argv[2], sys.argv[3])
