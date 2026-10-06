
from pathlib import Path

def test_ollama_refresh_controls_present():
    html=(Path(__file__).resolve().parents[1]/"static"/"index.html").read_text(encoding="utf-8")
    assert 'id="ollamaendpoint"' in html
    assert "saveOllamaEndpoint()" in html
    assert "refreshStatus()" in html
    assert 'id="ollamaerror"' in html
