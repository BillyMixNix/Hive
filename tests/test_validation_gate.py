"""
Tests for the empirical validation gate (Phase 3-5).

Covers:
  - Failed patch apply: variant file unchanged; live repo never written.
  - Failed self_verify: variant discarded; live repo file untouched.
  - Archive rollback: after evaluate() accepts a patch, rollback() restores
    the pre-patch file content from the archive.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure repo root is on sys.path (tests/ is one level down from Hive root).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from validation.variant import (
    apply_patch_to_variant,
    discard_variant,
    make_variant,
    self_verify,
)
from validation.archive import append as archive_append, rollback as archive_rollback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_CONTENT = "def greet():\n    return 'hello'\n"

_GOOD_PATCH = (
    "TARGET_FILE: target.py\n"
    "CHANGE_TYPE: diff_patch\n"
    "RISK_LEVEL: low\n"
    "STATUS: proposed\n"
    "REASON: change greeting.\n"
    "PATCH:\n"
    "--- target.py\n"
    "+++ target.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def greet():\n"
    "-    return 'hello'\n"
    "+    return 'hi'\n"
)

_BAD_PATCH = (
    "TARGET_FILE: target.py\n"
    "CHANGE_TYPE: diff_patch\n"
    "RISK_LEVEL: low\n"
    "STATUS: proposed\n"
    "REASON: patch that cannot be applied cleanly.\n"
    "PATCH:\n"
    "--- target.py\n"
    "+++ target.py\n"
    "@@ -99,2 +99,2 @@\n"
    " def nonexistent_anchor_line_xyz():\n"
    "-    pass\n"
    "+    return None\n"
)


def _make_mini_repo(tmp_path):
    """Create a minimal repo-like directory with one Python file."""
    target = tmp_path / "target.py"
    target.write_text(_VALID_CONTENT, encoding="utf-8")
    return tmp_path, target


# ---------------------------------------------------------------------------
# Test: failed apply leaves live repo untouched
# ---------------------------------------------------------------------------

class TestApplyFailureIsolation(unittest.TestCase):

    def test_live_file_untouched_when_patch_apply_fails(self, tmp_path=None):
        """
        When apply_patch_to_variant fails, the variant is the only thing
        attempted — the source (live) repo file must be unchanged.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td)
            target = repo_root / "target.py"
            target.write_text(_VALID_CONTENT, encoding="utf-8")

            variant_dir, vid = make_variant(repo_root)
            try:
                ok, err = apply_patch_to_variant(variant_dir, _BAD_PATCH, target_file="target.py")

                # Patch must fail (bad context lines).
                self.assertFalse(ok, f"Expected patch to fail, got ok=True. err={err}")

                # Original file in the live repo must not be touched.
                self.assertEqual(
                    target.read_text(encoding="utf-8"),
                    _VALID_CONTENT,
                    "Live repo file was modified during a failed apply — isolation broken.",
                )
            finally:
                discard_variant(variant_dir)

    def test_variant_dir_removed_after_discard(self):
        """discard_variant removes the directory; idempotent on double-call."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td)
            (repo_root / "dummy.py").write_text("x = 1\n")

            variant_dir, _ = make_variant(repo_root)
            self.assertTrue(variant_dir.exists())
            discard_variant(variant_dir)
            self.assertFalse(variant_dir.exists())
            discard_variant(variant_dir)  # second call must not raise


# ---------------------------------------------------------------------------
# Test: self_verify rejects patch that has no matching task tokens
# ---------------------------------------------------------------------------

class TestSelfVerifyIntentCheck(unittest.TestCase):

    def test_self_verify_fails_when_no_task_token_in_diff(self):
        """
        If task_note contains meaningful keywords that don't appear in the
        diff additions, self_verify must return (False, reason).
        """
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            variant_dir = Path(td)
            target = variant_dir / "mymodule.py"
            target.write_text("def foo():\n    return 'bar'\n", encoding="utf-8")

            off_task_patch = (
                "TARGET_FILE: mymodule.py\n"
                "PATCH:\n"
                "--- mymodule.py\n"
                "+++ mymodule.py\n"
                "@@ -1,2 +1,2 @@\n"
                " def foo():\n"
                "-    return 'bar'\n"
                "+    return 'baz'\n"
            )
            ok, reason = self_verify(
                variant_dir,
                task_note="implement authentication middleware pipeline",
                patch_text=off_task_patch,
                target_file="mymodule.py",
            )
            self.assertFalse(ok, "Expected intent check to fail for off-task patch")
            self.assertIn("Intent check failed", reason)

    def test_self_verify_passes_when_task_token_present(self):
        """Patch that includes a task keyword should pass the intent check."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            variant_dir = Path(td)
            target = variant_dir / "mymodule.py"
            target.write_text("def greet():\n    return 'hello'\n", encoding="utf-8")

            on_task_patch = (
                "TARGET_FILE: mymodule.py\n"
                "PATCH:\n"
                "--- mymodule.py\n"
                "+++ mymodule.py\n"
                "@@ -1,2 +1,2 @@\n"
                " def greet():\n"
                "-    return 'hello'\n"
                "+    return 'greet_updated'\n"
            )
            ok, reason = self_verify(
                variant_dir,
                task_note="update the greet function return value",
                patch_text=on_task_patch,
                target_file="mymodule.py",
            )
            self.assertTrue(ok, f"Expected intent check to pass; reason: {reason}")

    def test_self_verify_subdirectory_import_path(self):
        """
        self_verify must correctly import files in subdirectories by computing
        the dotted module path (e.g. validation.variant, not just variant).
        """
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            variant_dir = Path(td)
            # Create a package subdirectory with __init__ + a simple module
            pkg = variant_dir / "mypkg"
            pkg.mkdir()
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            mod = pkg / "util.py"
            mod.write_text("VALUE = 42\n", encoding="utf-8")

            subdir_patch = (
                "TARGET_FILE: mypkg/util.py\n"
                "PATCH:\n"
                "--- mypkg/util.py\n"
                "+++ mypkg/util.py\n"
                "@@ -1,1 +1,1 @@\n"
                "-VALUE = 42\n"
                "+VALUE = 99  # updated value\n"
            )
            ok, reason = self_verify(
                variant_dir,
                task_note="update the VALUE constant",
                patch_text=subdir_patch,
                target_file="mypkg/util.py",
            )
            self.assertTrue(
                ok,
                f"self_verify failed for subdirectory file; reason: {reason}\n"
                "This is likely the dotted-module-path bug.",
            )


# ---------------------------------------------------------------------------
# Test: archive rollback restores pre-patch content
# ---------------------------------------------------------------------------

class TestArchiveRollback(unittest.TestCase):

    def test_rollback_restores_pre_patch_content(self):
        """
        archive_rollback() must write pre_patch_content back to the live file,
        returning the file to its state before the patch was applied.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td)
            target = repo_root / "rollback_target.py"
            pre_patch = "def original():\n    return 'before'\n"
            post_patch = "def original():\n    return 'after'\n"

            target.write_text(post_patch, encoding="utf-8")  # simulates accepted patch

            archive_path = repo_root / "test_archive.jsonl"
            record = {
                "variant_id": "test_vid_001",
                "target_file": "rollback_target.py",
                "decision": "accept",
                "reason": "delta > noise_band",
                "task_note": "test rollback",
            }
            archive_append(
                record,
                patch_text="TARGET_FILE: rollback_target.py\nPATCH:\n",
                pre_patch_content=pre_patch,
                archive_path=str(archive_path),
            )

            success = archive_rollback(
                "test_vid_001",
                repo_root=str(repo_root),
                archive_path=str(archive_path),
            )

            self.assertTrue(success, "rollback() returned False — check archive write/read")
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                pre_patch,
                "File content after rollback does not match pre_patch_content.",
            )

    def test_rollback_returns_false_for_unknown_variant(self):
        """rollback() on a variant_id not in the archive must return False cleanly."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "empty.jsonl"
            result = archive_rollback(
                "nonexistent_vid",
                repo_root=td,
                archive_path=str(archive_path),
            )
            self.assertFalse(result)

    def test_rollback_returns_false_when_pre_patch_content_missing(self):
        """
        If the archive entry exists but has no pre_patch_content (e.g. the
        gate captured it before the file existed), rollback must return False.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            archive_path = Path(td) / "sparse.jsonl"
            record = {
                "variant_id": "sparse_vid",
                "target_file": "thing.py",
                "decision": "reject",
                "reason": "no gain",
                "task_note": "test",
            }
            archive_append(
                record,
                patch_text="TARGET_FILE: thing.py\nPATCH:\n",
                pre_patch_content=None,  # explicitly absent
                archive_path=str(archive_path),
            )
            result = archive_rollback(
                "sparse_vid",
                repo_root=td,
                archive_path=str(archive_path),
            )
            self.assertFalse(result)


# ---------------------------------------------------------------------------
# Test: evaluate() never writes live file on reject or apply-failure
# ---------------------------------------------------------------------------

class TestEvaluateLiveIsolation(unittest.TestCase):
    """
    Integration-level: gate.evaluate() must NEVER touch the live repo file
    unless decision == "accept".  Uses mocked benchmark so it runs fast.
    """

    def _make_mock_score(self, base_score, var_score):
        """Return a side_effect list for two score_variant calls."""
        return [[base_score] * 3, [var_score] * 3]

    def test_live_file_unchanged_on_patch_apply_failure(self):
        import tempfile
        from validation.gate import evaluate

        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td)
            target = repo_root / "interface.py"
            original_content = "class Interface:\n    pass\n"
            target.write_text(original_content, encoding="utf-8")

            archive_path = repo_root / "test_gate_archive.jsonl"

            with patch("validation.gate._archive_append"):
                record = evaluate(
                    patch=_BAD_PATCH.replace("TARGET_FILE: target.py", "TARGET_FILE: interface.py"),
                    task_note="greet function update",
                    repo_root=str(repo_root),
                    n=2,
                    k=2.0,
                )

            self.assertEqual(record["decision"], "reject")
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                original_content,
                "Live file was written even though patch failed to apply.",
            )

    def test_live_file_unchanged_on_reject(self):
        import tempfile
        from validation.gate import evaluate

        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td)
            target = repo_root / "interface.py"
            original_content = "class Interface:\n    pass\n"
            target.write_text(original_content, encoding="utf-8")

            # Patch scores same as baseline → delta=0 → reject
            with patch("validation.gate.score_variant", side_effect=[[1.0, 1.0], [1.0, 1.0]]):
                with patch("validation.gate._archive_append"):
                    with patch("validation.gate.apply_patch_to_variant", return_value=(True, None)):
                        with patch("validation.gate.self_verify", return_value=(True, "ok")):
                            record = evaluate(
                                patch=(
                                    "TARGET_FILE: interface.py\n"
                                    "PATCH:\n"
                                    "--- interface.py\n"
                                    "+++ interface.py\n"
                                    "@@ -1,2 +1,2 @@\n"
                                    " class Interface:\n"
                                    "-    pass\n"
                                    "+    pass  # no-op\n"
                                ),
                                task_note="interface no-op test",
                                repo_root=str(repo_root),
                                n=2,
                                k=2.0,
                            )

            self.assertEqual(record["decision"], "reject")
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                original_content,
                "Live file was written even though gate rejected the patch.",
            )


if __name__ == "__main__":
    unittest.main()
