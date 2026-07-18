import pytest

from twin_realms import TwinRealmsEngine
from tests.test_twin_realms_long_run import ADVERSARIAL_PROMPTS


@pytest.mark.parametrize("prompt", ADVERSARIAL_PROMPTS)
def test_control_language_cannot_bypass_world_resolution(prompt):
    engine = TwinRealmsEngine()
    before = engine.state.to_dict()

    result = engine.turn(prompt)

    assert result.intent.action == "unknown"
    assert result.intent.parameters["rejected_control_language"]
    assert not result.event.accepted
    assert result.event.reason == "intent could not be interpreted"
    assert engine.state.turn == 1
    after = engine.state.to_dict()
    after["turn"] = before["turn"]
    assert after == before
