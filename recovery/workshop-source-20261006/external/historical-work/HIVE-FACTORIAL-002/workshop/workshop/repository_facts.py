"""Small deterministic framework and integration facts for Hive prompts.

This module reads source as evidence only.  It never grants edit authority and
does not replace the repository map or the strict edit validator.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path


MAX_FACTS_CHARS = 6_000
_ROUTE_RE = re.compile(
    r"^\s*@(?P<target>[A-Za-z_]\w*)\.(?P<method>get|post|put|patch|delete|options|head)"
    r"\(\s*(['\"])(?P<path>[^'\"]+)\3",
    re.IGNORECASE,
)
_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+(?P<name>[A-Za-z_]\w*)\s*\(")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _route_examples(text: str) -> list[str]:
    lines = text.splitlines()
    examples: list[str] = []
    for index, line in enumerate(lines):
        match = _ROUTE_RE.match(line)
        if not match:
            continue
        example = line.strip()
        for following in lines[index + 1 : index + 5]:
            function = _DEF_RE.match(following)
            if function:
                example += "\n  " + following.strip()
                break
        if example not in examples:
            examples.append(example)
        if len(examples) >= 8:
            break
    return examples


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Await):
        node = node.value
    if not isinstance(node, ast.Call):
        return ""
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
        return f"{function.value.id}.{function.attr}"
    return ""


def _expression_type(node: ast.AST | None, names: dict[str, str]) -> str:
    if isinstance(node, ast.Await):
        return _expression_type(node.value, names)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return "boolean"
        if isinstance(node.value, str):
            return "string"
        if isinstance(node.value, int):
            return "integer"
        if isinstance(node.value, float):
            return "number"
        if node.value is None:
            return "null"
    if isinstance(node, ast.Name):
        return names.get(node.id, "")
    if isinstance(node, ast.Dict):
        return "object"
    if isinstance(node, (ast.List, ast.Tuple, ast.Set, ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        return "array"
    if isinstance(node, (ast.Compare, ast.BoolOp)) or isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return "boolean"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return {
            "bool": "boolean", "str": "string", "int": "integer",
            "float": "number", "list": "array", "tuple": "array", "dict": "object",
        }.get(node.func.id, "")
    if isinstance(node, ast.IfExp):
        left = _expression_type(node.body, names)
        right = _expression_type(node.orelse, names)
        return left if left and left == right else ""
    return ""


def _merge_name_type(names: dict[str, str], name: str, value_type: str) -> None:
    if not value_type:
        return
    current = names.get(name)
    if current is None or current == value_type:
        names[name] = value_type
    else:
        names.pop(name, None)


class _ScopeShape(ast.NodeVisitor):
    """Collect local static types and literal returns without nested scopes."""

    def __init__(self, call_returns: dict[str, list[str]] | None = None) -> None:
        self.call_returns = call_returns or {}
        self.names: dict[str, str] = {}
        self.keys: list[str] = []
        self.key_types: dict[str, set[str]] = {}
        self.tuple_returns: list[list[str]] = []

    def _assign(self, target: ast.AST, value: ast.AST) -> None:
        call_types = self.call_returns.get(_call_name(value), [])
        if isinstance(target, (ast.Tuple, ast.List)) and call_types:
            for index, item in enumerate(target.elts):
                if isinstance(item, ast.Name) and index < len(call_types):
                    _merge_name_type(self.names, item.id, call_types[index])
            return
        if isinstance(target, ast.Name):
            _merge_name_type(self.names, target.id, _expression_type(value, self.names))

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._assign(target, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._assign(node.target, node.value)

    def visit_Return(self, node: ast.Return) -> None:
        if isinstance(node.value, ast.Tuple):
            self.tuple_returns.append([
                _expression_type(item, self.names) for item in node.value.elts
            ])
        if not isinstance(node.value, ast.Dict):
            return
        for key, value in zip(node.value.keys, node.value.values):
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and key.value not in self.keys
            ):
                self.keys.append(key.value)
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                value_type = _expression_type(value, self.names)
                if value_type:
                    self.key_types.setdefault(key.value, set()).add(value_type)

    # A nested function/class is not part of the route handler's response
    # contract. Its returns must never leak into the outer interface record.
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return


def _scope_shape(node: ast.FunctionDef | ast.AsyncFunctionDef,
                 call_returns: dict[str, list[str]] | None = None) -> _ScopeShape:
    visitor = _ScopeShape(call_returns)
    for statement in node.body:
        visitor.visit(statement)
    return visitor


def _repository_call_returns(root: Path) -> dict[str, list[str]]:
    """Infer stable positional return types for local module functions."""

    result: dict[str, list[str]] = {}
    workshop = Path(root) / "workshop"
    if not workshop.is_dir():
        return result
    for path in sorted(workshop.glob("*.py"), key=lambda item: item.name.casefold()):
        try:
            tree = ast.parse(_read(path), filename=path.name)
        except (SyntaxError, ValueError, TypeError):
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            shape = _scope_shape(node)
            if not shape.tuple_returns:
                continue
            width = min(len(items) for items in shape.tuple_returns)
            types = []
            for index in range(width):
                observed = {items[index] for items in shape.tuple_returns if items[index]}
                types.append(next(iter(observed)) if len(observed) == 1 else "")
            if any(types):
                result[f"{path.stem}.{node.name}"] = types
    return result


def interfaces(root: Path) -> list[dict]:
    """Return a deterministic map of simple application HTTP interfaces.

    Only literal FastAPI-style decorators and literal dictionary response keys
    are reported.  Unknown/dynamic response shapes stay unknown rather than
    being guessed.  This is read-only evidence, never write authorization.
    """

    text = _read(Path(root) / "app.py")
    try:
        tree = ast.parse(text, filename="app.py")
    except (SyntaxError, ValueError, TypeError):
        return []

    call_returns = _repository_call_returns(root)
    records: list[dict] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        route = None
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not decorator.args:
                continue
            function = decorator.func
            if not isinstance(function, ast.Attribute) or function.attr.casefold() not in {
                "get", "post", "put", "patch", "delete", "options", "head",
            }:
                continue
            target = function.value
            path_arg = decorator.args[0]
            if not isinstance(target, ast.Name) or not isinstance(path_arg, ast.Constant) or not isinstance(path_arg.value, str):
                continue
            route = {
                "method": function.attr.upper(),
                "path": path_arg.value,
                "handler": node.name,
                "response_keys": [],
                "response_types": {},
            }
            break
        if route is None:
            continue

        shape = _scope_shape(node, call_returns)
        route["response_keys"] = shape.keys[:24]
        route["response_types"] = {
            key: next(iter(types))
            for key, types in shape.key_types.items()
            if len(types) == 1 and key in route["response_keys"]
        }
        records.append(route)

    # IntentEnvelope consumes this map directly, so discovery must not discard
    # a valid interface based on lexical position. Prompt rendering is bounded
    # independently by MAX_FACTS_CHARS.
    return sorted(
        records,
        key=lambda item: (item["path"].casefold(), item["method"], item["handler"].casefold()),
    )


def build(root: Path) -> str:
    """Return compact, deterministic repository-derived implementation facts."""

    root = Path(root)
    app_text = _read(root / "app.py")
    lowered = app_text.casefold()
    route_examples = _route_examples(app_text)

    fastapi = (
        "from fastapi" in lowered
        or "import fastapi" in lowered
        or "fastapi(" in lowered
        or "fastapi(" in app_text
    )
    flask = "from flask" in lowered or "import flask" in lowered or "flask(" in lowered
    if fastapi and not flask:
        framework = "FastAPI"
    elif flask and not fastapi:
        framework = "Flask"
    elif fastapi and flask:
        framework = "AMBIGUOUS: FastAPI and Flask signals both detected"
    else:
        framework = "unknown; do not assume a web framework"

    lines = [
        "REPOSITORY-DERIVED IMPLEMENTATION FACTS",
        "(deterministic read-only evidence; not write authorization)",
        f"web_framework: {framework}",
    ]
    if framework == "FastAPI":
        lines.extend([
            "backend_contract: use FastAPI route decorators and return JSON-compatible Python values",
            "backend_forbidden_substitutions: do not use Flask @app.route or jsonify",
        ])
    elif framework == "Flask":
        lines.append("backend_contract: follow the existing Flask route and response patterns")

    if route_examples:
        lines.append("local_route_examples:")
        lines.extend(f"  {example}" for example in route_examples)
    else:
        lines.append("local_route_examples: none detected")

    interface_records = interfaces(root)
    if interface_records:
        lines.append("existing_http_interfaces:")
        for record in interface_records:
            keys = ", ".join(record["response_keys"]) or "unknown"
            types = ", ".join(
                f"{key}={value}" for key, value in record.get("response_types", {}).items()
            ) or "unknown"
            lines.append(
                f"  {record['method']} {record['path']} -> {record['handler']}; "
                f"response_keys: {keys}; response_types: {types}"
            )
    else:
        lines.append("existing_http_interfaces: none detected")

    static_text = _read(root / "static" / "index.html")
    if "fetch(" in static_text or "/api/" in static_text:
        lines.append("frontend_contract: use the existing static/index.html api()/fetch() request path for backend data")

    rendered = "\n".join(lines)
    if len(rendered) <= MAX_FACTS_CHARS:
        return rendered
    return rendered[: MAX_FACTS_CHARS - 35] + "\n[FACTS BOUNDED]\n"
