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

    for command in (
        "block",
        "heavy attack hostile",
        "attack hostile",
        "rest",
        "attack hostile",
        "attack hostile",
    ):
        if runtime.engine.state.flags["game_over"]:
            break
        assert session.handle(command)

    assert runtime.engine.state.flags["victory"] is True
    assert runtime.engine.state.flags["defeat"] is False
    assert runtime.engine.state.characters["char:hostile"].alive is False
    assert any("[Game] Victory." in output for output in outputs)

    session.handle("save")
    loaded = TwinRealmsEngine.load(session.save_path)
    assert loaded.snapshot() == runtime.engine.snapshot()
    assert loaded.verify_replay()


def test_core_loop_tactical_actions_have_costs_and_logs(tmp_path):
    session, runtime, outputs = _session(tmp_path)
    session.handle("move to Den")
    player = runtime.engine.state.characters["char:player"]
    stamina_before = player.stamina

    session.handle("block")
    assert player.stamina == stamina_before - 6
    assert runtime.engine.events[-2].event_type == "blocked"
    assert "blocks" in runtime.engine.events[-2].facts["combat_log"]

    stamina_before = player.stamina
    session.handle("dodge")
    assert player.stamina == stamina_before - 8
    assert runtime.engine.events[-2].event_type == "dodged"
    assert "dodge" in runtime.engine.events[-2].facts["combat_log"]

    stamina_before = player.stamina
    session.handle("heavy attack hostile")
    player_event = runtime.engine.events[-2]
    assert player_event.intent["action"] == "heavy_attack"
    assert player_event.facts["stamina_spent"] == 18
    assert player.stamina <= stamina_before - 18
    assert "heavy attack" in player_event.facts["combat_log"]
    assert any("stamina" in output for output in outputs)


def test_core_loop_enemy_uses_valid_intents_only():
    runtime = TwinRealmsRuntime(
        TwinRealmsEngine(build_core_loop_world()),
        mode="baseline",
    )
    runtime.turn("move to Den")
    hostile_events = [
        event
        for event in runtime.engine.events
        if event.actor_id == "char:hostile"
    ]

    assert hostile_events
    assert all(event.accepted for event in hostile_events)
    assert {
        event.intent["action"] for event in hostile_events
    }.issubset({"attack", "heavy_attack", "block", "dodge", "rest"})
    assert all(
        event.intent["target_id"] == "char:player"
        for event in hostile_events
        if event.intent["action"] in {"attack", "heavy_attack"}
    )


def test_core_loop_heavy_attack_has_cooldown():
    engine = TwinRealmsEngine(build_core_loop_world())
    runtime = TwinRealmsRuntime(engine, mode="baseline")
    runtime.turn("move to Den")

    first = engine.apply_intent(
        runtime.engine.interpreter.interpret("heavy attack hostile", engine.state)
    )
    second = engine.apply_intent(
        runtime.engine.interpreter.interpret("heavy attack hostile", engine.state)
    )

    assert first.event.accepted
    assert second.event.accepted is False
    assert second.event.reason == "heavy attack is cooling down"
    assert engine.verify_replay()


def test_core_loop_good_choices_reduce_damage_and_can_win():
    def first_hostile_damage(commands):
        runtime = TwinRealmsRuntime(
            TwinRealmsEngine(build_core_loop_world()),
            mode="baseline",
        )
        for command in commands:
            runtime.turn(command)
        hostile_hits = [
            event
            for event in runtime.engine.events
            if event.actor_id == "char:hostile"
            and event.event_type == "attack_resolved"
        ]
        return hostile_hits[-1].facts["damage"]

    def tactical_play():
        runtime = TwinRealmsRuntime(
            TwinRealmsEngine(build_core_loop_world()),
            mode="baseline",
        )
        runtime.turn("move to Den")
        for command in (
            "block",
            "heavy attack hostile",
            "attack hostile",
            "rest",
            "attack hostile",
            "attack hostile",
        ):
            if runtime.engine.state.flags["game_over"]:
                break
            runtime.turn(command)
        return runtime.engine.state.flags["victory"]

    unguarded = first_hostile_damage(["move to Den"])
    guarded = first_hostile_damage(["move to Den", "block"])
    assert guarded < unguarded
    assert tactical_play() is True


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
