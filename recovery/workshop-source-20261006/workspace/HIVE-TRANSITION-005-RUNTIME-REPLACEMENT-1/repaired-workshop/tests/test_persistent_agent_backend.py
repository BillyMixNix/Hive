import asyncio
import json

import httpx

from workshop import persistent_agent, providers


def test_persistent_backend_reuses_role_session_and_returns_turn_text(monkeypatch):
    monkeypatch.setattr(providers, "openai_key", lambda: "test-key")
    state={"created":False,"continued":False,"turn_lists":0}

    def handler(request: httpx.Request):
        path=request.url.path
        if request.method == "POST" and path == "/v1/agents/sessions":
            state["created"]=True
            body=json.loads(request.content)
            assert body["environment"] == {"type":"none"}
            assert body["agent"]["model"] == "gpt-6-astra"
            assert body["agent"]["multi_agent"] == {"enabled": False}
            assert "max_concurrent_subagents" not in body["agent"]["multi_agent"]
            return httpx.Response(200,json={"id":"sess-1"})
        if request.method == "GET" and path == "/v1/agents/sessions/sess-1/turns":
            state["turn_lists"] += 1
            if state["continued"]:
                data=[{"id":"turn-2","status":"completed"},
                      {"id":"turn-1","status":"completed"}]
            else:
                data=[{"id":"turn-1","status":"completed"}]
            return httpx.Response(200,json={"data":data})
        if request.method == "GET" and path in {
            "/v1/agents/sessions/sess-1/turns/turn-1",
            "/v1/agents/sessions/sess-1/turns/turn-2",
        }:
            turn=request.url.path.rsplit("/", 1)[-1]
            usage=(
                {"input_tokens":1,"input_tokens_details":{"cached_tokens":0},
                 "output_tokens":2,"output_tokens_details":{"reasoning_tokens":1},"total_tokens":3}
                if turn == "turn-1" else
                {"input_tokens":2,"input_tokens_details":{"cached_tokens":1},
                 "output_tokens":3,"output_tokens_details":{"reasoning_tokens":2},"total_tokens":5}
            )
            return httpx.Response(200,json={"id":turn,"usage":usage})
        if request.method == "POST" and path == "/v1/agents/sessions/sess-1/events":
            state["continued"]=True
            body=json.loads(request.content)
            assert body["events"][0]["type"] == "agent.session.input.message"
            return httpx.Response(202)
        if request.method == "GET" and path == "/v1/agents/sessions/sess-1/items":
            turn="turn-2" if state["continued"] else "turn-1"
            text="second" if state["continued"] else "first"
            return httpx.Response(200,json={"data":[{"type":"message","role":"assistant","turn_id":turn,
                "content":[{"type":"output_text","text":text}]}]})
        return httpx.Response(404,text=path)

    client=httpx.AsyncClient(base_url="https://api.openai.com/v1",transport=httpx.MockTransport(handler))
    backend=persistent_agent.PersistentAgentBackend(client=client,poll_seconds=0)
    async def run():
        try:
            assert await backend("planner","one") == "first"
            assert await backend("planner","two") == "second"
        finally:
            await client.aclose()
    asyncio.run(run())
    assert backend.sessions == {"planner":"sess-1"}
    assert [m["turn_id"] for m in backend.metrics] == ["turn-1","turn-2"]
    assert [(m["input_tokens"], m["output_tokens"]) for m in backend.metrics] == [(1, 2), (2, 3)]
    assert [(m["cached_input_tokens"], m["reasoning_tokens"]) for m in backend.metrics] == [(0, 1), (1, 2)]
    assert all(m["usage_status"] == "reported" and m["usage_source"] == "turn_detail" for m in backend.metrics)


def test_missing_agents_usage_remains_unknown_not_zero(monkeypatch):
    monkeypatch.setattr(providers, "openai_key", lambda: "test-key")

    def handler(request: httpx.Request):
        path=request.url.path
        if request.method == "POST" and path == "/v1/agents/sessions":
            return httpx.Response(200,json={"id":"sess-unknown"})
        if request.method == "GET" and path == "/v1/agents/sessions/sess-unknown/turns":
            return httpx.Response(200,json={"data":[{"id":"turn-unknown","status":"completed"}]})
        if request.method == "GET" and path == "/v1/agents/sessions/sess-unknown/turns/turn-unknown":
            return httpx.Response(200,json={"id":"turn-unknown","usage":None})
        if request.method == "GET" and path == "/v1/agents/sessions/sess-unknown/items":
            return httpx.Response(200,json={"data":[{"type":"message","role":"assistant","turn_id":"turn-unknown",
                "content":[{"type":"output_text","text":"done"}]}]})
        return httpx.Response(404,text=path)

    client=httpx.AsyncClient(base_url="https://api.openai.com/v1",transport=httpx.MockTransport(handler))
    backend=persistent_agent.PersistentAgentBackend(client=client,poll_seconds=0)
    async def run():
        try:
            assert await backend("planner","task") == "done"
        finally:
            await client.aclose()
    asyncio.run(run())

    metric=backend.metrics[0]
    assert metric["usage_status"] == "unavailable"
    assert metric["input_tokens"] is None
    assert metric["output_tokens"] is None
    assert metric["total_tokens"] is None


def test_turn_detail_failure_falls_back_to_usage_from_turn_list(monkeypatch):
    monkeypatch.setattr(providers, "openai_key", lambda: "test-key")

    def handler(request: httpx.Request):
        path=request.url.path
        if request.method == "POST" and path == "/v1/agents/sessions":
            return httpx.Response(200,json={"id":"sess-fallback"})
        if request.method == "GET" and path == "/v1/agents/sessions/sess-fallback/turns":
            return httpx.Response(200,json={"data":[{"id":"turn-fallback","status":"completed",
                "usage":{"input_tokens":7,"output_tokens":4}}]})
        if request.method == "GET" and path == "/v1/agents/sessions/sess-fallback/turns/turn-fallback":
            return httpx.Response(404,text="not ready")
        if request.method == "GET" and path == "/v1/agents/sessions/sess-fallback/items":
            return httpx.Response(200,json={"data":[{"type":"message","role":"assistant","turn_id":"turn-fallback",
                "content":[{"type":"output_text","text":"done"}]}]})
        return httpx.Response(404,text=path)

    client=httpx.AsyncClient(base_url="https://api.openai.com/v1",transport=httpx.MockTransport(handler))
    backend=persistent_agent.PersistentAgentBackend(client=client,poll_seconds=0)
    async def run():
        try:
            assert await backend("planner","task") == "done"
        finally:
            await client.aclose()
    asyncio.run(run())

    metric=backend.metrics[0]
    assert metric["usage_status"] == "reported"
    assert metric["usage_source"] == "turn_list"
    assert metric["input_tokens"] == 7
    assert metric["output_tokens"] == 4
    assert metric["usage_lookup_error_type"] == "RuntimeError"


def test_failed_provider_attempt_is_still_recorded_without_fake_usage(monkeypatch):
    monkeypatch.setattr(providers, "openai_key", lambda: "test-key")

    def handler(request: httpx.Request):
        return httpx.Response(503,json={"error":{"message":"temporary failure"}})

    client=httpx.AsyncClient(base_url="https://api.openai.com/v1",transport=httpx.MockTransport(handler))
    backend=persistent_agent.PersistentAgentBackend(client=client)
    async def run():
        try:
            try:
                await backend("planner","task")
            except RuntimeError:
                pass
            else:
                raise AssertionError("provider failure should propagate")
        finally:
            await client.aclose()
    asyncio.run(run())

    assert len(backend.metrics) == 1
    assert backend.metrics[0]["status"] == "failed"
    assert backend.metrics[0]["input_tokens"] is None
    assert backend.metrics[0]["output_tokens"] is None


def test_persistent_backend_requires_api_key(monkeypatch):
    monkeypatch.setattr(providers, "openai_key", lambda: "")
    backend=persistent_agent.PersistentAgentBackend()
    try:
        asyncio.run(backend("planner","hello"))
    except RuntimeError as exc:
        assert "API key" in str(exc)
    else:
        raise AssertionError("missing key should fail closed")
    assert backend.metrics[0]["status"] == "failed"
    assert backend.metrics[0]["usage_status"] == "unavailable"
