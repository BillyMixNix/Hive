from __future__ import annotations

import json
import random
import time
from hashlib import sha256
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from .agent_loop import AffordanceBuilder, SituationalAwarenessBuilder
from .ai import ProposalMetrics, _parse_json_object
from .cognition import CognitionState, CognitionTrace
from .models import ActionIntent, WorldEvent, WorldState


class TwinRealmsHiveAdapter:
    """Hive cognition over actor-visible evidence and validated affordances."""

    def __init__(
        self,
        llm,
        *,
        cognition=None,
        lesson_memory=None,
        learning=False,
        affordances=None,
        awareness=None,
        memory_limit=12,
        transport_cooldown=30,
    ):
        self.llm = llm
        self.cognition = cognition or CognitionState()
        self.lesson_memory = lesson_memory
        self.learning = learning
        self.affordances = affordances or AffordanceBuilder()
        self.awareness = awareness or SituationalAwarenessBuilder()
        self.memory_limit = memory_limit
        self.transport_cooldown = transport_cooldown
        self.transport_failures = 0
        self.last_transport_error = None
        self._transport_retry_after = 0.0
        self.metrics = ProposalMetrics()
        self.phase_calls = {
            "observe": 0,
            "investigate": 0,
            "plan": 0,
            "act": 0,
            "learn": 0,
        }
        self.phase_valid = {phase: 0 for phase in self.phase_calls}
        self.phase_invalid = {phase: 0 for phase in self.phase_calls}
        self.phase_fallbacks = {phase: 0 for phase in self.phase_calls}
        self._engine = None

    @classmethod
    def using_hive(cls, **kwargs):
        from hive_llm import ask_hive

        return cls(ask_hive, **kwargs)

    def attach_engine(self, engine):
        self._engine = engine
        persisted = getattr(engine, "cognition_state", None)
        if persisted and not self.cognition.actors and not self.cognition.traces:
            self.cognition = CognitionState.from_dict(persisted)
        self._sync()

    def set_goal(self, actor_id, goal):
        actor = self.cognition.actor(actor_id, goal)
        actor.goal = str(goal).strip() or actor.goal
        self._sync()

    def ensure_actor(self, actor_id, state):
        self.cognition.actor(
            actor_id,
            self._default_goal(state.characters[actor_id]),
        )
        self._sync()

    def propose(self, actor_id, state: WorldState):
        actor = state.characters[actor_id]
        cognition = self.cognition.actor(
            actor_id,
            self._default_goal(actor),
        )
        options = self._present_options(
            actor_id,
            state,
            self.affordances.build(actor_id, state),
        )
        safe_option = next(
            option for option in options
            if option["intent"].action == "wait"
        )
        lessons = self._retrieve_lessons(actor_id, state, cognition)
        visible = self._visible_context(actor_id, state, options)

        observation = self._phase(
            "observe",
            actor_id,
            state.turn,
            self._observe_prompt(visible, cognition, lessons),
            fallback={
                "summary": "Use current visible state and resolved events.",
            },
            input_summary={"visible_context": visible},
        )
        cognition.observations.append({
            "turn": state.turn,
            **observation,
        })
        cognition.observations = cognition.observations[-self.memory_limit:]

        investigation = self._phase(
            "investigate",
            actor_id,
            state.turn,
            self._investigate_prompt(visible, cognition, observation),
            fallback={
                "needed": False,
                "question": None,
                "preferred_action": None,
                "reason": "No investigation proposed.",
            },
            input_summary={"observation": observation},
        )
        question = investigation.get("question")
        if investigation.get("needed") and isinstance(question, str):
            cognition.unresolved_questions.append(question)
            cognition.unresolved_questions = cognition.unresolved_questions[
                -self.memory_limit:
            ]

        plan = self._phase(
            "plan",
            actor_id,
            state.turn,
            self._plan_prompt(
                visible,
                cognition,
                observation,
                investigation,
                lessons,
            ),
            fallback={
                "goal": cognition.goal,
                "steps": ["Choose one valid action."],
                "success_condition": "The action resolves.",
            },
            input_summary={
                "goal": cognition.goal,
                "investigation": investigation,
                "lesson_ids": [
                    lesson.get("lesson_id") for lesson in lessons
                ],
            },
        )
        plan_id = f"plan:{uuid4().hex}"
        plan_record = {
            "plan_id": plan_id,
            "created_turn": state.turn,
            "status": "active",
            **plan,
        }
        cognition.plans.append(plan_record)
        cognition.plans = cognition.plans[-self.memory_limit:]

        self.metrics.calls += 1
        action = self._phase(
            "act",
            actor_id,
            state.turn,
            self._act_prompt(
                visible,
                cognition,
                observation,
                investigation,
                plan_record,
                lessons,
            ),
            fallback={
                "choice_id": safe_option["choice_id"],
                "confidence": 0.0,
            },
            input_summary={
                "plan_id": plan_id,
                "available_choice_ids": [
                    option["choice_id"] for option in options
                ],
            },
        )
        act_fell_back = self.cognition.traces[-1].source == "fallback"
        try:
            choice_id = str(action.get("choice_id") or "")
            selected = next(
                option for option in options
                if option["choice_id"] == choice_id
            )
            if act_fell_back:
                self.metrics.invalid += 1
                self.metrics.fallbacks += 1
            else:
                self.metrics.valid += 1
        except StopIteration:
            self.metrics.invalid += 1
            self.metrics.fallbacks += 1
            selected = safe_option
            choice_id = selected["choice_id"]

        used_lesson_ids = [
            lesson.get("lesson_id")
            for lesson in lessons
            if lesson.get("lesson_id")
        ]
        cognition.pending_lesson_ids = used_lesson_ids
        cognition.pending_lesson_context = {
            lesson["lesson_id"]: {
                "failure_code": (
                    lesson.get("failure_code")
                    or lesson.get("failure_reason")
                ),
                "trigger_pattern": lesson.get("trigger_pattern"),
                "fix_strategy": lesson.get("fix_strategy"),
                "retry_instruction": lesson.get("retry_instruction"),
            }
            for lesson in lessons
            if lesson.get("lesson_id")
        }
        for lesson in lessons:
            self._record_lesson_use(lesson, actor_id, state)
        intent = selected["intent"]
        parameters = dict(intent.parameters)
        parameters.update({
            "proposal_source": "hive_agent_adapter",
            "plan_id": plan_id,
            "choice_id": choice_id,
            "goal": cognition.goal,
            "lesson_ids": used_lesson_ids,
        })
        chosen_action = {
            "action": intent.action,
            "actor_id": intent.actor_id,
            "target_id": intent.target_id,
            "destination_id": intent.destination_id,
            "distance": intent.distance,
            "parameters": deepcopy(parameters),
        }
        cognition.decision_log.append({
            "turn": state.turn,
            "plan_id": plan_id,
            "observation": deepcopy(observation),
            "goal": cognition.goal,
            "available_affordances": [
                {
                    "choice_id": option["choice_id"],
                    "description": option["description"],
                    "action": option["intent"].action,
                    "target_id": option["intent"].target_id,
                    "destination_id": option["intent"].destination_id,
                }
                for option in options
            ],
            "choice_id": choice_id,
            "chosen_action": chosen_action,
            "result": None,
        })
        cognition.decision_log = cognition.decision_log[-self.memory_limit:]
        self._sync()
        return ActionIntent(
            action=intent.action,
            actor_id=intent.actor_id,
            target_id=intent.target_id,
            destination_id=intent.destination_id,
            distance=intent.distance,
            confidence=max(0.0, min(1.0, float(action.get("confidence", 0.5)))),
            parameters=parameters,
        )

    @staticmethod
    def _present_options(actor_id, state, options):
        presented = list(options)
        seed_material = f"{state.seed}:{state.turn}:{actor_id}:choices"
        seed = int.from_bytes(
            sha256(seed_material.encode("utf-8")).digest()[:8],
            "big",
        )
        random.Random(seed).shuffle(presented)
        return [
            {
                **option,
                "choice_id": f"a{index}",
            }
            for index, option in enumerate(presented, start=1)
        ]

    def reflect(self, event: WorldEvent, state: WorldState):
        cognition = self.cognition.actor(
            event.actor_id,
            self._default_goal(state.characters[event.actor_id]),
        )
        self.observe_world_event(event, state)
        plan_id = event.intent.get("parameters", {}).get("plan_id")
        for plan in reversed(cognition.plans):
            if plan.get("plan_id") == plan_id:
                plan["status"] = "progressed" if event.accepted else "rejected"
                plan["resolved_turn"] = event.turn
                plan["event_type"] = event.event_type
                plan["reason"] = event.reason
                break
        for decision in reversed(cognition.decision_log):
            if decision.get("plan_id") == plan_id:
                decision["result"] = {
                    "turn": event.turn,
                    "event_type": event.event_type,
                    "accepted": event.accepted,
                    "reason": event.reason,
                    "state_event_id": event.id,
                }
                break

        for lesson_id in cognition.pending_lesson_ids:
            lesson_context = cognition.pending_lesson_context.get(
                lesson_id, {}
            )
            applied = self._lesson_applied(lesson_context, event)
            self._record_lesson_outcome(
                lesson_id,
                success=event.accepted and applied,
                event=event,
                applied=applied,
            )
        cognition.pending_lesson_ids = []
        cognition.pending_lesson_context = {}
        cognition.last_failure_code = event.reason if not event.accepted else None

        if self.learning and not event.accepted and event.reason:
            lesson = self._phase(
                "learn",
                event.actor_id,
                event.turn,
                self._learn_prompt(event, cognition, state),
                fallback={
                    "failure_pattern": event.reason,
                    "retry_instruction": (
                        "Use current affordances and do not repeat the rejected "
                        "action until relevant state changes."
                    ),
                    "trigger_pattern": event.intent.get("action"),
                    "fix_strategy": "select_current_affordance",
                },
                input_summary={
                    "event_type": event.event_type,
                    "reason": event.reason,
                },
            )
            lesson_id = self._store_lesson(
                event.actor_id,
                event,
                lesson,
                state,
            )
            if lesson_id:
                cognition.lesson_ids.append(lesson_id)
                cognition.lesson_ids = cognition.lesson_ids[-self.memory_limit:]
        self._sync()

    def observe_world_event(self, event: WorldEvent, state: WorldState | None = None):
        state = state or (self._engine.state if self._engine else None)
        if state is None:
            return
        for actor_id, cognition in self.cognition.actors.items():
            if self._event_visible_to(actor_id, event, state):
                visible_event = {
                    "turn": event.turn,
                    "event_type": event.event_type,
                    "action": event.intent.get("action"),
                    "actor_id": event.actor_id,
                    "target_id": event.target_id,
                    "accepted": event.accepted,
                    "reason": event.reason,
                    "facts": deepcopy(event.facts),
                }
                if (
                    cognition.visible_events
                    and cognition.visible_events[-1]["turn"] == event.turn
                    and cognition.visible_events[-1]["actor_id"] == event.actor_id
                    and cognition.visible_events[-1]["event_type"]
                    == event.event_type
                ):
                    continue
                cognition.visible_events.append(visible_event)
                cognition.visible_events = cognition.visible_events[
                    -self.memory_limit:
                ]
        self._sync()

    def metrics_dict(self):
        data = self.metrics.to_dict()
        data["phase_calls"] = dict(self.phase_calls)
        data["phase_valid"] = dict(self.phase_valid)
        data["phase_invalid"] = dict(self.phase_invalid)
        data["phase_fallbacks"] = dict(self.phase_fallbacks)
        data["actors"] = len(self.cognition.actors)
        data["traces"] = len(self.cognition.traces)
        data["learning_enabled"] = self.learning
        data["transport_failures"] = self.transport_failures
        data["last_transport_error"] = self.last_transport_error
        return data

    def _phase(
        self,
        phase,
        actor_id,
        world_turn,
        prompt,
        *,
        fallback,
        input_summary,
    ):
        self.phase_calls[phase] += 1
        source = "hive"
        raw_response = None
        contract_error = None
        try:
            if time.monotonic() < self._transport_retry_after:
                raise RuntimeError(
                    "Hive transport circuit is open"
                    + (
                        f": {self.last_transport_error}"
                        if self.last_transport_error
                        else ""
                    )
                )
            raw_response = self._invoke(phase, prompt)
            output = _parse_json_object(raw_response)
            self._validate_phase_output(phase, output)
            if (
                phase == "act"
                and output["choice_id"]
                not in input_summary.get("available_choice_ids", [])
            ):
                raise ValueError(
                    "act choice_id is not in allowed_choice_ids"
                )
            self.phase_valid[phase] += 1
        except Exception as exc:
            if raw_response is None and not (
                isinstance(exc, RuntimeError)
                and str(exc).startswith("Hive transport circuit is open")
            ):
                self.transport_failures += 1
                self.last_transport_error = str(exc)
                self._transport_retry_after = (
                    time.monotonic() + self.transport_cooldown
                )
            output = deepcopy(fallback)
            contract_error = str(exc)
            output["_contract_error"] = contract_error
            output["_raw_response"] = str(raw_response or "")[:1000]
            source = "fallback"
            self.phase_invalid[phase] += 1
            self.phase_fallbacks[phase] += 1
        self.cognition.traces.append(CognitionTrace(
            trace_id=f"trace:{uuid4().hex}",
            actor_id=actor_id,
            world_turn=world_turn,
            phase=phase,
            input_summary=deepcopy(input_summary),
            output=deepcopy(output),
            source=source,
        ))
        return output

    @staticmethod
    def _validate_phase_output(phase, output):
        required = {
            "observe": {
                "summary": str,
            },
            "investigate": {
                "needed": bool,
                "reason": str,
            },
            "plan": {
                "goal": str,
                "steps": list,
                "success_condition": str,
            },
            "act": {
                "choice_id": str,
                "confidence": (int, float),
            },
            "learn": {
                "failure_pattern": str,
                "retry_instruction": str,
                "trigger_pattern": str,
                "fix_strategy": str,
            },
        }[phase]
        for field, expected_type in required.items():
            if field not in output or not isinstance(
                output[field], expected_type
            ):
                raise ValueError(
                    f"{phase} output has invalid field: {field}"
                )
        if phase == "investigate":
            if output.get("question") is not None and not isinstance(
                output.get("question"), str
            ):
                raise ValueError("investigate question must be string or null")
            if output.get("preferred_action") is not None and not isinstance(
                output.get("preferred_action"), str
            ):
                raise ValueError(
                    "investigate preferred_action must be string or null"
                )
        if phase == "act" and not 0 <= float(output["confidence"]) <= 1:
            raise ValueError("act confidence is outside bounds")

    def _invoke(self, phase, prompt):
        role = {
            "observe": "default",
            "investigate": "strategic",
            "plan": "planner",
            "act": "default",
            "learn": "reflector",
        }[phase]
        try:
            return self.llm(prompt, role=role)
        except TypeError:
            return self.llm(prompt)

    def _visible_context(self, actor_id, state, options):
        actor = state.characters[actor_id]
        cognition = self.cognition.actor(
            actor_id,
            self._default_goal(actor),
        )
        present = sorted(
            character.id
            for character in state.characters.values()
            if character.id != actor_id
            and character.active
            and character.alive
            and character.location_id == actor.location_id
        )
        return {
            "world_turn": state.turn,
            "actor": {
                "actor_id": actor_id,
                "location_id": actor.location_id,
                "health": actor.health,
                "max_health": actor.max_health,
                "stamina": actor.stamina,
                "max_stamina": actor.max_stamina,
                "inventory": list(actor.inventory),
                "equipment": dict(actor.equipment),
                "skills": dict(actor.skill_mastery),
                "jobs": dict(actor.jobs),
                "needs": dict(actor.needs),
                "coins": actor.coins,
                "faction_id": actor.faction_id,
                "reputation": dict(actor.reputation),
                "cultivation_stage": actor.cultivation_stage,
                "cultivation_progress": actor.cultivation_progress,
            },
            "location": {
                "location_id": actor.location_id,
                "danger": state.locations[actor.location_id].danger,
                "tags": list(state.locations[actor.location_id].tags),
                "connected_locations": sorted(
                    state.locations[actor.location_id].connections
                ),
                "present_characters": present,
                "ground_items": sorted(
                    state.ground_items.get(actor.location_id, [])
                ),
            },
            "role_evidence": self._actor_role_evidence(
                actor_id,
                state,
                present,
            ),
            "behavioral_evidence": self._behavioral_evidence(
                actor_id,
                cognition,
            ),
            "situational_awareness": self._actor_visible_awareness(
                actor_id,
                state,
                options,
            ),
            "available_choices": [
                {
                    "choice_id": option["choice_id"],
                    "description": option["description"],
                }
                for option in options
            ],
        }

    @staticmethod
    def _actor_role_evidence(actor_id, state, present):
        actor = state.characters[actor_id]
        faction = state.factions.get(actor.faction_id or "")
        dispositions = []
        for other_id in present:
            other = state.characters[other_id]
            relation = None
            if faction and other.faction_id:
                relation = (
                    100
                    if other.faction_id == actor.faction_id
                    else faction.relations.get(other.faction_id, 0)
                )
            dispositions.append({
                "actor_id": other_id,
                "faction_id": other.faction_id,
                "faction_relation": relation,
                "hostile_by_world_rule": (
                    "hostile" in actor.tags
                    or "hostile" in other.tags
                ),
            })
        pressures = [
            {
                "pressure_id": pressure_id,
                "severity": pressure.get("severity"),
                "affected_locations": list(
                    pressure.get("affected_locations", [])
                ),
            }
            for pressure_id, pressure in sorted(
                state.flags.get("world_pressures", {}).items()
            )
            if pressure.get("source_id") == actor_id
        ]
        return {
            "evidence_scope": "actor_identity_and_visible_relations",
            "tags": list(actor.tags),
            "faction": (
                {
                    "faction_id": faction.id,
                    "name": faction.name,
                    "values": list(faction.values),
                    "laws": list(faction.laws),
                }
                if faction
                else None
            ),
            "visible_dispositions": dispositions,
            "world_pressures_sourced_by_actor": pressures,
        }

    @staticmethod
    def _behavioral_evidence(actor_id, cognition):
        own_events = [
            event for event in cognition.visible_events
            if event.get("actor_id") == actor_id
        ]
        recent_actions = [
            event.get("action") or event.get("event_type")
            for event in own_events[-8:]
        ]
        repeated_action_streak = 0
        if recent_actions:
            latest = recent_actions[-1]
            for action in reversed(recent_actions):
                if action != latest:
                    break
                repeated_action_streak += 1
        return {
            "evidence_scope": "own_cognition_history",
            "recent_actions": recent_actions,
            "repeated_action_streak": repeated_action_streak,
            "latest_unresolved_question": (
                cognition.unresolved_questions[-1]
                if cognition.unresolved_questions
                else None
            ),
            "recent_plan_outcomes": [
                {
                    "plan_id": plan.get("plan_id"),
                    "status": plan.get("status"),
                    "event_type": plan.get("event_type"),
                    "reason": plan.get("reason"),
                }
                for plan in cognition.plans[-4:]
            ],
        }

    @staticmethod
    def _default_goal(actor):
        if "hostile" in actor.tags:
            return "Protect faction interests and respond to visible conditions."
        return (
            "Remain coherent with the world, satisfy needs, develop capabilities, "
            "and pursue useful local opportunities."
        )

    @staticmethod
    def _event_visible_to(actor_id, event, state):
        actor = state.characters.get(actor_id)
        event_actor = state.characters.get(event.actor_id)
        target = state.characters.get(event.target_id or "")
        if not actor:
            return False
        if actor_id in {event.actor_id, event.target_id}:
            return True
        return bool(
            actor.alive
            and actor.active
            and (
                event_actor
                and event_actor.location_id == actor.location_id
                or target
                and target.location_id == actor.location_id
            )
        )

    def _retrieve_lessons(self, actor_id, state, cognition):
        if not self.lesson_memory or not cognition.last_failure_code:
            return []
        return self.lesson_memory.get_retry_lessons(
            file=f"twin_realms/{actor_id}",
            change_type="action_selection",
            failure_code=cognition.last_failure_code,
            context_mode="world_agent",
            current_context={
                "actor_id": actor_id,
                "location_id": state.characters[actor_id].location_id,
                "world_turn": state.turn,
            },
            limit=3,
        )

    def _actor_visible_awareness(self, actor_id, state, options):
        actor = state.characters[actor_id]
        cognition = self.cognition.actor(
            actor_id,
            self._default_goal(actor),
        )
        visible_hostiles = sorted(
            character.id
            for character in state.characters.values()
            if character.id != actor_id
            and character.active
            and character.alive
            and character.location_id == actor.location_id
            and (
                "hostile" in character.tags
                or "hostile" in actor.tags
            )
        )
        incoming = [
            event for event in cognition.visible_events
            if event["event_type"] == "attack_resolved"
            and event.get("target_id") == actor_id
            and event["accepted"]
        ][-3:]
        recent_damage = sum(
            event.get("facts", {}).get("damage", 0)
            for event in incoming
        )
        actions = sorted({option["intent"].action for option in options})
        health_ratio = actor.health / actor.max_health
        stamina_ratio = actor.stamina / actor.max_stamina
        terminal_risk = (
            (1 - health_ratio) * 0.5
            + (1 - stamina_ratio) * 0.2
            + (0.2 if visible_hostiles else 0)
            + min(0.1, recent_damage / max(1, actor.max_health) * 0.2)
        )
        return {
            "evidence_scope": "actor_visible",
            "visible_hostiles": visible_hostiles,
            "hostile_proximity": [
                {
                    "actor_id": hostile_id,
                    "graph_distance": 0,
                    "location_id": actor.location_id,
                }
                for hostile_id in visible_hostiles
            ],
            "recent_damage": {
                "total": recent_damage,
                "hits": len(incoming),
                "last_turn": incoming[-1]["turn"] if incoming else None,
            },
            "health_stamina_risk": {
                "health": actor.health,
                "max_health": actor.max_health,
                "health_ratio": round(health_ratio, 3),
                "stamina": actor.stamina,
                "max_stamina": actor.max_stamina,
                "stamina_ratio": round(stamina_ratio, 3),
                "can_pay_attack_cost": actor.stamina >= 10,
            },
            "safe_exits": [
                {
                    "destination_id": destination_id,
                    "danger": state.locations[destination_id].danger,
                    "hostile_occupancy": "unknown",
                }
                for destination_id in sorted(
                    state.locations[actor.location_id].connections
                )
            ],
            "available_actions": actions,
            "goal_conflict_flags": {
                "hostile_present_while_progression_available": bool(
                    visible_hostiles
                    and {"craft", "cultivate", "gather", "train", "work"}
                    .intersection(actions)
                ),
                "low_stamina_while_hostile_present": bool(
                    visible_hostiles and actor.stamina < 10
                ),
            },
            "terminal_risk_score": round(min(1.0, terminal_risk), 3),
            "local_resources": [
                {
                    "resource_node_id": node.id,
                    "kind": node.resource_kind,
                    "quantity": node.quantity,
                }
                for node in state.resource_nodes.values()
                if node.location_id == actor.location_id
            ],
        }

    def _store_lesson(self, actor_id, event, lesson, state):
        if not self.lesson_memory:
            return None
        lesson_id = f"twin-realms:{uuid4().hex}"
        self.lesson_memory.add_lesson(
            file=f"twin_realms/{actor_id}",
            change_type="action_selection",
            failure_reason=event.reason,
            retry_instruction=str(lesson.get("retry_instruction") or ""),
            failure_pattern=str(
                lesson.get("failure_pattern") or event.reason
            ),
            source="twin_realms_hive_adapter",
            lesson_id=lesson_id,
            failure_code=event.reason,
            context_mode="world_agent",
            trigger_pattern=lesson.get("trigger_pattern"),
            fix_strategy=lesson.get("fix_strategy"),
            context_requirements={
                "actor_id": actor_id,
                "action": event.intent.get("action"),
            },
            scope="domain",
            current_location_id=state.characters[actor_id].location_id,
        )
        return lesson_id

    def _record_lesson_use(self, lesson, actor_id, state):
        if not self.lesson_memory or not lesson.get("lesson_id"):
            return
        self.lesson_memory.record_lesson_use(
            lesson["lesson_id"],
            match_reasons=lesson.get("_match_reasons"),
            reuse_context={
                "actor_id": actor_id,
                "location_id": state.characters[actor_id].location_id,
            },
        )

    def _record_lesson_outcome(
        self,
        lesson_id,
        success,
        event,
        *,
        applied,
    ):
        if not self.lesson_memory:
            return
        self.lesson_memory.record_lesson_outcome(
            lesson_id,
            success=success,
            outcome_note=(
                event.event_type
                if applied
                else f"lesson_not_applied:{event.event_type}"
            ),
            reuse_helped=success if applied else False,
            reuse_context={
                "actor_id": event.actor_id,
                "action": event.intent.get("action"),
                "lesson_applied": applied,
            },
        )

    @staticmethod
    def _lesson_applied(lesson, event):
        action = str(event.intent.get("action") or "").lower()
        failure_code = str(lesson.get("failure_code") or "").lower()
        retry = " ".join([
            str(lesson.get("retry_instruction") or ""),
            str(lesson.get("fix_strategy") or ""),
        ]).lower()
        trigger = str(lesson.get("trigger_pattern") or "").lower()
        if action and action in trigger:
            return event.reason != failure_code
        action_terms = {
            "rest": ("rest", "recover stamina", "increase stamina"),
            "observe": ("observe", "inspect", "look"),
            "move": ("move", "travel", "leave", "retreat"),
            "talk": ("talk", "ask", "speak"),
            "equip": ("equip", "wield", "wear"),
            "gather": ("gather", "harvest", "mine", "fish"),
            "cultivate": ("cultivate", "cycle qi"),
        }
        return any(
            term in retry
            for term in action_terms.get(action, ())
        )

    def _sync(self):
        if self._engine is not None:
            self._engine.cognition_state = self.cognition.to_dict()

    @staticmethod
    def _json_contract(phase, packet, shape, rules):
        return (
            f"PHASE: {phase}\n"
            "Return exactly one JSON object and no other text.\n"
            f"Exact shape: {json.dumps(shape, sort_keys=True)}\n"
            f"Rules: {rules}\n\n"
            f"Input packet:\n{json.dumps(packet, sort_keys=True)}"
        )

    def _observe_prompt(self, visible, cognition, lessons):
        visible_world = deepcopy(visible)
        visible_world.pop("available_choices", None)
        return self._json_contract(
            "observe",
            {
                "visible_world": visible_world,
                "goal": cognition.goal,
                "visible_events": cognition.visible_events[-4:],
                "lessons": [
                    {
                        "failure_pattern": lesson.get("failure_pattern"),
                        "retry_instruction": lesson.get("retry_instruction"),
                    }
                    for lesson in lessons
                ],
            },
            {
                "summary": "string",
            },
            (
                "Use only visible evidence. Do not infer hidden state. "
                "Treat role_evidence dispositions and situational_awareness "
                "visible_hostiles as authoritative world-derived facts. "
                "Do not describe a listed hostile as absent or non-threatening. "
                "Return only the summary field. summary must be at most 160 "
                "characters. Keep the entire JSON response under 40 words."
            ),
        )

    def _investigate_prompt(self, visible, cognition, observation):
        return self._json_contract(
            "investigate",
            {
                "goal": cognition.goal,
                "observation": observation,
                "unresolved_questions": cognition.unresolved_questions,
                "role_evidence": visible["role_evidence"],
                "situational_awareness": visible["situational_awareness"],
                "available_choices": visible["available_choices"],
            },
            {
                "needed": False,
                "question": None,
                "preferred_action": None,
                "reason": "string",
            },
            (
                "If evidence is missing, name an available information-gathering "
                "action type such as observe, talk, or move. Never request hidden state."
            ),
        )

    def _plan_prompt(
        self,
        visible,
        cognition,
        observation,
        investigation,
        lessons,
    ):
        return self._json_contract(
            "plan",
            {
                "goal": cognition.goal,
                "observation": observation,
                "investigation": investigation,
                "active_plans": cognition.plans[-3:],
                "lessons": lessons,
                "role_evidence": visible["role_evidence"],
                "situational_awareness": visible["situational_awareness"],
                "behavioral_evidence": visible["behavioral_evidence"],
                "available_choices": visible["available_choices"],
            },
            {
                "goal": "string",
                "steps": ["string"],
                "success_condition": "string",
            },
            (
                "Plan only through available choices and observable follow-up "
                "actions. Treat behavioral_evidence as read-only history: a "
                "progressed action is not a completed multi-step plan, and "
                "repeated information gathering without a new unresolved "
                "question may not advance the goal."
            ),
        )

    def _act_prompt(
        self,
        visible,
        cognition,
        observation,
        investigation,
        plan,
        lessons,
    ):
        return self._json_contract(
            "act",
            {
                "goal": cognition.goal,
                "observation": observation,
                "investigation": investigation,
                "plan": plan,
                "lessons": lessons,
                "role_evidence": visible["role_evidence"],
                "situational_awareness": visible["situational_awareness"],
                "behavioral_evidence": visible["behavioral_evidence"],
                "allowed_choice_ids": [
                    choice["choice_id"]
                    for choice in visible["available_choices"]
                ],
                "available_choices": visible["available_choices"],
            },
            {"choice_id": "a1", "confidence": 1.0},
            (
                "Choose exactly one listed choice_id. Do not emit an action name, "
                "entity ID, world mutation, or replacement packet. Treat "
                "behavioral_evidence as read-only history when judging whether "
                "repeating a choice advances the current plan. The choice_id "
                "must appear in allowed_choice_ids; do not invent the next ID."
            ),
        )

    def _learn_prompt(self, event, cognition, state):
        return self._json_contract(
            "learn",
            {
                "goal": cognition.goal,
                "resolved_event": event.to_dict(),
                "actor_location": state.characters[event.actor_id].location_id,
            },
            {
                "failure_pattern": "string",
                "retry_instruction": "string",
                "trigger_pattern": "string",
                "fix_strategy": "string",
            },
            (
                "Create a bounded action-selection lesson. It cannot change world "
                "rules and must refer only to the resolved failure."
            ),
        )
