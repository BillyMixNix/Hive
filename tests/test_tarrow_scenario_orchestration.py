from twin_realms import run_tarrow_scenario, run_tarrow_scenario_matrix
from twin_realms.cli import main


def test_tarrow_scenario_matrix_compares_player_paths():
    reports = run_tarrow_scenario_matrix(days=3)

    assert set(reports) == {"ignore", "defend", "rebuild"}
    assert all(report.replay_consistent for report in reports.values())
    assert all(report.end_turn == 73 for report in reports.values())
    assert reports["defend"].settlement_after["defense_level"] > (
        reports["ignore"].settlement_after["defense_level"]
    )
    assert reports["defend"].pressure_after["malformed_rumors"] < (
        reports["ignore"].pressure_after["malformed_rumors"]
    )
    assert reports["rebuild"].pressure_after["food"] > (
        reports["ignore"].pressure_after["food"]
    )
    assert reports["rebuild"].pressure_after["medicine"] > (
        reports["ignore"].pressure_after["medicine"]
    )
    assert reports["rebuild"].settlement_after["location_states"]["loc:shrine_road"] == (
        "restored"
    )


def test_tarrow_scenario_report_is_inspectable():
    report = run_tarrow_scenario("rebuild", days=2)
    payload = report.to_dict()

    assert payload["path"] == "rebuild"
    assert payload["commands"] == [
        "work carpenter",
        "move to Low Fields",
        "work farmer",
        "rest",
        "move to Healer Hut",
        "work healer",
    ]
    assert payload["rejected_commands"] == []
    assert payload["pressure_deltas"]
    assert payload["settlement_deltas"]
    assert any(
        event.get("job_id") == "carpenter"
        for event in payload["key_events"]
    )
    assert any(
        event.get("village_pressure_changes")
        for event in payload["key_events"]
    )


def test_tarrow_scenario_rejects_unknown_paths():
    try:
        run_tarrow_scenario("kingdom_war")
    except ValueError as exc:
        assert "unknown Tarrow scenario path" in str(exc)
    else:
        raise AssertionError("unknown scenario path should fail")


def test_tarrow_scenario_report_command_prints_path_summaries(capsys):
    main(["--scenario-report", "--scenario-days", "2"])

    output = capsys.readouterr().out
    assert "Tarrow scenario reports" in output
    assert "Path: ignore" in output
    assert "Path: defend" in output
    assert "Path: rebuild" in output
    assert "Replay consistent: yes" in output
