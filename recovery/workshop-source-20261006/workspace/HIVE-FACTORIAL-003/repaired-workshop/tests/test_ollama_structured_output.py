import asyncio
import inspect
import json
import threading

import httpx
import pytest

from workshop import providers


class ChunkedStream(httpx.AsyncByteStream):
    def __init__(self, payload):
        self.payload = payload

    async def __aiter__(self):
        for offset in range(0, len(self.payload), 7):
            yield self.payload[offset:offset + 7]


def ollama_response(text="ok"):
    # Split generated JSON across messages and NDJSON lines across byte chunks.
    chunks = [
        {"message": {"content": text[offset:offset + 3]}, "done": False}
        for offset in range(0, len(text), 3)
    ]
    chunks.append({
        "message": {}, "done": True,
        "prompt_eval_count": 17, "eval_count": 29,
    })
    payload = "\n".join(json.dumps(chunk, ensure_ascii=False) for chunk in chunks)
    return httpx.Response(
        200,
        headers={"content-type": "application/x-ndjson"},
        stream=ChunkedStream((payload + "\n").encode("utf-8")),
    )


@pytest.fixture
def mock_http(monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(providers, "_last_ollama_error", "")

    def install(handler):
        requests = []
        client_options = []

        def record(request):
            requests.append(request)
            return handler(request)

        transport = httpx.MockTransport(record)

        def client(*args, **kwargs):
            client_options.append(kwargs.copy())
            return real_client(*args, transport=transport, **kwargs)

        monkeypatch.setattr(providers.httpx, "AsyncClient", client)
        return requests, client_options

    return install


def test_schema_and_low_temperature_preserve_escaped_streamed_code(mock_http):
    schema = {
        "type": "object",
        "properties": {"code": {"type": "string"}},
        "required": ["code"],
        "additionalProperties": False,
    }
    code = (
        'path = r"C:\\work\\draft.json"\n'
        'print("say \\"hello\\"")\n'
        'print("snowman: \u2603")\n'
    )
    generated = json.dumps({"code": code}, ensure_ascii=False)
    response = ollama_response(generated)
    requests, clients = mock_http(lambda request: response)

    result = asyncio.run(providers.ollama_chat(
        "local-model", [{"role": "user", "content": "Write code"}],
        "Return JSON", response_format=schema, temperature=0.1,
        max_output_tokens=2048,
    ))

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{providers.OLLAMA_BASE}/api/chat"
    assert json.loads(request.content) == {
        "model": "local-model",
        "messages": [
            {"role": "system", "content": "Return JSON"},
            {"role": "user", "content": "Write code"},
        ],
        "stream": True,
        "format": schema,
        "options": {"temperature": 0.1, "num_predict": 2048},
    }
    assert clients == [{"timeout": 900.0, "trust_env": False}]
    assert request.extensions["timeout"] == dict.fromkeys(
        ("connect", "read", "write", "pool"), 900.0,
    )
    assert result == {
        "text": generated, "input_tokens": 17,
        "output_tokens": 29, "raw_id": None,
    }
    assert json.loads(result["text"])["code"] == code
    assert response.is_closed


@pytest.mark.parametrize(("controls", "extra_body"), [
    ({"response_format": "json"}, {"format": "json"}),
    ({"response_format": {}}, {"format": {}}),
    ({"temperature": 0.1}, {"options": {"temperature": 0.1}}),
    ({"temperature": 0.0}, {"options": {"temperature": 0.0}}),
    (
        {"response_format": "json", "temperature": 0.0},
        {"format": "json", "options": {"temperature": 0.0}},
    ),
    (
        {"response_format": "json", "temperature": 0.1, "max_output_tokens": 2048},
        {"format": "json", "options": {"temperature": 0.1, "num_predict": 2048}},
    ),
])
def test_controls_are_forwarded_only_when_provided(mock_http, controls, extra_body):
    requests, _ = mock_http(lambda request: ollama_response())

    asyncio.run(providers.ollama_chat("local-model", [], "Test", **controls))

    assert json.loads(requests[0].content) == {
        "model": "local-model",
        "messages": [{"role": "system", "content": "Test"}],
        "stream": True,
        **extra_body,
    }


@pytest.mark.parametrize("controls", [
    {}, {"response_format": None, "temperature": None},
])
@pytest.mark.parametrize("image_data_url", [None, "data:image/png;base64,aGVsbG8="])
def test_default_body_is_byte_for_byte_unchanged(mock_http, controls, image_data_url):
    requests, clients = mock_http(lambda request: ollama_response())
    messages = [{"role": "user", "content": 'Read "C:\\work\\draft.py"\nplease'}]
    expected_messages = [{"role": "system", "content": "Help"}, dict(messages[0])]
    if image_data_url:
        expected_messages[-1]["images"] = ["aGVsbG8="]
    expected_body = {
        "model": "local-model", "messages": expected_messages, "stream": True,
    }
    expected_bytes = httpx.Request("POST", "http://test/api/chat", json=expected_body).content

    # The pre-existing image argument must remain usable positionally.
    asyncio.run(providers.ollama_chat(
        "local-model", messages, "Help", image_data_url, **controls,
    ))

    assert len(requests) == 1
    assert requests[0].content == expected_bytes
    assert clients == [{"timeout": 900.0, "trust_env": False}]
    assert "images" not in messages[0]


def test_controls_are_keyword_only_and_absent_from_cloud_signatures():
    local_parameters = inspect.signature(providers.ollama_chat).parameters
    cloud_functions = (
        providers.build_openai_response_body, providers.openai_chat,
        providers.generate_image, providers.create_video, providers.get_video,
    )
    for name in ("response_format", "temperature"):
        assert local_parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert local_parameters[name].default is None
        for function in cloud_functions:
            assert name not in inspect.signature(function).parameters
    for name in ("max_output_tokens", "cancel_event", "total_timeout"):
        assert local_parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


class ActiveForeverStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        while True:
            await asyncio.sleep(0.001)
            yield b'{"message":{"content":" "},"done":false}\n'


def active_forever_response():
    return httpx.Response(
        200,
        headers={"content-type": "application/x-ndjson"},
        stream=ActiveForeverStream(),
    )


def test_total_generation_limit_stops_active_stream_without_retry(mock_http):
    responses = []

    def handler(_request):
        response = active_forever_response()
        responses.append(response)
        return response

    requests, _ = mock_http(handler)
    with pytest.raises(providers.OllamaRequestError, match="total limit"):
        asyncio.run(providers.ollama_chat(
            "local-model", [], "Test", max_output_tokens=32,
            total_timeout=0.03,
        ))

    assert len(requests) == 1
    assert responses[0].is_closed
    assert "attempt 1/2" in providers.ollama_last_error()


def test_cancel_event_interrupts_active_stream_without_retry(mock_http):
    cancel_event = threading.Event()
    responses = []

    def handler(_request):
        response = active_forever_response()
        responses.append(response)
        return response

    requests, _ = mock_http(handler)

    async def exercise():
        task = asyncio.create_task(providers.ollama_chat(
            "local-model", [], "Test", max_output_tokens=32,
            cancel_event=cancel_event, total_timeout=1.0,
        ))
        await asyncio.sleep(0.03)
        cancel_event.set()
        await task

    with pytest.raises(providers.OllamaRequestError, match="cancelled"):
        asyncio.run(exercise())

    assert len(requests) == 1
    assert responses[0].is_closed
    assert "attempt 1/2" in providers.ollama_last_error()


def test_invalid_local_generation_limits_fail_before_request(mock_http):
    requests, _ = mock_http(lambda request: ollama_response())
    with pytest.raises(ValueError, match="max_output_tokens"):
        asyncio.run(providers.ollama_chat(
            "local-model", [], "Test", max_output_tokens=0,
        ))
    with pytest.raises(providers.OllamaRequestError, match="total_timeout"):
        asyncio.run(providers.ollama_chat(
            "local-model", [], "Test", total_timeout=0,
        ))
    assert requests == []


@pytest.mark.parametrize("failure", ["timeout", "http_503"])
def test_structured_request_retries_once_with_identical_controls(mock_http, failure):
    def handler(request):
        if len(requests) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("temporary timeout", request=request)
            return httpx.Response(503, text="busy")
        return ollama_response('{"code":"ok"}')

    requests, clients = mock_http(handler)
    result = asyncio.run(providers.ollama_chat(
        "local-model", [], "Test", response_format="json", temperature=0.1,
    ))

    assert len(requests) == 2
    assert requests[0].content == requests[1].content
    assert json.loads(requests[1].content)["format"] == "json"
    assert json.loads(requests[1].content)["options"] == {"temperature": 0.1}
    assert clients == [{"timeout": 900.0, "trust_env": False}] * 2
    assert result["text"] == '{"code":"ok"}'
    assert providers.ollama_last_error() == ""


@pytest.mark.parametrize(("status", "attempts"), [(400, 1), (503, 2)])
def test_retry_limit_and_nonretryable_errors_are_unchanged(mock_http, status, attempts):
    requests, _ = mock_http(lambda request: httpx.Response(status, text="failed"))

    with pytest.raises(providers.OllamaRequestError, match=f"HTTP {status}: failed"):
        asyncio.run(providers.ollama_chat(
            "local-model", [], "Test", response_format="json", temperature=0.1,
        ))

    assert len(requests) == attempts
    assert f"chat attempt {attempts}/2" in providers.ollama_last_error()


def test_cloud_chat_body_and_timeout_remain_unchanged(mock_http, monkeypatch):
    monkeypatch.setattr(providers, "openai_key", lambda: "test-key")
    requests, clients = mock_http(lambda request: httpx.Response(
        200, json={"output_text": "cloud answer", "id": "mock-response"},
    ))

    result = asyncio.run(providers.openai_chat(
        "cloud-model", [{"role": "user", "content": "Hello"}], "Help",
    ))

    assert len(requests) == 1
    assert str(requests[0].url) == f"{providers.OPENAI_BASE}/responses"
    assert json.loads(requests[0].content) == {
        "model": "cloud-model",
        "instructions": "Help",
        "input": [{
            "role": "user", "content": [{"type": "input_text", "text": "Hello"}],
        }],
        "reasoning": {"effort": "medium"},
    }
    assert clients == [{"timeout": 180.0}]
    assert result["text"] == "cloud answer"
