import time
import app
from fastapi.testclient import TestClient

def test_hive_build_job_polls_without_state_wiring_failure(monkeypatch):
    async def fake_build(*args, **kwargs):
        for stage, progress in (("planning",10),("ui",30),("backend",45),("tests",60),("verification",75),("review",90)):
            kwargs["on_stage"](stage,progress,f"now {stage}")
        return {"id":"run-test","status":"staged","changed_files":[],"verification":{"passed":True},"review":{"approve":True},"metadata":{}}
    monkeypatch.setattr(app.hive, "run_build", fake_build)
    monkeypatch.setattr(app.hive, "save_run", lambda *args: None)
    monkeypatch.setattr(app, "require_mode_for_code", lambda: None)
    with TestClient(app.app) as client:
        response=client.post("/api/hive/build",json={"request":"test","allow_cloud":False})
        assert response.status_code==200
        job_id=response.json()["job_id"]
        for _ in range(50):
            status=client.get(f"/api/jobs/{job_id}").json()
            if status["state"] in {"completed","failed"}: break
            time.sleep(.01)
        assert status["state"]=="completed", status
        assert status["result"]["id"] == "run-test"
        assert [event["state"] for event in status["events"]] == [
            "planning", "ui", "backend", "tests", "verification", "review", "completed",
        ]
        progresses = [event["progress"] for event in status["events"]]
        assert progresses == sorted(progresses)
