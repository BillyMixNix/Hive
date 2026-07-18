"""Isolated repository variants and single-file unified-diff application."""

from __future__ import annotations

import ast
import hashlib
import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Iterable


_HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


def extract_target_file(patch_text: str) -> str | None:
    """Return the one repository-relative file targeted by a Hive patch."""

    declared = None
    diff_targets: set[str] = set()
    for raw_line in patch_text.splitlines():
        line = raw_line.strip()
        if line.startswith("TARGET_FILE:"):
            declared = line.split(":", 1)[1].strip()
        elif raw_line.startswith("+++ "):
            candidate = raw_line[4:].strip().split("\t", 1)[0]
            if candidate != "/dev/null":
                for prefix in ("a/", "b/"):
                    if candidate.startswith(prefix):
                        candidate = candidate[len(prefix) :]
                diff_targets.add(candidate)

    targets = set(diff_targets)
    if declared:
        targets.add(declared)
    if not targets:
        return None
    if len(targets) != 1:
        raise ValueError(f"Gate v1 accepts exactly one target file, got: {sorted(targets)}")

    target = next(iter(targets)).replace("\\", "/")
    candidate = Path(target)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Unsafe target path: {target}")
    return target


def _patch_body(patch_text: str) -> list[str]:
    lines = patch_text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == "PATCH:":
            return lines[index + 1 :]
    return lines


def _parse_hunks(patch_text: str) -> list[dict]:
    lines = _patch_body(patch_text)
    hunks: list[dict] = []
    current = None

    for line in lines:
        match = _HUNK_RE.match(line)
        if match:
            current = {
                "old_start": int(match.group("old_start")),
                "old_count": int(match.group("old_count") or "1"),
                "new_start": int(match.group("new_start")),
                "new_count": int(match.group("new_count") or "1"),
                "lines": [],
            }
            hunks.append(current)
            continue

        if current is None:
            continue
        if line.startswith("\\ No newline at end of file"):
            continue
        if line[:1] in {" ", "+", "-"}:
            current["lines"].append(line)

    if not hunks:
        raise ValueError("Patch contains no unified-diff hunks")
    return hunks


def _find_subsequence(lines: list[str], needle: list[str], expected: int) -> int:
    if not needle:
        return max(0, min(expected, len(lines)))

    end = len(lines) - len(needle) + 1
    candidates = [
        index
        for index in range(max(0, end))
        if lines[index : index + len(needle)] == needle
    ]
    if expected in candidates:
        return expected
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError("Patch context/removal block was not found in the target file")
    raise ValueError("Patch context is ambiguous in the target file")


def apply_unified_diff(original_text: str, patch_text: str) -> str:
    """Apply a one-file unified diff with strict old-context verification."""

    lines = original_text.splitlines()
    trailing_newline = original_text.endswith("\n")
    offset = 0

    for hunk in _parse_hunks(patch_text):
        old_block = [
            line[1:]
            for line in hunk["lines"]
            if line.startswith((" ", "-"))
        ]
        new_block = [
            line[1:]
            for line in hunk["lines"]
            if line.startswith((" ", "+"))
        ]
        if len(old_block) != hunk["old_count"]:
            raise ValueError(
                f"Hunk old-count mismatch: header={hunk['old_count']} actual={len(old_block)}"
            )
        if len(new_block) != hunk["new_count"]:
            raise ValueError(
                f"Hunk new-count mismatch: header={hunk['new_count']} actual={len(new_block)}"
            )

        expected = max(0, hunk["old_start"] - 1 + offset)
        start = _find_subsequence(lines, old_block, expected)
        lines[start : start + len(old_block)] = new_block
        offset += len(new_block) - len(old_block)

    result = "\n".join(lines)
    if trailing_newline or result:
        result += "\n"
    return result


def _ignore_variant_paths(_directory: str, names: Iterable[str]) -> set[str]:
    ignored = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        "backups",
    }
    return {
        name
        for name in names
        if name in ignored
        or name.startswith("_tmp_reliability_")
        or name.startswith(".hive_variant_")
    }


def make_variant(repo_root: str | Path, variant_id: str) -> Path:
    repo_root = Path(repo_root).resolve()
    parent = Path(tempfile.mkdtemp(prefix=f".hive_variant_{variant_id}_"))
    variant_root = parent / "repo"
    shutil.copytree(repo_root, variant_root, ignore=_ignore_variant_paths)
    return variant_root


def discard_variant(variant_root: str | Path) -> None:
    variant_root = Path(variant_root)
    parent = variant_root.parent
    if parent.name.startswith(".hive_variant_"):
        shutil.rmtree(parent, ignore_errors=True)
    else:
        shutil.rmtree(variant_root, ignore_errors=True)


def apply_patch_to_variant(
    variant_root: str | Path,
    patch_text: str,
    *,
    target_file: str | None = None,
) -> tuple[Path, str, str]:
    variant_root = Path(variant_root)
    target = target_file or extract_target_file(patch_text)
    if not target:
        raise ValueError("Patch does not declare a target file")

    target_path = variant_root / target
    if not target_path.is_file():
        raise FileNotFoundError(f"Target file does not exist in variant: {target}")
    before = target_path.read_text(encoding="utf-8")
    after = apply_unified_diff(before, patch_text)
    if before == after:
        raise ValueError("Patch produced no file change")
    target_path.write_text(after, encoding="utf-8")
    return target_path, before, after


def self_verify(
    variant_root: str | Path,
    *,
    target_file: str,
    verifier: Callable[[Path, str], tuple[bool, str] | bool] | None = None,
) -> tuple[bool, str]:
    """Run cheap checks before empirical scoring."""

    variant_root = Path(variant_root)
    target_path = variant_root / target_file
    if not target_path.is_file():
        return False, "target file missing after patch"

    try:
        source = target_path.read_text(encoding="utf-8")
        if target_path.suffix == ".py":
            ast.parse(source, filename=str(target_path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        return False, f"syntax/read verification failed: {exc}"

    if verifier is not None:
        result = verifier(variant_root, target_file)
        if isinstance(result, tuple):
            return bool(result[0]), str(result[1])
        return bool(result), "custom verifier passed" if result else "custom verifier failed"

    return True, "syntax/read verification passed"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
