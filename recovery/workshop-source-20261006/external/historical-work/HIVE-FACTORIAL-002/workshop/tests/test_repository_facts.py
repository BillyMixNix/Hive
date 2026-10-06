import asyncio
import json

from workshop import hive
from workshop import repository_facts


def _source(tmp_path):
    root = tmp_path / "source"
    (root / "static").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app.py").write_text(
        "from fastapi import FastAPI\n\n"
        "app = FastAPI(title='Example')\n\n"
        "@app.get('/api/health')\n"
        "def health():\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    (root / "static" / "index.html").write_text(
        "<script>async function load(){ return fetch('/api/health'); }</script>\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_health.py").write_text(
        "from fastapi.testclient import TestClient\n"
        "client = TestClient(app.app)\n"
        "def test_health():\n    assert client.get('/api/health').status_code == 200\n",
        encoding="utf-8",
    )
    return root


def test_repository_facts_detect_framework_and_local_patterns(tmp_path):
    facts = repository_facts.build(_source(tmp_path))

    assert "web_framework: FastAPI" in facts
    assert "backend_contract: use FastAPI route decorators" in facts
    assert "@app.get('/api/health')" in facts
    assert "def health()" in facts
    assert "frontend_contract:" in facts
    assert "@app.route" in facts
    assert "jsonify" in facts


def test_repository_facts_are_deterministic_and_bounded(tmp_path):
    root = _source(tmp_path)
    first = repository_facts.build(root)
    second = repository_facts.build(root)

    assert first == second
    assert len(first) <= repository_facts.MAX_FACTS_CHARS


def test_async_multiline_handler_keys_are_recovered_beyond_old_interface_cap(tmp_path):
    root = _source(tmp_path)
    routes = "\n".join(
        f"@app.get('/api/a-{index:02d}')\ndef route_{index}():\n    return {{'value': {index}}}\n"
        for index in range(40)
    )
    (root / "app.py").write_text(
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n\n"
        + routes
        + "\n@app.get('/api/status')\n"
          "async def status():\n"
          "    connected = True\n"
          "    return {\n"
          "        'ollama': connected,\n"
          "        'ollama_models': [],\n"
          "        'budget': {},\n"
          "    }\n",
        encoding="utf-8",
    )

    status = next(item for item in repository_facts.interfaces(root) if item["path"] == "/api/status")

    assert status == {
        "method": "GET",
        "path": "/api/status",
        "handler": "status",
        "response_keys": ["ollama", "ollama_models", "budget"],
        "response_types": {"ollama": "boolean", "ollama_models": "array", "budget": "object"},
    }


def test_dynamic_and_non_handler_text_do_not_create_interface_facts(tmp_path):
    root = _source(tmp_path)
    (root / "app.py").write_text(
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n"
        "ROUTE_TEXT = \"@app.get('/api/string-only')\"\n"
        "# @app.get('/api/comment-only')\n\n"
        "@app.get('/api/dynamic')\n"
        "def dynamic():\n"
        "    payload = {'guessed': True}\n"
        "    return payload\n\n"
        "@app.get('/api/outer')\n"
        "async def outer():\n"
        "    def nested():\n"
        "        return {'nested_only': True}\n"
        "    return {'real': True}\n\n"
        "def container():\n"
        "    @app.get('/api/nested-route')\n"
        "    def nested_route():\n"
        "        return {'fake': True}\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_fake_route.py").write_text(
        "TEXT = \"@app.get('/api/from-test')\"\n",
        encoding="utf-8",
    )

    records = repository_facts.interfaces(root)

    assert records == [
        {"method": "GET", "path": "/api/dynamic", "handler": "dynamic", "response_keys": [], "response_types": {}},
        {"method": "GET", "path": "/api/outer", "handler": "outer", "response_keys": ["real"], "response_types": {"real": "boolean"}},
    ]


def test_async_provider_tuple_types_flow_into_route_response_without_execution(tmp_path):
    root = _source(tmp_path)
    (root / "workshop").mkdir()
    (root / "workshop" / "providers.py").write_text(
        "async def ollama_status():\n"
        "    if True:\n"
        "        models = ['qwen']\n"
        "        return True, models\n"
        "    return False, []\n",
        encoding="utf-8",
    )
    (root / "app.py").write_text(
        "from fastapi import FastAPI\n"
        "from workshop import providers\n"
        "app = FastAPI()\n\n"
        "@app.get('/api/status')\n"
        "async def status():\n"
        "    ok, models = await providers.ollama_status()\n"
        "    return {\n"
        "        'ollama': ok,\n"
        "        'ollama_models': models,\n"
        "    }\n",
        encoding="utf-8",
    )

    status = repository_facts.interfaces(root)[0]

    assert status["response_types"] == {"ollama": "boolean", "ollama_models": "array"}


def test_planner_and_backend_worker_receive_repository_facts(tmp_path):
    root = _source(tmp_path)
    facts = repository_facts.build(root)
    repository_map = hive._repository_map(root)

    planner = hive._planner_prompt("Add a health endpoint", repository_map, facts)
    worker_context = hive._worker_context(root, "backend", "health endpoint", ["app.py"])
    worker = hive._worker_prompt(
        "backend",
        "Implement the backend health endpoint",
        ["app.py"],
        worker_context,
        ["endpoint uses the existing response pattern"],
        repository_facts_text=facts,
    )

    for prompt in (planner, worker):
        assert "REPOSITORY-DERIVED IMPLEMENTATION FACTS" in prompt
        assert "web_framework: FastAPI" in prompt
        assert "@app.get('/api/health')" in prompt
    assert "do not use Flask @app.route or jsonify" in worker


def test_live_build_records_facts_and_injects_them_into_worker_prompt(tmp_path, monkeypatch):
    root = _source(tmp_path)
    plan = {
        "summary": "Add a health endpoint",
        "ui_goal": "no change needed",
        "backend_goal": "Implement the backend health endpoint",
        "tests_goal": "no change needed",
        "worker_files": {"ui": [], "backend": ["app.py"], "tests": []},
        "acceptance": ["the endpoint uses the repository framework"],
        "worker_acceptance": {
            "ui": [],
            "backend": ["the endpoint uses the repository framework"],
            "tests": [],
        },
    }
    prompts = {}
    monkeypatch.setattr(hive, "verify_tree", lambda tree: {"passed": True, "checks": []})

    async def call(role, prompt):
        prompts[role] = prompt
        if role == "planner":
            return json.dumps(plan)
        if role == "backend":
            return json.dumps({"status": "implemented", "summary": "no-op", "edits": [], "risks": []})
        return json.dumps({"approve": False, "summary": "no change", "issues": [], "confidence": 0.0})

    run = asyncio.run(hive.run_build(root, tmp_path / "runs", "Add a health endpoint", "local", call))

    assert "web_framework: FastAPI" in run["repository_facts"]
    assert "web_framework: FastAPI" in prompts["planner"]
    assert "web_framework: FastAPI" in prompts["backend"]
