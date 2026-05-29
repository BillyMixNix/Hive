"""
Append-only variant archive — Darwin Gödel Machine pattern.

Every variant ever tried is recorded here with its full validation record
and the patch diff.  Rejected variants are data, not garbage — they can
be revisited, clustered, and learned from.

Storage: validation/archive.jsonl  (one JSON object per line, never overwritten)

Public API:
  append(record, patch_text, pre_patch_content=None, archive_path=None)
  read_all(archive_path=None) -> list[dict]
  get_by_variant_id(variant_id, archive_path=None) -> dict | None
  rollback(variant_id, repo_root, archive_path=None) -> bool
"""

import datetime
import json
from pathlib import Path

_DEFAULT_ARCHIVE = Path(__file__).parent / "archive.jsonl"


def _now():
    return datetime.datetime.utcnow().isoformat() + "Z"


def append(record, patch_text, pre_patch_content=None, archive_path=None):
    """
    Append a validation record to the archive.

    pre_patch_content: the raw text of the target file *before* the patch was
    applied.  Stored so rollback() can restore without reversing the diff.
    """
    path = Path(archive_path or _DEFAULT_ARCHIVE)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        **record,
        "patch_text": patch_text,
        "archived_at": _now(),
    }
    if pre_patch_content is not None:
        entry["pre_patch_content"] = pre_patch_content
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_all(archive_path=None):
    """Return all archived entries, oldest first."""
    path = Path(archive_path or _DEFAULT_ARCHIVE)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries


def get_by_variant_id(variant_id, archive_path=None):
    """Return the archive entry for a given variant_id, or None."""
    for entry in read_all(archive_path):
        if entry.get("variant_id") == variant_id:
            return entry
    return None


def rollback(variant_id, repo_root, archive_path=None):
    """
    Restore the target file to its pre-patch state for the given variant.

    Requires that the archive entry contains pre_patch_content (written
    by gate.evaluate when gate mode captures baseline content).
    Returns True on success, False if entry or content is missing.
    """
    entry = get_by_variant_id(variant_id, archive_path)
    if entry is None:
        return False
    content = entry.get("pre_patch_content")
    if content is None:
        return False
    target_file = entry.get("target_file") or _extract_target_file(entry.get("patch_text", ""))
    if target_file is None:
        return False
    target_path = Path(repo_root) / target_file
    target_path.write_text(content, encoding="utf-8")
    return True


def _extract_target_file(patch_text):
    for line in (patch_text or "").splitlines():
        if line.startswith("TARGET_FILE:"):
            return line.split(":", 1)[1].strip()
    return None
