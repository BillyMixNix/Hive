from twin_realms import TwinRealmsEngine, build_foundation_world
from twin_realms.models import ActionIntent


def _sequence():
    return [
        ActionIntent("observe", "char:player", target_id="char:malformed"),
        ActionIntent("attack", "char:player", target_id="char:malformed"),
        ActionIntent("rest", "char:player"),
        ActionIntent("drop", "char:player", parameters={"item_id": "item:iron_sword"}),
        ActionIntent("pickup", "char:player", parameters={"item_id": "item:iron_sword"}),
        ActionIntent("space_fold", "char:player", target_id="char:malformed", distance=5),
    ]


def test_same_actions_produce_exactly_equal_snapshots():
    first = TwinRealmsEngine(build_foundation_world(seed=31))
    second = TwinRealmsEngine(build_foundation_world(seed=31))

    for intent in _sequence():
        first.apply_intent(intent)
        second.apply_intent(intent)

    assert first.snapshot() == second.snapshot()
    assert first.verify_replay()
    assert second.verify_replay()


def test_periodic_save_load_preserves_authoritative_history(tmp_path):
    engine = TwinRealmsEngine(build_foundation_world(seed=11))
    path = tmp_path / "periodic-world.json"

    for index in range(60):
        engine.apply_intent(_sequence()[index % len(_sequence())])
        if (index + 1) % 10 == 0:
            engine.save(path)
            engine = TwinRealmsEngine.load(path)

    assert engine.state.turn == 60
    assert engine.verify_replay()
