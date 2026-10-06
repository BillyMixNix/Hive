import time

from fastapi.testclient import TestClient

import app
from app import _persistent_usage_summary
from workshop import runtime


def test_reported_turn_usage_aggregates_without_claiming_billed_cost():
    summary = _persistent_usage_summary([
        {
            "usage_status": "reported",
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
            "cached_input_tokens": 40,
            "reasoning_tokens": 5,
        },
        {
            "usage_status": "reported",
            "input_tokens": 50,
            "output_tokens": 10,
            "total_tokens": 60,
            "cached_input_tokens": 0,
            "reasoning_tokens": 2,
        },
    ])

    assert summary["status"] == "complete"
    assert summary["calls"] == 2
    assert summary["input_tokens"] == 150
    assert summary["output_tokens"] == 30
    assert summary["total_tokens"] == 180
    assert summary["cached_input_tokens"] == 40
    assert summary["reasoning_tokens"] == 7
    assert summary["cost_usd"] is None
    assert summary["cost_status"] == "not_reported_by_agents_turn_resource"


def test_partial_or_missing_turn_usage_is_not_reported_as_zero():
    summary = _persistent_usage_summary([
        {"usage_status": "reported", "input_tokens": 100, "output_tokens": 20,
         "total_tokens": 120, "cached_input_tokens": None, "reasoning_tokens": None},
        {"usage_status": "unavailable", "input_tokens": None, "output_tokens": None,
         "total_tokens": None, "cached_input_tokens": None, "reasoning_tokens": None},
    ])

    assert summary["status"] == "partial"
    assert summary["reported_input_tokens"] == 100
    assert summary["reported_output_tokens"] == 20
    assert summary["input_tokens"] is None
    assert summary["output_tokens"] is None
    assert summary["total_tokens"] is None
    assert summary["calls_with_unavailable_usage"] == 1
    assert summary["cost_usd"] is None


def test_explicit_zero_usage_is_distinguished_from_missing_usage():
    explicit_zero = _persistent_usage_summary([
        {"usage_status": "reported", "input_tokens": 0, "output_tokens": 0,
         "total_tokens": 0, "cached_input_tokens": 0, "reasoning_tokens": 0},
    ])
    missing = _persistent_usage_summary([
        {"usage_status": "unavailable", "input_tokens": None, "output_tokens": None,
         "total_tokens": None, "cached_input_tokens": None, "reasoning_tokens": None},
    ])

    assert explicit_zero["status"] == "complete"
    assert explicit_zero["input_tokens"] == 0
    assert missing["status"] == "unavailable"
    assert missing["input_tokens"] is None


def test_persistent_hive_run_does_not_publish_budget_counter_as_zero_cost(monkeypatch, tmp_path):
    saved = {}

    class FakePersistentBackend:
        def __init__(self, model):
            self.metrics = []

        async def __call__(self, role, prompt):
            self.metrics.append({
                "role": role,
                "provider": "openai_agents",
                "model": "gpt-6-astra",
                "session_id": "sess-test",
                "turn_id": "turn-test",
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
                "cached_input_tokens": None,
                "reasoning_tokens": None,
                "usage_status": "unavailable",
                "status": "completed",
            })
            return '{"plan":"controlled test response"}'

    async def fake_run_build(root, runs_root, request, local_model, agent_call, *, metadata, **kwargs):
        await agent_call("planner", "mock prompt")
        return {
            "id": "usage-test-run",
            "status": "ready",
            "metadata": metadata,
            "prompt_trace": [{"role": "planner", "call_id": "usage-test-run:call:0001"}],
        }

    monkeypatch.setattr(app, "JOBS", runtime.JobManager())
    monkeypatch.setattr(app, "HIVE_RUNS", tmp_path / "runs")
    monkeypatch.setattr(app, "CURRENT_SAFETY_MODE", "personal")
    monkeypatch.setattr(app, "require_mode_for_code", lambda: None)
    monkeypatch.setattr(app.persistent_agent, "PersistentAgentBackend", FakePersistentBackend)
    monkeypatch.setattr(app.hive, "run_build", fake_run_build)
    monkeypatch.setattr(app.hive, "save_run", lambda runs_root, run: saved.setdefault("run", run))
    monkeypatch.setattr(app.db, "add_ledger", lambda *args, **kwargs: None)

    with TestClient(app.app) as client:
        response = client.post("/api/hive/build", json={
            "request": "Telemetry-only mocked build",
            "allow_cloud": True,
            "agent_backend": "persistent",
            "persistent_agent_model": "gpt-6-astra",
        })
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        for _ in range(200):
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["state"] in {"completed", "failed"}:
                break
            time.sleep(0.01)

    assert job["state"] == "completed"
    run = saved["run"]
    assert run["metadata"]["cloud_spend"] is None
    assert run["metadata"]["cloud_spend_status"] == "not_reported_by_agents_turn_resource"
    assert run["metadata"]["agent_usage"]["status"] == "unavailable"
    assert run["metadata"]["agent_usage"]["input_tokens"] is None
    assert run["metadata"]["agent_calls"][0]["input_tokens"] is None
