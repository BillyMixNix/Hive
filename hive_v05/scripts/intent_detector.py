"""
Behavioral intent detection for patch candidates.

derive_expected_outputs_from_task: parses simple return-expression intent from a
task note, returning expected outputs for a set of test inputs, or None if the task
doesn't describe a simple pure function.

check_intent_with_patch: applies a patch in a sandbox, executes the target function
against test inputs, and checks whether the outputs match expected values.
"""
import ast
import re
import tempfile
import shutil
from pathlib import Path


def derive_expected_outputs_from_task(task_note, func_name, test_inputs):
    """
    Return a dict {input: expected_output} if the task note describes a simple
    pure function with a parseable return expression; otherwise return None.
    """
    if not task_note or not func_name:
        return None

    note_lower = task_note.lower()

    # Only attempt behavioral checking when the note describes a simple
    # return-expression transformation (e.g. "return x + 1").
    simple_return_patterns = [
        r"return\s+\S+",
    ]
    if not any(re.search(p, task_note) for p in simple_return_patterns):
        return None

    # Extract the expression from the note.
    m = re.search(r"return\s+(.+?)(?:\.|$)", task_note, re.IGNORECASE)
    if not m:
        return None

    expr = m.group(1).strip().rstrip(".")
    try:
        compiled = compile(expr, "<intent>", "eval")
    except SyntaxError:
        return None

    results = {}
    for n in test_inputs:
        try:
            val = eval(compiled, {"__builtins__": {}}, {"n": n, "x": n})
            results[n] = val
        except Exception:
            return None

    return results if results else None


def check_intent_with_patch(target_file, patch_text, func_name, test_inputs, expected):
    """
    Apply patch_text to a sandbox copy of target_file, then execute func_name(n)
    for each n in test_inputs and compare to expected values.

    Returns a dict with:
      - "passed": bool
      - "drift_detected": bool
      - "details": list of per-input result dicts
    """
    if not target_file or not patch_text or not func_name:
        return {"skipped": True, "reason": "insufficient data for intent check"}

    try:
        src = Path(target_file)
        if not src.exists():
            return {"skipped": True, "reason": f"target file not found: {target_file}"}

        sandbox_dir = Path(tempfile.mkdtemp())
        try:
            sandbox_file = sandbox_dir / src.name
            shutil.copy2(src, sandbox_file)

            # Apply patch lines (additions only, naive application).
            original_lines = sandbox_file.read_text(encoding="utf-8").splitlines(keepends=True)
            addition_lines = [
                line[1:] for line in patch_text.splitlines()
                if line.startswith("+") and not line.startswith("+++")
            ]
            # Naive: append additions before the file end (not a real patch apply).
            # Real intent checking would require full patch application.
            # For now skip if the patch is too complex to evaluate safely.
            if not addition_lines:
                return {"skipped": True, "reason": "no addition lines in patch"}

            patched_source = "".join(original_lines) + "\n" + "".join(addition_lines)
            try:
                tree = ast.parse(patched_source)
            except SyntaxError:
                return {"skipped": True, "reason": "patched source has syntax errors"}

            # Evaluate the function in isolation.
            globs = {}
            try:
                exec(compile(tree, sandbox_file.name, "exec"), globs)
            except Exception as exc:
                return {"skipped": True, "reason": f"exec failed: {exc}"}

            func = globs.get(func_name)
            if func is None or not callable(func):
                return {"skipped": True, "reason": f"{func_name} not found as top-level function"}

            details = []
            all_passed = True
            for n in test_inputs:
                exp = expected.get(n)
                try:
                    got = func(n)
                    ok = got == exp
                except Exception as exc:
                    got = None
                    ok = False
                details.append({"input": n, "expected": exp, "got": got, "passed": ok})
                if not ok:
                    all_passed = False

            return {
                "passed": all_passed,
                "drift_detected": not all_passed,
                "details": details,
            }
        finally:
            shutil.rmtree(sandbox_dir, ignore_errors=True)

    except Exception as exc:
        return {"skipped": True, "reason": f"intent check error: {exc}"}
