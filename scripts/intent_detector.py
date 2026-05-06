import runpy
import tempfile
import shutil
import json
import ast
import operator
import re
from pathlib import Path
from typing import Any, List

from executor import ExecutorAgent


_SAFE_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_SAFE_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def run_function_from_file(file_path: str, func_name: str, inputs: List[Any]):
    """Load a module from file and call `func_name` on each input.

    Returns list of outputs or raises if function not found or crashes.
    """
    ns = runpy.run_path(file_path)
    if func_name not in ns:
        raise RuntimeError(f"Function {func_name} not found in {file_path}")

    func = ns[func_name]
    outputs = []
    for inp in inputs:
        if isinstance(inp, (list, tuple)):
            out = func(*inp)
        else:
            out = func(inp)
        outputs.append(out)
    return outputs


def _eval_simple_expr(node, variables):
    if isinstance(node, ast.Expression):
        return _eval_simple_expr(node.body, variables)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, bool, str)):
        return node.value
    if isinstance(node, ast.Name) and node.id in variables:
        return variables[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BIN_OPS:
        left = _eval_simple_expr(node.left, variables)
        right = _eval_simple_expr(node.right, variables)
        return _SAFE_BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_UNARY_OPS:
        operand = _eval_simple_expr(node.operand, variables)
        return _SAFE_UNARY_OPS[type(node.op)](operand)
    raise ValueError(f"Unsupported intent expression: {ast.dump(node, include_attributes=False)}")


def derive_expected_outputs_from_task(task_desc: str, func_name: str, test_inputs: List[Any]):
    """Infer expected outputs from simple task text like "return x + 1".

    This intentionally handles only narrow, explicit return-expression requests.
    It returns None when the task is too complex for deterministic local checks.
    """
    text = task_desc or ""
    match = re.search(
        rf"\b(?:change|make|update)?\s*{re.escape(func_name)}\s+to\s+returns?\s+(.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        match = re.search(r"\breturns?\s+(.+)$", text, flags=re.IGNORECASE)
    if match is None:
        return None

    expr_text = match.group(1).strip()
    expr_text = re.split(r"[.;\n]", expr_text, maxsplit=1)[0].strip()
    if not expr_text:
        return None

    try:
        expr_ast = ast.parse(expr_text, mode="eval")
    except SyntaxError:
        return None

    outputs = []
    for inp in test_inputs:
        if isinstance(inp, (list, tuple)):
            if len(inp) != 1:
                return None
            x_value = inp[0]
        else:
            x_value = inp
        try:
            outputs.append(_eval_simple_expr(expr_ast, {"x": x_value}))
        except Exception:
            return None
    return outputs


def check_intent_with_patch(target_file: str, patch_text: str, func_name: str, test_inputs: List[Any], expected_outputs: List[Any]):
    """Apply patch in sandbox and compare behavior against expected outputs.

    Returns a dict containing baseline outputs, patched outputs, and a boolean `drift_detected`.
    """
    target = Path(target_file)
    if not target.exists():
        raise FileNotFoundError(f"Target file missing: {target_file}")

    # baseline
    try:
        baseline = run_function_from_file(str(target), func_name, test_inputs)
    except Exception as e:
        return {"error": f"baseline execution failed: {e}"}

    # quick check baseline vs expected
    baseline_matches = baseline == expected_outputs

    # structural verification + candidate build (do not rely on sandbox temp files)
    executor = ExecutorAgent()
    original_text = target.read_text(encoding='utf-8')
    verification = executor.verify_patch_context(patch_text, str(target), file_text=original_text)

    patched_outputs = None
    applied = verification.get('verified', False)

    report = {
        'verified': verification.get('verified', False),
        'checks': verification.get('checks', {}),
    }

    if applied:
        # build candidate text and run behavior on a temporary file we control
        try:
            candidate = executor.build_candidate_text(patch_text, str(target), file_text=original_text, verification=verification)
            candidate_text = candidate.get('candidate_text')
        except Exception as e:
            return {
                'baseline': baseline,
                'baseline_matches_expected': baseline_matches,
                'applied': False,
                'report': {'error_build_candidate': str(e), 'verification': verification},
                'drift_detected': False,
            }

        # write candidate to temp file and execute
        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.py', encoding='utf-8') as tf:
            tf.write(candidate_text)
            tf_path = tf.name
        try:
            patched_outputs = run_function_from_file(tf_path, func_name, test_inputs)
        except Exception as e:
            # cleanup
            try:
                Path(tf_path).unlink()
            except Exception:
                pass
            return {
                "baseline": baseline,
                "baseline_matches_expected": baseline_matches,
                "applied": True,
                "report": report,
                "patched_error": str(e),
                "drift_detected": True,
            }
        # cleanup
        try:
            Path(tf_path).unlink()
        except Exception:
            pass

    drift = False
    if patched_outputs is not None:
        drift = patched_outputs != expected_outputs

    return {
        "baseline": baseline,
        "baseline_matches_expected": baseline_matches,
        "applied": applied,
        "report": report,
        "patched_outputs": patched_outputs,
        "drift_detected": drift,
    }


if __name__ == '__main__':
    # quick CLI demo
    import sys
    if len(sys.argv) < 2:
        print('Usage: intent_detector.py <target_file>')
        sys.exit(1)

    target = sys.argv[1]
    print('Run demo not implemented in CLI')
