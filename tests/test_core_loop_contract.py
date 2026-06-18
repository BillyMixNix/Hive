from twin_realms import (
    TerminalPlayer,
    TwinRealmsEngine,
    TwinRealmsRuntime,
    build_core_loop_world,
)
from twin_realms.cli import _build_world_for_args
from types import SimpleNamespace


def _session(tmp_path, *, state=None):
    outputs = []
    runtime = TwinRealmsRuntime(
        TwinRealmsEngine(state or build_core_loop_world()),
        mode="baseline",
    )
    session = TerminalPlayer(
        runtime,
        save_path=tmp_path / "core-save.json",
        output_fn=outputs.append,
    )
    return session, runtime, outputs


def test_core_loop_new_game_has_player_location_enemy_and_save_load(tmp_path):
    state = _build_world_for_args(SimpleNamespace(scenario="core", tier=0))
    engine = TwinRealmsEngine(state)

    assert state.flags["scenario_id"] == "core_loop"
    assert state.player_id == "char:player"
    assert len(state.locations) == 2
    assert state.characters["char:hostile"].location_id == "loc:den"

    save_path = tmp_path / "new-core.json"
    engine.save(save_path)
    loaded = TwinRealmsEngine.load(save_path)

    assert loaded.snapshot() == engine.snapshot()
    assert loaded.verify_replay()


def test_core_loop_player_can_move_encounter_enemy_and_win(tmp_path):
    session, runtime, outputs = _session(tmp_path)

    assert session.handle("move to Den")
    assert runtime.engine.state.characters["char:player"].location_id == "loc:den"
    assert runtime.engine.events[-1].intent["actor_id"] == "char:hostile"

    while not runtime.engine.state.flags["game_over"]:
        assert session.handle("attack hostile")

    assert runtime.engine.state.flags["victory"] is True
    assert runtime.engine.state.flags["defeat"] is False
    assert runtime.engine.state.characters["char:hostile"].alive is False
    assert any("[Game] Victory." in output for output in outputs)

    session.handle("save")
    loaded = TwinRealmsEngine.load(session.save_path)
    assert loaded.snapshot() == runtime.engine.snapshot()
    assert loaded.verify_replay()


def test_core_loop_player_can_die_and_replay_defeat(tmp_path):
    state = build_core_loop_world()
    player = state.characters[state.player_id]
    player.location_id = "loc:den"
    player.health = 10
    session, runtime, outputs = _session(tmp_path, state=state)

    assert session.handle("rest")

    assert runtime.engine.state.flags["game_over"] is True
    assert runtime.engine.state.flags["defeat"] is True
    assert runtime.engine.state.characters["char:player"].alive is False
    assert any("[Game] You died." in output for output in outputs)

    session.handle("save")
    loaded = TwinRealmsEngine.load(session.save_path)
    assert loaded.snapshot() == runtime.engine.snapshot()
    assert loaded.verify_replay()


def test_core_loop_script_is_deterministic():
    def run_script():
        runtime = TwinRealmsRuntime(
            TwinRealmsEngine(build_core_loop_world()),
            mode="baseline",
        )
        runtime.turn("move to Den")
        while not runtime.engine.state.flags["game_over"]:
            runtime.turn("attack hostile")
        return runtime.engine.snapshot()

    assert run_script() == run_script()
