"""Bounded, read-only source context for Hive workers.

This module intentionally has no dependency on ``workshop.hive``.  Context is
evidence for a worker prompt; it is never a write authorization mechanism.
"""

from __future__ import annotations

import ast
from bisect import bisect_right
from html.parser import HTMLParser
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .hive_html import Document


MAX_OWNED_CONTEXT_CHARS = 16_000
MAX_INTEGRATION_CONTEXT_CHARS = 8_000
MAX_ENDPOINT_TEST_PATTERN_CHARS = 5_000
MAX_PREVIOUS_PROPOSAL_CHARS = 6_000
MAX_REQUESTED_CONTEXT_CHARS = 16_000
MAX_OWNED_PATHS = 20
MAX_STRUCTURAL_TARGET_CHARS = 4_000
MAX_OBSERVATION_RESULT_CHARS = 6_000
MAX_OBSERVATION_MATCHES = 40

_MAX_ANALYSIS_BYTES = 1_000_000
_SMALL_FILE_CHARS = 8_000
_MAX_FILE_EXCERPT_CHARS = 5_000
_MAX_EXCERPT_LINES = 36
_MAX_EXCERPT_BLOCKS = 6
_MAX_DISPLAY_PATH_CHARS = 240

_SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".html",
        ".htm",
        ".js",
        ".mjs",
        ".cjs",
        ".css",
        ".json",
        ".toml",
        ".ini",
        ".cfg",
        ".bat",
        ".cmd",
        ".java",
        ".kt",
        ".kts",
        ".gradle",
        ".xml",
        ".properties",
        ".sh",
        ".sql",
        ".scala",
        ".md",
        ".txt",
        ".yaml",
        ".yml",
    }
)

_EXCLUDED_PARTS = frozenset(
    {
        ".git",
        "vendor",
        ".venv",
        "venv",
        "env",
        "envs",
        "virtualenv",
        ".tox",
        ".pytest_cache",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".cache",
        "cache",
        "caches",
        "node_modules",
        "data",
        "media",
        "reports",
        "snapshots",
        "workspace",
        "hive_runs",
        "self_snapshots",
        "logs",
        "build",
        "dist",
        "releases",
    }
)

_INTEGRATION_TERMS = frozenset(
    {
        "api",
        "endpoint",
        "endpoints",
        "route",
        "routes",
        "fastapi",
        "testclient",
        "http",
        "request",
        "requests",
        "integration",
        "frontend",
        "browser",
        "fetch",
        "client",
    }
)
_QUERY_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "with",
        "for",
        "from",
        "into",
        "over",
        "this",
        "that",
        "these",
        "those",
        "are",
        "was",
        "were",
        "will",
        "would",
        "should",
        "could",
        "have",
        "has",
        "had",
        "not",
        "only",
        "read",
        "write",
        "file",
        "files",
        "context",
        "worker",
        "agent",
    }
)
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")

OBSERVATION_OPERATIONS = frozenset(
    {"search_text", "list_symbols", "read_symbol", "read_file_excerpt", "find_similar_code"}
)


@dataclass(frozen=True)
class _ReadResult:
    text: str | None
    size: int = 0
    truncated: bool = False
    reason: str = ""


def _raw_path(value: object) -> str:
    try:
        raw = os.fspath(value)  # type: ignore[arg-type]
    except TypeError:
        raw = str(value or "")
    return str(raw).replace("\\", "/").strip()


def _display_path(value: object) -> str:
    raw = _raw_path(value)
    if len(raw) <= _MAX_DISPLAY_PATH_CHARS:
        return raw
    return raw[:_MAX_DISPLAY_PATH_CHARS] + "… [PATH DISPLAY TRUNCATED]"


def _safe_relative(value: object) -> tuple[str, str]:
    """Normalize an exact relative path, returning ``(path, reason)``."""

    # Validate the complete input.  Display clipping is presentation-only and
    # must never change which path is resolved or read.
    raw = _raw_path(value)
    if not raw:
        return raw, "empty path"
    if "\x00" in raw:
        return raw, "NUL in path"
    if _WINDOWS_ABSOLUTE_RE.match(raw) or raw.startswith("/") or raw.startswith("//"):
        return raw, "absolute path"
    if ":" in raw:
        return raw, "drive or stream path"

    parts: list[str] = []
    for part in raw.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            return raw, "path traversal"
        if part.startswith(".") or part.casefold() in _EXCLUDED_PARTS:
            return raw, "excluded path"
        if any(ch in part for ch in "*?["):
            return raw, "non-exact path"
        parts.append(part)
    if not parts:
        return raw, "empty path"
    return "/".join(parts), ""


def _resolved_root(root: Path) -> Path:
    try:
        return Path(root).resolve(strict=False)
    except (OSError, RuntimeError):
        return Path(root).absolute()


def _resolve_inside(root: Path, rel: str) -> tuple[Path | None, str]:
    candidate = root.joinpath(*rel.split("/"))
    try:
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        return None, "could not resolve path"
    try:
        resolved.relative_to(root)
    except ValueError:
        return None, "symlink resolves outside root"
    try:
        resolved_rel = resolved.relative_to(root).as_posix()
    except ValueError:
        return None, "symlink resolves outside root"
    if resolved_rel:
        _, target_reason = _safe_relative(resolved_rel)
        if target_reason:
            return None, f"symlink resolves to {target_reason}"
    return resolved, ""


def _is_source_path(rel: str) -> bool:
    return Path(rel).suffix.casefold() in _SOURCE_SUFFIXES


def _looks_binary(data: bytes) -> bool:
    sample = data[:8_192]
    if b"\x00" in sample:
        return True
    controls = sum(
        1
        for byte in sample
        if (byte < 9 or 14 <= byte < 32) and byte not in (9, 10, 13)
    )
    return controls > max(4, len(sample) // 100)


def _read_source(path: Path, rel: str) -> _ReadResult:
    if not _is_source_path(rel):
        return _ReadResult(None, reason="non-source or binary")
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            data = handle.read(_MAX_ANALYSIS_BYTES + 1)
    except (OSError, ValueError) as exc:
        return _ReadResult(None, reason=f"read failed: {type(exc).__name__}")
    if _looks_binary(data):
        return _ReadResult(None, size=size, reason="non-source or binary")
    truncated = len(data) > _MAX_ANALYSIS_BYTES
    try:
        text = data[:_MAX_ANALYSIS_BYTES].decode("utf-8")
    except UnicodeDecodeError:
        return _ReadResult(None, size=size, truncated=truncated, reason="non-source or binary")
    return _ReadResult(text, size=size, truncated=truncated)


def _exact_file(root: Path, value: object) -> tuple[str, Path | None, _ReadResult]:
    display = _display_path(value)
    rel, reason = _safe_relative(value)
    if reason:
        return display, None, _ReadResult(None, reason=reason)
    resolved, resolve_reason = _resolve_inside(root, rel)
    if resolve_reason or resolved is None:
        return rel, None, _ReadResult(None, reason=resolve_reason or "unsafe path")
    try:
        if not resolved.exists():
            return rel, resolved, _ReadResult(None, reason="file does not exist")
        if not resolved.is_file():
            return rel, resolved, _ReadResult(None, reason="not a regular file")
    except OSError as exc:
        return rel, None, _ReadResult(None, reason=f"stat failed: {type(exc).__name__}")
    return rel, resolved, _read_source(resolved, rel)


def _unique_paths(values: Iterable[object] | object | None) -> list[object]:
    if values is None:
        return []
    if isinstance(values, (str, bytes, os.PathLike)):
        values = [values]
    result: list[object] = []
    seen: set[str] = set()
    try:
        iterator = iter(values)  # type: ignore[arg-type]
    except TypeError:
        iterator = iter([values])
    for value in iterator:
        key = _raw_path(value).casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= MAX_OWNED_PATHS:
            break
    return result


def _marker(label: str, rel: str) -> str:
    return f"===== {label}: {rel} =====\n"


def _query_tokens(query: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                token.casefold()
                for token in _TOKEN_RE.findall(query or "")
                if token.casefold() not in _QUERY_STOPWORDS
            }
        )
    )


def _word_tokens(text: str) -> list[str]:
    words: list[str] = []
    for token in _TOKEN_RE.findall(text.casefold()):
        words.append(token)
        words.extend(part for part in token.split("_") if len(part) >= 3)
    return words


def _token_count(text: str, token: str) -> int:
    return sum(1 for found in _word_tokens(text) if found == token)


def _matched_terms(text: str, tokens: tuple[str, ...]) -> int:
    words = set(_word_tokens(text))
    return sum(token in words for token in tokens)


def _clip_line(line: str, limit: int = 420) -> str:
    if len(line) <= limit:
        return line
    return line[: max(0, limit - 23)] + " [LINE TRUNCATED]"


def _web_terms(text: str) -> set[str]:
    # Keep full identifiers and split camelCase / snake_case for natural queries.
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return set(_query_tokens(text)) | set(_query_tokens(parts.replace("_", " ")))


class _HtmlRegions(HTMLParser):
    """Index containers and headings; offsets always refer to original source."""
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.regions = []
        self.stack = []
        self.heading = False
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag in {"section", "article", "main", "aside", "form", "dialog"} or (tag == "div" and "id" in attributes):
            region = {"tag": tag, "start": self.getpos()[0], "end": None,
                      "label": attributes.get("id", ""), "depth": len(self.stack)}
            self.regions.append(region)
            self.stack.append(region)
        elif tag == "div":
            # Track nested divs so their end tags do not close an indexed parent.
            self.stack.append({"tag": tag})
        if re.fullmatch(r"h[1-6]", tag):
            self.heading = True

    def handle_endtag(self, tag):
        if re.fullmatch(r"h[1-6]", tag):
            self.heading = False
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                for region in self.stack[index:]:
                    if "start" in region:
                        region["end"] = self.getpos()[0]
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.heading:
            for region in reversed(self.stack):
                if "label" in region:
                    region["label"] += " " + data
                    break


def _js_symbols(text: str) -> dict[str, tuple[int, int, str]]:
    # Mask strings/comments before balancing delimiters, preserving line offsets.
    masked = re.sub(r"//[^\n]*|/\*[\s\S]*?\*/|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`",
                    lambda match: re.sub(r"[^\n]", " ", match.group()), text)
    line_starts = [0] + [match.end() for match in re.finditer("\n", text)]

    def closing(start, left, right):
        depth = 0
        for position in range(start, len(masked)):
            if masked[position] == left: depth += 1
            elif masked[position] == right:
                depth -= 1
                if depth == 0: return position
        return None

    symbols = {}
    pattern = r"(?m)^[ \t]*(?:async\s+)?function\s+([\w$]+)\s*(\()|^[ \t]*(?:const|let|var)\s+([\w$]+)\s*=\s*(?:async\s*)?(?:\([^\n;]*\)|[\w$]+)\s*=>\s*(\{)"
    for match in re.finditer(pattern, masked):
        name = match.group(1) or match.group(3)
        body = match.end() - 1
        if match.group(1):
            params_end = closing(body, "(", ")")
            if params_end is None: continue
            body = params_end + 1
            while body < len(masked) and masked[body].isspace(): body += 1
            if body >= len(masked) or masked[body] != "{": continue
        end = closing(body, "{", "}")
        if end is not None:
            symbols[name] = (bisect_right(line_starts, match.start()),
                             bisect_right(line_starts, end), text[body:end + 1])
    return symbols


def _web_excerpt_candidates(rel, text, query):
    tokens = _web_terms(query)
    lines = text.splitlines()
    symbols = _js_symbols(text)
    candidates, handlers = [], set()
    if Path(rel).suffix.casefold() in {".html", ".htm"}:
        regions = _HtmlRegions(text).regions
        for region in regions:
            hits = len(tokens & _web_terms(region["label"]))
            if not hits: continue
            start = region["start"]
            end = min(region["end"] or start + 8, start + _MAX_EXCERPT_LINES - 1)
            region_text = "\n".join(lines[start - 1:end])
            candidates.append((1500 + hits * 100 + region["depth"], start, end, "HTML region id/heading"))
            for attr in re.finditer(r'''\bon\w+\s*=\s*(["'])(.*?)\1''', region_text):
                handlers.update(re.findall(r"([\w$]+)\s*\(", attr.group(2)))
    roots = []
    for name, (start, end, body) in symbols.items():
        hits = len(tokens & _web_terms(name))
        if not hits and name not in handlers: continue
        rank = 1000 + hits * 80 + (200 if name in handlers and hits else 0)
        if not hits: rank = 400
        roots.append((rank, name))
        candidates.append((rank, start, min(end, start + _MAX_EXCERPT_LINES - 1), "JavaScript symbol " + name))
    # Link the strongest task-related handlers to local helper definitions.
    # This surfaces api()/requestJSON() without hard-coding their names.
    for rank, name in sorted(roots, reverse=True)[:2]:
        if rank < 1000: continue
        for helper in dict.fromkeys(re.findall(r"([\w$]+)\s*\(", symbols[name][2])):
            if helper == name or helper not in symbols: continue
            start, end, _ = symbols[helper]
            candidates.append((rank - 1, start, min(end, start + _MAX_EXCERPT_LINES - 1), "JavaScript helper " + helper))
    return candidates


def _excerpt_candidates(rel: str, text: str, query: str) -> list[tuple[int, int, int, str]]:
    lines = text.splitlines()
    tokens = _query_tokens(query)
    candidates: list[tuple[int, int, int, str]] = []
    web = Path(rel).suffix.casefold() in {".html", ".htm", ".js", ".mjs", ".cjs"}
    if web:
        candidates = _web_excerpt_candidates(rel, text, query)
        if candidates:
            return sorted(set(candidates), key=lambda item: (-item[0], item[1], item[2], item[3]))

    def add(start: int, end: int, rank: int, reason: str) -> None:
        if not lines:
            return
        start = max(1, min(start, len(lines)))
        end = max(start, min(end, len(lines)))
        if end - start + 1 > _MAX_EXCERPT_LINES:
            end = start + _MAX_EXCERPT_LINES - 1
        candidates.append((rank, start, end, reason))

    for index, line in enumerate(lines, 1):
        lowered = line.casefold()
        if re.match(r"\s*(from\s+\S+\s+import|import\s+)", line):
            add(index, min(index + 2, len(lines)), 70, "imports")
        if line.lstrip().startswith("@"):
            add(index, min(index + 3, len(lines)), 72, "decorator")
        line_words = set(_word_tokens(lowered))
        if tokens and any(token in line_words for token in tokens):
            rank = 86 + (10 * len(set(tokens) & line_words) if web else 0)
            add(max(1, index - 1), min(index + 1, len(lines)), rank, "query match")

    if Path(rel).suffix.casefold() in {".py", ".pyi"}:
        try:
            tree = ast.parse(text, filename=rel)
        except (SyntaxError, ValueError, TypeError):
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                start = node.lineno
                if node.decorator_list:
                    start = min([start] + [decorator.lineno for decorator in node.decorator_list])
                end = getattr(node, "end_lineno", None) or start
                node_text = " ".join(lines[start - 1 : min(end, start + _MAX_EXCERPT_LINES - 1)])
                lowered = f"{getattr(node, 'name', '')} {node_text}".casefold()
                name_hits = _matched_terms(str(getattr(node, "name", "")), tokens)
                body_hits = sum(min(_token_count(node_text, token), 3) for token in tokens)
                rank = 80 + name_hits * 45 + body_hits * 10
                add(start, end, rank, "AST function/class" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "AST class")

    if not candidates and lines:
        add(1, min(8, len(lines)), 20, "source header")
    return sorted(candidates, key=lambda item: (-item[0], item[1], item[2], item[3]))


def _bounded_excerpt(rel: str, text: str, size: int, query: str, limit: int) -> str:
    if limit <= 0:
        return ""
    lines = text.splitlines()
    intro = f"[BOUNDED EXCERPT: full file omitted; source size={size} bytes]\n"
    outro = "[END BOUNDED EXCERPT]\n"
    if not lines:
        return (intro + "[EMPTY SOURCE]\n" + outro)[:limit]

    if Path(rel).suffix.casefold() in {".html", ".htm", ".js", ".mjs", ".cjs"}:
        # Spend the same budget on complete, distinct regions before clipping.
        candidates = _excerpt_candidates(rel, text, query)
        selected = []
        remaining = limit - len(intro) - len(outro)
        while candidates and len(selected) < _MAX_EXCERPT_BLOCKS:
            def priority(item):
                rank, start, end, _ = item
                # Equal matches in adjacent lines should not exhaust the budget.
                nearby = sum(abs(start - prior[0]) < _MAX_EXCERPT_LINES for prior in selected)
                return (rank / (1 + nearby), -start, -end)
            candidate = max(candidates, key=priority)
            candidates.remove(candidate)
            _, start, end, reason = candidate
            if any(not (end < old_start or start > old_end) for old_start, old_end, _ in selected): continue
            block = f"[EXCERPT lines {start}-{end}; reason={reason}]\n" + "\n".join(_clip_line(line) for line in lines[start - 1:end]) + "\n"
            if len(block) > remaining: continue
            selected.append((start, end, block))
            remaining -= len(block)
        if selected:
            return intro + "".join(block for _, _, block in sorted(selected)) + outro
        # Tiny budgets still receive an explicitly clipped source excerpt below.

    pieces = [intro]
    used_ranges: list[tuple[int, int]] = []
    for _, start, end, reason in _excerpt_candidates(rel, text, query):
        if len(pieces) >= _MAX_EXCERPT_BLOCKS + 1:
            break
        if any(not (end < old_start or start > old_end) for old_start, old_end in used_ranges):
            continue
        block = "[EXCERPT lines {}-{}; reason={}]\n{}\n".format(
            start,
            end,
            reason,
            "\n".join(_clip_line(line) for line in lines[start - 1 : end]),
        )
        if sum(len(piece) for piece in pieces) + len(block) + len(outro) > limit:
            remaining = limit - sum(len(piece) for piece in pieces) - len(outro)
            if remaining > 80:
                pieces.append(block[:remaining].rstrip() + "\n[EXCERPT BLOCK TRUNCATED]\n")
            break
        pieces.append(block)
        used_ranges.append((start, end))
    pieces.append(outro)
    output = "".join(pieces)
    if len(output) <= limit:
        return output
    notice = "[BOUNDED EXCERPT: full file omitted]\n"
    tail = "\n[EXCERPT OUTPUT TRUNCATED]\n"
    if limit <= len(notice) + len(tail):
        return notice[:limit]
    return notice + output[len(notice) : limit - len(tail)] + tail


def _file_body(rel: str, read: _ReadResult, query: str, limit: int) -> str:
    if read.text is None:
        return f"[NOT READ: {read.reason}]\n"
    if not read.text:
        return "[EMPTY FILE]\n"
    full_text = read.text if read.text.endswith("\n") else read.text + "\n"
    if not read.truncated and len(read.text) <= _SMALL_FILE_CHARS:
        if len(full_text) <= limit:
            return full_text
        return _bounded_excerpt(rel, read.text, read.size, query, limit)
    return _bounded_excerpt(rel, read.text, read.size, query, min(limit, _MAX_FILE_EXCERPT_CHARS))


def _render_exact_section(
    root: Path,
    values: Iterable[object] | object | None,
    label: str,
    heading: str,
    budget: int,
    query: str,
) -> str:
    values_list = _unique_paths(values)
    header = f"===== {heading} (READ ONLY; NOT WRITE AUTHORIZATION) =====\n"
    if not values_list:
        return header + "[no exact paths supplied]\n"

    entries = []
    marker_total = len(header)
    for value in values_list:
        rel, _, read = _exact_file(root, value)
        actual_rel = rel or _display_path(value) or "<empty>"
        display = _display_path(actual_rel)
        marker = _marker(label, display)
        entries.append((actual_rel, read, marker))
        marker_total += len(marker)

    # Reserve space for every marker before reading any content.  This keeps
    # the ownership list visible even when all owned files are very large.
    content_left = max(0, budget - marker_total)
    blocks = [header]
    for index, (actual_rel, read, marker) in enumerate(entries):
        slots_left = len(entries) - index
        per_file_limit = content_left // slots_left if slots_left else content_left
        body = _file_body(actual_rel, read, query, per_file_limit)
        if len(body) > per_file_limit:
            body = "[CONTENT OMITTED]\n"[:per_file_limit]
        if len(body) > content_left:
            body = "[CONTENT OMITTED]\n"[:content_left]
        if body:
            content_left -= len(body)
        blocks.append(marker + body)
    return "".join(blocks)


def _prioritize_targets(values: Iterable[str], query: str, limit: int = 24) -> list[str]:
    """Keep structural edit targets compact while retaining source order.

    A worker still receives the complete owned source excerpt.  This index is
    only a deterministic list of names it can target, so it does not need to
    guess a placeholder anchor when the relevant source is large.
    """

    indexed = list(dict.fromkeys(value.strip() for value in values if value and value.strip()))
    original_order = {value: index for index, value in enumerate(indexed)}
    tokens = set(_web_terms(query))
    indexed.sort(key=lambda value: (
        0 if tokens & _web_terms(value) else 1,
        original_order[value],
    ))
    return indexed[:limit]


def _structural_targets(rel: str, text: str, query: str) -> dict[str, list[str]]:
    suffix = Path(rel).suffix.casefold()
    result: dict[str, list[str]] = {}
    if suffix in {".py", ".pyi"}:
        try:
            tree = ast.parse(text, filename=rel)
        except (SyntaxError, ValueError, TypeError):
            tree = None
        if tree is not None:
            result["top_level_symbol"] = _prioritize_targets(
                [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))],
                query,
            )
    elif suffix in {".html", ".htm"}:
        ids: list[str] = []
        headings: list[str] = []
        try:
            document = Document(text)
            ids = [str(node.attrs.get("id")) for node in document.nodes if node.attrs.get("id")]
            headings = [
                " ".join("".join(node.text).split())
                for node in document.nodes
                if node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}
            ]
        except (ValueError, RecursionError):
            ids = re.findall(r'''\bid\s*=\s*(["'])(.*?)\1''', text)
            ids = [item[1] for item in ids]
            headings = [
                " ".join(match.group(2).split())
                for match in re.finditer(r'''<h[1-6][^>]*>(.*?)</h[1-6]>''', text, re.I | re.S)
            ]
        if ids:
            result["element_id"] = _prioritize_targets(ids, query)
        if headings:
            result["direct_heading"] = _prioritize_targets(headings, query)
        symbols = _js_symbols(text)
        if symbols:
            result["top_level_symbol"] = _prioritize_targets(symbols, query)
    elif suffix in {".js", ".mjs", ".cjs"}:
        symbols = _js_symbols(text)
        if symbols:
            result["top_level_symbol"] = _prioritize_targets(symbols, query)
    return result


def _render_structural_targets(root: Path, values: Iterable[object] | object | None, query: str) -> str:
    """Render exact owned-file edit targets without granting write authority."""

    values_list = _unique_paths(values)
    header = "===== STRUCTURAL TARGET INDEX (READ ONLY; NOT WRITE AUTHORIZATION) =====\n"
    blocks = [header]
    used = len(header)
    for value in values_list:
        rel, path, read = _exact_file(root, value)
        if not rel or read.text is None:
            continue
        targets = _structural_targets(rel, read.text, query)
        if not targets:
            continue
        lines = [f"--- {rel} ---\n"]
        labels = (
            ("element_id", "HTML element_id targets"),
            ("direct_heading", "HTML direct-heading targets"),
            ("top_level_symbol", "top-level symbol targets"),
        )
        for key, label in labels:
            values_for_key = targets.get(key)
            if values_for_key:
                lines.append(f"{label}: {', '.join(values_for_key)}\n")
        block = "".join(lines)
        if used + len(block) > MAX_STRUCTURAL_TARGET_CHARS:
            remaining = MAX_STRUCTURAL_TARGET_CHARS - used
            if remaining > 80:
                blocks.append(block[:remaining] + "[STRUCTURAL TARGET INDEX BOUNDED]\n")
            break
        blocks.append(block)
        used += len(block)
    if len(blocks) == 1:
        blocks.append("[no deterministic structural targets found]\n")
    return "".join(blocks)


class ObservationError(ValueError):
    """A rejected or unavailable bounded read-only observation."""


def _bounded_observation(text: str, limit: int = MAX_OBSERVATION_RESULT_CHARS) -> tuple[str, bool]:
    text = str(text or "")
    if len(text) <= limit:
        return text, False
    marker = "\n[OBSERVATION RESULT BOUNDED]\n"
    return text[: max(0, limit - len(marker))] + marker, True


def _observation_file(root: Path, value: object) -> tuple[str, str, _ReadResult]:
    rel, _, read = _exact_file(_resolved_root(root), value)
    if read.text is None:
        raise ObservationError(f"cannot observe {rel or _display_path(value) or '<empty>'}: {read.reason}")
    return rel, read.text, read


def _observation_files(root: Path, value: object | None = None) -> list[tuple[str, Path, _ReadResult]]:
    resolved_root = _resolved_root(root)
    if value is not None:
        rel, path, read = _exact_file(resolved_root, value)
        if path is None or read.text is None:
            raise ObservationError(f"cannot observe {rel or _display_path(value) or '<empty>'}: {read.reason}")
        return [(rel, path, read)]
    return [
        (rel, path, read)
        for rel, path in _iter_source_files(resolved_root)
        if (read := _read_source(path, rel)).text is not None
    ]


def _observation_result(operation: str, text: str, **metadata: Any) -> dict[str, Any]:
    result, bounded = _bounded_observation(text)
    metadata = dict(metadata)
    metadata["result_chars"] = len(result)
    metadata["bounded"] = bounded
    return {"ok": True, "operation": operation, "metadata": metadata, "result": result}


def _read_python_symbol(rel: str, text: str, symbol: str) -> str | None:
    try:
        tree = ast.parse(text, filename=rel)
    except (SyntaxError, ValueError, TypeError):
        return None
    lines = text.splitlines()
    matches = [
        node for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == symbol
    ]
    if len(matches) != 1:
        return None
    node = matches[0]
    start = min([node.lineno] + [decorator.lineno for decorator in node.decorator_list])
    end = getattr(node, "end_lineno", None) or node.lineno
    return "\n".join(lines[start - 1 : end]) + "\n"


def _read_html_symbol(text: str, symbol: str) -> str | None:
    try:
        regions = _HtmlRegions(text).regions
    except (ValueError, RecursionError):
        return None
    lines = text.splitlines()
    matches = []
    for region in regions:
        label = str(region.get("label") or "").strip()
        first_label = label.split(None, 1)[0] if label else ""
        if first_label == symbol or label == symbol:
            matches.append(region)
    if len(matches) != 1:
        return None
    region = matches[0]
    start = max(1, int(region.get("start") or 1))
    end = min(len(lines), int(region.get("end") or start + _MAX_EXCERPT_LINES - 1))
    return "\n".join(lines[start - 1 : end]) + "\n"


def _read_js_symbol(text: str, symbol: str) -> str | None:
    entry = _js_symbols(text).get(symbol)
    if not entry:
        return None
    lines = text.splitlines()
    start, end, _ = entry
    return "\n".join(lines[start - 1 : end]) + "\n"


def observe(root: Path, operation: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Execute one deterministic, bounded, read-only repository observation.

    This function never imports or executes repository code and never returns a
    write authorization.  Exact path validation is shared with worker context.
    """

    operation = str(operation or "").strip().casefold()
    if operation not in OBSERVATION_OPERATIONS:
        raise ObservationError(f"unsupported observation operation: {operation or '<empty>'}")
    args = dict(arguments or {})

    if operation == "search_text":
        query = str(args.get("query") or "")
        if not query.strip():
            raise ObservationError("search_text requires a non-empty query")
        path_value = args.get("path")
        files = _observation_files(root, path_value) if path_value is not None else _observation_files(root)
        needle = query.casefold()
        matches: list[str] = []
        total = 0
        for rel, _, read in files:
            for line_number, line in enumerate(read.text.splitlines(), 1):
                if needle not in line.casefold():
                    continue
                total += 1
                if len(matches) < MAX_OBSERVATION_MATCHES:
                    matches.append(f"{rel}:{line_number}: {_clip_line(line)}")
        output = "\n".join(matches) or "[no matches]"
        if total > len(matches):
            output += f"\n[{total - len(matches)} additional matches omitted]"
        return _observation_result("search_text", output, matches=total, files_scanned=len(files))

    path_value = args.get("path")
    if operation != "find_similar_code" and path_value is None:
        raise ObservationError(f"{operation} requires an exact path")

    if operation == "find_similar_code":
        # This operation intentionally supports repository-wide search.  An
        # optional exact path narrows the deterministic candidate set, but it
        # is not required by the protocol.
        query = str(args.get("query") or "")
        if not query.strip():
            raise ObservationError("find_similar_code requires a non-empty query")
        files = _observation_files(root, path_value) if path_value is not None else _observation_files(root)
        tokens = _query_tokens(query)
        if not tokens:
            raise ObservationError("find_similar_code query has no searchable terms")
        candidates = []
        for candidate_rel, _, candidate_read in files:
            score = sum(min(_token_count(candidate_read.text, token), 8) * 10 for token in tokens)
            score += sum(min(_token_count(candidate_rel, token), 2) * 12 for token in tokens)
            if score > 0:
                candidates.append((score, candidate_rel, candidate_read))
        candidates.sort(key=lambda item: (-item[0], item[1].casefold(), item[1]))
        blocks = []
        for score, candidate_rel, candidate_read in candidates[:8]:
            body = _file_body(candidate_rel, candidate_read, query, 1_200)
            blocks.append(f"===== SIMILAR SOURCE: {candidate_rel} (score {score}) =====\n{body}")
        output = "\n".join(blocks) or "[no similar source found]"
        return _observation_result("find_similar_code", output, files_scored=len(files), matches=len(candidates))

    rel, text, read = _observation_file(root, path_value)

    if operation == "list_symbols":
        targets = _structural_targets(rel, text, "")
        output_lines = [f"path: {rel}"]
        for key in ("top_level_symbol", "element_id", "direct_heading"):
            values = targets.get(key) or []
            if values:
                output_lines.append(f"{key}: {', '.join(values)}")
        if len(output_lines) == 1:
            output_lines.append("[no deterministic symbols found]")
        return _observation_result("list_symbols", "\n".join(output_lines), path=rel)

    if operation == "read_file_excerpt":
        query = str(args.get("query") or "")
        try:
            limit = int(args.get("max_chars", 3_000))
        except (TypeError, ValueError) as exc:
            raise ObservationError("read_file_excerpt max_chars must be an integer") from exc
        if limit < 1 or limit > 4_000:
            raise ObservationError("read_file_excerpt max_chars must be between 1 and 4000")
        excerpt = _file_body(rel, read, query, limit)
        bounded, was_bounded = _bounded_observation(excerpt, limit)
        return {
            "ok": True,
            "operation": operation,
            "metadata": {"path": rel, "source_bytes": read.size, "result_chars": len(bounded), "bounded": was_bounded},
            "result": bounded,
        }

    if operation == "read_symbol":
        symbol = str(args.get("symbol") or "").strip()
        if not symbol:
            raise ObservationError("read_symbol requires a non-empty symbol")
        suffix = Path(rel).suffix.casefold()
        if suffix in {".py", ".pyi"}:
            excerpt = _read_python_symbol(rel, text, symbol)
        elif suffix in {".js", ".mjs", ".cjs"}:
            excerpt = _read_js_symbol(text, symbol)
        elif suffix in {".html", ".htm"}:
            excerpt = _read_html_symbol(text, symbol)
        else:
            excerpt = None
        if excerpt is None:
            raise ObservationError(f"symbol not found uniquely in {rel}: {symbol}")
        return _observation_result("read_symbol", excerpt, path=rel, symbol=symbol)

    raise ObservationError(f"unsupported observation operation: {operation}")


def _iter_source_files(root: Path) -> Iterable[tuple[str, Path]]:
    def onerror(_: OSError) -> None:
        return None

    for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False, onerror=onerror):
        dirnames[:] = sorted(
            [
                name
                for name in dirnames
                if not name.startswith(".")
                and name.casefold() not in _EXCLUDED_PARTS
                and not (Path(directory) / name).is_symlink()
            ],
            key=str.casefold,
        )
        for filename in sorted(filenames, key=str.casefold):
            path = Path(directory) / filename
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                continue
            safe_rel, reason = _safe_relative(rel)
            if reason or safe_rel != rel or not _is_source_path(safe_rel):
                continue
            resolved, resolve_reason = _resolve_inside(root, safe_rel)
            if resolve_reason or resolved is None:
                continue
            try:
                if not resolved.is_file():
                    continue
            except OSError:
                continue
            yield safe_rel, resolved


def _is_integration_query(query: str) -> bool:
    return bool(set(_query_tokens(query)) & _INTEGRATION_TERMS)


def _score_supporting(rel: str, text: str, agent: str, query: str) -> int:
    tokens = _query_tokens(query)
    if not tokens:
        return 0
    lowered = text.casefold()
    lowered_rel = rel.casefold()
    score = sum(min(_token_count(lowered, token), 8) * 10 for token in tokens)
    score += sum(min(_token_count(lowered_rel, token), 2) * 12 for token in tokens)
    integration = _is_integration_query(query)
    if integration:
        if lowered_rel == "app.py":
            score += 300
            if "fastapi" in lowered or "@app." in lowered or "apirouter" in lowered:
                score += 140
        if lowered_rel.startswith("tests/") and (
            "testclient" in lowered
            or "from app import" in lowered
            or "import app" in lowered
            or "fastapi" in lowered
        ):
            score += 260
        if lowered_rel.startswith("static/") and (
            "fetch(" in lowered or "/api/" in lowered or "endpoint" in lowered or "route" in lowered
        ):
            score += 190
        if "hive" in lowered_rel and "hive" not in tokens:
            score -= 700
    if agent.casefold() == "ui" and lowered_rel.startswith("static/"):
        score += 25
    if agent.casefold() == "tests" and lowered_rel.startswith("tests/"):
        score += 80
        if integration and (
            "testclient" in lowered
            or "from app import" in lowered
            or "import app" in lowered
            or "static/index.html" in lowered
            or "read_text(" in lowered
        ):
            score += 180
    if agent.casefold() == "backend" and lowered_rel == "app.py":
        score += 25
    return score


def _render_supporting(root: Path, agent: str, query: str, owned: set[str]) -> str:
    header = "===== INTEGRATION SUPPORTING CONTEXT (READ ONLY; NOT WRITE AUTHORIZATION) =====\n"
    candidates: list[tuple[int, str, Path, _ReadResult]] = []
    for rel, path in _iter_source_files(root):
        if rel.casefold() in owned:
            continue
        # Test fixtures are valuable when the tests worker owns them, but they
        # are a poor integration source for implementation workers.  They
        # commonly contain intentionally bogus model responses and adversarial
        # strings from protocol tests.  Feeding those fixtures to UI/backend
        # workers can make a small local model imitate the fixture instead of
        # implementing the current task.
        if rel.casefold().startswith("tests/") and agent.casefold() != "tests":
            continue
        read = _read_source(path, rel)
        if read.text is None:
            continue
        score = _score_supporting(rel, read.text, agent, query)
        if score > 0:
            candidates.append((score, rel, path, read))
    candidates.sort(key=lambda item: (-item[0], item[1].casefold(), item[1]))

    if not candidates:
        return header + "[no matching safe source context]\n"
    used = len(header)
    blocks = [header]
    for score, rel, _, read in candidates[:12]:
        marker = f"===== SUPPORTING FILE: {rel} (relevance {score}; read-only) =====\n"
        if used + len(marker) >= MAX_INTEGRATION_CONTEXT_CHARS:
            break
        body_limit = min(_MAX_FILE_EXCERPT_CHARS, MAX_INTEGRATION_CONTEXT_CHARS - used - len(marker))
        body = _file_body(rel, read, query, body_limit)
        if not body:
            continue
        if len(body) > body_limit:
            body = "[CONTENT OMITTED: bounded supporting context budget exhausted]\n"
        if used + len(marker) + len(body) > MAX_INTEGRATION_CONTEXT_CHARS:
            remaining = MAX_INTEGRATION_CONTEXT_CHARS - used - len(marker)
            body = body[: max(0, remaining)]
        if not body:
            break
        blocks.append(marker + body)
        used += len(marker) + len(body)
        if used >= MAX_INTEGRATION_CONTEXT_CHARS:
            break
    return "".join(blocks)


def endpoint_test_patterns(root: Path, query: str) -> str:
    """Return bounded repository-local TestClient patterns for test workers.

    A file qualifies only when it actually constructs a TestClient and uses
    that client for an HTTP method.  This excludes planner/protocol fixtures
    that merely mention endpoint text and prevents invented external clients
    or dependencies from becoming the default testing pattern.
    """

    header = (
        "===== REPOSITORY-LOCAL ENDPOINT TEST PATTERNS "
        "(READ ONLY; NOT WRITE AUTHORIZATION) =====\n"
        "Use the imports, in-process client construction, monkeypatch style, and HTTP calls shown here. "
        "Do not add an HTTP dependency or assume an external server unless a selected pattern does so.\n"
    )
    candidates: list[tuple[int, str, _ReadResult]] = []
    tokens = _query_tokens(query)
    for rel, path in _iter_source_files(_resolved_root(root)):
        if not rel.casefold().startswith("tests/") or Path(rel).suffix.casefold() != ".py":
            continue
        read = _read_source(path, rel)
        text = read.text or ""
        if "testclient" not in text.casefold():
            continue
        clients = re.findall(r"(?m)^\s*([A-Za-z_]\w*)\s*=\s*TestClient\s*\(", text)
        if not clients or not any(
            re.search(rf"\b{re.escape(client)}\.(?:get|post|put|patch|delete)\s*\(", text)
            for client in clients
        ):
            continue
        score = 500
        score += 250 if "endpoint" in Path(rel).stem.casefold() else 0
        score += sum(min(_token_count(text, token), 4) * 15 for token in tokens)
        score += sum(min(_token_count(rel, token), 2) * 20 for token in tokens)
        candidates.append((score, rel, read))
    candidates.sort(key=lambda item: (-item[0], item[1].casefold(), item[1]))
    if not candidates:
        return header + "[no repository-local in-process endpoint test pattern found]\n"

    blocks = [header]
    used = len(header)
    for score, rel, read in candidates[:3]:
        marker = f"===== ENDPOINT TEST PATTERN: {rel} (relevance {score}; read-only) =====\n"
        remaining = MAX_ENDPOINT_TEST_PATTERN_CHARS - used - len(marker)
        if remaining <= 120:
            break
        body = _file_body(rel, read, query, min(2_000, remaining))
        if len(body) > remaining:
            body = body[:remaining]
        blocks.append(marker + body)
        used += len(marker) + len(body)
    return "".join(blocks)


def _compact(value: Any, depth: int = 0) -> Any:
    if isinstance(value, str):
        return value if len(value) <= 600 else value[:600] + "… [value truncated]"
    if depth >= 6:
        return "[nested value omitted]"
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        items = sorted(value.items(), key=lambda item: str(item[0]).casefold())
        for index, (key, item) in enumerate(items):
            if index >= 20:
                output["…"] = f"{len(items) - 20} additional keys omitted"
                break
            output[str(key)] = _compact(item, depth + 1)
        return output
    if isinstance(value, (list, tuple)):
        output = [_compact(item, depth + 1) for item in value[:20]]
        if len(value) > 20:
            output.append(f"… {len(value) - 20} additional items omitted")
        return output
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:600]


def _json_preview(value: Any, limit: int = 1_800) -> str:
    try:
        rendered = json.dumps(_compact(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        rendered = json.dumps(str(value)[:600], ensure_ascii=False)
    if len(rendered) <= limit:
        return rendered
    return rendered[: max(0, limit - 31)] + "… [proposal truncated]"


def _render_previous_proposals(previous_proposals: Iterable[Mapping[str, Any]] | None) -> str:
    if not previous_proposals:
        return ""
    header = "===== PREVIOUS PROPOSALS (UNVERIFIED READ ONLY NOT AUTHORIZATION; bounded) =====\n"
    used = len(header)
    blocks = [header]
    try:
        proposals = iter(previous_proposals)
    except TypeError:
        proposals = iter(())
    for index, proposal in enumerate(proposals, 1):
        if not isinstance(proposal, Mapping):
            block = f"--- proposal {index} ---\nUNVERIFIED READ ONLY NOT AUTHORIZATION\n[invalid proposal shape]\n"
        else:
            parsed = proposal.get("parsed")
            if not isinstance(parsed, Mapping):
                parsed = {}
            response_status = parsed.get("status")
            if response_status not in {"implemented", "plan_insufficient"}:
                response_status = "unknown"
            edit_manifest = []
            for edit in parsed.get("edits", []) if isinstance(parsed.get("edits"), list) else []:
                if not isinstance(edit, Mapping):
                    continue
                # Keep only structural metadata.  Raw code, summaries, error
                # prose, anchors and other model-authored content are omitted
                # so an unrelated proposal cannot become a later worker's
                # pseudo-task while still exposing useful integration facts.
                path = edit.get("path")
                operation = edit.get("operation")
                if isinstance(path, str) and isinstance(operation, str):
                    edit_manifest.append({"path": path[:240], "operation": operation[:80]})
            failure = proposal.get("failure")
            failure_meta = {}
            if isinstance(failure, Mapping):
                for key in ("stage", "exception_type"):
                    value = failure.get(key)
                    if isinstance(value, str) and value:
                        failure_meta[key] = value[:120]
            block = (
                f"--- proposal {index} (UNVERIFIED READ ONLY NOT AUTHORIZATION) ---\n"
                f"role: {_json_preview(proposal.get('role', ''), 120)}\n"
                f"execution_status: {_json_preview(proposal.get('status', ''), 120)}\n"
                f"response_status: {_json_preview(response_status, 120)}\n"
                f"planned_files: {_json_preview(proposal.get('planned_files', []), 900)}\n"
                f"edit_manifest: {_json_preview(edit_manifest, 1_200)}\n"
            )
            if failure_meta:
                block += f"failure_metadata: {_json_preview(failure_meta, 300)}\n"
        if used + len(block) > MAX_PREVIOUS_PROPOSAL_CHARS:
            notice = "[PREVIOUS PROPOSALS TRUNCATED TO BOUNDED READ-ONLY CONTEXT]\n"
            if used + len(notice) <= MAX_PREVIOUS_PROPOSAL_CHARS:
                blocks.append(notice)
            break
        blocks.append(block)
        used += len(block)
    return "".join(blocks)


def previous_proposals_context(previous_proposals: Iterable[Mapping[str, Any]] | None) -> str:
    """Render sanitized proposal metadata for a later read-only consumer.

    This public wrapper is also used by replanning prompts so they cannot
    accidentally serialize raw worker output into a new model contract.
    """

    return _render_previous_proposals(previous_proposals)


def worker_context(
    root: Path,
    agent: str,
    query: str,
    planned_files,
    previous_proposals=(),
) -> str:
    """Return bounded worker context without granting write authority.

    ``planned_files`` are exact owned paths for display and read priority only.
    Supporting files are selected across safe source roles and are explicitly
    labeled read-only.  At most 20 owned paths are considered.
    """

    resolved_root = _resolved_root(root)
    owned_values = _unique_paths(planned_files)
    owned_text = _render_exact_section(
        resolved_root,
        owned_values,
        "OWNED FILE",
        "OWNED WORKER CONTEXT",
        MAX_OWNED_CONTEXT_CHARS,
        query,
    )
    owned_paths = set()
    for value in owned_values:
        rel, reason = _safe_relative(value)
        if not reason:
            owned_paths.add(rel.casefold())
    supporting_text = _render_supporting(resolved_root, agent, query, owned_paths)
    endpoint_patterns = endpoint_test_patterns(resolved_root, query) if agent.casefold() == "tests" else ""
    structural_text = _render_structural_targets(resolved_root, owned_values, query)
    proposals_text = previous_proposals_context(previous_proposals)
    # Keep the exact owned-file excerpt's legacy bound intact.  The target
    # index is separate read-only metadata, so it must not consume the file
    # excerpt budget or make consumers mistake it for source text.
    return owned_text + endpoint_patterns + supporting_text + structural_text + proposals_text


def requested_context(root: Path, files, query: str = "") -> str:
    """Return bounded, read-only context for explicitly requested files."""

    return _render_exact_section(
        _resolved_root(root),
        files,
        "REQUESTED FILE",
        "REQUESTED FILE CONTEXT",
        MAX_REQUESTED_CONTEXT_CHARS,
        query,
    )
