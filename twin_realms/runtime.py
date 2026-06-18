from __future__ import annotations

from dataclasses import dataclass, field

from .engine import TwinRealmsEngine
from .models import ActionIntent


@dataclass
class RuntimeTurn:
    player_result: object
    npc_results: list[object] = field(default_factory=list)
    knowledge_events: list[object] = field(default_factory=list)
    world_results: list[object] = field(default_factory=list)


class TwinRealmsRuntime:
    MODES = {
        "baseline",
        "assisted",
        "adaptive",
        "hive",
        "hive_learning",
    }

    def __init__(
        self,
        engine: TwinRealmsEngine,
        *,
        mode="baseline",
        npc_planner=None,
        knowledge_agent=None,
        npc_ids=None,
        npc_scope="fixed",
        npc_limit=None,
        auto_promote=True,
    ):
        if mode not in self.MODES:
            raise ValueError(f"unsupported runtime mode: {mode}")
        if npc_scope not in {"fixed", "local", "all"}:
            raise ValueError(f"unsupported NPC scope: {npc_scope}")
        self.engine = engine
        self.mode = mode
        self.npc_planner = npc_planner
        self.knowledge_agent = knowledge_agent
        self.npc_ids = list(npc_ids or [])
        self.npc_scope = npc_scope
        self.npc_limit = npc_limit
        self.auto_promote = auto_promote
        self.player_turns = 0
        self.knowledge_supported = 0
        self.knowledge_promoted = 0
        if self.npc_planner and hasattr(self.npc_planner, "attach_engine"):
            self.npc_planner.attach_engine(engine)
        if self.npc_planner and hasattr(self.npc_planner, "ensure_actor"):
            for npc_id in self.npc_ids:
                if npc_id in engine.state.characters:
                    self.npc_planner.ensure_actor(npc_id, engine.state)

    def turn(self, player_input):
        self.player_turns += 1
        player_result = self.engine.turn(player_input)
        return self._complete_turn(player_result)

    def intent_turn(self, intent):
        """Resolve an exact human-selected intent, then advance NPC actors."""
        self.player_turns += 1
        player_result = self.engine.apply_intent(intent)
        return self._complete_turn(player_result)

    def _complete_turn(self, player_result, player_observer=None):
        npc_ids = self._npc_ids_for_turn()
        if self.npc_planner and hasattr(self.npc_planner, "ensure_actor"):
            for npc_id in npc_ids:
                self.npc_planner.ensure_actor(npc_id, self.engine.state)
        if (
            self.npc_planner
            and hasattr(self.npc_planner, "observe_world_event")
        ):
            self._forward_event(
                self.npc_planner,
                player_result.event,
            )
        knowledge_events = self._learn_from(player_result.event)
        npc_results = []
        if self.mode in {
            "assisted", "adaptive", "hive", "hive_learning"
        } and self.npc_planner:
            for npc_id in npc_ids:
                npc = self.engine.state.characters.get(npc_id)
                if not npc or not npc.alive or not npc.active:
                    continue
                result = self.engine.apply_intent(
                    self.npc_planner.propose(npc_id, self.engine.state)
                )
                if hasattr(self.npc_planner, "reflect"):
                    self.npc_planner.reflect(result.event, self.engine.state)
                if (
                    player_observer
                    and hasattr(player_observer, "observe_world_event")
                ):
                    self._forward_event(player_observer, result.event)
                npc_results.append(result)
                knowledge_events.extend(self._learn_from(result.event))
        world_results = self._advance_world_time()
        return RuntimeTurn(
            player_result,
            npc_results,
            knowledge_events,
            world_results,
        )

    def _advance_world_time(self, turns=1):
        if self.engine.state.flags.get("scenario_id") != "tarrow_aftermath":
            return []
        results = []
        for _ in range(turns):
            results.append(
                self.engine.apply_intent(
                    ActionIntent("world_tick", self.engine.state.player_id)
                )
            )
        return results

    def _npc_ids_for_turn(self):
        state = self.engine.state
        player = state.characters[state.player_id]
        if self.npc_scope == "fixed":
            candidates = list(self.npc_ids)
        else:
            candidates = [
                character.id
                for character in state.characters.values()
                if character.id != state.player_id
                and character.active
                and character.alive
                and (
                    self.npc_scope == "all"
                    or character.location_id == player.location_id
                )
            ]
        if self.npc_limit is not None and self.npc_limit > 0:
            candidates = candidates[:self.npc_limit]
        return candidates

    def agent_turn(self, player_agent):
        if hasattr(player_agent, "attach_engine"):
            player_agent.attach_engine(self.engine)
        self.player_turns += 1
        player_intent = player_agent.propose(
            self.engine.state.player_id,
            self.engine.state,
        )
        player_result = self.engine.apply_intent(player_intent)
        player_agent.reflect(player_result.event, self.engine.state)
        return self._complete_turn(
            player_result,
            player_observer=player_agent,
        )

    def _forward_event(self, agent, event):
        try:
            agent.observe_world_event(event, self.engine.state)
        except TypeError:
            agent.observe_world_event(event)

    def _learn_from(self, event):
        if self.mode != "adaptive" or not self.knowledge_agent:
            return []
        proposal = self.knowledge_agent.propose(event)
        if not proposal:
            return []
        recorded = self.engine.observe_knowledge_proposal(
            proposal["key"],
            proposal["statement"],
            event,
            source="llm",
            auto_promote=self.auto_promote,
        )
        if recorded:
            self.knowledge_supported += 1
            self.knowledge_promoted += int(recorded.promoted)
        return [recorded] if recorded else []

    def metrics(self):
        metrics = {
            "mode": self.mode,
            "player_turns": self.player_turns,
            "world_turns": self.engine.state.turn,
            "events": len(self.engine.events),
            "npc_scope": self.npc_scope,
            "scheduled_npcs": len(self._npc_ids_for_turn()),
            "replay_consistent": self.engine.verify_replay(),
            "narration_guard_violations": getattr(
                self.engine.narrator,
                "guard_violation_count",
                0,
            ),
        }
        for name, component in (
            ("intent", self.engine.interpreter),
            ("npc", self.npc_planner),
            ("knowledge", self.knowledge_agent),
        ):
            if component and hasattr(component, "metrics"):
                metrics[f"{name}_proposals"] = component.metrics.to_dict()
        if self.knowledge_agent:
            calls = self.knowledge_agent.metrics.calls
            metrics["knowledge_evidence"] = {
                "supported": self.knowledge_supported,
                "promoted": self.knowledge_promoted,
                "support_rate": self.knowledge_supported / calls if calls else 0.0,
            }
        return metrics
