import runpy
import tempfile
import shutil
import json
from pathlib import Path
from typing import Any, List

from executor import ExecutorAgent


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
