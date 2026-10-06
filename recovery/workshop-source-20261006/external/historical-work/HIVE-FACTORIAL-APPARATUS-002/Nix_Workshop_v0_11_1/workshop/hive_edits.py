"""Boundary-aware edit lowering and deterministic structural checks.

This module has no write or scope authority. Hive checks ownership before
source access, then validates the lowered ordinary edit with its existing
validator. All proposed contents remain in memory until the batch is valid.
"""
from __future__ import annotations

import ast
from collections import Counter
from functools import lru_cache
import json
from pathlib import Path
import re
import shutil
import subprocess

from .hive_html import Document

OPERATIONS = frozenset({'insert_before_symbol', 'insert_after_symbol', 'insert_after_element'})
MAX_SOURCE_CHARS = 1_000_000
PY_SYMBOLS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
JS_SUFFIXES = {'.js', '.mjs', '.cjs'}
HTML_SUFFIXES = {'.html', '.htm'}


class StructuralEditError(ValueError):
    def __init__(self, message, *, path='', code='invalid_structure', line=None, operation='', symbol='', repairable=True):
        self.detail = {'code': code, 'path': path, 'operation': operation, 'message': str(message), 'repairable': repairable}
        if line is not None: self.detail['line'] = line
        if symbol: self.detail['symbol'] = symbol
        super().__init__(f'{path}: {message}' if path else str(message))


def policy_edit(edit):
    """Preflight new syntax through the UNCHANGED legacy ownership validator."""
    if edit.get('operation') not in OPERATIONS:
        return edit
    return {'path': edit.get('path'), 'operation': 'replace',
            'find': '[host will resolve a complete structural target]', 'replace': ''}


def _bounded(source, path):
    if len(source) > MAX_SOURCE_CHARS:
        raise StructuralEditError('source exceeds structural analysis limit', path=path, code='source_limit')


def _python(source, path):
    _bounded(source, path)
    try:
        tree = ast.parse(source, filename=path)
        # AST construction alone allows some errors such as a module-level return.
        compile(tree, path, 'exec')
        return tree
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise StructuralEditError(str(exc), path=path, code='python_syntax',
                                  line=getattr(exc, 'lineno', None)) from exc


@lru_cache(maxsize=48)
def _js_cached(node, source, mode):
    try:
        result = subprocess.run([node, '--max-old-space-size=128', str(Path(__file__).with_name('hive_js.cjs'))],
                                input=json.dumps({'source': source, 'mode': mode}),
                                capture_output=True, text=True, encoding='utf-8', timeout=10)
        data = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise StructuralEditError(f'JavaScript parser unavailable/failed: {exc}', code='js_parser', repairable=False) from exc
    if result.returncode or data.get('error'):
        raise StructuralEditError(data.get('error', 'JavaScript parse failed'), code='javascript_syntax',
                                  line=data.get('line'))
    return data


def _javascript(source, mode='script'):
    _bounded(source, '')
    node = shutil.which('node')
    if not node:
        raise StructuralEditError('Node.js is required for structural JavaScript validation; no edit was written',
                                  code='js_parser_unavailable', repairable=False)
    return _js_cached(node, source, mode)


def _html(source):
    _bounded(source, '')
    try:
        return Document(source)
    except (ValueError, RecursionError) as exc:
        raise StructuralEditError(str(exc), code='html_structure') from exc


def _web(source, suffix):
    if suffix in JS_SUFFIXES:
        return None, [(0, len(source), 'module' if suffix == '.mjs' else 'script',
                       _javascript(source, 'module' if suffix == '.mjs' else 'script'))]
    doc = _html(source)
    scripts = []
    for n, mode in doc.scripts():
        try:
            data = _javascript(source[n.start_end:n.end_start], mode)
        except StructuralEditError as exc:
            if exc.detail.get('line') is not None:
                exc.detail['line'] += source[:n.start_end].count('\n')
            raise
        scripts.append((n.start_end, n.end_start, mode, data))
    return doc, scripts


def _python_span(source, symbol, path):
    tree = _python(source, path)
    matches = [n for n in tree.body if isinstance(n, PY_SYMBOLS) and n.name == symbol]
    if len(matches) != 1:
        raise StructuralEditError(f'symbol {symbol!r} must identify one top-level definition; found {len(matches)}',
                                  path=path, code='symbol_resolution', symbol=symbol)
    node = matches[0]
    lines = source.splitlines(keepends=True)
    first = min([node.lineno] + [d.lineno for d in node.decorator_list])
    return sum(map(len, lines[:first - 1])), sum(map(len, lines[:node.end_lineno]))


def lower_edit(path, source, edit):
    """Resolve a named boundary to an ordinary exact replacement, without writes."""
    op = edit.get('operation')
    if op not in OPERATIONS: return edit
    suffix = Path(path).suffix.lower()
    insert = edit.get('insert')
    try:
        if not isinstance(insert, str) or not insert.strip():
            raise StructuralEditError('structural insertion requires nonempty insert text', code='edit_shape')
        if op == 'insert_after_element':
            if suffix not in HTML_SUFFIXES:
                raise StructuralEditError('element insertion requires an HTML file', code='unsupported_language')
            start, end = _html(source).after_element(edit)
        else:
            symbol = edit.get('symbol')
            if not isinstance(symbol, str) or not re.fullmatch(r'[A-Za-z_$][\w$]*', symbol):
                raise StructuralEditError('symbol must be an exact, unqualified top-level name', code='edit_shape')
            if suffix == '.py':
                _python(insert, path)
                start, end = _python_span(source, symbol, path)
            elif suffix in JS_SUFFIXES | HTML_SUFFIXES:
                _, scripts = _web(source, suffix)
                matches = [(base + n['start'], base + n['end'], mode)
                           for base, _, mode, data in scripts for n in data['symbols'] if n['name'] == symbol]
                if len(matches) != 1:
                    raise StructuralEditError(f'symbol {symbol!r} must identify one top-level definition; found {len(matches)}',
                                              code='symbol_resolution', symbol=symbol)
                start, end, mode = matches[0]
                _javascript(insert, mode)
            else:
                raise StructuralEditError('symbol insertion supports Python and JavaScript only', code='unsupported_language')
        original = source[start:end]
        if not original or source.count(original) != 1:
            raise StructuralEditError('resolved structural target is not a unique exact source span', code='symbol_resolution')
        addition = '\n\n' + insert.strip('\r\n') + '\n\n'
        replacement = addition + original if op == 'insert_before_symbol' else original + addition
        return {'path': edit['path'], 'operation': 'replace', 'find': original, 'replace': replacement}
    except (StructuralEditError, ValueError) as exc:
        if not isinstance(exc, StructuralEditError):
            exc = StructuralEditError(str(exc), code='html_target')
        exc.detail.update(path=path, operation=op)
        raise exc


def _python_decorators(tree):
    # Preserve every binding, including methods and repeated names (e.g.
    # overloads). A name-only dictionary would hide an earlier definition.
    result, counts = {}, Counter()
    def visit(node, scope=()):
        for child in ast.iter_child_nodes(node):
            child_scope = scope
            if isinstance(child, PY_SYMBOLS):
                counter_key = (scope, child.name)
                ordinal = counts[counter_key]
                counts[counter_key] += 1
                child_scope = scope + ((type(child).__name__, child.name, ordinal),)
                group = scope + ((type(child).__name__, child.name),)
                result.setdefault(group, []).append([ast.dump(d) for d in child.decorator_list])
            visit(child, child_scope)
    visit(tree)
    return result


def _assert_new_globals(fragment_names, old_names, new_names):
    old, new = Counter(old_names), Counter(new_names)
    for name in fragment_names:
        if old[name] or new[name] != 1:
            raise StructuralEditError(f'inserted symbol {name!r} must be a new top-level sibling, not nested or duplicated; '
                                      'use insert_before_symbol/insert_after_symbol', code='symbol_not_top_level', symbol=name)


def validate_transition(path, before, after, edit):
    """Validate syntax and the structural promises of each insertion."""
    op = edit.get('operation', 'replace')
    insertion = op == 'insert_after_anchor' or op in OPERATIONS
    fragment = edit.get('insert', edit.get('replace', '')) if insertion else ''
    suffix = Path(path).suffix.lower()
    try:
        if suffix == '.py':
            current = _python(after, path)
            if insertion:
                previous = _python(before, path)
                new_decorators = _python_decorators(current)
                for key, decorators in _python_decorators(previous).items():
                    if new_decorators.get(key) != decorators:
                        name = '.'.join(part[1] for part in key)
                        raise StructuralEditError(f'insertion moved or changed decorators on {name!r}; '
                                                  'insert before/after the complete symbol, never its decorator/header',
                                                  code='decorator_boundary', symbol=name)
                try:
                    piece = ast.parse(fragment)
                except SyntaxError:
                    piece = None  # An existing exact inline/body insertion may be a partial expression.
                if piece:
                    _assert_new_globals([n.name for n in piece.body if isinstance(n, PY_SYMBOLS)],
                                        [n.name for n in previous.body if isinstance(n, PY_SYMBOLS)],
                                        [n.name for n in current.body if isinstance(n, PY_SYMBOLS)])
        elif suffix in JS_SUFFIXES | HTML_SUFFIXES:
            _, new_scripts = _web(after, suffix)
            if insertion and op != 'insert_after_element':
                old_doc, old_scripts = _web(before, suffix)
                in_script = op in {'insert_before_symbol', 'insert_after_symbol'} or suffix in JS_SUFFIXES
                fragment_mode = next((mode for _, _, mode, data in old_scripts
                                      if any(n['name'] == edit.get('symbol') for n in data['symbols'])),
                                     old_scripts[0][2] if old_scripts else 'script')
                if op == 'insert_after_anchor' and suffix in HTML_SUFFIXES:
                    anchor = str(edit.get('anchor', edit.get('find', '')))
                    offset = before.index(anchor) + len(anchor)
                    in_script = any(start <= offset <= end for start, end, _, _ in old_scripts)
                    fragment_mode = next((mode for start, end, mode, _ in old_scripts if start <= offset <= end), fragment_mode)
                    if not in_script and any(n.start < offset < n.start_end or n.end_start < offset < n.end
                                             for n in old_doc.nodes):
                        raise StructuralEditError('insertion splits an HTML tag; target a complete element', code='html_boundary')
                if in_script:
                    try:
                        piece = _javascript(fragment, fragment_mode)
                    except StructuralEditError:
                        if op in OPERATIONS: raise
                        piece = None
                    if piece:
                        _assert_new_globals([n['name'] for n in piece['symbols']],
                                            [name for _, _, _, data in old_scripts for name in data['globals']],
                                            [name for _, _, _, data in new_scripts for name in data['globals']])
    except StructuralEditError as exc:
        exc.detail.update(path=path, operation=op)
        raise


def validate_file(path, original, proposed):
    """Cross-edit checks run on the complete in-memory proposal, not halfway through it."""
    suffix = Path(path).suffix.lower()
    if suffix not in HTML_SUFFIXES: return
    try:
        before, old_scripts = _web(original, suffix)
        after, new_scripts = _web(proposed, suffix)
        old_globals = {name for _, _, mode, data in old_scripts if mode == 'script' for name in data['globals']}
        new_globals = {name for _, _, mode, data in new_scripts if mode == 'script' for name in data['globals']}
        builtins = {'alert', 'confirm', 'prompt', 'fetch', 'setTimeout', 'clearTimeout', 'setInterval',
                    'clearInterval', 'parseInt', 'parseFloat', 'Number', 'String', 'Boolean', 'encodeURIComponent'}
        old_handlers = before.handlers()
        for handler in after.handlers():
            calls = _javascript(handler, 'handler')['calls']
            for name in calls:
                if (handler not in old_handlers or name in old_globals) and name not in new_globals | builtins:
                    raise StructuralEditError(f'inline HTML handler calls {name!r}, but it has no top-level binding; '
                                              'do not nest the handler in another function', code='handler_binding', symbol=name)
    except StructuralEditError as exc:
        exc.detail.update(path=path)
        raise
