import asyncio
from copy import deepcopy
import json

import pytest

from workshop import hive, hive_edits

SOURCE = '@app.post("/restore")\ndef restore():\n    return 1\n'
INSERT = '@app.get("/summary")\ndef summary():\n    return {"count": 1}\n'
BAD = {'status': 'implemented', 'summary': 'summary endpoint', 'risks': [], 'edits': [
    {'path': 'app.py', 'operation': 'insert_after_anchor', 'anchor': '@app.post("/restore")', 'insert': '\n' + INSERT}]}
GOOD = {'status': 'implemented', 'summary': 'summary endpoint', 'risks': [], 'edits': [
    {'path': 'app.py', 'operation': 'insert_before_symbol', 'symbol': 'restore', 'insert': INSERT}]}


def plan():
    return {'summary': 'Backend summary', 'ui_goal': 'no change needed',
            'backend_goal': 'Implement a summary endpoint', 'tests_goal': 'no change needed',
            'worker_files': {'ui': [], 'backend': ['app.py'], 'tests': []},
            'acceptance': ['Overall summary works'],
            'worker_acceptance': {'ui': [], 'backend': ['Own criterion: preserve the restore route'], 'tests': []}}


@pytest.fixture
def source(tmp_path, monkeypatch):
    root = tmp_path / 'source'
    root.mkdir()
    (root / 'app.py').write_text(SOURCE, encoding='utf-8')
    (root / 'workshop').mkdir()
    (root / 'workshop/helper.py').write_text('def helper():\n    return 1\n', encoding='utf-8')
    monkeypatch.setattr(hive, 'verify_tree', lambda stage: {'passed': True, 'checks': []})
    return root


def execute(source, callback):
    return asyncio.run(hive.run_build(source, source.parent / 'runs', 'original summary request', 'local', callback))


def reviewer():
    return {'approve': True, 'summary': 'review fixture', 'issues': [], 'confidence': 1}


def test_same_worker_repairs_before_any_write_and_keeps_actual_prompt_contract(source):
    calls = []
    async def call(role, prompt):
        calls.append(role)
        if role == 'planner': return json.dumps(plan())
        if role == 'reviewer': return json.dumps(reviewer())
        assert role == 'backend'
        if calls.count('backend') == 1:
            assert 'insert_before_symbol' in prompt and 'insert_after_element' not in prompt
            return json.dumps(BAD)
        assert prompt.startswith('STRUCTURAL EDIT REPAIR\n')
        assert 'Originating worker: backend' in prompt
        assert 'decorator_boundary' in prompt
        assert 'Own criterion: preserve the restore route' in prompt
        assert 'YOUR RESPONSIBILITY' in prompt and 'TEAM PLAN' in prompt
        assert 'COMPLETE replacement proposal' in prompt
        assert 'No file from the rejected proposal was written' in prompt
        assert json.dumps(BAD) in prompt
        schema = hive.response_schema_for_prompt(role, prompt)
        implementation = next(branch for branch in schema['anyOf']
                               if branch.get('properties', {}).get('status', {}).get('enum') == ['implemented'])
        variants = implementation['properties']['edits']['items']['anyOf']
        assert all(v['properties']['path']['enum'] == ['app.py'] for v in variants)
        stage = next((source.parent / 'runs').glob('*/stage/app.py'))
        assert stage.read_text() == SOURCE
        return json.dumps(GOOD)
    run = execute(source, call)
    assert calls == ['planner', 'backend', 'backend', 'reviewer']
    assert run['status'] == 'ready' and not run['applied']
    assert not run.get('errors')
    assert (source / 'app.py').read_text() == SOURCE
    history = run['edit_repairs']
    assert len(history) == 1 and history[0]['outcome'] == 'repaired'
    assert history[0]['original_payload'] == BAD and history[0]['repair_payload'] == GOOD
    assert history == run['agents']['backend']['edit_repairs']
    saved = json.loads((source.parent / 'runs' / run['id'] / 'run.json').read_text())
    assert saved['edit_repairs'] == history


@pytest.mark.parametrize('reply', [BAD, 'not json', {'status': 'plan_insufficient', 'blocker_type': 'scope_change', 'reason': '',
    'evidence': 'app.py', 'requested_files': ['workshop/helper.py'], 'requested_plan_change': 'need helper'}])
def test_second_invalid_reply_fails_closed_without_recursion(source, reply):
    calls = []
    async def call(role, prompt):
        calls.append(role)
        if role == 'planner': return json.dumps(plan())
        if role == 'reviewer': return json.dumps(reviewer())
        value = BAD if calls.count('backend') == 1 else reply
        return value if isinstance(value, str) else json.dumps(value)
    run = execute(source, call)
    assert calls == ['planner', 'backend', 'backend', 'reviewer']
    assert run['status'] == 'rejected' and not run['changed_files']
    assert run['edit_repairs'][0]['outcome'] == 'failed'
    assert run['agents']['backend']['failure'] in run['errors']
    if reply == BAD:
        assert run['agents']['backend']['failure']['edit_repair_repeated'] is True
    assert (source.parent / 'runs' / run['id'] / 'stage/app.py').read_text() == SOURCE


@pytest.mark.parametrize('bad_path', ['workshop/helper.py', 'static/index.html', '../outside.py'])
def test_repair_cannot_add_unplanned_cross_role_or_unsafe_files(source, bad_path):
    attempts = []
    async def call(role, prompt):
        if role == 'planner': return json.dumps(plan())
        if role == 'reviewer': return json.dumps(reviewer())
        attempts.append(prompt)
        value = deepcopy(BAD if len(attempts) == 1 else GOOD)
        if len(attempts) == 2:
            value['edits'].append({'path': bad_path, 'operation': 'create', 'replace': 'VALUE = 2\n'})
        return json.dumps(value)
    run = execute(source, call)
    assert len(attempts) == 2
    assert run['status'] == 'rejected' and not run['changed_files']
    assert run['agents']['backend']['failure']['exception_type'] == 'EditValidationError'
    assert (source.parent / 'runs' / run['id'] / 'stage/app.py').read_text() == SOURCE


def test_initial_ownership_violation_is_not_structurally_retried(source):
    calls = []
    async def call(role, prompt):
        calls.append(role)
        if role == 'planner': return json.dumps(plan())
        if role == 'reviewer': return json.dumps(reviewer())
        value = deepcopy(BAD)  # First edit is structurally bad; later edit breaks scope.
        value['edits'].append({'path': 'workshop/helper.py', 'operation': 'replace', 'find': '1', 'replace': '2'})
        return json.dumps(value)
    run = execute(source, call)
    assert calls == ['planner', 'backend', 'reviewer']
    assert run['edit_repairs'] == []
    assert run['agents']['backend']['failure']['exception_type'] == 'EditValidationError'


def test_repair_provider_failure_is_recorded_and_not_retried(source):
    calls = []
    async def call(role, prompt):
        calls.append(role)
        if role == 'planner': return json.dumps(plan())
        if role == 'reviewer': return json.dumps(reviewer())
        if calls.count('backend') == 1: return json.dumps(BAD)
        raise RuntimeError('normal provider/budget gate denied the repair')
    run = execute(source, call)
    assert calls.count('backend') == 2
    assert run['agents']['backend']['failure']['stage'] == 'agent_call'
    assert run['edit_repairs'][0]['outcome'] == 'failed'
    assert not run['changed_files'] and not run['applied']


@pytest.mark.parametrize('valid_after_replan', [False, True])
def test_edit_repair_budget_does_not_reset_after_approved_replan(source, valid_after_replan):
    original = plan()
    revised = deepcopy(original)
    revised['worker_files']['backend'].append('workshop/helper.py')
    calls = []
    async def call(role, prompt):
        calls.append(role)
        if role == 'planner':
            if calls.count('planner') == 1: return json.dumps(original)
            assert prompt.startswith('PLANNER REPLAN REQUEST')
            return json.dumps({'decision': 'revise', 'reason': 'authorize helper', 'plan': revised})
        if role == 'reviewer': return json.dumps(reviewer())
        if role != 'backend':
            return json.dumps({'status': 'implemented', 'summary': 'no change', 'edits': [], 'risks': []})
        backend_count = calls.count('backend')
        if backend_count == 1:
            return json.dumps(BAD)
        if 2 <= backend_count <= hive.MAX_OBSERVATIONS_PER_WORKER + 1:
            if backend_count == 2:
                assert prompt.startswith('STRUCTURAL EDIT REPAIR')
            return json.dumps({'status': 'observe', 'operation': 'search_text',
                'arguments': {'query': f'restore {backend_count - 1}'},
                'reason': 'Inspect the structural boundary before deciding whether a scope change is necessary'})
        if backend_count == hive.MAX_OBSERVATIONS_PER_WORKER + 2:
            return json.dumps({'status': 'plan_insufficient', 'blocker_type': 'scope_change', 'reason': 'summary needs helper',
                'evidence': 'workshop/helper.py owns the shared count', 'requested_files': ['workshop/helper.py'],
                'requested_plan_change': 'authorize the existing helper'})
        if backend_count == hive.MAX_OBSERVATIONS_PER_WORKER + 3:
            schema = hive.response_schema_for_prompt(role, prompt)
            implementation = next(branch for branch in schema['anyOf']
                                   if branch.get('properties', {}).get('status', {}).get('enum') == ['implemented'])
            assert implementation['properties']['edits']['items']['anyOf'][0]['properties']['path']['enum'] == ['app.py', 'workshop/helper.py']
            if valid_after_replan:
                value = deepcopy(GOOD)
                value['edits'].append({'path': 'workshop/helper.py', 'operation': 'insert_after_symbol',
                                      'symbol': 'helper', 'insert': 'def added_helper():\n    return 2\n'})
                return json.dumps(value)
        return json.dumps(BAD)
    run = execute(source, call)
    expected_backend_calls = hive.MAX_OBSERVATIONS_PER_WORKER + 3
    assert calls.count('backend') == expected_backend_calls
    assert calls[0] == 'planner' and calls[-1] == 'reviewer'
    assert len(run['edit_repairs']) == 1
    assert run['replans'][0]['decision'] == 'revise'
    if valid_after_replan:
        assert run['status'] == 'ready'
        assert run['changed_files'] == ['app.py', 'workshop/helper.py']
    else:
        assert run['agents']['backend']['failure']['edit_repair_budget_exhausted'] is True
        assert not run['changed_files']


def test_next_role_sees_repaired_proposal_as_read_only(source):
    p = plan()
    p.update(tests_goal='Add endpoint coverage')
    p['worker_files']['tests'] = ['tests/test_summary.py']
    p['worker_acceptance']['tests'] = ['Cover the summary']
    p['interface_contracts'] = [{
        'name': 'summary_test_contract',
        'owner': 'backend',
        'consumer_roles': ['tests'],
        'contract': 'The backend summary behavior is covered by the regression test.',
    }]
    backend_calls = []
    async def call(role, prompt):
        if role == 'planner': return json.dumps(p)
        if role == 'reviewer': return json.dumps(reviewer())
        if role == 'backend':
            backend_calls.append(prompt)
            return json.dumps(BAD if len(backend_calls) == 1 else GOOD)
        previous = prompt.split('===== PREVIOUS PROPOSALS', 1)[1]
        assert 'UNVERIFIED READ ONLY' in previous
        assert 'insert_before_symbol' in previous and 'insert_after_anchor' not in previous
        return json.dumps({'status': 'implemented', 'summary': 'test fixture', 'risks': [], 'edits': [
            {'path': 'tests/test_summary.py', 'operation': 'create', 'replace': 'def test_count():\n    assert 1 == 1\n'}]})
    run = execute(source, call)
    assert run['status'] == 'ready'
    assert run['changed_files'] == ['app.py', 'tests/test_summary.py']


def test_missing_anchor_gets_one_originating_worker_repair(source):
    calls = []
    async def call(role, prompt):
        calls.append(role)
        if role == 'planner': return json.dumps(plan())
        if role == 'reviewer': return json.dumps(reviewer())
        if calls.count('backend') == 1:
            return json.dumps({'status': 'implemented', 'summary': 'summary endpoint', 'risks': [], 'edits': [
                {'path': 'app.py', 'operation': 'replace', 'find': 'missing!', 'replace': 'x'}
            ]})
        assert prompt.startswith('STRUCTURAL EDIT REPAIR\n')
        assert 'anchor_resolution' in prompt
        return json.dumps(GOOD)
    run = execute(source, call)
    assert calls == ['planner', 'backend', 'backend', 'reviewer']
    assert run['status'] == 'ready'
    assert run['changed_files'] == ['app.py']
    assert run['edit_repairs'][0]['outcome'] == 'repaired'
    assert run['edit_repairs'][0]['diagnostic']['structural']['code'] == 'anchor_resolution'


def test_missing_parser_is_not_a_request_for_model_repair(source, monkeypatch):
    (source / 'static').mkdir()
    (source / 'static/index.html').write_text('<script>function ready(){}</script>')
    p = plan()
    p.update(ui_goal='Display a summary', backend_goal='no change needed')
    p['worker_files'] = {'ui': ['static/index.html'], 'backend': [], 'tests': []}
    p['worker_acceptance'] = {'ui': ['Display a summary'], 'backend': [], 'tests': []}
    monkeypatch.setattr(hive_edits.shutil, 'which', lambda _: None)
    calls = []
    async def call(role, prompt):
        calls.append(role)
        if role == 'planner': return json.dumps(p)
        if role == 'reviewer': return json.dumps(reviewer())
        return json.dumps({'edits': [{'path': 'static/index.html', 'operation': 'insert_after_symbol',
                                      'symbol': 'ready', 'insert': 'function summary(){}'}]})
    run = execute(source, call)
    assert calls == ['planner', 'ui', 'reviewer']
    assert run['edit_repairs'] == []
    assert run['agents']['ui']['failure']['structural']['repairable'] is False
