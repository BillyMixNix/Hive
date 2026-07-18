from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from .content import build_foundation_world
from .intent import IntentInterpreter
from .knowledge import WorldKnowledge
from .models import ActionIntent, KnowledgeEvent, TurnResult, WorldEvent, WorldState
from .narrative import NarrativeGenerator
from .simulation import WorldSimulator


class TwinRealmsEngine:
    def __init__(
        self,
        state=None,
        *,
        interpreter=None,
        simulator=None,
        narrator=None,
        knowledge=None,
    ):
        self.initial_state = deepcopy(state or build_foundation_world())
        self.state = deepcopy(self.initial_state)
        self.interpreter = interpreter or IntentInterpreter()
        self.simulator = simulator or WorldSimulator()
        self.narrator = narrator or NarrativeGenerator()
        self.initial_knowledge = deepcopy(knowledge or WorldKnowledge())
        self.knowledge = deepcopy(self.initial_knowledge)
        self.events: list[WorldEvent] = []
        self.knowledge_events: list[KnowledgeEvent] = []
        self.cognition_state: dict = {}

    def turn(self, player_input):
        intent = self.interpreter.interpret(player_input, self.state)
        return self.apply_intent(intent)

    def promote_knowledge(self, key, min_observations=3, min_confidence=0.8):
        if self.events:
            raise RuntimeError("world rules can only be promoted before the run starts")
        record = self.knowledge.promote(key, min_observations, min_confidence)
        self.initial_knowledge = deepcopy(self.knowledge)
        return record

    def apply_intent(self, intent):
        event = self.simulator.resolve(self.state, intent, self.knowledge)
        self.events.append(event)
        narrative = self.narrator.render(event, deepcopy(self.state))
        return TurnResult(
            intent=intent,
            event=event,
            narrative=narrative,
            state_digest=self.simulator.state_digest(self.state),
        )

    def observe_knowledge_proposal(
        self,
        key,
        statement,
        event,
        *,
        source="llm",
        auto_promote=True,
        min_observations=3,
        min_confidence=0.8,
    ):
        from .ai import evaluate_hypothesis

        confirmed = evaluate_hypothesis(key, event)
        if confirmed is None:
            return None
        record = self.knowledge.observe(key, statement, confirmed=confirmed)
        promoted = False
        if (
            auto_promote
            and record.status != "promoted"
            and record.observations >= min_observations
            and record.confidence >= min_confidence
        ):
            self.knowledge.promote(key, min_observations, min_confidence)
            promoted = True
        knowledge_event = KnowledgeEvent(
            turn=event.turn,
            key=key,
            statement=statement,
            confirmed=confirmed,
            promoted=promoted,
            source=source,
        )
        self.knowledge_events.append(knowledge_event)
        return knowledge_event

    def replay(self):
        replayed = deepcopy(self.initial_state)
        knowledge = deepcopy(self.initial_knowledge)
        knowledge_by_turn = {}
        for knowledge_event in self.knowledge_events:
            knowledge_by_turn.setdefault(knowledge_event.turn, []).append(knowledge_event)
        for recorded in self.events:
            intent = ActionIntent.from_dict(recorded.intent)
            actual = self.simulator.resolve(replayed, intent, knowledge)
            if actual.to_dict() != recorded.to_dict():
                raise AssertionError(
                    f"replay diverged at turn {recorded.turn}: "
                    f"{actual.to_dict()} != {recorded.to_dict()}"
                )
            for knowledge_event in knowledge_by_turn.get(recorded.turn, []):
                knowledge.observe(
                    knowledge_event.key,
                    knowledge_event.statement,
                    confirmed=knowledge_event.confirmed,
                )
                if knowledge_event.promoted:
                    knowledge.records[knowledge_event.key].status = "promoted"
        self._last_replayed_knowledge = knowledge
        return replayed

    def verify_replay(self):
        replayed = self.replay()
        return (
            self.simulator.state_digest(replayed) == self.simulator.state_digest(self.state)
            and self._last_replayed_knowledge.to_dict() == self.knowledge.to_dict()
        )

    def snapshot(self):
        return {
            "initial_state": self.initial_state.to_dict(),
            "initial_knowledge": self.initial_knowledge.to_dict(),
            "state": self.state.to_dict(),
            "events": [event.to_dict() for event in self.events],
            "knowledge_events": [
                knowledge_event.to_dict()
                for knowledge_event in self.knowledge_events
            ],
            "knowledge": self.knowledge.to_dict(),
            "cognition_state": deepcopy(self.cognition_state),
        }

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(self.snapshot(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            last_error = None
            for attempt in range(6):
                try:
                    os.replace(temporary, path)
                    last_error = None
                    break
                except PermissionError as exc:
                    last_error = exc
                    time.sleep(0.05 * (attempt + 1))
            if last_error:
                raise last_error
        finally:
            if temporary.exists():
                temporary.unlink()
        return path

    @classmethod
    def load(cls, path, *, narrator=None):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        engine = cls(
            WorldState.from_dict(data["initial_state"]),
            narrator=narrator,
            knowledge=WorldKnowledge.from_dict(data.get("initial_knowledge")),
        )
        engine.state = WorldState.from_dict(data["state"])
        engine.knowledge = WorldKnowledge.from_dict(data.get("knowledge"))
        engine.events = [WorldEvent.from_dict(event) for event in data["events"]]
        engine.knowledge_events = [
            KnowledgeEvent.from_dict(event)
            for event in data.get("knowledge_events", [])
        ]
        engine.cognition_state = deepcopy(data.get("cognition_state") or {})
        engine.simulator.assert_invariants(engine.state)
        if not engine.verify_replay():
            raise ValueError("saved world does not match its event history")
        return engine
