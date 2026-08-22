import pytest

from kingdom.human_trial import (
    PILOT_TRIAL_1,
    packet_attention_units,
    render_learning_packet,
)


def test_pilot_trial_answer_key_is_stable():
    assert PILOT_TRIAL_1.answer_key() == (
        False,
        True,
        True,
        True,
        True,
        False,
        True,
        True,
    )


def test_pilot_trial_scores_exact_answers():
    correct, total = PILOT_TRIAL_1.score_answers(PILOT_TRIAL_1.answer_key())
    assert (correct, total) == (8, 8)


def test_pilot_trial_rejects_wrong_answer_count():
    with pytest.raises(ValueError, match="expected 8 answers"):
        PILOT_TRIAL_1.score_answers([True])


def test_learning_packet_is_bounded_and_does_not_leak_answer_key():
    packet = render_learning_packet(PILOT_TRIAL_1)
    assert "average effect" in packet
    assert "Aster + Brim" not in packet
    assert "answer" not in packet.lower()
    assert packet_attention_units(packet) < 2.0
