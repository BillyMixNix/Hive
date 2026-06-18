from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CognitionTrace:
    trace_id: str
    actor_id: str
    world_turn: int
    phase: str
    input_summary: dict[str, Any]
    output: dict[str, Any]
    source: str


@dataclass
class ActorCognition:
    actor_id: str
    goal: str
    observations: list[dict[str, Any]] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    plans: list[dict[str, Any]] = field(default_factory=list)
    visible_events: list[dict[str, Any]] = field(default_factory=list)
    lesson_ids: list[str] = field(default_factory=list)
    last_failure_code: str | None = None
    pending_lesson_ids: list[str] = field(default_factory=list)
    pending_lesson_context: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )


@dataclass
class CognitionState:
    actors: dict[str, ActorCognition] = field(default_factory=dict)
    traces: list[CognitionTrace] = field(default_factory=list)
    version: int = 1

    def actor(self, actor_id, default_goal):
        if actor_id not in self.actors:
            self.actors[actor_id] = ActorCognition(
                actor_id=actor_id,
                goal=default_goal,
            )
        return self.actors[actor_id]

    def to_dict(self):
        return {
            "version": self.version,
            "actors": {
                actor_id: asdict(actor)
                for actor_id, actor in self.actors.items()
            },
            "traces": [asdict(trace) for trace in self.traces],
        }

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        return cls(
            actors={
                actor_id: ActorCognition(**record)
                for actor_id, record in (data.get("actors") or {}).items()
            },
            traces=[
                CognitionTrace(**record)
                for record in data.get("traces", [])
            ],
            version=int(data.get("version", 1)),
        )
