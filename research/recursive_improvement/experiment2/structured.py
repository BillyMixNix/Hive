"""Experiment-owned compact transport, never a model-authored evaluator change."""
import ast
import difflib
import json
import re
import textwrap

from research.recursive_improvement.experiment1.run import restrict_method, strict_json


FILE = "planner.py"
SYMBOL = "_extract_json_object"


def method_node(source):
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "PlannerAgent")
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == SYMBOL)


PLAN_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "target_file": {"const": FILE}, "target_symbol": {"const": SYMBOL},
        "objective": {"const": "extract_first_json_object"},
        "approach": {"type": "string", "minLength": 10, "maxLength": 500},
    },
    "required": ["target_file", "target_symbol", "objective", "approach"],
}
CODE_SCHEMA = {"type": "object", "additionalProperties": False,
               "properties": {"method_source": {"type": "string", "maxLength": 10000}},
               "required": ["method_source"]}


def validate_plan(raw):
    plan = strict_json(raw)
    if not isinstance(plan, dict) or set(plan) != set(PLAN_SCHEMA["required"]):
        raise ValueError("Plan schema mismatch")
    if (plan["target_file"] != FILE or plan["target_symbol"] != SYMBOL or
            plan["objective"] != "extract_first_json_object"):
        raise ValueError("Plan changed objective or authority")
    approach = plan["approach"]
    if not isinstance(approach, str) or not 10 <= len(approach) <= 500:
        raise ValueError("Plan description envelope failed")
    lower = approach.lower()
    if "json" not in lower or not any(x in lower for x in ("extract", "decod", "pars")):
        raise ValueError("Plan not grounded in JSON extraction")
    if any(name != FILE for name in re.findall(r"\b[\w]+\.py\b", approach)):
        raise ValueError("Plan references unauthorized file")
    if "new feature" in lower:
        raise ValueError("Generic feature drift")
    return plan


def hive_plan(plan):
    """Deterministic contract serialization; the algorithm remains model-authored."""
    validate_plan(json.dumps(plan))
    description = plan["approach"]
    return json.dumps({"goal": f"Repair JSON extraction in {FILE}: {description}",
        "work_mode": "repair", "domain": "code", "artifact": "JSON extraction",
        "operation": "modify_logic", "validation": "external frozen cases", "task_type": "bugfix",
        "tasks": [{"title": "Repair JSON extraction", "description": description,
            "target_file": FILE, "target_symbol": SYMBOL, "change_intent": "modify_existing_logic",
            "expected_operation": "modify_logic", "completion_cues": [], "work_mode": "repair"}],
        "dependencies": [FILE], "risks": [], "next_action": f"Modify {SYMBOL} in {FILE}: {description}",
        "status": "planned"})


def method_to_contract(raw, original):
    data = strict_json(raw)
    if not isinstance(data, dict) or set(data) != {"method_source"} or not isinstance(data["method_source"], str):
        raise ValueError("Coder schema mismatch")
    method = data["method_source"].strip("\n")
    if len(method) > 10000 or not method.startswith(f"def {SYMBOL}("):
        raise ValueError("Coder must return the single unindented target method")
    parsed = ast.parse(method)
    if len(parsed.body) != 1 or not isinstance(parsed.body[0], ast.FunctionDef):
        raise ValueError("Coder added top-level code")
    node = method_node(original)
    lines = original.splitlines(keepends=True)
    replacement = textwrap.indent(method.rstrip() + "\n", " " * node.col_offset)
    changed = "".join(lines[:node.lineno-1]) + replacement + "".join(lines[node.end_lineno:])
    restrict_method(original, changed)
    if ast.dump(method_node(original)) == ast.dump(method_node(changed)):
        raise ValueError("No method change")
    diff = "".join(difflib.unified_diff(original.splitlines(keepends=True), changed.splitlines(keepends=True),
                                        fromfile=FILE, tofile=FILE))
    return (f"TARGET_FILE: {FILE}\nCHANGE_TYPE: diff_patch\nRISK_LEVEL: low\nSTATUS: proposed\n"
            "REASON: Model-authored JSON extraction repair\nPATCH:\n" + diff)


def compact_prompt(role, protocol, original, public, plan=None):
    node = method_node(original)
    method = textwrap.dedent("\n".join(original.splitlines()[node.lineno-1:node.end_lineno]))
    schema = PLAN_SCHEMA if role == "planner" else CODE_SCHEMA
    prompt = (f"You are Hive's {role}. Repair only PlannerAgent.{SYMBOL} in {FILE}.\n"
              f"Required behavior: {protocol['contract']}\n"
              f"Current method (module already imports json):\n{method}\n"
              f"Public examples: {json.dumps(public, ensure_ascii=False)}\n"
              "Keep the method signature exactly. No other files, methods, tests, permissions or sandbox edits. Do not introduce additional def/class statements.\n")
    if role == "coder":
        prompt += f"Approved model plan: {json.dumps(plan)}\nReturn the complete method at indentation zero. No prose, fences, diff or explanation.\n"
    else:
        prompt += "Propose a brief concrete algorithm for JSON extraction. No unrelated feature work.\n"
    return prompt + "Return only JSON matching this schema:\n" + json.dumps(schema)
