from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from statistics import mean
from typing import Iterable


FEATURES = ("Aster", "Brim", "Cinder", "Dusk", "Ember", "Flux")


@dataclass(frozen=True)
class Interaction:
    features: tuple[str, ...]
    weight: int


@dataclass(frozen=True)
class CausalWorld:
    world_id: str
    bias: int
    main: dict[str, int]
    interactions: tuple[Interaction, ...]

    def score(self, state: dict[str, int]) -> int:
        value = self.bias
        value += sum(self.main.get(name, 0) * int(bool(state.get(name, 0))) for name in FEATURES)
        for term in self.interactions:
            if all(state.get(name, 0) for name in term.features):
                value += term.weight
        return value

    def outcome(self, state: dict[str, int]) -> bool:
        return self.score(state) >= 0

    def all_states(self) -> list[dict[str, int]]:
        return [dict(zip(FEATURES, bits)) for bits in product((0, 1), repeat=len(FEATURES))]

    def marginal_score_effect(self, feature: str) -> float:
        others = tuple(name for name in FEATURES if name != feature)
        differences: list[int] = []
        for bits in product((0, 1), repeat=len(others)):
            base = dict(zip(others, bits))
            off = {**base, feature: 0}
            on = {**base, feature: 1}
            differences.append(self.score(on) - self.score(off))
        return mean(differences)


@dataclass(frozen=True)
class HumanTrial:
    trial_id: str
    world: CausalWorld
    condition: str
    test_states: tuple[dict[str, int], ...]

    def answer_key(self) -> tuple[bool, ...]:
        return tuple(self.world.outcome(state) for state in self.test_states)

    def score_answers(self, answers: Iterable[bool]) -> tuple[int, int]:
        supplied = tuple(bool(value) for value in answers)
        key = self.answer_key()
        if len(supplied) != len(key):
            raise ValueError(f"expected {len(key)} answers, got {len(supplied)}")
        return sum(actual == expected for actual, expected in zip(supplied, key)), len(key)


def render_state(state: dict[str, int]) -> str:
    enabled = [name for name in FEATURES if state.get(name, 0)]
    return ", ".join(enabled) if enabled else "none"


def render_learning_packet(trial: HumanTrial) -> str:
    world = trial.world
    if trial.condition == "flat":
        lines = [
            "A device is STABLE when its hidden stability score is zero or greater.",
            "A large exploration estimated the average score change caused by each switch across all other configurations.",
            "Positive values usually help stability; negative values usually hurt it. These are averages, so interactions may exist.",
        ]
        for feature in FEATURES:
            effect = world.marginal_score_effect(feature)
            sign = "+" if effect >= 0 else ""
            lines.append(f"- {feature}: average effect {sign}{effect:g}")
        lines.append("Your job is to use this compressed model to predict new configurations.")
        return "\n".join(lines)

    if trial.condition == "structured":
        lines = [
            "A device is STABLE when its stability score is zero or greater.",
            f"Start every configuration at {world.bias:+d} points.",
        ]
        for feature in FEATURES:
            weight = world.main.get(feature, 0)
            if weight:
                lines.append(f"- {feature} ON: {weight:+d}")
        for interaction in world.interactions:
            joined = " + ".join(interaction.features)
            lines.append(f"- If {joined} are all ON together: additional {interaction.weight:+d}")
        lines.append("Add all applicable effects. Score >= 0 means STABLE; score < 0 means UNSTABLE.")
        return "\n".join(lines)

    if trial.condition == "ordinary":
        ranked = sorted(FEATURES, key=lambda name: abs(world.marginal_score_effect(name)), reverse=True)
        strongest = ranked[:3]
        lines = [
            "A device can be stable or unstable depending on six switches. The explored cases suggest a few broad patterns.",
            f"The strongest overall stabilizer is {strongest[0]}, followed by {strongest[1]} and {strongest[2]} in overall influence.",
            "Some switches change meaning depending on what else is active, so the broad trends are not absolute.",
        ]
        for feature in ranked:
            effect = world.marginal_score_effect(feature)
            direction = "stabilizing" if effect > 0 else "destabilizing" if effect < 0 else "neutral on average"
            lines.append(f"- {feature} is {direction} overall (average shift {effect:+g}).")
        lines.append("Use those patterns, including the warning about interactions, to predict the new cases.")
        return "\n".join(lines)

    raise ValueError(f"unknown condition {trial.condition!r}")


def packet_attention_units(packet: str) -> float:
    # One attention unit is 100 words. The benchmark records rather than hides packet-size differences.
    words = len(packet.split())
    return max(words / 100.0, 0.01)


PILOT_WORLD_1 = CausalWorld(
    world_id="pilot-01",
    bias=-1,
    main={
        "Aster": 2,
        "Brim": 1,
        "Cinder": -1,
        "Dusk": 2,
        "Ember": 0,
        "Flux": -2,
    },
    interactions=(
        Interaction(("Aster", "Brim"), -4),
        Interaction(("Cinder", "Dusk"), 3),
        Interaction(("Ember", "Flux"), 4),
        Interaction(("Aster", "Dusk", "Flux"), 3),
    ),
)


PILOT_TRIAL_1 = HumanTrial(
    trial_id="K0-N1-001",
    world=PILOT_WORLD_1,
    condition="flat",
    test_states=(
        {"Aster": 1, "Brim": 1, "Cinder": 0, "Dusk": 0, "Ember": 0, "Flux": 0},
        {"Aster": 0, "Brim": 0, "Cinder": 1, "Dusk": 1, "Ember": 0, "Flux": 0},
        {"Aster": 0, "Brim": 0, "Cinder": 0, "Dusk": 0, "Ember": 1, "Flux": 1},
        {"Aster": 1, "Brim": 0, "Cinder": 0, "Dusk": 1, "Ember": 0, "Flux": 1},
        {"Aster": 1, "Brim": 0, "Cinder": 1, "Dusk": 0, "Ember": 1, "Flux": 0},
        {"Aster": 0, "Brim": 1, "Cinder": 1, "Dusk": 0, "Ember": 0, "Flux": 1},
        {"Aster": 1, "Brim": 1, "Cinder": 1, "Dusk": 1, "Ember": 0, "Flux": 0},
        {"Aster": 1, "Brim": 1, "Cinder": 0, "Dusk": 1, "Ember": 1, "Flux": 1},
    ),
)
