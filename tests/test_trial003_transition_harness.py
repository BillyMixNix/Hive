from __future__ import annotations

import copy

import pytest

from experiments.trial003.transition_harness import (
    TinyMachine,
    canonical_snapshot,
    restore_snapshot,
    shortest_separator,
)


def test_trial003_harness_detects_hidden_input_cursor() -> None:
    left = TinyMachine(input_tape=(11, 22), input_cursor=0)
    right = TinyMachine(input_tape=(11, 22), input_cursor=1)

    # The deliberately incomplete projection calls these realities equal.
    assert canonical_snapshot(left, include_input_cursor=False) == canonical_snapshot(
        right, include_input_cursor=False
    )

    separator = shortest_separator(
        left,
        right,
        [("NOP", None), ("READ", None), ("ADD", 1)],
        max_depth=2,
        projection_includes_cursor=False,
    )

    assert separator == (("READ", None),)


def test_trial003_full_snapshot_refuses_false_equivalence() -> None:
    left = TinyMachine(input_tape=(11, 22), input_cursor=0)
    right = TinyMachine(input_tape=(11, 22), input_cursor=1)

    assert canonical_snapshot(left) != canonical_snapshot(right)
    with pytest.raises(ValueError, match="not equivalent"):
        shortest_separator(
            left,
            right,
            [("READ", None)],
            max_depth=1,
            projection_includes_cursor=True,
        )


def test_trial003_snapshot_is_detached_from_live_mutation() -> None:
    machine = TinyMachine(
        pc=4,
        acc=7,
        stack=[1, 2],
        memory={9: 10, 1: 2},
        input_tape=(3, 4),
        input_cursor=1,
    )
    frozen = canonical_snapshot(machine)

    machine.stack.append(99)
    machine.memory[1] = 999
    machine.input_cursor = 2
    machine.acc = -5

    assert frozen == canonical_snapshot(
        TinyMachine(
            pc=4,
            acc=7,
            stack=[1, 2],
            memory={1: 2, 9: 10},
            input_tape=(3, 4),
            input_cursor=1,
        )
    )


def test_trial003_snapshot_recursively_canonicalizes_memory_order() -> None:
    first = TinyMachine(memory={1: 10, 2: 20, 3: 30})
    second = TinyMachine()
    second.memory[3] = 30
    second.memory[1] = 10
    second.memory[2] = 20

    assert canonical_snapshot(first) == canonical_snapshot(second)


def test_trial003_restore_continuation_matches_uninterrupted_machine() -> None:
    original = TinyMachine(input_tape=(4, 8, 15, 16, 23, 42))
    prefix = [("READ", None), ("PUSH", None), ("READ", None), ("ADD", 5), ("STORE", 7)]
    suffix = [("READ", None), ("PUSH", None), ("LOAD", 7), ("ADD", 2), ("READ", None)]

    for cause in prefix:
        original.step(cause)

    checkpoint = canonical_snapshot(original)
    restored = restore_snapshot(checkpoint)

    for cause in suffix:
        original.step(cause)
        restored.step(cause)
        assert canonical_snapshot(original) == canonical_snapshot(restored)


def test_trial003_restore_is_fresh_object_graph() -> None:
    original = TinyMachine(stack=[1, 2], memory={5: 6}, input_tape=(7, 8), input_cursor=1)
    restored = restore_snapshot(canonical_snapshot(original))

    assert restored is not original
    assert restored.stack is not original.stack
    assert restored.memory is not original.memory

    restored.stack.append(3)
    restored.memory[5] = 99

    assert original.stack == [1, 2]
    assert original.memory == {5: 6}
