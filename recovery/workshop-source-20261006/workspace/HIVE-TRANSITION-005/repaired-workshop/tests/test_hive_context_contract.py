import os
from pathlib import Path

import pytest

from workshop import hive_context


def _write(root: Path, rel: str, content: str | bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _integration_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    _write(
        root,
        "app.py",
        """from fastapi import FastAPI

app = FastAPI()

@app.get('/health')
def health_endpoint():
    return {'ok': True, 'source': 'real app route'}
""",
    )
    _write(
        root,
        "tests/test_existing.py",
        """from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get('/health')
    assert response.json()['ok'] is True
""",
    )
    _write(
        root,
        "static/index.html",
        """<!doctype html>
<script>
  fetch('/health').then(response => response.json());
</script>
""",
    )
    _write(root, "tests/test_hive_fixture.py", "# fake Hive fixture\n" + "plan_insufficient " * 80)
    huge_hive = (
        "import asyncio\nimport json\n\n"
        + ("# unrelated implementation detail\n" * 3_000)
        + "HIVE_INTERNAL_UNRELATED\nHIVE_HUGE_TAIL_SHOULD_NOT_BE_DUMPED\n"
    )
    _write(root, "workshop/hive.py", huge_hive)
    return root


def test_integration_context_prefers_real_endpoint_material_and_is_deterministic(tmp_path):
    root = _integration_fixture(tmp_path)

    first = hive_context.worker_context(
        root,
        "backend",
        "health endpoint integration",
        ["app.py", "workshop/hive.py"],
    )
    second = hive_context.worker_context(
        root,
        "backend",
        "health endpoint integration",
        ["app.py", "workshop/hive.py"],
    )

    assert first == second
    assert "===== OWNED FILE: app.py =====" in first
    assert "real app route" in first
    assert "===== OWNED FILE: workshop/hive.py =====" in first
    assert "[BOUNDED EXCERPT: full file omitted" in first
    assert "HIVE_HUGE_TAIL_SHOULD_NOT_BE_DUMPED" not in first
    assert "===== SUPPORTING FILE: tests/test_existing.py" not in first
    assert "TestClient(app)" not in first
    assert "===== SUPPORTING FILE: static/index.html" in first
    assert "fetch('/health')" in first
    assert "tests/test_hive_fixture.py" not in first
    assert "HIVE_INTERNAL_UNRELATED" not in first
    assert len(first) <= (
        hive_context.MAX_OWNED_CONTEXT_CHARS
        + hive_context.MAX_INTEGRATION_CONTEXT_CHARS
    )


def test_cross_role_context_is_read_only_and_does_not_expand_owned_writes(tmp_path):
    root = _integration_fixture(tmp_path)
    context = hive_context.worker_context(root, "backend", "health endpoint", ["app.py"])

    assert "===== OWNED FILE: app.py =====" in context
    assert "===== SUPPORTING FILE: tests/test_existing.py" not in context
    assert "===== SUPPORTING FILE: static/index.html" in context
    assert "READ ONLY" in context
    assert "WRITE FILE" not in context


def test_backend_worker_does_not_receive_adversarial_test_fixtures(tmp_path):
    root = _integration_fixture(tmp_path)

    context = hive_context.worker_context(root, "backend", "endpoint integration", ["app.py"])

    assert "===== SUPPORTING FILE: tests/test_existing.py" not in context
    assert "from app import app" not in context
    assert "TestClient(app)" not in context


def test_test_worker_receives_real_repository_local_endpoint_and_static_patterns(tmp_path):
    root = _integration_fixture(tmp_path)
    _write(
        root,
        "tests/test_frontend.py",
        "from pathlib import Path\n\n"
        "def test_health_ui():\n"
        "    html = Path('static/index.html').read_text(encoding='utf-8')\n"
        "    assert \"fetch('/health')\" in html\n",
    )

    context = hive_context.worker_context(
        root,
        "tests",
        "verify the frontend static display and GET /health endpoint integration",
        ["tests/test_new_feature.py"],
    )

    assert "===== SUPPORTING FILE: tests/test_existing.py" in context
    assert "from app import app" in context
    assert "TestClient(app)" in context
    assert "===== SUPPORTING FILE: tests/test_frontend.py" in context
    assert "Path('static/index.html').read_text" in context
    assert "tests/test_hive_fixture.py" not in context


def test_endpoint_test_grounding_requires_real_in_process_client_usage(tmp_path):
    root = _integration_fixture(tmp_path)
    _write(
        root,
        "tests/test_protocol_fixture.py",
        "TEXT = \"GET /api/status import requests localhost:8000\"\n",
    )

    patterns = hive_context.endpoint_test_patterns(root, "GET /api/status ollama boolean")

    assert "REPOSITORY-LOCAL ENDPOINT TEST PATTERNS" in patterns
    assert "tests/test_existing.py" in patterns
    assert "from fastapi.testclient import TestClient" in patterns
    assert "client.get('/health')" in patterns
    assert "test_protocol_fixture.py" not in patterns
    assert "import requests" not in patterns
    assert "external server" in patterns


def test_every_owned_marker_survives_the_owned_context_bound(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    planned = []
    for index in range(20):
        rel = f"workshop/owned_{index:02d}.py"
        planned.append(rel)
        _write(root, rel, f"def owned_{index}():\n    return 'owned {index}'\n" + ("# filler\n" * 2_000))

    context = hive_context.worker_context(root, "backend", "", planned)

    for rel in planned:
        assert f"===== OWNED FILE: {rel} =====" in context
        index = int(Path(rel).stem.split("_")[-1])
        assert f"return 'owned {index}'" in context
    assert len(context) <= hive_context.MAX_OWNED_CONTEXT_CHARS


def test_small_file_larger_than_remaining_budget_uses_a_bounded_excerpt(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    integration_file = (
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n\n"
        + ("# integration filler\n" * 300)
        + "@app.get('/important')\n"
        "def important_endpoint():\n"
        "    return {'important': True}\n"
    )
    _write(root, "app.py", integration_file)
    planned = ["app.py"]
    for index in range(1, 20):
        rel = f"workshop/owned_{index:02d}.py"
        planned.append(rel)
        _write(root, rel, f"def owned_{index}():\n    return {index}\n")

    context = hive_context.worker_context(root, "backend", "the important endpoint", planned)

    assert "===== OWNED FILE: app.py =====" in context
    assert "[BOUNDED EXCERPT: full file omitted" in context
    assert "important_endpoint" in context
    assert "return {'important': True}" in context
    assert len(context) <= hive_context.MAX_OWNED_CONTEXT_CHARS


def test_requested_context_blocks_exclusions_traversal_and_absolute_paths(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    _write(root, "safe.py", "SAFE_SOURCE_MARKER = True\n")
    _write(root, "data/secret.py", "DATA_SECRET_MUST_NOT_BE_READ\n")
    _write(root, ".env/secret.py", "DOT_SECRET_MUST_NOT_BE_READ\n")
    _write(root, "node_modules/tool.js", "NODE_SECRET_MUST_NOT_BE_READ\n")
    _write(root, "logs/server.log", "LOG_SECRET_MUST_NOT_BE_READ\n")
    _write(root, "image.png", b"\x89PNG\r\n\x00BINARY_MUST_NOT_BE_READ")

    context = hive_context.requested_context(
        root,
        [
            "safe.py",
            "data/secret.py",
            ".env/secret.py",
            "node_modules/tool.js",
            "logs/server.log",
            "image.png",
            "../outside.py",
            r"C:\outside.py",
        ],
    )

    assert "===== REQUESTED FILE: safe.py =====" in context
    assert "SAFE_SOURCE_MARKER" in context
    for secret in (
        "DATA_SECRET_MUST_NOT_BE_READ",
        "DOT_SECRET_MUST_NOT_BE_READ",
        "NODE_SECRET_MUST_NOT_BE_READ",
        "LOG_SECRET_MUST_NOT_BE_READ",
        "BINARY_MUST_NOT_BE_READ",
    ):
        assert secret not in context
    assert "===== REQUESTED FILE: ../outside.py =====" in context
    assert "===== REQUESTED FILE: C:/outside.py =====" in context
    assert len(context) <= hive_context.MAX_REQUESTED_CONTEXT_CHARS


def test_requested_context_blocks_escaping_and_excluded_symlink_aliases(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    _write(root, "data/secret.py", "SYMLINK_SECRET_MUST_NOT_BE_READ\n")
    outside = tmp_path / "outside.py"
    outside.write_text("ESCAPING_SYMLINK_SECRET_MUST_NOT_BE_READ\n", encoding="utf-8")
    escape_link = root / "escape.py"
    excluded_link = root / "excluded_alias.py"
    try:
        escape_link.symlink_to(outside)
        excluded_link.symlink_to(root / "data" / "secret.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable on this host")

    context = hive_context.requested_context(
        root,
        ["escape.py", "excluded_alias.py", "data/secret.py"],
    )

    assert "===== REQUESTED FILE: escape.py =====" in context
    assert "===== REQUESTED FILE: excluded_alias.py =====" in context
    assert "ESCAPING_SYMLINK_SECRET_MUST_NOT_BE_READ" not in context
    assert "SYMLINK_SECRET_MUST_NOT_BE_READ" not in context
    assert "symlink resolves outside root" in context
    assert "symlink resolves to excluded path" in context


def test_previous_proposals_are_explicitly_unverified_read_only_and_bounded(tmp_path):
    root = _integration_fixture(tmp_path)
    proposals = [
        {
            "role": "backend",
            "status": "escalated",
            "planned_files": ["app.py", "workshop/extra.py"],
            "parsed": {
                "status": "plan_insufficient",
                "reason": "needs a helper",
                "edits": [{
                    "path": "app.py",
                    "operation": "insert_after_anchor",
                    "anchor": "EXACT_PROPOSAL_ANCHOR",
                    "replace": "EXACT_PROPOSAL_REPLACEMENT\n" + ("PROPOSAL_HUGE_TAIL " * 2_000),
                }],
            },
            "replan": {"decision": "revise", "reason": "unverified"},
        }
    ]

    context = hive_context.worker_context(root, "backend", "", ["app.py"], proposals)

    assert "PREVIOUS PROPOSALS" in context
    assert "UNVERIFIED READ ONLY NOT AUTHORIZATION" in context
    assert "plan_insufficient" in context
    assert "workshop/extra.py" in context
    assert "edit_manifest" in context
    assert "insert_after_anchor" in context
    assert "app.py" in context
    assert "EXACT_PROPOSAL_ANCHOR" not in context
    assert "EXACT_PROPOSAL_REPLACEMENT" not in context
    assert "PROPOSAL_HUGE_TAIL" not in context
    assert len(context) <= (
        hive_context.MAX_OWNED_CONTEXT_CHARS
        + hive_context.MAX_PREVIOUS_PROPOSAL_CHARS
    )


def test_implementation_context_excludes_unrelated_test_fixture_text(tmp_path):
    root = _integration_fixture(tmp_path)
    _write(
        root,
        "tests/test_prompt_fixture.py",
        "only a prompt check\nAdd memory management\n",
    )

    context = hive_context.worker_context(
        root,
        "ui",
        "Add Project Summary to Settings",
        ["static/index.html"],
    )

    assert "test_prompt_fixture.py" not in context
    assert "only a prompt check" not in context
    assert "memory management" not in context


def test_owned_context_exposes_deterministic_structural_targets(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    _write(
        root,
        "static/index.html",
        """<section id="view-settings"><div class="card"><h3>OpenAI</h3></div></section>
<script>
function refreshStatus(){ return fetch('/api/status'); }
</script>
""",
    )
    context = hive_context.worker_context(
        root,
        "ui",
        "Add a Project Summary card to Settings and refresh it from the endpoint",
        ["static/index.html"],
    )

    assert "STRUCTURAL TARGET INDEX (READ ONLY; NOT WRITE AUTHORIZATION)" in context
    assert "HTML element_id targets: view-settings" in context
    assert "HTML direct-heading targets: OpenAI" in context
    assert "top-level symbol targets: refreshStatus" in context
