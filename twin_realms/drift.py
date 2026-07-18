from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass


@dataclass
class DriftReport:
    complexity_tier: int
    world_turns: int
    active_characters: int
    total_characters: int
    total_items: int
    action_diversity: int
    rejection_rate: float
    max_repeated_action_streak: int
    invalid_reference_rejections: int
    unavailable_actor_rejections: int
    narration_guard_violations: int
    replay_consistent: bool
    event_counts: dict[str, int]

    @property
    def drift_detected(self):
        return (
            not self.replay_consistent
            or self.invalid_reference_rejections > 0
            or self.unavailable_actor_rejections > 0
            or self.narration_guard_violations > 0
            or self.max_repeated_action_streak >= 25
            or self.rejection_rate >= 0.95
        )

    def to_dict(self):
        data = asdict(self)
        data["drift_detected"] = self.drift_detected
        return data


class DriftAuditor:
    REFERENCE_REASONS = {
        "target is unavailable",
        "target is not present",
        "destination does not exist",
        "item is not carried",
        "item is not on the ground here",
        "theft target is not present",
        "target does not carry that item",
        "skill is unknown",
        "job is unknown",
    }

    def audit(self, engine):
        actions = [event.intent.get("action", "unknown") for event in engine.events]
        event_counts = Counter(event.event_type for event in engine.events)
        rejected = [event for event in engine.events if not event.accepted]
        return DriftReport(
            complexity_tier=int(engine.state.flags.get("complexity_tier", 0)),
            world_turns=engine.state.turn,
            active_characters=sum(
                character.active and character.alive
                for character in engine.state.characters.values()
            ),
            total_characters=len(engine.state.characters),
            total_items=len(engine.state.items),
            action_diversity=len(set(actions)),
            rejection_rate=len(rejected) / len(engine.events) if engine.events else 0.0,
            max_repeated_action_streak=self._max_streak(actions),
            invalid_reference_rejections=sum(
                event.reason in self.REFERENCE_REASONS
                for event in rejected
            ),
            unavailable_actor_rejections=sum(
                event.reason == "actor is unavailable"
                for event in rejected
            ),
            narration_guard_violations=getattr(
                engine.narrator,
                "guard_violation_count",
                0,
            ),
            replay_consistent=engine.verify_replay(),
            event_counts=dict(sorted(event_counts.items())),
        )

    @staticmethod
    def _max_streak(actions):
        maximum = 0
        current = 0
        previous = None
        for action in actions:
            current = current + 1 if action == previous else 1
            maximum = max(maximum, current)
            previous = action
        return maximum
