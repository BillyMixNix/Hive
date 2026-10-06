import asyncio
from workshop import providers

def test_ollama_chat_failure_preserves_diagnostics(monkeypatch):
    class BrokenClient:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): return False
        def stream(self,*args,**kwargs):
            raise TimeoutError("model runner timed out")
    monkeypatch.setattr(providers.httpx,"AsyncClient",lambda *a,**k: BrokenClient())
    try:
        asyncio.run(providers.ollama_chat("qwen",[],"test"))
    except providers.OllamaRequestError as exc:
        assert "Ollama chat failed" in str(exc)
        assert "TimeoutError" in str(exc)
    else: raise AssertionError("expected diagnostic provider error")

def test_ollama_chat_uses_long_local_stream_timeout_and_no_cloud_change(monkeypatch):
    captured={}

    class OneShotStream:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): return False
        @property
        def is_success(self): return True
        async def aiter_lines(self):
            yield '{"message":{"content":"ok"},"done":false}'
            yield '{"message":{},"done":true,"eval_count":1}'

    class Client:
        def __init__(self,*args,**kwargs): captured.update(kwargs)
        async def __aenter__(self): return self
        async def __aexit__(self,*args): return False
        def stream(self,*args,**kwargs): return OneShotStream()

    monkeypatch.setattr(providers.httpx,"AsyncClient",Client)
    result=asyncio.run(providers.ollama_chat("qwen",[],"test"))
    assert result["text"] == "ok"
    assert captured["timeout"] == 900.0
    assert captured["trust_env"] is False
