import ast
import json
from pathlib import Path
import shutil

import pytest

from workshop import hive, hive_edits

NODE = pytest.mark.skipif(not shutil.which('node'), reason='Node required for JS structure tests')


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return path


def apply(root, role, edit, files=None):
    return hive.apply_agent_edits(root, role, {'edits': [edit]}, files or [edit['path']])


@pytest.mark.parametrize('operation', ['insert_before_symbol', 'insert_after_symbol'])
@pytest.mark.parametrize('definition', ['def existing():\n    return 1',
                                      'async def existing():\n    return 1',
                                      'class existing:\n    value = 1'])
def test_python_complete_decorated_symbols(tmp_path, operation, definition):
    old = '# Unicode ahead: 😀 é\n@first\n@second(\n    "value"\n)\n' + definition + '\n'
    path = write(tmp_path, 'app.py', old)
    apply(tmp_path, 'backend', {'path': 'app.py', 'operation': operation,
                               'symbol': 'existing', 'insert': 'def added():\n    return 2\n'})
    text = path.read_text(encoding='utf-8')
    tree = ast.parse(text)
    existing = next(n for n in tree.body if getattr(n, 'name', None) == 'existing')
    assert [ast.unparse(x) for x in existing.decorator_list] == ['first', "second('value')"]
    assert definition in text
    names = [n.name for n in tree.body if isinstance(n, hive_edits.PY_SYMBOLS)]
    assert names == (['added', 'existing'] if operation == 'insert_before_symbol' else ['existing', 'added'])


@pytest.mark.parametrize('source,symbol', [
    ('def existing():\n    pass\n', 'missing'),
    ('def existing():\n    pass\ndef existing():\n    pass\n', 'existing'),
    ('def outer():\n    def nested():\n        pass\n', 'nested'),
])
def test_missing_ambiguous_and_nested_symbols_fail_closed(tmp_path, source, symbol):
    path = write(tmp_path, 'app.py', source)
    with pytest.raises(hive_edits.StructuralEditError, match='one top-level'):
        apply(tmp_path, 'backend', {'path': 'app.py', 'operation': 'insert_after_symbol',
                                   'symbol': symbol, 'insert': 'def added():\n    pass\n'})
    assert path.read_text() == source


def test_legacy_decorator_split_is_rejected(tmp_path):
    source = '@app.post("/restore")\ndef restore():\n    return 1\n'
    path = write(tmp_path, 'app.py', source)
    with pytest.raises(hive_edits.StructuralEditError) as caught:
        apply(tmp_path, 'backend', {'path': 'app.py', 'operation': 'insert_after_anchor',
            'anchor': '@app.post("/restore")', 'insert': '\n@app.get("/summary")\ndef summary():\n    return 0\n'})
    assert caught.value.detail['code'] == 'decorator_boundary'
    assert path.read_text() == source


@pytest.mark.parametrize('bad', ['def added(:\n    pass', 'return 2', 'def added():\n'])
def test_invalid_python_cannot_be_created(tmp_path, bad):
    with pytest.raises(hive_edits.StructuralEditError):
        apply(tmp_path, 'tests', {'path': 'tests/test_new.py', 'operation': 'create', 'replace': bad})
    assert not (tmp_path / 'tests/test_new.py').exists()


def test_structural_batch_is_atomic_across_files(tmp_path):
    original = 'def existing():\n    return 1\n'
    path = write(tmp_path, 'app.py', original)
    with pytest.raises(hive_edits.StructuralEditError):
        hive.apply_agent_edits(tmp_path, 'backend', {'edits': [
            {'path': 'app.py', 'operation': 'insert_after_symbol', 'symbol': 'existing',
             'insert': 'def added():\n    return 2\n'},
            {'path': 'workshop/new.py', 'operation': 'create', 'replace': 'def broken(:'},
        ]}, ['app.py', 'workshop/new.py'])
    assert path.read_text() == original
    assert not (tmp_path / 'workshop/new.py').exists()


@pytest.mark.parametrize('role,path,planned', [('backend', 'static/index.html', ['static/index.html']),
                                           ('backend', 'workshop/other.py', ['app.py']),
                                           ('ui', 'app.py', ['app.py']),
                                           ('tests', '../app.py', ['../app.py'])])
def test_new_primitives_never_bypass_ownership(tmp_path, role, path, planned):
    with pytest.raises(hive.EditValidationError):
        apply(tmp_path, role, {'path': path, 'operation': 'insert_before_symbol',
                              'symbol': 'existing', 'insert': 'def added():\n    pass\n'}, planned)
    assert not list(tmp_path.rglob('*'))


def test_unchanged_validator_sees_preflight_and_lowered_edit(tmp_path, monkeypatch):
    write(tmp_path, 'app.py', 'def existing():\n    return 1\n')
    original_validator = hive.validate_edit
    seen = []
    def validator(role, edit, planned):
        seen.append(dict(edit))
        return original_validator(role, edit, planned)
    monkeypatch.setattr(hive, 'validate_edit', validator)
    apply(tmp_path, 'backend', {'path': 'app.py', 'operation': 'insert_after_symbol',
                               'symbol': 'existing', 'insert': 'def added():\n    return 2\n'})
    assert len(seen) == 2
    assert all(e['operation'] == 'replace' and e['path'] == 'app.py' for e in seen)
    assert seen[1]['find'] == 'def existing():\n    return 1\n'


@NODE
@pytest.mark.parametrize('operation', ['insert_before_symbol', 'insert_after_symbol'])
@pytest.mark.parametrize('definition', [
    'async function existing(){ const r = /[{}]/; return `😀 ${"}"}`; }',
    'const existing = async () => { /* } misleading */ return {value: "{"}; };',
])
def test_js_parser_preserves_whole_top_level_symbols(tmp_path, operation, definition):
    source = '<script>const note="😀";\n' + definition + '\n</script>'
    path = write(tmp_path, 'static/index.html', source)
    apply(tmp_path, 'ui', {'path': 'static/index.html', 'operation': operation,
                         'symbol': 'existing', 'insert': 'async function added(){ return 2; }'})
    text = path.read_text(encoding='utf-8')
    assert definition in text
    _, scripts = hive_edits._web(text, '.html')
    assert {n['name'] for n in scripts[0][3]['symbols']} == {'existing', 'added'}


@NODE
def test_legacy_nested_js_handler_rejected(tmp_path):
    old = '<script>async function refreshStatus(){\n return 1;\n}</script>'
    path = write(tmp_path, 'static/index.html', old)
    with pytest.raises(hive_edits.StructuralEditError) as caught:
        apply(tmp_path, 'ui', {'path': 'static/index.html', 'operation': 'insert_after_anchor',
            'anchor': 'async function refreshStatus(){', 'insert': 'async function refreshSummary(){ return 2; }\n'})
    assert caught.value.detail['code'] == 'symbol_not_top_level'
    assert path.read_text() == old


@NODE
def test_js_duplicate_symbols_fail_closed(tmp_path):
    old = '<script>function f(){} function f(){}</script>'
    path = write(tmp_path, 'static/index.html', old)
    with pytest.raises(hive_edits.StructuralEditError, match='found 2'):
        apply(tmp_path, 'ui', {'path': 'static/index.html', 'operation': 'insert_after_symbol',
                             'symbol': 'f', 'insert': 'function added(){}'})
    assert path.read_text() == old


def test_js_parser_missing_is_a_failure_not_a_skip(tmp_path, monkeypatch):
    write(tmp_path, 'static/index.html', '<script>function f(){}</script>')
    monkeypatch.setattr(hive_edits.shutil, 'which', lambda _: None)
    with pytest.raises(hive_edits.StructuralEditError, match='Node.js is required'):
        apply(tmp_path, 'ui', {'path': 'static/index.html', 'operation': 'insert_after_symbol',
                             'symbol': 'f', 'insert': 'function added(){}'})


@pytest.mark.parametrize('selector', [{'heading': 'Spend telemetry'}, {'element_id': 'spend'}])
def test_html_card_is_inserted_after_complete_element(tmp_path, selector):
    old = '<section><div id="spend" class="card"><h3>Spend telemetry</h3><div id="usage">old</div></div></section>'
    path = write(tmp_path, 'static/index.html', old)
    apply(tmp_path, 'ui', {'path': 'static/index.html', 'operation': 'insert_after_element',
                         **selector, 'insert': '<div id="summary" class="card"><h3>Project Summary</h3></div>'})
    doc = hive_edits._html(path.read_text())
    spend, summary = [next(n for n in doc.nodes if n.attrs.get('id') == key) for key in ('spend', 'summary')]
    assert spend.parent is summary.parent
    assert spend.end < summary.start


@pytest.mark.parametrize('source,selector,insert', [
    ('<div id="a"></div>', {'element_id': 'missing'}, '<p>new</p>'),
    ('<div><h3>Same</h3></div><div><h3>Same</h3></div>', {'heading': 'Same'}, '<p>new</p>'),
    ('<div id="a"></div>', {'element_id': 'a'}, '<div>unclosed'),
    ('<div id="a"></div>', {'element_id': 'a'}, '<p id="a">duplicate</p>'),
    ('<div id="a"></div>', {'element_id': 'a'}, '<script>bad()</script>'),
])
def test_html_targets_and_fragments_fail_closed(tmp_path, source, selector, insert):
    path = write(tmp_path, 'static/index.html', source)
    with pytest.raises(hive_edits.StructuralEditError):
        apply(tmp_path, 'ui', {'path': 'static/index.html', 'operation': 'insert_after_element', **selector, 'insert': insert})
    assert path.read_text() == source


@NODE
def test_handler_binding_is_checked_after_complete_batch(tmp_path):
    old = '<div id="existing">old</div><script>function ready(){}</script>'
    path = write(tmp_path, 'static/index.html', old)
    hive.apply_agent_edits(tmp_path, 'ui', {'edits': [
        {'path': 'static/index.html', 'operation': 'insert_after_element', 'element_id': 'existing',
         'insert': '<button onclick="refreshSummary()">Refresh</button>'},
        {'path': 'static/index.html', 'operation': 'insert_after_symbol', 'symbol': 'ready',
         'insert': 'function refreshSummary(){return 1;}'},
    ]}, ['static/index.html'])
    assert 'refreshSummary' in path.read_text()


@NODE
def test_replacement_cannot_hide_new_handler_in_nested_scope(tmp_path):
    old = '<script>function ready(){}</script>'
    path = write(tmp_path, 'static/index.html', old)
    bad = '<button onclick="refreshSummary()">Go</button><script>function ready(){function refreshSummary(){}}</script>'
    with pytest.raises(hive_edits.StructuralEditError) as caught:
        apply(tmp_path, 'ui', {'path': 'static/index.html', 'operation': 'replace', 'find': old, 'replace': bad})
    assert caught.value.detail['code'] == 'handler_binding'
    assert path.read_text() == old


def test_new_schema_paths_remain_exact():
    schema = hive.agent_response_schema('backend', planned_files=['app.py'])
    implementation = next(branch for branch in schema['anyOf']
                          if branch.get('properties', {}).get('status', {}).get('enum') == ['implemented'])
    variants = implementation['properties']['edits']['items']['anyOf']
    assert all(v['properties']['path']['enum'] == ['app.py'] for v in variants)
    assert set(hive_edits.OPERATIONS) <= {op for v in variants for op in v['properties']['operation']['enum']}


@NODE
def test_module_binding_is_not_an_inline_global(tmp_path):
    source = '<div id="existing"></div><script type="module">function refreshSummary(){}</script>'
    path = write(tmp_path, 'static/index.html', source)
    with pytest.raises(hive_edits.StructuralEditError, match='no top-level binding'):
        apply(tmp_path, 'ui', {'path': 'static/index.html', 'operation': 'insert_after_element',
                             'element_id': 'existing', 'insert': '<button onclick="refreshSummary()">Go</button>'})
    assert path.read_text() == source


@NODE
def test_second_script_module_uses_its_own_parse_mode(tmp_path):
    source = '<script>function first(){}</script><script type="module">export function target(){}</script>'
    path = write(tmp_path, 'static/index.html', source)
    apply(tmp_path, 'ui', {'path': 'static/index.html', 'operation': 'insert_after_symbol', 'symbol': 'target',
                         'insert': 'export function added(){return 1;}'})
    _, scripts = hive_edits._web(path.read_text(), '.html')
    assert scripts[0][3]['globals'] == ['first']
    assert scripts[1][3]['globals'] == ['target', 'added']


@NODE
def test_parser_never_executes_proposed_javascript(tmp_path):
    probe = tmp_path / 'must-not-exist.txt'
    source = '<script>function existing(){}</script>'
    write(tmp_path, 'static/index.html', source)
    payload = "require('node:fs').writeFileSync(" + json.dumps(str(probe)) + ", 'executed');"
    apply(tmp_path, 'ui', {'path': 'static/index.html', 'operation': 'insert_after_symbol',
                         'symbol': 'existing', 'insert': payload})
    assert not probe.exists()


def test_unfinished_html_replacement_fails_closed(tmp_path):
    path = write(tmp_path, 'static/index.html', '<p>old</p>')
    with pytest.raises(hive_edits.StructuralEditError, match='unfinished HTML'):
        apply(tmp_path, 'ui', {'path': 'static/index.html', 'operation': 'replace', 'find': '<p>old</p>', 'replace': '<div'})
    assert path.read_text() == '<p>old</p>'


@pytest.mark.parametrize('source,anchor,insert', [
    ('@first\ndef same():\n    return 1\n@second\ndef same():\n    return 2\n',
     '@first', '\n@added\ndef new():\n    return 3\n'),
    ('class C:\n    @first\n    def existing(self):\n        return 1\n',
     '    @first', '\n    @added\n    def new(self):\n        return 2\n'),
    ('class C:\n    @first\n    def existing(self):\n        return 1\n',
     '    @first', '\n    def existing(self):\n        return 2\n'),
])
def test_decorator_guard_covers_duplicate_names_and_methods(tmp_path, source, anchor, insert):
    path = write(tmp_path, 'app.py', source)
    with pytest.raises(hive_edits.StructuralEditError) as caught:
        apply(tmp_path, 'backend', {'path': 'app.py', 'operation': 'insert_after_anchor',
                                   'anchor': anchor, 'insert': insert})
    assert caught.value.detail['code'] == 'decorator_boundary'
    assert path.read_text() == source
