from pathlib import Path

import pytest

from executor import ExecutorAgent


ADDITIONS_ONLY_PATCH = (
    "--- target.py\n"
    "+++ target.py\n"
    "@@ -1,0 +1,1 @@\n"
    "+    return revised_value\n"
)


def test_rejected_verification_exposes_structured_checks(tmp_path: Path):
    target = tmp_path / "target.py"
    target.write_text("def target():\n    return 1\n", encoding="utf-8")
    executor = ExecutorAgent(backup_dir=tmp_path / "backups")

    result = executor.verify_patch_context(ADDITIONS_ONLY_PATCH, str(target))

    assert result["verified"] is False
    assert result["checks"]["anchor_found"] is False
    assert result["checks"]["safe_to_apply"] is False


def test_apply_failure_reports_checks_instead_of_keyerror(tmp_path: Path):
    target = tmp_path / "target.py"
    target.write_text("def target():\n    return 1\n", encoding="utf-8")
    executor = ExecutorAgent(backup_dir=tmp_path / "backups")

    with pytest.raises(ValueError, match="anchor_found"):
        executor.apply_patch(ADDITIONS_ONLY_PATCH, str(target))
