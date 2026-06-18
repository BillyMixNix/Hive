from __future__ import annotations

from dataclasses import dataclass

from .engine import TwinRealmsEngine
from .runtime import TwinRealmsRuntime


@dataclass
class BenchmarkReport:
    mode: str
    player_turns: int
    world_events: int
    accepted_events: int
    rejected_events: int
    replay_consistent: bool
    metrics: dict

    def to_dict(self):
        return {
            "mode": self.mode,
            "player_turns": self.player_turns,
            "world_events": self.world_events,
            "accepted_events": self.accepted_events,
            "rejected_events": self.rejected_events,
            "replay_consistent": self.replay_consistent,
            "metrics": self.metrics,
        }


class TwinRealmsBenchmark:
    def run(
        self,
        inputs,
        *,
        mode="baseline",
        engine=None,
        npc_planner=None,
        knowledge_agent=None,
        npc_ids=None,
    ):
        runtime = TwinRealmsRuntime(
            engine or TwinRealmsEngine(),
            mode=mode,
            npc_planner=npc_planner,
            knowledge_agent=knowledge_agent,
            npc_ids=npc_ids,
        )
        labeled = 0
        correct = 0
        for entry in inputs:
            if isinstance(entry, tuple):
                player_input, expected_action = entry
                labeled += 1
            else:
                player_input = entry
                expected_action = None
            result = runtime.turn(player_input)
            if expected_action is not None:
                correct += int(result.player_result.intent.action == expected_action)
        accepted = sum(event.accepted for event in runtime.engine.events)
        metrics = runtime.metrics()
        if labeled:
            metrics["interpretation_accuracy"] = correct / labeled
        return BenchmarkReport(
            mode=mode,
            player_turns=len(inputs),
            world_events=len(runtime.engine.events),
            accepted_events=accepted,
            rejected_events=len(runtime.engine.events) - accepted,
            replay_consistent=runtime.engine.verify_replay(),
            metrics=metrics,
        )
