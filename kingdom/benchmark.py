from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class TransferTrial:
    condition: str
    correct: int
    total: int
    attention_units: float

    def __post_init__(self) -> None:
        if self.total < 1:
            raise ValueError("total must be >= 1")
        if not 0 <= self.correct <= self.total:
            raise ValueError("correct must be between 0 and total")
        if self.attention_units <= 0:
            raise ValueError("attention_units must be > 0")

    @property
    def accuracy(self) -> float:
        return self.correct / self.total

    @property
    def understanding_per_attention(self) -> float:
        return self.accuracy / self.attention_units


@dataclass(frozen=True)
class AmplificationReport:
    baseline_condition: str
    assisted_condition: str
    baseline_accuracy: float
    assisted_accuracy: float
    accuracy_gain: float
    baseline_attention: float
    assisted_attention: float
    gain_per_assisted_attention: float


def compare_transfer(baseline: TransferTrial, assisted: TransferTrial) -> AmplificationReport:
    gain = assisted.accuracy - baseline.accuracy
    return AmplificationReport(
        baseline_condition=baseline.condition,
        assisted_condition=assisted.condition,
        baseline_accuracy=baseline.accuracy,
        assisted_accuracy=assisted.accuracy,
        accuracy_gain=gain,
        baseline_attention=baseline.attention_units,
        assisted_attention=assisted.attention_units,
        gain_per_assisted_attention=gain / assisted.attention_units,
    )


def best_condition(trials: Iterable[TransferTrial]) -> TransferTrial:
    values = list(trials)
    if not values:
        raise ValueError("at least one trial is required")
    return max(values, key=lambda trial: (trial.understanding_per_attention, trial.accuracy))
