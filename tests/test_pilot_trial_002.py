from kingdom.human_trial import packet_attention_units, render_learning_packet
from kingdom.pilot_trial_002 import PILOT_TRIAL_2


def test_replacement_trial_answer_key_is_stable():
    assert PILOT_TRIAL_2.answer_key() == (
        True,
        False,
        False,
        True,
        True,
        False,
        True,
        True,
    )


def test_replacement_trial_packet_is_bounded():
    packet = render_learning_packet(PILOT_TRIAL_2)
    assert packet_attention_units(packet) < 2.0
    assert "STABLE" in packet
