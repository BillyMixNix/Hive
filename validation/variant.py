"""
Isolated variant management for the empirical validation gate.

A variant is a sibling copy of the codebase with one patch applied.
The live repo is NEVER touched until gate.evaluate() calls _promote().

Public API:
  make_variant(repo_root, variant_id=None) -> (variant_dir: Path, variant_id: str)
  apply_patch_to_variant(variant_dir, patch_text, target_file=None) -> (ok: bool, error: str|None)
  self_verify(variant_dir, task_note, patch_text, target_file=None) -> (ok: bool, reason: str)
  score_variant(codebase_dir, n=1) -> list[float]
  discard_variant(variant_dir)
"""

import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

_COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "_variant_*", ".git", "backups", "tests/_tmp*"
)


def make_variant(repo_root, variant_id=None):
    """
    Copy repo_root to a sibling temp directory.
    Returns (variant_dir: Path, variant_id: str).
    The caller is responsible for calling discard_variant() when done.
    """
    repo_root = Path(repo_root).resolve()
    vid = variant_id or f"v_{uuid.uuid4().hex[:8]}"
    variant_dir = repo_root.parent / f"_variant_{vid}"
    if variant_dir.exists():
        shutil.rmtree(str(variant_dir))
    shutil.copytree(str(repo_root), str(variant_dir), ignore=_COPY_IGNORE)
    return variant_dir, vid


def _extract_target_file(patch_text):
    for line in patch_text.splitlines():
        if line.startswith("TARGET_FILE:"):
            return line.split(":", 1)[1].strip()
    return None


def apply_patch_to_variant(variant_dir, patch_text, target_file=None):
    """
    Apply a Hive-format unified diff to target_file inside variant_dir.
    Uses the live executor (same Python environment) but writes to the variant path.
    Returns (ok: bool, error: str|None).
    """
    variant_dir = Path(variant_dir)
    if target_file is None:
        target_file = _extract_target_file(patch_text)
    if target_file is None:
        return False, "Could not determine target file from patch"

    target_path = variant_dir / target_file
    if not target_path.exists():
        return False, f"Target file not found in variant: {target_file}"

    try:
        from executor import ExecutorAgent  # live env executor
        backup_dir = variant_dir / "_patch_backups"
        backup_dir.mkdir(exist_ok=True)
        executor = ExecutorAgent(backup_dir=str(backup_dir))
        executor.apply_patch(patch_text, str(target_path))
        return True, None
    except Exception as exc:
        return False, str(exc)


def _intent_tokens(task_note):
    """
    Extract lowercase identifier tokens from a task_note for intent checking.
    Strips stop-words so only meaningful domain terms remain.
    """
    import re
    _STOP = frozenset({
        "a", "an", "the", "to", "in", "of", "for", "on", "and", "or", "is",
        "it", "be", "by", "at", "as", "if", "so", "do", "up", "we", "that",
        "this", "with", "from", "into", "before", "after", "when", "than",
        "should", "would", "could", "will", "has", "have", "had", "are",
        "was", "were", "not", "but", "add", "use", "make", "call", "get",
        "set", "put", "return", "update", "insert", "remove", "change",
    })
    tokens = re.findall(r"[a-z_]\w*", (task_note or "").lower())
    return {t for t in tokens if len(t) >= 4 and t not in _STOP}


def self_verify(variant_dir, task_note, patch_text, target_file=None):
    """
    Cheap pre-scoring sanity check (Voyager-style).
    Checks:
      1. Target file exists and has valid Python syntax.
      2. The module is importable (subprocess, so it doesn't pollute this process).
      3. Intent: the diff's added lines contain at least one token from task_note,
         OR the diff is non-trivial (has real additions beyond whitespace).
         This catches content-free patches and obvious off-task edits without
         requiring full NLP.  The full intent anchor is yours to harden further
         (see spec §9: "the most Hive-specific piece").
    Returns (ok: bool, reason: str).
    """
    variant_dir = Path(variant_dir)
    if target_file is None:
        target_file = _extract_target_file(patch_text)
    if target_file is None:
        return False, "Cannot determine target file"

    target_path = variant_dir / target_file
    if not target_path.exists():
        return False, f"Target file missing after patch: {target_file}"

    # Check 1: syntax
    source = target_path.read_text(encoding="utf-8")
    try:
        compile(source, str(target_path), "exec")
    except SyntaxError as exc:
        return False, f"Syntax error in patched file: {exc}"

    # Check 2: importability — derive dotted module path so subdirectory files
    # like validation/variant.py resolve as "validation.variant", not "variant".
    rel = target_path.relative_to(variant_dir).with_suffix("")
    module_name = ".".join(rel.parts)
    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        cwd=str(variant_dir),
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        stderr_snip = result.stderr.strip()[:400]
        return False, f"Import check failed for {module_name}: {stderr_snip}"

    # Check 3: intent — added lines must be non-trivial and loosely on-task
    added_lines = [
        line[1:].strip()
        for line in patch_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    real_additions = [l for l in added_lines if l]
    if not real_additions:
        return False, "Intent check failed: patch has no non-empty added lines"

    # Keyword overlap between task_note and added content
    task_tokens = _intent_tokens(task_note)
    if task_tokens:
        added_text = " ".join(real_additions).lower()
        if not any(tok in added_text for tok in task_tokens):
            return (
                False,
                f"Intent check failed: none of the task_note keywords "
                f"({', '.join(sorted(task_tokens)[:6])}) appear in the diff additions. "
                f"Patch may be off-task. Strengthen the anchor or widen this check."
            )

    return True, "ok"


def score_variant(codebase_dir, n=1):
    """
    Run benchmark_harness.py N times from codebase_dir (subprocess).
    Each run imports modules from codebase_dir, so variant code differences are captured.
    Returns list of float scores (0.0–1.0).
    """
    codebase_dir = Path(codebase_dir).resolve()
    scores = []
    for _ in range(n):
        result = subprocess.run(
            [sys.executable, "benchmark_harness.py", "--score"],
            cwd=str(codebase_dir),
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Harness subprocess failed (exit {result.returncode}): "
                f"{result.stderr.strip()[:500]}"
            )
        data = json.loads(result.stdout.strip())
        scores.append(float(data["score"]))
    return scores


def discard_variant(variant_dir):
    """Remove the variant directory. Safe to call even if already removed."""
    shutil.rmtree(str(variant_dir), ignore_errors=True)
