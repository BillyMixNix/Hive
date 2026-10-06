from pathlib import Path

import pytest

from direct_context import (
    CONTEXT_CHAR_BUDGET, MAX_REQUEST_FIELD_CHARS, build_context, direct_prompt,
)


def _put(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_oversize_repository_is_bounded_without_blind_tail_truncation(tmp_path):
    for index in range(16):
        name = f"src/main/java/demo/Unrelated{index:02d}.java"
        _put(tmp_path, name, f"public class Unrelated{index:02d} {{\n" +
             (f"// unrelated filler {index}\n" * 4000) + "}\n")
    _put(tmp_path, "src/main/java/demo/TargetHandler.java",
         "package demo;\npublic class TargetHandler {\n"
         "  public int computeTarget(int x) { return x + 1; }\n}\n")
    full_chars = sum(len(path.read_text()) for path in tmp_path.rglob("*.java"))
    assert full_chars > 1_048_576
    task = "Add TargetHandler.computeTarget handling for missing values."
    context, manifest = build_context(tmp_path, task)
    field = direct_prompt("Return one safe diff.", task, context)
    assert len(context) <= CONTEXT_CHAR_BUDGET
    assert len(field) <= MAX_REQUEST_FIELD_CHARS < 1_048_576
    assert task in field
    assert "public int computeTarget" in field
    selected = [row for row in manifest["files"] if row["included_sections"]]
    assert any(row["path"].endswith("TargetHandler.java") for row in selected)
    assert len(selected) < len(manifest["files"])
    assert all(row["reason"] for row in manifest["files"])
    assert all("sha256" in row for row in selected)


def test_determinism_and_source_provenance(tmp_path):
    _put(tmp_path, "src/main/java/demo/Target.java", "public class Target { int value; }\n")
    _put(tmp_path, "src/test/java/demo/TargetTest.java", "public class TargetTest {}\n")
    first = build_context(tmp_path, "Update Target value")
    second = build_context(tmp_path, "Update Target value")
    assert first == second
    assert first[1]["files"][0]["included_sections"]


def test_frozen_tests_and_runtime_paths_never_enter_model_context(tmp_path):
    _put(tmp_path, "src/main/java/demo/Target.java", "public class Target {}\n")
    _put(tmp_path, "src/test/java/demo/FrozenAcceptance.java", "SECRET_ACCEPTANCE_ASSERTION\n")
    _put(tmp_path, "frozen-tests/AnotherAcceptance.java", "SECRET_SECOND_ASSERTION\n")
    _put(tmp_path, "build/Generated.java", "SECRET_GENERATED\n")
    context, manifest = build_context(
        tmp_path, "Update Target",
        forbidden_paths=["src/test/java/demo/FrozenAcceptance.java"],
    )
    assert "SECRET_ACCEPTANCE_ASSERTION" not in context
    assert "SECRET_SECOND_ASSERTION" not in context
    assert "SECRET_GENERATED" not in context
    excluded = {row["path"]: row["reason"] for row in manifest["files"]}
    assert excluded["src/test/java/demo/FrozenAcceptance.java"] == "frozen_acceptance_excluded"
    assert {row["path"] for row in manifest["excluded_subtrees"]} >= {"frozen-tests/", "build/"}


def test_oversize_single_file_uses_recorded_bounded_sections(tmp_path):
    lines = [f"// filler line {index:05d}\n" for index in range(20_000)]
    lines[18_000] = "public int rareTargetSymbol() { return 42; }\n"
    _put(tmp_path, "src/main/java/demo/Giant.java", "".join(lines))
    context, manifest = build_context(tmp_path, "Change rareTargetSymbol")
    assert "rareTargetSymbol()" in context
    row = next(row for row in manifest["files"] if row["path"].endswith("Giant.java"))
    assert row["reason"] == "bounded_relevant_excerpts"
    assert any(section["start_line"] <= 18_001 <= section["end_line"]
               for section in row["included_sections"])
    assert len(context) <= CONTEXT_CHAR_BUDGET


def test_prompt_field_guard_is_independent_of_context_allocator():
    with pytest.raises(ValueError, match="safe bound"):
        direct_prompt("instructions", "x" * MAX_REQUEST_FIELD_CHARS, "context")
