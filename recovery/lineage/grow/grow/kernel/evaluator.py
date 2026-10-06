from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Callable


class EvaluationError(RuntimeError):
    pass


_ALLOWED_AST_NODES = {
    ast.Module,
    ast.Expr,
    ast.FunctionDef,
    ast.arguments,
    ast.arg,
    ast.Return,
    ast.Assign,
    ast.If,
    ast.Compare,
    ast.Eq,
    ast.Name,
    ast.Load,
    ast.Store,
    ast.Constant,
    ast.Subscript,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.BinOp,
    ast.Add,
    ast.List,
    ast.Tuple,
}


def validate_workshop_source(source: str) -> dict[str, Any]:
    """Reject executable workshop features that could escape candidate isolation."""
    errors: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"passed": False, "errors": [f"syntax: {exc}"]}

    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    non_doc_body = [
        node for node in tree.body
        if not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        )
    ]
    if len(functions) != 1 or functions[0].name != "build_repair_packet":
        errors.append("workshop must define exactly one function named build_repair_packet")
    if any(not isinstance(node, ast.FunctionDef) for node in non_doc_body):
        errors.append("module may contain only a docstring and build_repair_packet")

    if functions:
        fn = functions[0]
        positional = [arg.arg for arg in fn.args.args]
        kwonly = [arg.arg for arg in fn.args.kwonlyargs]
        if positional != ["case"] or kwonly != ["presentation_order"]:
            errors.append("build_repair_packet signature must be (case, *, presentation_order=...)")
        if fn.decorator_list:
            errors.append("workshop decorators are forbidden")

    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_AST_NODES:
            errors.append(f"forbidden AST node: {type(node).__name__}")
        if isinstance(node, ast.Assign):
            if any(not isinstance(target, ast.Name) for target in node.targets):
                errors.append("assignment targets must be local names; candidate input mutation is forbidden")
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "case"
            and isinstance(node.slice, ast.Constant)
            and node.slice.value in {"expected_value", "expected_source"}
        ):
            errors.append(f"oracle field access forbidden: {node.slice.value}")
    return {"passed": not errors, "errors": sorted(set(errors))}


def _load_builder(module_path: str | Path) -> Callable[..., str]:
    path = Path(module_path)
    source = path.read_text(encoding="utf-8")
    safety = validate_workshop_source(source)
    if not safety["passed"]:
        raise EvaluationError("unsafe candidate workshop: " + "; ".join(safety["errors"]))
    namespace: dict[str, Any] = {"__builtins__": {}}
    exec(compile(source, str(path), "exec"), namespace, namespace)
    builder = namespace.get("build_repair_packet")
    if not callable(builder):
        raise EvaluationError("candidate workshop must define build_repair_packet(case, ...)")
    return builder


def parse_model_answer(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1])
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:].lstrip("\n")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EvaluationError(f"model output was not strict JSON: {text[:240]}") from exc
    if not isinstance(payload, dict):
        raise EvaluationError("model answer must be a JSON object")
    return payload


def evaluate_case(
    *,
    workshop_module: str | Path,
    case: dict[str, Any],
    invoke_model: Callable[[str], str],
    presentation_order: str = "stored_first",
) -> dict[str, Any]:
    try:
        builder = _load_builder(workshop_module)
        public_case = {
            "goal": case["goal"],
            "stored_value": case["stored_value"],
            "current_value": case["current_value"],
        }
        prompt = builder(public_case, presentation_order=presentation_order)
    except (EvaluationError, KeyError, TypeError, ValueError) as exc:
        return {
            "case_id": case["case_id"],
            "passed": False,
            "answer": None,
            "error": str(exc),
            "prompt_sha256": None,
            "raw_output_sha256": None,
        }
    raw = invoke_model(prompt)
    try:
        answer = parse_model_answer(raw)
        selected_source = str(answer.get("selected_source") or "").strip().lower()
        selected_value = answer.get("selected_value")
        passed = selected_source == case["expected_source"] and selected_value == case["expected_value"]
        error = None
    except EvaluationError as exc:
        answer = None
        passed = False
        error = str(exc)
    return {
        "case_id": case["case_id"],
        "passed": passed,
        "answer": answer,
        "error": error,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "raw_output_sha256": hashlib.sha256((raw or "").encode("utf-8")).hexdigest(),
    }


def counterbalanced_probe(
    *,
    workshop_module: str | Path,
    case: dict[str, Any],
    invoke_model: Callable[[str], str],
) -> dict[str, Any]:
    first = evaluate_case(
        workshop_module=workshop_module,
        case=case,
        invoke_model=invoke_model,
        presentation_order="stored_first",
    )
    second = evaluate_case(
        workshop_module=workshop_module,
        case=case,
        invoke_model=invoke_model,
        presentation_order="current_first",
    )
    first_value = (first.get("answer") or {}).get("selected_value")
    second_value = (second.get("answer") or {}).get("selected_value")
    supported = first["passed"] != second["passed"] or first_value != second_value
    return {
        "status": "DIAGNOSIS_SUPPORTED" if supported else "DIAGNOSIS_INCONCLUSIVE",
        "stored_first": first,
        "current_first": second,
    }
