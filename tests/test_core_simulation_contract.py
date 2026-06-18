from twin_realms import (
    TerminalPlayer,
    TwinRealmsEngine,
    TwinRealmsRuntime,
    build_core_loop_world,
)
from twin_realms.models import ActionIntent


def _runtime():
    return TwinRealmsRuntime(
        TwinRealmsEngine(build_core_loop_world()),
        mode="baseline",
    )


def _tick(engine, count=1):
    result = None
    for _ in range(count):
        result = engine.apply_intent(ActionIntent("world_tick", engine.state.player_id))
    return result


def test_core_npc_schedules_are_inspectable(tmp_path):
    outputs = []
    session = TerminalPlayer(
        _runtime(),
        save_path=tmp_path / "core-sim-save.json",
        output_fn=outputs.append,
    )

    assert session.handle("schedules")

    rendered = "\n".join(outputs)
    assert "Worker" in rendered
    assert "jobs worker" in rendered
    assert "needs fatigue" in rendered
    assert "dawn->Field" in rendered
    assert "night->Camp" in rendered


def test_core_world_tick_moves_worker_to_job_and_home():
    runtime = _runtime()
    state = runtime.engine.state
    worker = state.characters["char:worker"]

    assert worker.location_id == "loc:camp"

    dawn = _tick(runtime.engine, 6)
    assert worker.location_id == "loc:field"
    assert dawn.event.facts["npc_updates"][0]["task"] == "follow_schedule"
    assert dawn.event.facts["npc_updates"][0]["moved"] is True

    day = _tick(runtime.engine, 3)
    assert worker.location_id == "loc:field"
    assert day.event.facts["npc_updates"][0]["task"] == "work"
    assert worker.skill_mastery["worker"] > 0

    dusk = _tick(runtime.engine, 9)
    assert worker.location_id == "loc:camp"
    assert dusk.event.facts["npc_updates"][0]["task"] == "follow_schedule"
    assert runtime.engine.verify_replay()


def test_core_worker_responds_to_danger():
    state = build_core_loop_world()
    worker = state.characters["char:worker"]
    worker.location_id = "loc:den"
    worker.needs["safety"] = 80
    runtime = TwinRealmsRuntime(TwinRealmsEngine(state), mode="baseline")
    worker = runtime.engine.state.characters["char:worker"]

    result = _tick(runtime.engine)
    update = result.event.facts["npc_updates"][0]

    assert update["task"] == "respond_to_danger"
    assert update["danger_id"] == "char:hostile"
    assert update["location_after"] == "loc:camp"
    assert worker.needs["safety"] == 60
    assert runtime.engine.verify_replay()


def test_wait_day_surfaces_npc_updates(tmp_path):
    outputs = []
    session = TerminalPlayer(
        _runtime(),
        save_path=tmp_path / "core-sim-save.json",
        output_fn=outputs.append,
    )

    assert session.handle("wait day")

    rendered = "\n".join(outputs)
    assert "Worker" in rendered
    assert "follow schedule" in rendered or "work" in rendered or "rest" in rendered
    assert session.engine.verify_replay()
