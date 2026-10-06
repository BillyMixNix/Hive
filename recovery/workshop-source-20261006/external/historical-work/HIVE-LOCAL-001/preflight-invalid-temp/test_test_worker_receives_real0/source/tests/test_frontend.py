from pathlib import Path

def test_health_ui():
    html = Path('static/index.html').read_text(encoding='utf-8')
    assert "fetch('/health')" in html
