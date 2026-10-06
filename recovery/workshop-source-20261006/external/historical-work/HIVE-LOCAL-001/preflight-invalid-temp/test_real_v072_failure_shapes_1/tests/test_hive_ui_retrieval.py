import re
from pathlib import Path

import pytest

from workshop import hive_context


def _owned_excerpt(root, query):
    context = hive_context.worker_context(root, "ui", query, ["static/index.html"])
    owned = context.split("===== INTEGRATION SUPPORTING CONTEXT", 1)[0]
    assert "READ ONLY; NOT WRITE AUTHORIZATION" in owned
    return owned.split("===== OWNED FILE: static/index.html =====\n", 1)[1]


def _assert_bounds(excerpt):
    assert len(excerpt) <= hive_context._MAX_FILE_EXCERPT_CHARS
    assert "[BOUNDED EXCERPT: full file omitted" in excerpt
    ranges = re.findall(r"\[EXCERPT lines (\d+)-(\d+);", excerpt)
    assert 1 <= len(ranges) <= hive_context._MAX_EXCERPT_BLOCKS
    assert all(1 <= int(end) - int(start) + 1 <= hive_context._MAX_EXCERPT_LINES
               for start, end in ranges)


def test_real_settings_query_includes_markup_and_complete_refresh_helpers(tmp_path):
    source_path = Path(__file__).resolve().parents[1] / "static" / "index.html"
    source = source_path.read_text(encoding="utf-8")
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_text(source, encoding="utf-8")
    query = "Add a refresh control to the Settings panel to display the project summary"

    excerpt = _owned_excerpt(tmp_path, query)

    assert excerpt == _owned_excerpt(tmp_path, query)
    assert '<section id="view-settings"' in excerpt
    assert next(line for line in source.splitlines() if "<h3>OpenAI</h3>" in line) in excerpt
    api = next(line for line in source.splitlines() if line.startswith("async function api("))
    refresh = "async function refreshStatus(){" + source.split(
        "async function refreshStatus(){", 1
    )[1].split("\n}", 1)[0] + "\n}"
    assert api in excerpt
    assert refresh in excerpt
    assert excerpt.index('<section id="view-settings"') < excerpt.index("async function api(")
    _assert_bounds(excerpt)


@pytest.mark.parametrize("anchor", [
    '<section id="view-stockroom">\n<div class="cards">',
    '<section id="view-tools">\n<div class="cards">\n<h2>Stockroom</h2>',
])
def test_late_html_target_and_camel_case_handler_beat_repetitive_css(tmp_path, anchor):
    helper = "\n".join([
        "async function requestJSON(url) {",
        "  const response = await fetch(url);",
        "  const payload = await response.json();",
        "  if (!response.ok) throw Error(payload.detail);",
        "  return payload;",
        "}",
    ])
    handler = "\n".join([
        "const reloadInventory = async () => {",
        "  const rows = await requestJSON('/stockroom');",
        "  document.getElementById('stockCount').textContent = rows.length;",
        "  return rows;",
        "};",
    ])
    css = ".panel { display: grid; --summary: 'stockroom reload inventory'; }\n" * 6_000
    decoys = "\n".join(f"function inventoryHint{i}() {{ return {i}; }}" for i in range(30))
    source = (
        "<style>\n" + css + "</style>\n" + anchor
        + '\n<button onclick="reloadInventory()">Update counts</button>\n'
        + '<output id="stockCount">Existing inventory card</output>\n</div>\n</section>\n'
        + "<script>\n" + helper + "\n" + decoys + "\n" + handler + "\n</script>\n"
    )
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_text(source, encoding="utf-8")
    query = "Add a reload control to the Stockroom panel to display inventory summary"

    excerpt = _owned_excerpt(tmp_path, query)

    assert excerpt == _owned_excerpt(tmp_path, query)
    assert anchor in excerpt
    assert "Existing inventory card" in excerpt
    assert handler in excerpt
    assert helper in excerpt
    assert ".panel { display:" not in excerpt
    _assert_bounds(excerpt)


@pytest.mark.parametrize("suffix", [".js", ".mjs", ".cjs"])
@pytest.mark.parametrize("query", ["reload inventory", "reloadInventory"])
def test_javascript_symbols_include_related_local_helpers(tmp_path, suffix, query):
    helper = "function readRows() {\n  return [{count: 7}];\n}"
    handler = "const reloadInventory = () => {\n  return readRows();\n};"
    source = ("// reload inventory placeholder\n" * 1_000) + helper + "\n" + handler
    rel = "inventory" + suffix
    (tmp_path / rel).write_text(source, encoding="utf-8")

    context = hive_context.requested_context(tmp_path, [rel], query)

    assert handler in context
    assert helper in context
    assert f"===== REQUESTED FILE: {rel} =====" in context
    assert len(context) <= hive_context.MAX_REQUESTED_CONTEXT_CHARS


@pytest.mark.parametrize("limit", [0, 30, 100, 500, 5_000])
def test_ui_excerpts_keep_existing_character_limits(limit):
    source = "<style>\n" + (".panel { display: grid; }\n" * 1_000) + "</style>\n"
    source += '<section id="view-inventory">\n<h2>Inventory</h2>\n</section>\n'
    first = hive_context._bounded_excerpt("ui.htm", source, len(source), "inventory panel", limit)
    second = hive_context._bounded_excerpt("ui.htm", source, len(source), "inventory panel", limit)
    assert len(first) <= limit
    assert first == second
