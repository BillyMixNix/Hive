
from pathlib import Path

def test_ollama_http_discovery_ignores_proxy_env():
    src = (Path(__file__).resolve().parents[1] / "workshop" / "providers.py").read_text(encoding="utf-8")
    assert "httpx.AsyncClient(timeout=5.0, trust_env=False)" in src

def test_manual_model_hint_present():
    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
    assert "Discovery can fail even when a model is usable." in html
    assert "Use custom" in html
