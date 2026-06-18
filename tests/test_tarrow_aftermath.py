from twin_realms import (
    TerminalPlayer,
    TwinRealmsEngine,
    TwinRealmsRuntime,
    build_tarrow_aftermath_world,
    run_tarrow_heartbeat,
)
from twin_realms.cli import _build_world_for_args, main
from twin_realms.fidelity import (
    FIDELITY_BACKGROUND,
    FIDELITY_HIVE,
    FIDELITY_LEADER,
    FIDELITY_REACTIVE,
    FIDELITY_SCHEDULED,
    get_fidelity,
)
from types import SimpleNamespace


def test_tarrow_aftermath_has_composable_demo_parts():
    state = build_tarrow_aftermath_world()
    tiers = {
        get_fidelity(character)
        for character in state.characters.values()
    }

    assert state.flags["scenario_id"] == "tarrow_aftermath"
    assert len(state.characters) == 20
    assert len(state.locations) == 5
    assert len(state.factions) == 2
    assert set(state.flags["village_pressures"]) == {
        "fear",
        "food",
        "medicine",
        "trust_in_ren",
        "malformed_rumors",
    }
    assert {
        FIDELITY_BACKGROUND,
        FIDELITY_SCHEDULED,
        FIDELITY_REACTIVE,
        FIDELITY_HIVE,
        FIDELITY_LEADER,
    }.issubset(tiers)
    assert TwinRealmsEngine(state).verify_replay()


def test_tarrow_day_seven_differs_without_player_forcing_changes(tmp_path):
    engine = TwinRealmsEngine(build_tarrow_aftermath_world())
    report = run_tarrow_heartbeat(engine=engine)

    assert report.scenario_id == "tarrow_aftermath"
    assert report.start_day == 1
    assert report.end_day == 7
    assert report.turns_advanced == 6 * 24
    assert engine.state.flags["current_day"] == 7
    assert report.pressure_deltas
    assert report.memory_delta > 0
    assert report.changed_without_player_force
    assert report.replay_consistent
    assert report.to_dict()["changed_without_player_force"]
    assert report.state_digest == engine.simulator.state_digest(engine.state)

    save_path = tmp_path / "tarrow-day-seven.json"
    engine.save(save_path)
    loaded = TwinRealmsEngine.load(save_path)
    assert loaded.snapshot() == engine.snapshot()


def test_tarrow_heartbeat_report_command_prints_human_summary(capsys):
    main(["--heartbeat-report"])

    output = capsys.readouterr().out
    assert "Tarrow heartbeat report" in output
    assert "Days: 1 -> 7" in output
    assert "Village pressures:" in output
    assert "Changed without player force: yes" in output
    assert "Replay consistent: yes" in output


def test_tarrow_scenario_can_start_from_cli_world_selection():
    state = _build_world_for_args(SimpleNamespace(scenario="tarrow", tier=0))

    assert state.flags["scenario_id"] == "tarrow_aftermath"


def test_terminal_village_command_surfaces_tarrow_pressures(tmp_path):
    outputs = []
    runtime = TwinRealmsRuntime(
        TwinRealmsEngine(build_tarrow_aftermath_world()),
        mode="baseline",
    )
    session = TerminalPlayer(
        runtime,
        save_path=tmp_path / "tarrow-human-save.json",
        output_fn=outputs.append,
    )

    assert session.handle("village")

    output = outputs[-1]
    assert "Village pressures:" in output
    assert "malformed rumors" in output
    assert "World pressures:" in output
    assert "Malformed Remnant" in output


def test_tarrow_player_turn_advances_world_pressure_tick(tmp_path):
    outputs = []
    runtime = TwinRealmsRuntime(
        TwinRealmsEngine(build_tarrow_aftermath_world()),
        mode="baseline",
    )
    session = TerminalPlayer(
        runtime,
        save_path=tmp_path / "tarrow-human-save.json",
        output_fn=outputs.append,
    )
    before = dict(runtime.engine.state.flags["village_pressures"])

    assert session.handle("rest")

    after = runtime.engine.state.flags["village_pressures"]
    assert runtime.engine.events[-1].intent["action"] == "world_tick"
    assert after != before
    assert any(output.startswith("[Village]") for output in outputs)
    assert runtime.engine.verify_replay()


def test_tarrow_wait_day_advances_visible_world_time(tmp_path):
    outputs = []
    runtime = TwinRealmsRuntime(
        TwinRealmsEngine(build_tarrow_aftermath_world()),
        mode="baseline",
    )
    session = TerminalPlayer(
        runtime,
        save_path=tmp_path / "tarrow-human-save.json",
        output_fn=outputs.append,
    )

    assert session.handle("wait day")

    assert runtime.engine.state.flags["current_day"] == 2
    assert runtime.engine.state.turn == 25
    assert any("people remember the change" in output for output in outputs)
    assert runtime.engine.verify_replay()
