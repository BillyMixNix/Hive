"""Replay the actual v0.7.2 failure shapes against real Workshop source.

These are deterministic captured-proposal regressions, not live model tests.
"""
import ast
from pathlib import Path
import shutil

import pytest

from workshop import hive, hive_edits

ROOT = Path(__file__).resolve().parents[1]
FILES = ['app.py', 'static/index.html', 'tests/test_hive_endpoints.py', 'tests/test_hive_ui_retrieval.py']
UI_CODE = "async function refreshProjectSummary(){\n  let s=await api('/api/project/summary');\n  $('project-summary').textContent=`Workspace files: ${s.workspace_files}, Python files: ${s.python_files}, Total bytes: ${s.total_bytes}`;\n}"
CARD = '<div class="card"><h3>Project Summary</h3><div id="project-summary">—</div><button class="btn" onclick="refreshProjectSummary()">Refresh</button></div>'
BACKEND_CODE = '''@app.get("/api/project/summary")
def project_summary():
    workspace_files = 0
    python_files = 0
    total_bytes = 0
    for p in WORKSPACE.iterdir():
        if p.is_file():
            workspace_files += 1
            total_bytes += p.stat().st_size
            if p.suffix == ".py":
                python_files += 1
    return {"workspace_files": workspace_files, "python_files": python_files, "total_bytes": total_bytes}
'''
BAD = {
    'ui': [
        {'path': FILES[1], 'operation': 'insert_after_anchor', 'anchor': '<h3>Spend telemetry</h3>',
         'insert': CARD.replace('project-summary', 'boundary-bad-073').replace('refreshProjectSummary', 'boundaryBad073')},
        {'path': FILES[1], 'operation': 'insert_after_anchor', 'anchor': 'async function refreshStatus(){',
         'insert': UI_CODE.replace('project-summary', 'boundary-bad-073').replace('refreshProjectSummary', 'boundaryBad073')}],
    'backend': [{'path': FILES[0], 'operation': 'insert_after_anchor', 'anchor': '@app.post("/api/workspace/restore")', 'insert': '\n' + BACKEND_CODE}],
    'tests': [{'path': FILES[2], 'operation': 'insert_after_anchor', 'anchor': 'def test_hive_apply_requires_approval():',
               'insert': '\n\ndef test_project_summary_endpoint():\n    assert client.get("/api/project/summary").status_code == 200\n'},
              {'path': FILES[3], 'operation': 'insert_after_anchor', 'anchor': 'def test_real_settings_query_includes_markup_and_complete_refresh_helpers(tmp_path):',
               'insert': '\n\ndef test_project_summary_display():\n    assert True\n'}],
}


@pytest.fixture
def real_source(tmp_path):
    for rel in FILES:
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((ROOT / rel).read_bytes())
    return tmp_path


@pytest.mark.skipif(not shutil.which('node'), reason='Node required for actual UI checks')
@pytest.mark.parametrize('role,code', [('ui', 'symbol_not_top_level'), ('backend', 'decorator_boundary'), ('tests', 'python_syntax')])
def test_real_v072_failure_shapes_rejected_before_writes(real_source, role, code):
    baseline = {rel: (real_source / rel).read_bytes() for rel in FILES}
    with pytest.raises(hive_edits.StructuralEditError) as caught:
        hive.apply_agent_edits(real_source, role, {'edits': BAD[role]}, [e['path'] for e in BAD[role]])
    assert caught.value.detail['code'] == code
    assert {rel: (real_source / rel).read_bytes() for rel in FILES} == baseline


@pytest.mark.skipif(not shutil.which('node'), reason='Node required for actual UI checks')
def test_structural_replacement_operations_preserve_real_integration_boundaries(real_source):
    # Unique probe names keep this regression valid after Project Summary is
    # actually implemented in Workshop; do not assume the feature stays absent.
    probe_code = UI_CODE.replace('refreshProjectSummary', 'boundaryProbe073').replace('project-summary', 'boundary-probe-073')
    probe_card = CARD.replace('refreshProjectSummary', 'boundaryProbe073').replace('project-summary', 'boundary-probe-073')
    probe_backend = BACKEND_CODE.replace('project_summary', 'boundary_probe_073').replace('/api/project/summary', '/api/boundary-probe-073')
    hive.apply_agent_edits(real_source, 'ui', {'edits': [
        {'path': FILES[1], 'operation': 'insert_after_element', 'heading': 'Spend telemetry', 'insert': probe_card},
        {'path': FILES[1], 'operation': 'insert_after_symbol', 'symbol': 'refreshStatus', 'insert': probe_code},
    ]}, [FILES[1]])
    hive.apply_agent_edits(real_source, 'backend', {'edits': [
        {'path': FILES[0], 'operation': 'insert_before_symbol', 'symbol': 'restore_snapshot', 'insert': probe_backend},
    ]}, [FILES[0]])
    hive.apply_agent_edits(real_source, 'tests', {'edits': [
        {'path': FILES[2], 'operation': 'insert_after_symbol', 'symbol': 'test_hive_apply_requires_approval',
         'insert': 'def test_boundary_probe_endpoint_073():\n    assert client.get("/api/boundary-probe-073").status_code == 200\n'},
        {'path': FILES[3], 'operation': 'insert_after_symbol', 'symbol': 'test_real_settings_query_includes_markup_and_complete_refresh_helpers',
         'insert': 'def test_boundary_probe_display_073():\n    assert True\n'},
    ]}, FILES[2:])
    tree = ast.parse((real_source / 'app.py').read_text(encoding='utf-8'))
    functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert [ast.unparse(d) for d in functions['restore_snapshot'].decorator_list] == ["app.post('/api/workspace/restore')"]
    assert [ast.unparse(d) for d in functions['boundary_probe_073'].decorator_list] == ["app.get('/api/boundary-probe-073')"]
    doc, scripts = hive_edits._web((real_source / FILES[1]).read_text(encoding='utf-8'), '.html')
    assert 'boundaryProbe073' in scripts[0][3]['globals']
    summary = next(n for n in doc.nodes if n.attrs.get('id') == 'boundary-probe-073').parent
    spend = next(n for n in doc.nodes if n.attrs.get('id') == 'usage').parent
    assert summary.parent is spend.parent
    for rel in FILES[2:]:
        compile((real_source / rel).read_text(encoding='utf-8'), rel, 'exec')
