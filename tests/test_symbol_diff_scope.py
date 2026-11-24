"""Trusted fixtures and archived patches are parsed as data, never executed."""
import ast
import difflib
from pathlib import Path

import pytest

from coder_validation import (
    extract_changed_def_names, validate_symbol_locked_patch,
)


SOURCE = '''import json
class Sample:
    def target(self, value):
        return value

    def neighbor(self):
        return 7
'''

HISTORICAL_SOURCE = '''import json
class PlannerAgent:
    def preceding(self):
        return dict(
        )

    def _extract_json_object(self, raw_response):
        start = raw_response.find("{")
        end = raw_response.rfind("}")

        if start == -1 or end == -1 or end < start:
            raise ValueError("No JSON object found in model response.")

        return raw_response[start:end + 1]

    def _validate_task_list(self, tasks):
        if not isinstance(tasks, list) or not tasks:
            pass
'''


def validate(source, changed, name="target", context=3, tag=None):
    node = next(n for n in ast.walk(ast.parse(source))
                if isinstance(n, ast.FunctionDef) and n.name == name)
    span = {k: getattr(node, k) for k in ("lineno", "end_lineno", "col_offset", "end_col_offset")}
    symbol_id = f"sample.py::{name}"
    anchor = {**span, "target_symbol": name, "target_symbol_id": symbol_id, "target_file": "sample.py"}
    task = {"target_file": "sample.py", "target_symbol": name, "metadata": {"anchor": anchor}}
    if tag:
        task["tag"] = tag
    block = {**span, "name": name, "symbol_id": symbol_id}
    patch = "".join(difflib.unified_diff(source.splitlines(True), changed.splitlines(True),
                                      fromfile="sample.py", tofile="sample.py", n=context))
    data = {"target_file": "sample.py", "patch": patch, "context_mode": "exact_symbol_block",
            "context_target": name, "context_symbol_id": symbol_id, "context_span": span}
    return validate_symbol_locked_patch(data, task, block, original_source=source)


def test_unchanged_neighbor_context_does_not_block_a_local_edit():
    assert validate(SOURCE, SOURCE.replace("return value", "return str(value)"))


def test_body_only_hunk_does_not_require_a_changed_def_line():
    assert validate(SOURCE, SOURCE.replace("return value", "return str(value)"), context=0)


@pytest.mark.parametrize("changed", [
    SOURCE.replace("return 7", "return 8"),
    SOURCE.replace("return value", "return str(value)").replace("return 7", "return 8"),
    SOURCE.replace("import json", "import os"),
    SOURCE + "\nSIDE_EFFECT = 1\n",
    SOURCE.replace("    def neighbor", "    @staticmethod\n    def neighbor"),
    SOURCE + "\nclass Added:\n    pass\n",
])
def test_real_out_of_scope_edits_are_blocked_even_without_def_context(changed):
    with pytest.raises(ValueError, match="symbol_anchor_drift"):
        validate(SOURCE, changed, context=0)


def test_changed_def_names_excludes_context_but_keeps_real_added_definitions():
    patch = " def target(self):\n-    return 1\n+    return 2\n def neighbor(self):\n+def added():\n+    pass\n"
    assert extract_changed_def_names(patch) == {"added"}


def test_existing_complexity_helper_exception_is_preserved_without_weakening_bugfix_scope():
    changed = SOURCE.replace("return value", "return self.helper(value)") + "\n    def helper(self, value):\n        return str(value)\n"
    with pytest.raises(ValueError, match="symbol_anchor_drift"):
        validate(SOURCE, changed)
    assert validate(SOURCE, changed, tag="complexity")
    with pytest.raises(ValueError, match="symbol_anchor_drift"):
        validate(SOURCE, changed + "\n    def extra(self):\n        return 0\n", tag="complexity")


def test_archived_experiment2_patches_no_longer_trigger_neighbor_drift():
    root = Path(__file__).resolve().parents[1]
    # Fixed fixture: changing the subject's planner.py cannot change this test.
    source = HISTORICAL_SOURCE
    from validation.variant import apply_unified_diff
    for seed in (1729, 2718, 31415):
        patch = (root / f"docs/research/experiment2/candidate-{seed}.patch").read_text()
        changed = apply_unified_diff(source, patch)
        assert validate(source, changed, name="_extract_json_object")
