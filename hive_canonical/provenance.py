"""Independent source-content comparison around the recovered candidate engine."""

from __future__ import annotations

from pathlib import Path

from .legacy.workshop import external_root


class CandidateIntegrityError(ValueError):
    """The isolated candidate no longer matches the host-authorized source scope."""


def source_index(root: Path) -> dict[str, dict[str, str | int]]:
    """Index the engine's bounded, link-rejecting source inventory by content."""
    resolved = Path(root).resolve(strict=True)
    return {
        relative.as_posix(): {
            "sha256": external_root._file_digest(path, resolved, info),
            "size": info.st_size,
        }
        for path, relative, info in external_root._inventory(resolved)
    }


def assert_scoped_change(
    original: dict[str, dict[str, str | int]],
    candidate: dict[str, dict[str, str | int]],
    allowed_paths: tuple[str, ...],
    claimed_paths: list[str],
    *,
    require_change: bool = True,
) -> tuple[str, ...]:
    changed = tuple(sorted(path for path in original.keys() | candidate.keys()
                           if original.get(path) != candidate.get(path)))
    if (require_change and not changed) or set(changed) != set(claimed_paths):
        raise CandidateIntegrityError("candidate edits differ from the recorded changed-file list")
    if any(path not in allowed_paths for path in changed):
        raise CandidateIntegrityError("candidate contains an out-of-scope source change")
    return changed
