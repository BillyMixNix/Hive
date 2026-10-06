"""The model-facing edit contract must be executable by Hive for each file."""

import json
import shutil

import pytest

from workshop import hive, hive_edits
from workshop.hive_protocol import worker_edit_contract


JAVA = "src/main/java/example/Greeting.java"


def _variants(paths):
    schema = hive.agent_response_schema("backend", planned_files=paths)
    implementation = next(branch for branch in schema["anyOf"]
                          if branch.get("properties", {}).get("status", {}).get("enum") == ["implemented"])
    return implementation["properties"]["edits"]["items"]["anyOf"]


def _external_scope():
    return hive._ACTIVE_AGENT_SCOPES.set({role: ("**",) for role in ("ui", "backend", "tests")})


def test_file_type_operation_inventory():
    exact = {"replace", "create", "insert_after_anchor"}
    symbol = {"insert_before_symbol", "insert_after_symbol"}
    assert set(hive_edits.supported_operations(JAVA)) == exact
    assert set(hive_edits.supported_operations("app.py")) == exact | symbol
    for suffix in ("js", "mjs", "cjs"):
        assert set(hive_edits.supported_operations(f"static/app.{suffix}")) == exact | symbol
    assert set(hive_edits.supported_operations("static/index.html")) == exact | symbol | {"insert_after_element"}
    assert set(hive_edits.supported_operations("README.md")) == exact


def test_java_only_prompt_and_schema_exclude_unsupported_edits():
    prompt = hive._worker_prompt("backend", "Change Greeting", [JAVA], "source")
    assert "insert_after_symbol" not in prompt
    assert "insert_before_symbol" not in prompt
    assert "insert_after_element" not in prompt
    assert "replace, create, insert_after_anchor" in worker_edit_contract([JAVA])
    advertised = {op for variant in _variants([JAVA])
                  for op in variant["properties"]["operation"]["enum"]}
    assert advertised == set(hive_edits.supported_operations(JAVA))
    assert all(variant["properties"]["path"]["enum"] == [JAVA] for variant in _variants([JAVA]))


def test_mixed_scope_schema_ties_each_operation_to_eligible_paths():
    paths = [JAVA, "app.py", "static/app.js", "static/index.html"]
    for variant in _variants(paths):
        for path in variant["properties"]["path"]["enum"]:
            for operation in variant["properties"]["operation"]["enum"]:
                assert hive_edits.operation_supported(path, operation)
    assert all(JAVA not in variant["properties"]["path"]["enum"]
               for variant in _variants(paths)
               if "insert_after_symbol" in variant["properties"]["operation"]["enum"])


@pytest.mark.parametrize("operation", ["insert_before_symbol", "insert_after_symbol", "insert_after_element"])
def test_java_unsupported_operation_rejected_before_source_access(tmp_path, operation):
    token = _external_scope()
    try:
        with pytest.raises(hive.EditValidationError, match="not executable"):
            hive.apply_agent_edits(tmp_path, "backend", {"edits": [{
                "path": JAVA, "operation": operation, "symbol": "Greeting",
                "element_id": "x", "insert": "public void f() {}",
            }]}, [JAVA])
        assert not (tmp_path / JAVA).exists()
    finally:
        hive._ACTIVE_AGENT_SCOPES.reset(token)


def test_every_advertised_java_operation_edits_candidate(tmp_path):
    token = _external_scope()
    try:
        original = "package example;\npublic class Greeting {\n    String text() { return \"old\"; }\n}\n"
        path = tmp_path / JAVA
        path.parent.mkdir(parents=True)
        path.write_text(original, encoding="utf-8")
        edits = [
            {"path": JAVA, "operation": "replace", "find": 'return "old";', "replace": 'return "new";'},
            {"path": JAVA, "operation": "insert_after_anchor", "anchor": "package example;", "insert": "\n// synthetic edit smoke"},
            {"path": "src/main/java/example/Added.java", "operation": "create",
             "replace": "package example;\npublic class Added {}\n"},
        ]
        assert {edit["operation"] for edit in edits} == set(hive_edits.supported_operations(JAVA))
        changed = hive.apply_agent_edits(tmp_path, "backend", {"edits": edits},
                                         [JAVA, "src/main/java/example/Added.java"])
        assert set(changed) == {JAVA, "src/main/java/example/Added.java"}
        assert 'return "new";' in path.read_text(encoding="utf-8")
        assert "synthetic edit smoke" in path.read_text(encoding="utf-8")
        assert "class Added" in (tmp_path / "src/main/java/example/Added.java").read_text(encoding="utf-8")
    finally:
        hive._ACTIVE_AGENT_SCOPES.reset(token)


def test_python_and_javascript_symbol_edits_remain_available(tmp_path):
    python = tmp_path / "app.py"
    python.write_text("def existing():\n    return 1\n", encoding="utf-8")
    hive.apply_agent_edits(tmp_path, "backend", {"edits": [{"path": "app.py",
        "operation": "insert_after_symbol", "symbol": "existing",
        "insert": "def added():\n    return 2\n"}]}, ["app.py"])
    assert "def added" in python.read_text(encoding="utf-8")
    assert "insert_after_symbol" in json.dumps(_variants(["app.py"]))


@pytest.mark.skipif(not shutil.which("node"), reason="Node required for JS structural edits")
def test_javascript_symbol_edit_remains_executable(tmp_path):
    path = tmp_path / "static/app.js"
    path.parent.mkdir()
    path.write_text("function existing() { return 1; }\n", encoding="utf-8")
    token = _external_scope()
    try:
        hive.apply_agent_edits(tmp_path, "ui", {"edits": [{"path": "static/app.js",
            "operation": "insert_after_symbol", "symbol": "existing",
            "insert": "function added() { return 2; }"}]}, ["static/app.js"])
    finally:
        hive._ACTIVE_AGENT_SCOPES.reset(token)
    assert "function added" in path.read_text(encoding="utf-8")

