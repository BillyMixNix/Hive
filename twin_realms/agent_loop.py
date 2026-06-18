from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field

from .ai import ProposalMetrics, _parse_json_object
from .models import ActionIntent, WorldEvent, WorldState


@dataclass
class AgentMind:
    actor_id: str
    goal: str
    recent_outcomes: list[dict] = field(default_factory=list)
    completed_goals: int = 0
    revised_goals: int = 0


class AffordanceBuilder:
    """Builds actions that are structurally executable in the current state."""

    def build(self, actor_id, state: WorldState):
        actor = state.characters[actor_id]
        affordances = []

        def add(intent, description):
            affordances.append({
                "choice_id": f"a{len(affordances) + 1}",
                "description": description,
                "intent": intent,
            })

        add(ActionIntent("wait", actor_id), "Wait and observe changes.")
        add(ActionIntent("rest", actor_id), "Recover stamina and tend injuries.")
        add(ActionIntent("observe", actor_id), "Observe the current location.")

        for destination_id in sorted(state.locations[actor.location_id].connections):
            add(
                ActionIntent("move", actor_id, destination_id=destination_id),
                f"Move to {destination_id}.",
            )

        present = sorted(
            character.id
            for character in state.characters.values()
            if character.id != actor_id
            and character.active
            and character.alive
            and character.location_id == actor.location_id
        )
        for target_id in present:
            add(
                ActionIntent("observe", actor_id, target_id=target_id),
                f"Observe {target_id}.",
            )
            add(
                ActionIntent("talk", actor_id, target_id=target_id),
                f"Talk to {target_id}.",
            )
            target = state.characters[target_id]
            if "hostile" in actor.tags or "hostile" in target.tags:
                add(
                    ActionIntent("attack", actor_id, target_id=target_id),
                    f"Attack {target_id}.",
                )
            if "merchant" in target.tags:
                for item_id in sorted(target.inventory):
                    price = state.items[item_id].value
                    if actor.coins >= price:
                        add(
                            ActionIntent(
                                "trade",
                                actor_id,
                                target_id=target_id,
                                parameters={"item_id": item_id},
                            ),
                            f"Buy {item_id} from {target_id} for {price} coins.",
                        )

        for item_id in sorted(actor.inventory):
            item = state.items[item_id]
            if item.slot and actor.equipment.get(item.slot) != item_id:
                add(
                    ActionIntent(
                        "equip",
                        actor_id,
                        parameters={"item_id": item_id},
                    ),
                    f"Equip {item_id}.",
                )
            add(
                ActionIntent(
                    "drop",
                    actor_id,
                    parameters={"item_id": item_id},
                ),
                f"Drop {item_id}.",
            )

        for item_id in sorted(state.ground_items.get(actor.location_id, [])):
            add(
                ActionIntent(
                    "pickup",
                    actor_id,
                    parameters={"item_id": item_id},
                ),
                f"Pick up {item_id}.",
            )

        for skill_id in sorted(state.flags.get("skills", [])):
            if actor.stamina >= 8:
                add(
                    ActionIntent(
                        "train",
                        actor_id,
                        parameters={"skill_id": skill_id},
                    ),
                    f"Train {skill_id}.",
                )

        for job_id in sorted(state.flags.get("jobs", [])):
            job_sites = state.flags.get("job_sites", {}).get(job_id)
            if (
                actor.stamina >= 12
                and (not job_sites or actor.location_id in job_sites)
            ):
                add(
                    ActionIntent(
                        "work",
                        actor_id,
                        parameters={"job_id": job_id},
                    ),
                    f"Work as {job_id}.",
                )
        for node in sorted(
            state.resource_nodes.values(),
            key=lambda resource: resource.id,
        ):
            if (
                node.location_id == actor.location_id
                and node.quantity > 0
                and actor.stamina >= 8
            ):
                add(
                    ActionIntent(
                        "gather",
                        actor_id,
                        parameters={"resource_node_id": node.id},
                    ),
                    f"Gather {node.resource_kind} from {node.id}.",
                )
        for recipe_id, recipe in sorted(
            state.flags.get("recipes", {}).items()
        ):
            available = {
                kind: sum(
                    state.items[item_id].kind == kind
                    for item_id in actor.inventory
                )
                for kind in recipe.get("inputs", {})
            }
            if (
                actor.stamina >= 12
                and actor.skill_mastery.get(recipe["skill"], 0)
                >= recipe.get("min_mastery", 0)
                and all(
                    available[kind] >= required
                    for kind, required in recipe.get("inputs", {}).items()
                )
            ):
                add(
                    ActionIntent(
                        "craft",
                        actor_id,
                        parameters={"recipe_id": recipe_id},
                    ),
                    f"Craft {recipe_id}.",
                )
        if state.flags.get("cultivation_stages") and actor.stamina >= 16:
            add(
                ActionIntent("cultivate", actor_id),
                "Cultivate and advance toward the next realm stage.",
            )
        if actor.schedule:
            add(
                ActionIntent("follow_schedule", actor_id),
                "Follow the current home or work schedule.",
            )
        return affordances


class SituationalAwarenessBuilder:
    """Derives tactical evidence without selecting or modifying actions."""

    PROGRESSION_ACTIONS = {
        "craft",
        "cultivate",
        "equip",
        "gather",
        "pickup",
        "trade",
        "train",
        "work",
    }
    DEFENSIVE_ACTIONS = {"equip", "move", "rest", "wait"}
    COMBAT_ACTIONS = {"attack", "space_fold"}

    def build(self, actor_id, state, options, observed_events):
        actor = state.characters[actor_id]
        hostiles = sorted(
            character.id
            for character in state.characters.values()
            if character.id != actor_id
            and character.active
            and character.alive
            and (
                "hostile" in character.tags
                or "hostile" in actor.tags
            )
        )
        distances = {
            hostile_id: self._distance(
                state,
                actor.location_id,
                state.characters[hostile_id].location_id,
            )
            for hostile_id in hostiles
        }
        visible_hostiles = [
            hostile_id
            for hostile_id in hostiles
            if distances[hostile_id] == 0
        ]
        incoming = [
            event
            for event in observed_events
            if event.event_type == "attack_resolved"
            and event.target_id == actor_id
            and event.accepted
        ][-3:]
        recent_damage = {
            "total": sum(event.facts.get("damage", 0) for event in incoming),
            "hits": len(incoming),
            "last_turn": incoming[-1].turn if incoming else None,
            "turns_since_last_hit": (
                state.turn - incoming[-1].turn if incoming else None
            ),
        }
        actions = sorted({option["intent"].action for option in options})
        safe_exits = []
        for destination_id in sorted(
            state.locations[actor.location_id].connections
        ):
            destination_hostiles = [
                hostile_id
                for hostile_id in hostiles
                if state.characters[hostile_id].location_id == destination_id
            ]
            if not destination_hostiles:
                safe_exits.append({
                    "destination_id": destination_id,
                    "danger": state.locations[destination_id].danger,
                    "visible_hostiles": [],
                })
        health_ratio = (
            actor.health / actor.max_health if actor.max_health else 0.0
        )
        stamina_ratio = (
            actor.stamina / actor.max_stamina if actor.max_stamina else 0.0
        )
        risk_score = self._terminal_risk(
            actor,
            visible_hostiles,
            distances,
            recent_damage,
            safe_exits,
        )
        return {
            "visible_hostiles": visible_hostiles,
            "hostile_proximity": [
                {
                    "actor_id": hostile_id,
                    "graph_distance": distances[hostile_id],
                    "location_id": state.characters[hostile_id].location_id,
                }
                for hostile_id in hostiles
            ],
            "recent_damage": recent_damage,
            "health_stamina_risk": {
                "health": actor.health,
                "max_health": actor.max_health,
                "health_ratio": round(health_ratio, 3),
                "health_band": self._band(health_ratio),
                "stamina": actor.stamina,
                "max_stamina": actor.max_stamina,
                "stamina_ratio": round(stamina_ratio, 3),
                "stamina_band": self._band(stamina_ratio),
                "can_pay_attack_cost": actor.stamina >= 10,
            },
            "safe_exits": safe_exits,
            "available_actions": {
                "defensive": [
                    action for action in actions
                    if action in self.DEFENSIVE_ACTIONS
                ],
                "combat": [
                    action for action in actions
                    if action in self.COMBAT_ACTIONS
                ],
                "progression": [
                    action for action in actions
                    if action in self.PROGRESSION_ACTIONS
                ],
            },
            "goal_conflict_flags": {
                "hostile_present_while_progression_available": bool(
                    visible_hostiles
                    and self.PROGRESSION_ACTIONS.intersection(actions)
                ),
                "hostile_present_without_combat_action": bool(
                    visible_hostiles
                    and not self.COMBAT_ACTIONS.intersection(actions)
                ),
                "low_stamina_while_hostile_present": bool(
                    visible_hostiles and actor.stamina < 10
                ),
                "critical_health_while_hostile_present": bool(
                    visible_hostiles and health_ratio <= 0.25
                ),
                "no_safe_exit_while_hostile_present": bool(
                    visible_hostiles and not safe_exits
                ),
            },
            "terminal_risk_score": risk_score,
            "regional_context": {
                "faction_id": actor.faction_id,
                "reputation": actor.reputation,
                "coins": actor.coins,
                "needs": actor.needs,
                "cultivation": {
                    "stage": actor.cultivation_stage,
                    "progress": actor.cultivation_progress,
                    "realm": actor.realm,
                },
                "current_schedule": actor.schedule,
                "local_resources": [
                    {
                        "resource_node_id": node.id,
                        "kind": node.resource_kind,
                        "quantity": node.quantity,
                    }
                    for node in sorted(
                        state.resource_nodes.values(),
                        key=lambda resource: resource.id,
                    )
                    if node.location_id == actor.location_id
                ],
                "local_world_pressures": [
                    {
                        "pressure_id": pressure_id,
                        "severity": pressure["severity"],
                    }
                    for pressure_id, pressure in sorted(
                        state.flags.get("world_pressures", {}).items()
                    )
                    if actor.location_id in pressure.get(
                        "affected_locations", []
                    )
                ],
            },
        }

    @staticmethod
    def _band(ratio):
        if ratio <= 0.25:
            return "critical"
        if ratio <= 0.5:
            return "high"
        if ratio <= 0.75:
            return "moderate"
        return "low"

    @staticmethod
    def _distance(state, origin_id, destination_id):
        if origin_id == destination_id:
            return 0
        queue = deque([(origin_id, 0)])
        visited = {origin_id}
        while queue:
            location_id, distance = queue.popleft()
            for connected_id in state.locations[location_id].connections:
                if connected_id == destination_id:
                    return distance + 1
                if connected_id not in visited:
                    visited.add(connected_id)
                    queue.append((connected_id, distance + 1))
        return None

    @staticmethod
    def _terminal_risk(
        actor,
        visible_hostiles,
        distances,
        recent_damage,
        safe_exits,
    ):
        if not actor.alive or not actor.active:
            return 1.0
        score = 0.0
        health_ratio = actor.health / actor.max_health
        stamina_ratio = actor.stamina / actor.max_stamina
        score += (1.0 - health_ratio) * 0.45
        score += (1.0 - stamina_ratio) * 0.15
        if visible_hostiles:
            score += 0.2
        elif any(distance == 1 for distance in distances.values()):
            score += 0.08
        if recent_damage["hits"]:
            score += min(0.15, recent_damage["total"] / actor.max_health * 0.3)
        if visible_hostiles and not safe_exits:
            score += 0.05
        return round(min(1.0, score), 3)


class GroundedLLMAgent:
    def __init__(
        self,
        llm,
        *,
        goals=None,
        affordances=None,
        memory_limit=6,
        situational_awareness=False,
        awareness_builder=None,
    ):
        self.llm = llm
        self.goals = dict(goals or {})
        self.affordances = affordances or AffordanceBuilder()
        self.memory_limit = memory_limit
        self.situational_awareness = situational_awareness
        self.awareness_builder = (
            awareness_builder or SituationalAwarenessBuilder()
        )
        self.observed_events: list[WorldEvent] = []
        self.minds: dict[str, AgentMind] = {}
        self.metrics = ProposalMetrics()
        self.repeated_failure_blocks = 0
        self.goal_revisions = 0

    def propose(self, actor_id, state: WorldState):
        mind = self._mind(actor_id, state)
        options = self.affordances.build(actor_id, state)
        options = self._suppress_recent_failure(options, mind)
        options = self._suppress_stagnation(options, mind)
        options = self._rank_and_relabel(options, state.characters[actor_id])
        self.metrics.calls += 1
        try:
            proposal = _parse_json_object(
                self.llm(self.build_prompt(actor_id, state, mind, options))
            )
            choice_id = str(proposal.get("choice_id") or "")
            selected = next(
                option for option in options
                if option["choice_id"] == choice_id
            )
            self.metrics.valid += 1
            intent = selected["intent"]
            parameters = dict(intent.parameters)
            parameters["proposal_source"] = "grounded_llm_agent"
            parameters["goal"] = mind.goal
            parameters["choice_id"] = choice_id
            return ActionIntent(
                action=intent.action,
                actor_id=intent.actor_id,
                target_id=intent.target_id,
                destination_id=intent.destination_id,
                distance=intent.distance,
                confidence=float(proposal.get("confidence", 0.5)),
                parameters=parameters,
            )
        except (StopIteration, TypeError, ValueError, json.JSONDecodeError):
            self.metrics.invalid += 1
            self.metrics.fallbacks += 1
            fallback = self._fallback(options, state.characters[actor_id])
            parameters = dict(fallback.parameters)
            parameters["invalid_model_proposal"] = True
            parameters["goal"] = mind.goal
            return ActionIntent(
                fallback.action,
                actor_id,
                target_id=fallback.target_id,
                destination_id=fallback.destination_id,
                distance=fallback.distance,
                confidence=0.0,
                parameters=parameters,
            )

    def reflect(self, event: WorldEvent, state: WorldState):
        self.observe_world_event(event)
        mind = self._mind(event.actor_id, state)
        mind.recent_outcomes.append({
            "turn": event.turn,
            "action": event.intent.get("action"),
            "target_id": event.target_id,
            "destination_id": event.intent.get("destination_id"),
            "accepted": event.accepted,
            "reason": event.reason,
            "event_type": event.event_type,
        })
        mind.recent_outcomes = mind.recent_outcomes[-self.memory_limit:]
        if not event.accepted and event.reason:
            mind.revised_goals += 1
            self.goal_revisions += 1

    def observe_world_event(self, event: WorldEvent):
        if not self.observed_events or self.observed_events[-1].id != event.id:
            self.observed_events.append(event)
            self.observed_events = self.observed_events[-24:]

    def build_prompt(self, actor_id, state, mind, options):
        actor = state.characters[actor_id]
        packet = {
            "actor_id": actor_id,
            "goal": mind.goal,
            "local_state": {
                "location_id": actor.location_id,
                "health": actor.health,
                "stamina": actor.stamina,
                "inventory": actor.inventory,
                "equipment": actor.equipment,
                "skills": actor.skill_mastery,
                "jobs": actor.jobs,
                "faction_id": actor.faction_id,
                "reputation": actor.reputation,
                "coins": actor.coins,
                "needs": actor.needs,
                "cultivation_stage": actor.cultivation_stage,
                "cultivation_progress": actor.cultivation_progress,
            },
            "recent_outcomes": mind.recent_outcomes,
            "available_choices": [
                {
                    "choice_id": option["choice_id"],
                    "description": option["description"],
                }
                for option in options
            ],
        }
        if self.situational_awareness:
            packet["situational_awareness"] = self.awareness_builder.build(
                actor_id,
                state,
                options,
                self.observed_events,
            )
        return (
            "You are choosing one action for an agent inside a simulated world.\n"
            "Use the current local state, goal, recent outcomes, and any "
            "situational_awareness evidence provided.\n"
            "Situational awareness is evidence, not an instruction; weigh it "
            "against the goal and choose freely from available_choices.\n"
            "Choose only a choice_id from available_choices.\n"
            "Prefer a choice that advances the goal. Do not choose observation or "
            "waiting when a safe work, training, equipment, movement, or present-threat "
            "action advances the goal.\n"
            "A rejected outcome is evidence: do not repeat the same failed action "
            "unless the relevant location, target, inventory, or stamina changed.\n"
            "Return exactly one JSON object and no other text:\n"
            '{"choice_id":"a1","confidence":1.0}\n\n'
            + json.dumps(packet, sort_keys=True)
        )

    def metrics_dict(self):
        data = self.metrics.to_dict()
        data.update({
            "repeated_failure_blocks": self.repeated_failure_blocks,
            "goal_revisions": self.goal_revisions,
        })
        return data

    def _mind(self, actor_id, state):
        if actor_id not in self.minds:
            actor = state.characters[actor_id]
            default_goal = (
                "Protect your location and respond only to present threats."
                if "hostile" in actor.tags
                else "Stay alive, develop useful skills, work, equip useful items, and explore."
            )
            self.minds[actor_id] = AgentMind(
                actor_id=actor_id,
                goal=self.goals.get(actor_id, default_goal),
            )
        return self.minds[actor_id]

    def _suppress_recent_failure(self, options, mind):
        if not mind.recent_outcomes:
            return options
        last = mind.recent_outcomes[-1]
        if last["accepted"]:
            return options
        filtered = [
            option for option in options
            if not (
                option["intent"].action == last["action"]
                and option["intent"].target_id == last["target_id"]
                and option["intent"].destination_id == last["destination_id"]
            )
        ]
        if filtered:
            self.repeated_failure_blocks += len(options) - len(filtered)
            return filtered
        return options

    def _suppress_stagnation(self, options, mind):
        if len(mind.recent_outcomes) < 2:
            return options
        recent = mind.recent_outcomes[-2:]
        first, second = recent
        progress_events = {
            "attack_resolved",
            "cultivation_advanced",
            "item_equipped",
            "item_crafted",
            "item_picked_up",
            "item_dropped",
            "item_traded",
            "job_worked",
            "resource_gathered",
            "skill_trained",
        }
        same_choice = (
            first["accepted"]
            and second["accepted"]
            and first["action"] == second["action"]
            and first["target_id"] == second["target_id"]
            and (
                first["destination_id"] == second["destination_id"]
                or second["action"] == "move"
            )
        )
        if not same_choice or second["event_type"] in progress_events:
            return options
        filtered = [
            option for option in options
            if not (
                option["intent"].action == second["action"]
                and option["intent"].target_id == second["target_id"]
                and (
                    option["intent"].destination_id == second["destination_id"]
                    or second["action"] == "move"
                )
            )
        ]
        if filtered:
            self.repeated_failure_blocks += len(options) - len(filtered)
            return filtered
        return options

    @staticmethod
    def _fallback(options, actor):
        preferred = ["rest"] if actor.stamina < actor.max_stamina // 3 else []
        preferred.extend([
            "craft",
            "gather",
            "work",
            "cultivate",
            "train",
            "trade",
            "equip",
            "follow_schedule",
            "observe",
            "move",
            "wait",
        ])
        for action in preferred:
            match = next(
                (option["intent"] for option in options if option["intent"].action == action),
                None,
            )
            if match:
                return match
        return options[0]["intent"]

    @staticmethod
    def _rank_and_relabel(options, actor):
        if "hostile" in actor.tags:
            priority = {
                "attack": 0,
                "move": 1,
                "observe": 2,
                "rest": 3,
                "wait": 4,
                "talk": 5,
            }
        else:
            priority = {
                "equip": 0,
                "craft": 1,
                "gather": 2,
                "work": 3,
                "cultivate": 4,
                "train": 5,
                "trade": 6,
                "move": 7,
                "follow_schedule": 8,
                "pickup": 9,
                "talk": 10,
                "observe": 11,
                "rest": 12,
                "wait": 13,
                "drop": 14,
                "attack": 15,
            }
            if any(option["intent"].action == "attack" for option in options):
                priority["attack"] = -2
            if actor.stamina < 12:
                priority["rest"] = -1
        ranked = sorted(
            options,
            key=lambda option: (
                priority.get(option["intent"].action, 50),
                option["description"],
            ),
        )
        for index, option in enumerate(ranked, start=1):
            option["choice_id"] = f"a{index}"
        return ranked
