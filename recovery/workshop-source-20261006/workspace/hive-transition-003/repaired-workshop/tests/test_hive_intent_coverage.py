import asyncio
import json
from pathlib import Path

import pytest

from workshop import hive, repository_facts


REQUEST = "Add a Settings display showing the currently running Workshop version."
OLLAMA_REQUEST = "Add a Settings display showing whether Ollama is currently connected."


def _source(tmp_path):
    root = tmp_path / "source"
    (root / "static").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app.py").write_text(
        "from fastapi import FastAPI\n\n"
        "app = FastAPI(version='0.10.1')\n\n"
        "@app.get('/api/health')\n"
        "def health():\n"
        "    return {'ok': True, 'version': app.version, 'jobs': {}}\n",
        encoding="utf-8",
    )
    (root / "static" / "index.html").write_text(
        '<section id="view-settings"><div class="card"><h3>OpenAI</h3></div></section>\n'
        '<script>async function api(url){ return fetch(url); }</script>\n',
        encoding="utf-8",
    )
    (root / "tests" / "test_existing_status.py").write_text(
        "from fastapi.testclient import TestClient\n"
        "import app\n\n"
        "client = TestClient(app.app)\n\n"
        "def test_existing_status_contract():\n"
        "    response = client.get('/api/status')\n"
        "    assert response.status_code == 200\n"
        "    assert response.json()['ollama'] is True\n",
        encoding="utf-8",
    )
    return root


def _ollama_source(tmp_path):
    root = _source(tmp_path)
    routes = "\n".join(
        f"@app.get('/api/a-{index:02d}')\ndef route_{index}():\n    return {{'value': {index}}}\n"
        for index in range(40)
    )
    (root / "app.py").write_text(
        "from fastapi import FastAPI\n\n"
        "app = FastAPI(version='0.10.4')\n\n"
        + routes
        + "\n@app.get('/api/status')\n"
          "async def status():\n"
          "    connected = True\n"
          "    return {\n"
          "        'ollama': connected,\n"
          "        'ollama_models': ['qwen2.5-coder:14b'],\n"
          "        'budget': {},\n"
          "    }\n",
        encoding="utf-8",
    )
    return root


def _ui_only_plan():
    return {
        "summary": "Show the version in Settings",
        "ui_goal": "Display the running version in Settings",
        "backend_goal": "no change needed",
        "tests_goal": "no change needed",
        "worker_files": {"ui": ["static/index.html"], "backend": [], "tests": []},
        "acceptance": ["Settings displays the currently running version"],
        "worker_acceptance": {
            "ui": ["Settings displays the running version"], "backend": [], "tests": [],
        },
        "interface_contracts": [],
    }


def _covered_plan():
    return {
        "summary": "Show the running version in Settings using the existing health interface",
        "ui_goal": "Display the running version in Settings from the existing health interface",
        "backend_goal": "no change needed",
        "tests_goal": "Add regression coverage for the Settings version display",
        "worker_files": {
            "ui": ["static/index.html"],
            "backend": [],
            "tests": ["tests/test_settings_version.py"],
        },
        "acceptance": ["Settings displays the version returned by GET /api/health"],
        "worker_acceptance": {
            "ui": ["Settings reads and displays version from GET /api/health"],
            "backend": [],
            "tests": ["Regression coverage proves the Settings display consumes GET /api/health version"],
        },
        "interface_contracts": [{
            "name": "existing_health_version",
            "owner": "backend",
            "consumer_roles": ["ui", "tests"],
            "contract": "GET /api/health returns JSON containing version",
        }],
    }


def _redundant_backend_plan():
    plan = _covered_plan()
    plan["backend_goal"] = "Modify the existing /api/health endpoint to include the Workshop version in the response."
    plan["worker_files"]["backend"] = ["app.py"]
    plan["worker_acceptance"]["backend"] = ["GET /api/health returns version"]
    return plan


def _ollama_plan(*, redundant_backend=False, invented_interface=False):
    path = "/api/config/ollama-status" if invented_interface else "/api/status"
    plan = {
        "summary": "Show the current Ollama connection state in Settings",
        "ui_goal": "Display the current Ollama connection state in Settings",
        "backend_goal": "no change needed",
        "tests_goal": "Add regression coverage for the Settings Ollama status display",
        "worker_files": {
            "ui": ["static/index.html"],
            "backend": [],
            "tests": ["tests/test_settings_ollama.py"],
        },
        "acceptance": ["Settings displays the ollama value returned by GET /api/status"],
        "worker_acceptance": {
            "ui": ["Settings reads and displays ollama from GET /api/status"],
            "backend": [],
            "tests": ["Regression coverage exercises the Settings display against GET /api/status ollama"],
        },
        "interface_contracts": [{
            "name": "existing_ollama_status",
            "owner": "backend",
            "consumer_roles": ["ui", "tests"],
            "contract": f"GET {path} returns JSON containing ollama",
        }],
    }
    if redundant_backend:
        plan["backend_goal"] = f"Implement GET {path} returning ollama connection status"
        plan["worker_files"]["backend"] = ["app.py"]
        plan["worker_acceptance"]["backend"] = [f"GET {path} returns ollama"]
    return plan


def test_interface_map_recovers_literal_response_keys(tmp_path):
    root = _source(tmp_path)
    records = repository_facts.interfaces(root)

    assert records == [{
        "method": "GET", "path": "/api/health", "handler": "health",
        "response_keys": ["ok", "version", "jobs"],
        "response_types": {"ok": "boolean", "jobs": "object"},
    }]
    facts = repository_facts.build(root)
    assert "GET /api/health -> health; response_keys: ok, version, jobs" in facts


def test_runtime_display_intent_envelope_is_deterministic(tmp_path):
    root = _source(tmp_path)

    first = hive._intent_envelope(REQUEST, root)
    second = hive._intent_envelope(REQUEST, root)

    assert first == second
    requirement = first["requirements"][0]
    assert requirement["consumer_role"] == "ui"
    assert requirement["target_surface"] == "settings"
    assert requirement["require_tests"] is True
    assert requirement["existing_interface"] == {
        "method": "GET", "path": "/api/health", "handler": "health",
        "response_keys": ["version"],
        "response_types": {},
    }


def test_ollama_status_request_gets_nonempty_verified_intent_envelope(tmp_path):
    root = _ollama_source(tmp_path)

    envelope = hive._intent_envelope(OLLAMA_REQUEST, root)

    assert envelope["requirements"] == [{
        "id": "R1",
        "behavior": OLLAMA_REQUEST,
        "consumer_role": "ui",
        "target_surface": "settings",
        "data_kind": "runtime",
        "require_tests": True,
        "existing_interface": {
            "method": "GET",
            "path": "/api/status",
            "handler": "status",
            "response_keys": ["ollama"],
            "response_types": {"ollama": "boolean"},
        },
    }]


@pytest.mark.parametrize("backend_goal", [
    "Ensure GET /api/status returns ollama.",
    "Make sure GET /api/status exposes ollama.",
    "Have GET /api/status provide ollama.",
    "Verify GET /api/status includes ollama.",
    "Keep the status interface supplying the ollama field for consumers.",
])
def test_redundant_provider_paraphrases_have_identical_structural_decision(tmp_path, backend_goal):
    root = _ollama_source(tmp_path)
    envelope = hive._intent_envelope(OLLAMA_REQUEST, root)
    raw = _ollama_plan(redundant_backend=True)
    raw["backend_goal"] = backend_goal
    raw["provider_changes"] = [{
        "requirement_id": "R1",
        "method": "GET",
        "path": "/api/status",
        "response_fields": [{"name": "ollama", "type": "boolean"}],
    }]
    plan, _ = hive._normalize_plan(raw)

    with pytest.raises(hive.PlanValidationError) as failure:
        hive._validate_intent_coverage(plan, envelope)

    message = str(failure.value)
    assert "provider_changes identifies no concrete user-requested" in message
    assert "backend must be no change needed" in message


def test_user_requested_missing_field_is_a_legitimate_provider_delta(tmp_path):
    root = _ollama_source(tmp_path)
    request = (
        "Add a Settings display showing whether Ollama is currently connected "
        "and expose an ollama_latency_ms integer field."
    )
    envelope = hive._intent_envelope(request, root)
    raw = _ollama_plan(redundant_backend=True)
    raw["backend_goal"] = "Add the requested ollama_latency_ms field to GET /api/status"
    raw["worker_acceptance"]["backend"] = ["GET /api/status includes integer ollama_latency_ms"]
    raw["provider_changes"] = [{
        "requirement_id": "R1",
        "method": "GET",
        "path": "/api/status",
        "response_fields": [
            {"name": "ollama", "type": "boolean"},
            {"name": "ollama_latency_ms", "type": "integer"},
        ],
    }]
    plan, _ = hive._normalize_plan(raw)

    hive._validate_intent_coverage(plan, envelope)

    assert "backend" in hive._active_plan_roles(plan)


def test_invented_replacement_ollama_endpoint_requires_correction(tmp_path):
    root = _ollama_source(tmp_path)
    envelope = hive._intent_envelope(OLLAMA_REQUEST, root)
    plan, _ = hive._normalize_plan(_ollama_plan(redundant_backend=True, invented_interface=True))

    with pytest.raises(hive.PlanValidationError) as failure:
        hive._validate_intent_coverage(plan, envelope)

    assert "missing interface contract for GET /api/status" in str(failure.value)


def test_corrected_ollama_plan_uses_existing_interface_with_backend_inactive(tmp_path):
    root = _ollama_source(tmp_path)
    envelope = hive._intent_envelope(OLLAMA_REQUEST, root)
    plan, _ = hive._normalize_plan(_ollama_plan())

    hive._validate_intent_coverage(plan, envelope)

    assert hive._active_plan_roles(plan) == ["ui", "tests"]
    assert plan["backend_goal"] == "no change needed"
    assert plan["worker_files"]["backend"] == []


def test_ollama_planner_correction_precedes_workers_and_leaves_backend_inactive(tmp_path, monkeypatch):
    root = _ollama_source(tmp_path)
    bad = _ollama_plan(redundant_backend=True)
    bad["backend_goal"] = "Ensure the /api/status endpoint returns Ollama connection status."
    bad["provider_changes"] = [{
        "requirement_id": "R1", "method": "GET", "path": "/api/status",
        "response_fields": [{"name": "ollama", "type": "boolean"}],
    }]
    good = _ollama_plan()
    calls = []
    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})

    async def call(role, prompt):
        calls.append((role, prompt))
        if role == "planner":
            if len([item for item in calls if item[0] == "planner"]) == 1:
                return json.dumps(bad)
            assert "provider_changes identifies no concrete user-requested" in prompt
            assert '"response_keys"' in prompt and '"ollama"' in prompt
            assert '"response_types"' in prompt and '"boolean"' in prompt
            return json.dumps(good)
        if role == "tests":
            assert "REPOSITORY-LOCAL ENDPOINT TEST PATTERNS" in prompt
            assert "from fastapi.testclient import TestClient" in prompt
            assert "client = TestClient(app.app)" in prompt
            assert "client.get('/api/status')" in prompt
            assert "verified JSON value types ollama=boolean" in prompt
            assert "Do not add an HTTP dependency or assume an external server" in prompt
        if role == "reviewer":
            return json.dumps({"approve": False, "summary": "diagnostic", "issues": [], "confidence": 1.0})
        return json.dumps({"status": "implemented", "summary": "bounded no-op", "edits": [], "risks": []})

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", OLLAMA_REQUEST, "local", call))

    assert [role for role, _ in calls[:2]] == ["planner", "planner"]
    assert [role for role, _ in calls if role in hive.AGENT_SCOPES] == ["ui", "tests"]
    assert run["agents"]["backend"]["status"] == "skipped"
    assert run["plan"]["interface_contracts"][0]["contract"] == "GET /api/status returns JSON containing ollama"


def test_ui_only_plan_cannot_drop_runtime_contract_or_tests(tmp_path):
    root = _source(tmp_path)
    envelope = hive._intent_envelope(REQUEST, root)
    plan, _ = hive._normalize_plan(_ui_only_plan())

    with pytest.raises(hive.PlanValidationError) as failure:
        hive._validate_intent_coverage(plan, envelope)

    message = str(failure.value)
    assert "regression coverage requires an active tests role" in message
    assert "missing interface contract for GET /api/health" in message


def test_existing_interface_satisfies_provider_without_backend_edit(tmp_path):
    root = _source(tmp_path)
    envelope = hive._intent_envelope(REQUEST, root)
    plan, _ = hive._normalize_plan(_covered_plan())

    hive._validate_intent_coverage(plan, envelope)
    assert plan["backend_goal"] == "no change needed"
    assert plan["worker_files"]["backend"] == []


def test_redundant_backend_assignment_requires_planner_correction(tmp_path):
    root = _source(tmp_path)
    envelope = hive._intent_envelope(REQUEST, root)
    plan, _ = hive._normalize_plan(_redundant_backend_plan())

    with pytest.raises(hive.PlanValidationError) as failure:
        hive._validate_intent_coverage(plan, envelope)

    message = str(failure.value)
    assert "repository-verified GET /api/health already supplies response keys ['version']" in message
    assert "backend must be no change needed" in message


def test_new_interface_still_requires_and_accepts_backend_work(tmp_path):
    plan = _covered_plan()
    plan["backend_goal"] = "Implement GET /api/new-summary in app.py"
    plan["worker_files"]["backend"] = ["app.py"]
    plan["worker_acceptance"]["backend"] = ["GET /api/new-summary returns summary JSON"]
    plan["interface_contracts"][0] = {
        "name": "new_summary",
        "owner": "backend",
        "consumer_roles": ["ui", "tests"],
        "contract": "GET /api/new-summary returns JSON containing summary",
    }
    envelope = {
        "version": 1,
        "requirements": [{
            "id": "R1", "behavior": "Display a new summary", "consumer_role": "ui",
            "target_surface": "settings", "data_kind": "runtime", "require_tests": True,
            "existing_interface": {},
        }],
    }
    normalized, _ = hive._normalize_plan(plan)

    hive._validate_intent_coverage(normalized, envelope)
    assert "backend" in hive._active_plan_roles(normalized)


def test_unknown_existing_response_shape_is_not_assumed_sufficient(tmp_path):
    plan, _ = hive._normalize_plan(_covered_plan())
    envelope = {
        "version": 1,
        "requirements": [{
            "id": "R1", "behavior": REQUEST, "consumer_role": "ui",
            "target_surface": "settings", "data_kind": "runtime", "require_tests": True,
            "existing_interface": {"method": "GET", "path": "/api/health", "handler": "health", "response_keys": []},
        }],
    }

    with pytest.raises(hive.PlanValidationError, match="response shape is not statically verified"):
        hive._validate_intent_coverage(plan, envelope)


def test_fabricated_existing_interface_is_rejected(tmp_path):
    root = _source(tmp_path)
    envelope = hive._intent_envelope(REQUEST, root)
    plan = _covered_plan()
    plan["interface_contracts"][0]["contract"] = "GET /api/version returns JSON containing version"
    normalized, _ = hive._normalize_plan(plan)

    with pytest.raises(hive.PlanValidationError, match="GET /api/health"):
        hive._validate_intent_coverage(normalized, envelope)


def test_literal_static_settings_copy_does_not_invent_runtime_dependency(tmp_path):
    root = _source(tmp_path)
    envelope = hive._intent_envelope("Add the literal text 'Version information' to Settings.", root)
    assert envelope["requirements"] == []


def test_plan_correction_happens_before_workers_and_propagates_obligation(tmp_path, monkeypatch):
    root = _source(tmp_path)
    bad = _ui_only_plan()
    good = _covered_plan()
    calls = []
    worker_queries = {}
    original_context = hive._worker_context
    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})

    def capture_context(source_root, role, query, planned_files=(), previous_proposals=()):
        worker_queries[role] = query
        return original_context(source_root, role, query, planned_files, previous_proposals)

    monkeypatch.setattr(hive, "_worker_context", capture_context)

    async def call(role, prompt):
        calls.append((role, prompt))
        if role == "planner":
            if len([item for item in calls if item[0] == "planner"]) == 1:
                return json.dumps(bad)
            assert "regression coverage requires an active tests role" in prompt
            assert "missing interface contract for GET /api/health" in prompt
            assert "IMMUTABLE INTENT OBLIGATIONS" in prompt
            assert 'ROLES REQUIRED BY IMMUTABLE INTENT OBLIGATIONS:\n["ui", "tests"]' in prompt
            assert '"owner": "backend"' in prompt
            assert '"consumer_roles": [\n    "ui",\n    "tests"\n  ]' in prompt
            assert prompt.response_schema["properties"]["interface_contracts"]["minItems"] == 1
            return json.dumps(good)
        if role == "ui":
            assert "IMMUTABLE INTENT OBLIGATIONS RELEVANT TO YOUR ROLE" in prompt
            assert "/api/health" in prompt and "version" in prompt
        if role == "tests":
            assert "/api/health" in prompt and "version" in prompt
        if role == "reviewer":
            return json.dumps({"approve": False, "summary": "diagnostic", "issues": [], "confidence": 1.0})
        return json.dumps({"status": "implemented", "summary": "bounded no-op", "edits": [], "risks": []})

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", REQUEST, "local", call))

    assert [role for role, _ in calls[:2]] == ["planner", "planner"]
    assert [role for role, _ in calls if role in hive.AGENT_SCOPES] == ["ui", "tests"]
    assert run["agents"]["backend"]["status"] == "skipped"
    assert [item["status"] for item in run["plan_attempts"]] == ["rejected", "accepted"]
    assert "/api/health" in worker_queries["ui"] and "version" in worker_queries["ui"]
    assert run["intent_envelope"] == run["plan"]["_intent_envelope"]


def test_redundant_backend_is_corrected_before_any_worker_runs(tmp_path, monkeypatch):
    root = _source(tmp_path)
    bad = _redundant_backend_plan()
    good = _covered_plan()
    calls = []
    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})

    async def call(role, prompt):
        calls.append(role)
        if role == "planner":
            if calls.count("planner") == 1:
                return json.dumps(bad)
            assert "repository-verified GET /api/health already supplies" in prompt
            return json.dumps(good)
        if role == "reviewer":
            return json.dumps({"approve": False, "summary": "diagnostic", "issues": [], "confidence": 1.0})
        return json.dumps({"status": "implemented", "summary": "bounded no-op", "edits": [], "risks": []})

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", REQUEST, "local", call))

    assert calls[:2] == ["planner", "planner"]
    assert [role for role in calls if role in hive.AGENT_SCOPES] == ["ui", "tests"]
    assert run["agents"]["backend"]["status"] == "skipped"


def test_malformed_correction_exhausts_once_without_worker_execution(tmp_path, monkeypatch):
    root = _source(tmp_path)
    calls = []
    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})

    async def call(role, prompt):
        calls.append(role)
        assert role == "planner"
        return json.dumps(_ui_only_plan())

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", REQUEST, "local", call))

    assert calls == ["planner", "planner"]
    assert run["status"] == "failed"
    assert "Planner correction budget exhausted" in run["errors"][-1]["exception_message"]


def test_verify_tree_delegates_to_isolated_verifier(tmp_path, monkeypatch):
    tree = tmp_path / "stage"
    tree.mkdir()
    (tree / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    seen = []
    monkeypatch.setattr(hive.hive_verifier, "verify_tree_isolated", lambda candidate: (
        seen.append(candidate) or {"passed": True, "checks": [], "isolation": {"backend": "docker"}}
    ))

    result = hive.verify_tree(tree)

    assert result["passed"] is True
    assert seen == [tree]
    assert result["isolation"]["backend"] == "docker"
