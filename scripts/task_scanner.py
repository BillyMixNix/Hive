#!/usr/bin/env python3
"""
Scans Hive's own codebase for known problem patterns and emits candidate
task dicts for the autonomous improvement queue.

Patterns detected:
  - Hardcoded allowlist sets (KNOWN_FILES, ALLOWED_* constants)
  - Bare raise ValueError in validation paths (should be soft fallbacks)
  - TODO / FIXME comments
  - High cyclomatic complexity (too many decision paths in one function)
  - Long functions (hard to test and reason about)
  - Swallowed exceptions (bare except/pass that hides failures)
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

# Complexity threshold: functions with CC above this are flagged.
# Set at 10 to avoid flooding the queue with minor cases.
COMPLEXITY_THRESHOLD = 10

# Functions longer than this (in source lines) are flagged.
LONG_FUNCTION_THRESHOLD = 60

# Very large functions (CC > this) are skipped — too risky for in-place rewrite.
COMPLEXITY_SKIP_THRESHOLD = 50


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
    findings.extend(_find_high_complexity(tree, filename, priority))
    findings.extend(_find_long_functions(tree, filename, priority))
    findings.extend(_find_swallowed_exceptions(tree, filename, priority))

    # Deduplicate: one task per (file, symbol) pair — take first occurrence.
    seen = set()
    deduped = []
    for f in findings:
        key = (f["target_file"], f.get("target_symbol"))
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    return deduped


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


def _compute_cyclomatic_complexity(func_node):
    """Approximate McCabe cyclomatic complexity via decision node count."""
    count = 1
    for node in ast.walk(func_node):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler,
                             ast.With, ast.Assert, ast.comprehension)):
            count += 1
        elif isinstance(node, ast.BoolOp):
            count += len(node.values) - 1
    return count


def _find_high_complexity(tree, filename, priority):
    """Flag functions with cyclomatic complexity above threshold."""
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        func_name = node.name
        cc = _compute_cyclomatic_complexity(node)
        if cc <= COMPLEXITY_THRESHOLD:
            continue
        if cc > COMPLEXITY_SKIP_THRESHOLD:
            # Too complex for safe in-place rewrite — skip.
            continue
        findings.append({
            "note": (
                f"The function {func_name} in {filename} has high cyclomatic "
                f"complexity (~{cc} decision paths). It handles too many cases "
                f"in one place. Simplify by extracting repeated decision logic "
                f"into a dispatch table or named helper, reducing branch count."
            ),
            "target_file": filename,
            "target_symbol": func_name,
            "tag": "complexity",
            "priority_hint": priority,
        })
    return findings


def _find_long_functions(tree, filename, priority):
    """Flag functions that exceed the line-length threshold."""
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not (hasattr(node, "end_lineno") and hasattr(node, "lineno")):
            continue
        func_name = node.name
        func_lines = node.end_lineno - node.lineno + 1
        if func_lines <= LONG_FUNCTION_THRESHOLD:
            continue
        # Skip extremely long functions — too risky for in-place rewrite.
        if func_lines > 200:
            continue
        findings.append({
            "note": (
                f"The function {func_name} in {filename} is {func_lines} lines long. "
                f"Functions this long are hard to test and modify safely. "
                f"Refactor by extracting a logical sub-step into a named helper "
                f"or collapsing repeated patterns into a loop."
            ),
            "target_file": filename,
            "target_symbol": func_name,
            "tag": "complexity",
            "priority_hint": priority,
        })
    return findings


def _find_swallowed_exceptions(tree, filename, priority):
    """Flag except handlers that silently swallow exceptions with bare pass."""
    findings = []
    seen_funcs = set()
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        func_name = func.name
        if func_name in seen_funcs:
            continue
        for node in ast.walk(func):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                seen_funcs.add(func_name)
                findings.append({
                    "note": (
                        f"The function {func_name} in {filename} contains an except "
                        f"handler that silently discards exceptions with bare pass. "
                        f"At minimum, log the exception so failures are visible "
                        f"rather than silently swallowed."
                    ),
                    "target_file": filename,
                    "target_symbol": func_name,
                    "tag": "error-handling",
                    "priority_hint": priority,
                })
                break
    return findings


def scan_repo(root=None, skip_dirs=None):
    """Scan all .py files in the repo and return all candidate task dicts."""
    root = Path(root or REPO_ROOT)
    skip_dirs = set(skip_dirs or {
        "backups", ".git", "__pycache__", "tmp_stress", "hive_v05", "tests",
    })
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
    for r in results[:10]:
        print(json.dumps(r, indent=2))
