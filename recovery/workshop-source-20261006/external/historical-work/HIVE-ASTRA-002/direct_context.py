"""Deterministic, task-relevant read-only context for the Astra direct control.

This module is an input representation, not a planner or a coding agent. It
never reads frozen acceptance sources or executes repository code.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path


CONTEXT_CHAR_BUDGET = 320_000
INDEX_CHAR_BUDGET = 24_000
FILE_CHAR_BUDGET = 90_000
MAX_REQUEST_FIELD_CHARS = 400_000
MAX_SOURCE_BYTES = 2_000_000
MAX_SELECTED_FILES = 24
EXCLUDED_DIRS = frozenset({
    ".git", ".gradle", ".venv", "venv", "node_modules", "build", "dist",
    "out", "target", "run-gametest", "run-questtest", "logs", "hive_runs",
    "__pycache__", ".pytest_cache", "frozen-tests", "data-runtime",
})
TEXT_SUFFIXES = frozenset({".java", ".gradle", ".properties", ".md", ".txt", ".json"})
TEXT_NAMES = frozenset({"gradlew", "gradlew.bat", "settings.gradle", "build.gradle"})
STOP_WORDS = frozenset({
    "add", "and", "are", "all", "that", "this", "from", "with", "using",
    "return", "returns", "method", "class", "public", "new", "existing",
    "must", "should", "when", "where", "into", "then", "only", "not",
    "the", "for", "its", "use", "each", "any", "preserve", "without",
})
SYMBOL_RE = re.compile(r"\b(?:class|interface|record|enum)\s+([A-Za-z_$][\w$]*)|"
                       r"\b(?:public|protected)\s+(?:static\s+)?(?:final\s+)?"
                       r"[\w<>?,.\[\] ]+\s+([A-Za-z_$][\w$]*)\s*\(")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tokens(value: str) -> tuple[str, ...]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    words = {word.casefold() for word in re.findall(r"[A-Za-z][A-Za-z0-9_]*", expanded)}
    words.update(word.casefold() for word in re.findall(r"[A-Za-z_$][\w$]*", value)
                 if len(word) >= 4)
    return tuple(sorted(word for word in words if len(word) >= 3 and word not in STOP_WORDS))


def _is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def _files(root: Path, forbidden: frozenset[str]) -> tuple[list[tuple[str, Path, str | None]], list[dict]]:
    files: list[tuple[str, Path, str | None]] = []
    pruned: list[dict] = []
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        retained = []
        for name in sorted(dirs, key=lambda part: (part.casefold(), part)):
            path = base / name
            if _is_link(path) or name.casefold() in EXCLUDED_DIRS or name.startswith("."):
                pruned.append({"path": path.relative_to(root).as_posix() + "/",
                               "reason": "linked_or_excluded_runtime_subtree"})
                continue
            retained.append(name)
        dirs[:] = retained
        for name in sorted(names, key=lambda part: (part.casefold(), part)):
            path = base / name
            rel = path.relative_to(root).as_posix()
            lower = rel.casefold()
            reason = None
            if _is_link(path) or not path.is_file():
                reason = "linked_or_special"
            elif lower in forbidden or lower.startswith("frozen-tests/"):
                reason = "frozen_acceptance_excluded"
            elif name.startswith(".") or "secret" in lower or "credential" in lower:
                reason = "secret_or_hidden"
            elif path.suffix.casefold() not in TEXT_SUFFIXES and name.casefold() not in TEXT_NAMES:
                reason = "non_source_or_binary"
            files.append((rel, path, reason))
    return sorted(files, key=lambda row: row[0]), sorted(pruned, key=lambda row: row["path"])


def _line_windows(content: str, tokens: tuple[str, ...], char_budget: int) -> tuple[str, list[dict]]:
    """Select disjoint scored line windows; ties spread across the file."""
    lines = content.splitlines(keepends=True)
    if not lines:
        return "", []
    scored = []
    for index, line in enumerate(lines):
        folded = line.casefold()
        score = sum(1 for token in tokens if token in folded)
        if score:
            scored.append((score, index))
    if not scored:
        scored = [(1, 0)]
    scored.sort(key=lambda item: (-item[0], item[1]))
    # Evenly sampled ties avoid a first-chunks-only bias in long source files.
    rank_groups: dict[int, list[int]] = {}
    for score, index in scored:
        rank_groups.setdefault(score, []).append(index)
    centers = []
    for score in sorted(rank_groups, reverse=True):
        group = rank_groups[score]
        while group:
            centers.append(group.pop(len(group) // 2))
    chosen: set[int] = set()
    windows: list[tuple[int, int]] = []
    used = 0
    for center in centers:
        if center in chosen:
            continue
        start, end = max(0, center - 10), min(len(lines), center + 11)
        fresh = [i for i in range(start, end) if i not in chosen]
        fragment = "".join(lines[i] for i in fresh)
        if used + len(fragment) > char_budget:
            continue
        chosen.update(fresh)
        windows.append((start, end))
        used += len(fragment)
        if used >= char_budget - 1000:
            break
    merged = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    sections = [{"start_line": start + 1, "end_line": end} for start, end in merged]
    text = "".join(f"--- lines {start + 1}-{end} ---\n{''.join(lines[start:end])}"
                   for start, end in merged)
    return text, sections


def build_context(root: Path, task: str, *, forbidden_paths=()) -> tuple[str, dict]:
    """Return a bounded field and complete selection/omission provenance.

    The task is used only for deterministic lexical ranking. The caller must
    retain its exact wording separately. No source or test is executed.
    """
    root = Path(root).resolve(strict=True)
    if not root.is_dir() or _is_link(root):
        raise ValueError("repository context root must be a real directory")
    if not isinstance(task, str) or not task.strip():
        raise ValueError("direct task must be nonempty")
    forbidden = frozenset(str(item).replace("\\", "/").casefold() for item in forbidden_paths)
    if any(item.startswith("/") or ".." in item.split("/") for item in forbidden):
        raise ValueError("frozen-test exclusions must be repository-relative")
    query = _tokens(task)
    records = []
    files, excluded_subtrees = _files(root, forbidden)
    for rel, path, reason in files:
        row = {"path": rel, "reason": reason, "included_sections": []}
        if reason:
            records.append((row, None, (), 0))
            continue
        size = path.stat().st_size
        if size > MAX_SOURCE_BYTES:
            row["reason"] = "source_over_read_bound"
            records.append((row, None, (), 0))
            continue
        raw = path.read_bytes()
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            row["reason"] = "not_utf8_source"
            records.append((row, None, (), 0))
            continue
        if "\x00" in content:
            row["reason"] = "binary_nul"
            records.append((row, None, (), 0))
            continue
        row.update({"sha256": _sha(raw), "bytes": len(raw), "chars": len(content)})
        symbols = tuple(sorted(set(match.group(1) or match.group(2)
                                   for match in SYMBOL_RE.finditer(content))))
        path_text = rel.casefold()
        stem = path.stem.casefold()
        lowered = content.casefold()
        score = sum(60 for token in query if token == stem)
        score += sum(15 for token in query if token in path_text)
        score += sum(8 for token in query if any(token in symbol.casefold() for symbol in symbols))
        score += sum(min(lowered.count(token), 3) for token in query)
        # Source-type preference breaks meaningful ties; it is not relevance.
        if score and rel.startswith("src/main/"):
            score += 2
        row["rank_score"] = score
        row["symbols"] = symbols[:80]
        records.append((row, content, symbols, score))

    index_lines = ["REPOSITORY INDEX (read-only; paths and declarations)\n"]
    index_used = len(index_lines[0])
    for row, content, symbols, _ in sorted(records, key=lambda item: item[0]["path"]):
        if content is None:
            continue
        line = row["path"] + (" :: " + ", ".join(symbols[:12]) if symbols else "") + "\n"
        if index_used + len(line) > INDEX_CHAR_BUDGET:
            row["index_status"] = "omitted_index_budget"
            continue
        index_lines.append(line)
        index_used += len(line)
        row["index_status"] = "included"
    blocks = ["".join(index_lines), "\nSELECTED REPOSITORY SOURCE (read-only)\n"]
    remaining = CONTEXT_CHAR_BUDGET - sum(map(len, blocks))
    selected = 0
    for row, content, _, score in sorted(records, key=lambda item: (-item[3], item[0]["path"])):
        if content is None:
            continue
        if score <= 0:
            row["reason"] = "no_task_relevance"
            continue
        if selected >= MAX_SELECTED_FILES:
            row["reason"] = "file_count_budget"
            continue
        header = f"\n===== FILE: {row['path']} =====\n"
        footer = f"\n===== END FILE: {row['path']} =====\n"
        available = min(FILE_CHAR_BUDGET, remaining - len(header) - len(footer))
        if available < 1500:
            row["reason"] = "context_char_budget"
            continue
        if len(content) <= available:
            excerpt = content
            row["included_sections"] = [{"start_line": 1, "end_line": len(content.splitlines())}]
            row["reason"] = "full_source"
        else:
            excerpt, sections = _line_windows(content, query, available - 200)
            if not excerpt:
                row["reason"] = "no_fitting_excerpt"
                continue
            row["included_sections"] = sections
            row["reason"] = "bounded_relevant_excerpts"
        block = header + excerpt + footer
        if len(block) > remaining:
            raise AssertionError("context allocator exceeded its budget")
        blocks.append(block)
        remaining -= len(block)
        selected += 1
    context = "".join(blocks)
    if len(context) > CONTEXT_CHAR_BUDGET:
        raise AssertionError("direct context exceeds the declared character budget")
    manifest = {
        "policy": "deterministic-path-symbol-lexical-v1",
        "context_char_budget": CONTEXT_CHAR_BUDGET,
        "request_field_char_budget": MAX_REQUEST_FIELD_CHARS,
        "context_chars": len(context),
        "context_sha256": _sha(context.encode("utf-8")),
        "query_tokens": query,
        "excluded_subtrees": excluded_subtrees,
        "files": [row for row, _, _, _ in sorted(records, key=lambda item: item[0]["path"])],
    }
    return context, manifest


def direct_prompt(instructions: str, task: str, context: str) -> str:
    field = f"{instructions}\n\nTASK REQUEST (verbatim):\n{task}\n\n{context}"
    if len(field) > MAX_REQUEST_FIELD_CHARS:
        raise ValueError("direct request field exceeds the predeclared safe bound")
    return field
