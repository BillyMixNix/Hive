"""Preserved planner input and fail-closed local context transport; no Ollama."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from workshop import hive, providers
from workshop.hive_protocol import LOCAL_CONTEXT_WINDOW, response_schema_for_prompt
from test_ollama_structured_output import mock_http, ollama_response, ChunkedStream
from test_planner_transition import scoped

FIXTURES = Path(__file__).resolve().parents[2] / 'evidence/planner-input-fixtures'


@pytest.mark.parametrize('attempt', [1, 2])
def test_historical_critical_information_survives_actual_http_serialization(mock_http, attempt):
    saved = json.loads((FIXTURES / f'{attempt:02d}/request.json').read_text())
    requests, _ = mock_http(lambda request: ollama_response('{}'))
    asyncio.run(providers.ollama_chat(saved['model'], saved['messages'], saved['instructions'],
                    **saved['options'], context_window=LOCAL_CONTEXT_WINDOW))
    body = json.loads(requests[0].content)
    assert body['messages'] == [{'role': 'system', 'content': saved['instructions']}] + saved['messages']
    assert body['format'] == saved['options']['response_format']
    assert body['options'] == {'temperature': 0.1, 'num_predict': 2048, 'num_ctx': 12288}
    assert body['truncate'] is False
    prompt = body['messages'][1]['content']
    for fact in ('USER CHANGE REQUEST:', 'preserve complete UTF-16 surrogate pairs',
                 'section-sign sanitization', 'ordinary ASCII', 'REPOSITORY MAP',
                 'Each file must have exactly one worker owner', "exact goal 'no change needed'",
                 'src/main/java/dev/atmcompanion/state/SnapshotFormatter.java'):
        assert fact in prompt
    if attempt == 2:
        assert 'assigned to both backend and tests' in prompt
        assert 'PREVIOUS PLAN REJECTED BEFORE WORKER EXECUTION:' in prompt


def test_correction_construction_still_matches_preserved_full_input(scoped):
    run = json.loads((FIXTURES / 'run.json').read_text())
    raw = run['plan_attempts'][0]['raw']
    with pytest.raises(hive.HostWriteScopeError) as failure:
        hive._normalize_plan(hive._extract_json(raw))
    correction = hive._plan_correction_prompt(run['request'], run['repository_map'], raw,
        failure.value, run['repository_facts'], run['intent_envelope'], external_mode=True)
    saved = json.loads((FIXTURES / '02/request.json').read_text())
    assert str(correction) == saved['messages'][0]['content']
    assert response_schema_for_prompt('planner', correction) == saved['options']['response_format']


@pytest.mark.parametrize('context', [4096, 8192, 12288])
def test_configured_window_propagates_without_mutating_messages(mock_http, context):
    requests, _ = mock_http(lambda request: ollama_response())
    messages = [{'role': 'user', 'content': 'Complete prompt \u2603'}]
    asyncio.run(providers.ollama_chat('local', messages, 'System',
                                    context_window=context, max_output_tokens=128))
    body = json.loads(requests[0].content)
    assert body['options']['num_ctx'] == context
    assert body['truncate'] is False
    assert body['messages'][1:] == messages


@pytest.mark.parametrize('context', [0, -1, True, '8192', 8192.0, 128])
def test_invalid_or_output_consumed_window_fails_before_send(mock_http, context):
    requests, _ = mock_http(lambda request: ollama_response())
    with pytest.raises(ValueError, match='context_window'):
        asyncio.run(providers.ollama_chat('local', [], 'System',
                                        context_window=context, max_output_tokens=128))
    assert not requests


@pytest.mark.parametrize('streamed', [False, True])
def test_oversized_context_error_is_explicit_and_never_retried_or_accepted(mock_http, streamed):
    # Shape and token counts reproduced by the local no-truncate sentinel probe.
    error = {'error': 'request (5034 tokens) exceeds the available context size (4096 tokens)'}
    if streamed:
        response = httpx.Response(200, stream=ChunkedStream((json.dumps(error)+'\n').encode()))
    else:
        response = httpx.Response(400, json=error)
    requests, _ = mock_http(lambda request: response)
    with pytest.raises(providers.OllamaRequestError, match='exceeds the available context'):
        asyncio.run(providers.ollama_chat('local', [{'role':'user','content':'full prompt'}],
                    'System', context_window=4096, max_output_tokens=2048))
    assert len(requests) == 1
    assert json.loads(requests[0].content)['truncate'] is False


@pytest.mark.parametrize('attempt', [0, 1])
def test_prior_overlap_outputs_still_rejected_after_transport_repair(scoped, attempt):
    run = json.loads((FIXTURES / 'run.json').read_text())
    with pytest.raises(hive.HostWriteScopeError, match='assigned to both backend and tests'):
        hive._normalize_plan(hive._extract_json(run['plan_attempts'][attempt]['raw']))
