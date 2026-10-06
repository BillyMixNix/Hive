"""HIVE-TRANSITION-001: scope must be actionable before correction is spent."""
import copy
import json
from pathlib import Path

import pytest

from workshop import hive
from workshop.hive_protocol import PLAN_SCHEMA, response_schema_for_prompt
from test_host_write_scope import (
    ALLOWED, OUTSIDE, plan, plan_with_unauthorized_test_role, run_fixture,
)

ARTIFACTS = Path(__file__).resolve().parents[2] / 'evidence/ordinal-03'
HISTORICAL_SCOPE = ['src/main/java/dev/atmcompanion/state/SnapshotFormatter.java']


@pytest.fixture
def scoped():
    tokens = [(hive._HOST_WRITE_SCOPE, hive._HOST_WRITE_SCOPE.set(tuple(HISTORICAL_SCOPE))),
              (hive._ACTIVE_AGENT_SCOPES, hive._ACTIVE_AGENT_SCOPES.set(hive.EXTERNAL_AGENT_SCOPES)),
              (hive._EXTERNAL_ROOT_MODE, hive._EXTERNAL_ROOT_MODE.set(True))]
    yield
    for var, token in reversed(tokens):
        var.reset(token)


@pytest.mark.parametrize('attempt', [1, 2])
def test_preserved_planner_artifacts_remain_rejected_with_scope_diagnostic(scoped, attempt):
    raw = (ARTIFACTS / f'planner-{attempt}.response.txt').read_text()
    parsed = hive._extract_json(raw)
    before = copy.deepcopy(parsed)
    with pytest.raises(hive.HostWriteScopeError) as failure:
        hive._normalize_plan(parsed)
    assert 'SnapshotFormatterTest.java' in str(failure.value)
    if attempt == 1:
        assert 'multi-role plan requires at least one interface contract' in str(failure.value)
    assert parsed == before  # No dropping the offending assignment or inventing a plan.


def test_valid_equivalent_historical_plan_passes_without_invented_contract(scoped):
    p = json.loads((ARTIFACTS / 'planner-1.response.txt').read_text())
    p['tests_goal'] = 'no change needed'
    p['worker_files']['tests'] = []
    p['worker_acceptance']['tests'] = []
    normalized, warnings = hive._normalize_plan(p)
    hive._validate_host_write_scope(normalized)
    assert not warnings
    assert normalized['worker_files']['backend'] == HISTORICAL_SCOPE
    assert normalized['interface_contracts'] == []


@pytest.mark.parametrize('raw', ['{"summary":', '[]', '{"worker_files": 4}',
                                '{"summary":"x","worker_files":{"backend":[null]}}'])
def test_malformed_plans_still_rejected(scoped, raw):
    with pytest.raises((ValueError, TypeError)):
        hive._normalize_plan(hive._extract_json(raw))


def test_both_scoped_schemas_exclude_unauthorized_paths_and_keep_global_schema(scoped):
    before = copy.deepcopy(PLAN_SCHEMA)
    raw = (ARTIFACTS / 'planner-1.response.txt').read_text()
    with pytest.raises(hive.HostWriteScopeError) as failure:
        hive._normalize_plan(hive._extract_json(raw))
    first = hive._planner_prompt('Change behavior', external_mode=True)
    correction = hive._plan_correction_prompt('Change behavior', '', raw, failure.value, external_mode=True)
    for prompt in (first, correction):
        schema = response_schema_for_prompt('planner', prompt)
        for branch in schema.get('anyOf', [schema]):
            for role in hive.AGENT_SCOPES:
                assert branch['properties']['worker_files']['properties'][role]['items']['enum'] == HISTORICAL_SCOPE
        assert "exact goal 'no change needed'" in prompt
    assert all('minItems' not in branch['properties']['interface_contracts']
               for branch in correction.response_schema['anyOf'])
    assert 'SnapshotFormatterTest.java' in correction
    assert PLAN_SCHEMA == before


def test_role_specific_schema_constraints_do_not_alias():
    token = hive._HOST_WRITE_SCOPE.set(('app.py', 'tests/test_app.py'))
    try:
        fields = hive._planner_response_schema()['properties']['worker_files']['properties']
        assert fields['backend']['items']['enum'] == ['app.py']
        assert fields['tests']['items']['enum'] == ['tests/test_app.py']
        assert fields['ui']['maxItems'] == 0
        assert 'maxItems' not in fields['backend'] or fields['backend']['maxItems'] == 20
    finally:
        hive._HOST_WRITE_SCOPE.reset(token)


def test_absent_authority_and_empty_authority_have_distinct_schemas():
    before = copy.deepcopy(PLAN_SCHEMA)
    assert hive._planner_response_schema() == before
    token = hive._HOST_WRITE_SCOPE.set(())
    try:
        fields = hive._planner_response_schema()['properties']['worker_files']['properties']
        assert all(field['maxItems'] == 0 for field in fields.values())
    finally:
        hive._HOST_WRITE_SCOPE.reset(token)
    assert PLAN_SCHEMA == before


def test_live_duplicate_ownership_is_rejected_before_dispatch(scoped):
    run = json.loads((ARTIFACTS.parent / 'live/01-J001-r1-qwen2.5-coder-14b-hive/run.json').read_text())
    for attempt in run['plan_attempts']:
        with pytest.raises(hive.HostWriteScopeError, match='assigned to both backend and tests'):
            hive._normalize_plan(hive._extract_json(attempt['raw']))


def test_overlap_correction_can_deactivate_role(tmp_path, monkeypatch):
    bad = plan_with_unauthorized_test_role()
    bad['worker_files']['tests'] = [ALLOWED]
    result, roles, prompts, checks, _ = run_fixture(tmp_path, monkeypatch, [bad, plan()])
    assert roles == ['planner', 'planner', 'backend', 'reviewer']
    assert 'assigned to both' in result['plan_attempts'][0]['failure']['exception_message']
    assert all('minItems' not in branch['properties']['interface_contracts']
               for branch in prompts[1][1].response_schema['anyOf'])
    assert result['changed_files'] == [ALLOWED] and len(checks) == 1


def test_repeated_overlap_correction_never_dispatches_workers(tmp_path, monkeypatch):
    bad = plan_with_unauthorized_test_role()
    bad['worker_files']['tests'] = [ALLOWED]
    result, roles, _, checks, _ = run_fixture(tmp_path, monkeypatch, [bad, bad])
    assert roles == ['planner', 'planner']
    assert not checks and not result['changed_files']
    assert result['status'] == 'failed'


def test_correction_of_masked_scope_can_dispatch_only_valid_worker(tmp_path, monkeypatch):
    bad = plan_with_unauthorized_test_role()
    bad['interface_contracts'] = []
    result, roles, prompts, checks, baseline = run_fixture(tmp_path, monkeypatch, [bad, plan()])
    assert roles == ['planner', 'planner', 'backend', 'reviewer']
    assert result['status'] == 'ready', result.get('errors')
    assert len(checks) == 1  # Synthetic verification sentinel, not a frozen acceptance result.
    assert result['changed_files'] == [ALLOWED]
    assert result['applied'] is False
    assert 'return 1;' in (baseline / ALLOWED).read_text()
    failure = result['plan_attempts'][0]['failure']
    assert failure['exception_type'] == 'HostWriteScopeError'
    assert OUTSIDE in failure['exception_message']
    assert 'multi-role plan requires' in failure['exception_message']
    assert all('minItems' not in branch['properties']['interface_contracts']
               for branch in prompts[1][1].response_schema['anyOf'])


@pytest.mark.parametrize('defect', ['scope', 'missing_contract', 'malformed'])
def test_bad_correction_never_dispatches_workers(tmp_path, monkeypatch, defect):
    bad = plan_with_unauthorized_test_role()
    bad['interface_contracts'] = []
    corrected = copy.deepcopy(bad)
    if defect == 'missing_contract':
        # All paths allowed, but the independently required multi-role contract is absent.
        corrected['worker_files']['tests'] = [ALLOWED]
    elif defect == 'malformed':
        corrected = {'summary': 'incomplete'}
    result, roles, _, checks, baseline = run_fixture(tmp_path, monkeypatch, [bad, corrected])
    assert roles == ['planner', 'planner']
    assert result['status'] == 'failed'
    assert not checks and not result['changed_files']
    assert result['verification'] is None
    assert len(result['plan_attempts']) == 2
    assert 'return 1;' in (baseline / ALLOWED).read_text()
