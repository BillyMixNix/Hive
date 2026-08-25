from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from itertools import product
from typing import Iterable, Sequence


Cause = tuple[str, int | None]


@dataclass
class TinyMachine:
    """Small deterministic transition system used to validate the Trial 003 harness.

    `input_tape` is immutable configuration for the lifetime of a machine; `input_cursor`
    is mutable authority because it changes the result of a future READ transition.
    """

    pc: int = 0
    acc: int = 0
    stack: list[int] = field(default_factory=list)
    memory: dict[int, int] = field(default_factory=dict)
    input_tape: tuple[int, ...] = ()
    input_cursor: int = 0
    semantics_version: int = 1

    def step(self, cause: Cause) -> None:
        op, arg = cause
        if self.semantics_version != 1:
            raise ValueError("unsupported semantics_version")

        if op == "ADD":
            if arg is None:
                raise ValueError("ADD requires an argument")
            self.acc += int(arg)
        elif op == "PUSH":
            self.stack.append(self.acc)
        elif op == "POP":
            if not self.stack:
                raise IndexError("empty stack")
            self.acc = self.stack.pop()
        elif op == "STORE":
            if arg is None:
                raise ValueError("STORE requires an address")
            self.memory[int(arg)] = self.acc
        elif op == "LOAD":
            if arg is None:
                raise ValueError("LOAD requires an address")
            self.acc = self.memory.get(int(arg), 0)
        elif op == "READ":
            if self.input_cursor >= len(self.input_tape):
                self.acc = -1
            else:
                self.acc = self.input_tape[self.input_cursor]
                self.input_cursor += 1
        elif op == "NOP":
            pass
        else:
            raise ValueError(f"unknown cause {op!r}")

        self.pc += 1


def snapshot_payload(machine: TinyMachine, *, include_input_cursor: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": 1,
        "pc": machine.pc,
        "acc": machine.acc,
        "stack": list(machine.stack),
        "memory": [[address, machine.memory[address]] for address in sorted(machine.memory)],
        "input_tape": list(machine.input_tape),
        "semantics_version": machine.semantics_version,
    }
    if include_input_cursor:
        payload["input_cursor"] = machine.input_cursor
    return payload


def canonical_snapshot(machine: TinyMachine, *, include_input_cursor: bool = True) -> bytes:
    """Return a detached, recursively canonical byte representation."""

    payload = snapshot_payload(machine, include_input_cursor=include_input_cursor)
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def restore_snapshot(snapshot: bytes) -> TinyMachine:
    payload = json.loads(snapshot.decode("utf-8"))
    if payload.get("schema") != 1:
        raise ValueError("unsupported snapshot schema")
    if "input_cursor" not in payload:
        raise ValueError("snapshot omits authoritative input_cursor")

    return TinyMachine(
        pc=int(payload["pc"]),
        acc=int(payload["acc"]),
        stack=[int(value) for value in payload["stack"]],
        memory={int(address): int(value) for address, value in payload["memory"]},
        input_tape=tuple(int(value) for value in payload["input_tape"]),
        input_cursor=int(payload["input_cursor"]),
        semantics_version=int(payload["semantics_version"]),
    )


def apply_causes(machine: TinyMachine, causes: Sequence[Cause]) -> TinyMachine:
    clone = copy.deepcopy(machine)
    for cause in causes:
        clone.step(cause)
    return clone


def shortest_separator(
    left: TinyMachine,
    right: TinyMachine,
    causes: Iterable[Cause],
    *,
    max_depth: int = 4,
    projection_includes_cursor: bool = False,
) -> tuple[Cause, ...] | None:
    """Find the shortest identical cause sequence that separates equal projections.

    This is an adversarial search helper. It only accepts a starting pair if the chosen
    representation already calls the pair equal. A separator is returned when the two
    *full authoritative* successor snapshots diverge after the same cause sequence.
    """

    left_projection = canonical_snapshot(left, include_input_cursor=projection_includes_cursor)
    right_projection = canonical_snapshot(right, include_input_cursor=projection_includes_cursor)
    if left_projection != right_projection:
        raise ValueError("starting states are not equivalent under the selected projection")

    alphabet = tuple(causes)
    for depth in range(1, max_depth + 1):
        for sequence in product(alphabet, repeat=depth):
            l2 = apply_causes(left, sequence)
            r2 = apply_causes(right, sequence)
            if canonical_snapshot(l2) != canonical_snapshot(r2):
                return tuple(sequence)
    return None
