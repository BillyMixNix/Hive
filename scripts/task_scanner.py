#!/usr/bin/env python3
"""
Scans Hive's own codebase for known problem patterns and emits candidate
task dicts for the autonomous improvement queue.

Patterns detected:
  - Hardcoded allowlist sets (KNOWN_FILES, ALLOWED_* constants)
  - Bare raise ValueError in validation paths (should be soft fallbacks)
  - TODO / FIXME comments
"""
import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

HARDCODED_SET_NAMES = {
    "KNOWN_FILES", "ALLOWED_CHANGE_INTENTS", "ALLOWED_EXPECTED_OPERATIONS",
    "ALLOWED_TASK_TYPES", "ALLOWED_TASK_KINDS", "CLAUDE_ROLES",
}

CRITICAL_PATH_FILES = {"planner.py", "coder.py", "executor.py", "router.py", "main.py"}


def scan_file(path):
    """Scan a single .py file and return a list of candidate task dicts."""
    findings = []
    try:
        source = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except Exception:
        return findings

    filename = Path(path).name
    priority = "high" if filename in CRITICAL_PATH_FILES else "medium"

    findings.extend(_find_hardcoded_sets(tree, filename, priority))
    findings.extend(_find_bare_raises(tree, filename, priority))
    findings.extend(_find_todos(source, filename, priority))
    return findings


def _find_hardcoded_sets(tree, filename, priority):
    # Build a map: constant name → first function that references it
    const_to_func = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in HARDCODED_SET_NAMES:
                if child.id not in const_to_func:
                    const_to_func[child.id] = node.name

    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id not in HARDCODED_SET_NAMES:
                continue
            # Use the referencing function as the anchor, not the constant itself.
            # If no function references it, skip — no valid anchor exists.
            anchor_symbol = const_to_func.get(target.id)
            if anchor_symbol is None:
                continue
            findings.append({
                "note": (
                    f"The {target.id} set in {filename} is hardcoded. "
                    f"Consider making it dynamic or adding a fuzzy fallback "
                    f"so novel inputs are handled gracefully instead of hard-failing."
                ),
                "target_file": filename,
                "target_symbol": anchor_symbol,
                "tag": "self-improvement",
                "priority_hint": priority,
            })
    return findings


def _find_bare_raises(tree, filename, priority):
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        func_name = node.name
        if not any(kw in func_name for kw in ("valid", "check", "verify", "enforce")):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Raise):
                continue
            if child.exc is None:
                continue
            exc = child.exc
            if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                if exc.func.id == "ValueError":
                    findings.append({
                        "note": (
                            f"The function {func_name} in {filename} contains a bare "
                            f"raise ValueError that hard-fails on unexpected input. "
                            f"Consider a fuzzy fallback or soft filter instead."
                        ),
                        "target_file": filename,
                        "target_symbol": func_name,
                        "tag": "self-improvement",
                        "priority_hint": priority,
                    })
                    break
    return findings


def _find_todos(source, filename, priority):
    findings = []
    for i, line in enumerate(source.splitlines(), 1):
        match = re.search(r"#\s*(TODO|FIXME)[:\s]+(.*)", line, re.IGNORECASE)
        if match:
            findings.append({
                "note": f"{filename} line {i}: {match.group(0).strip()}",
                "target_file": filename,
                "target_symbol": None,
                "tag": "todo",
                "priority_hint": "low",
            })
    return findings


def scan_repo(root=None, skip_dirs=None):
    """Scan all .py files in the repo and return all candidate task dicts."""
    root = Path(root or REPO_ROOT)
    skip_dirs = set(skip_dirs or {"backups", ".git", "__pycache__", "tmp_stress"})
    candidates = []
    for py_file in sorted(root.rglob("*.py")):
        if any(part in skip_dirs for part in py_file.parts):
            continue
        candidates.extend(scan_file(py_file))
    return candidates


if __name__ == "__main__":
    import json
    results = scan_repo()
    print(f"Found {len(results)} candidates")
    for r in results[:5]:
        print(json.dumps(r, indent=2))
