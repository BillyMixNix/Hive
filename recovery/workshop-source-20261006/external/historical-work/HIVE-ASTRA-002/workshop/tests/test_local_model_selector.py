
from pathlib import Path

def test_local_model_is_select_not_free_text():
    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
    assert '<select id="localmodel"' in html
    assert "qwen3.5:9b" not in html
    assert "qwen2.5-coder:14b" in html

def test_hive_build_ui_present():
    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="view-hive"' in html
    assert "Plan + Run Agents" in html
