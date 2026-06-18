from __future__ import annotations

from copy import deepcopy

from .models import ActionIntent


class FrontendBoundary:
    """DTO boundary for 3D clients; simulation remains authoritative."""

    def __init__(self, runtime):
        self.runtime = runtime

    @property
    def engine(self):
        return self.runtime.engine

    def export_world_state(self):
        state = self.engine.state
        return {
            "schema": "twin_realms.frontend.v1",
            "turn": state.turn,
            "state_digest": self.engine.simulator.state_digest(state),
            "player_id": state.player_id,
            "locations": {
                location_id: {
                    "id": location.id,
                    "name": location.name,
                    "connections": list(location.connections),
                    "danger": location.danger,
                    "settlement_id": location.settlement_id,
                    "tags": list(location.tags),
                    "position": self._location_position(location_id),
                }
                for location_id, location in sorted(state.locations.items())
            },
            "entities": {
                actor_id: self._entity_export(actor_id)
                for actor_id in sorted(state.characters)
            },
            "resources": {
                node_id: {
                    "id": node.id,
                    "location_id": node.location_id,
                    "kind": node.resource_kind,
                    "quantity": node.quantity,
                    "capacity": node.capacity,
                    "position": self._offset_position(
                        self._location_position(node.location_id),
                        node_id,
                    ),
                }
                for node_id, node in sorted(state.resource_nodes.items())
            },
            "settlements": deepcopy(state.flags.get("settlements") or {}),
            "pressures": deepcopy(state.flags.get("world_pressures") or {}),
            "available_player_commands": self.player_commands(),
        }

    def player_commands(self):
        state = self.engine.state
        actor = state.characters[state.player_id]
        commands = [
            {
                "command": "wait",
                "label": "Wait",
                "intent": ActionIntent("wait", actor.id).to_dict(),
            },
            {
                "command": "rest",
                "label": "Rest",
                "intent": ActionIntent("rest", actor.id).to_dict(),
            },
            {
                "command": "observe",
                "label": "Observe",
                "intent": ActionIntent("observe", actor.id).to_dict(),
            },
        ]
        for destination_id in sorted(state.locations[actor.location_id].connections):
            commands.append({
                "command": "move",
                "label": f"Move to {state.locations[destination_id].name}",
                "intent": ActionIntent(
                    "move",
                    actor.id,
                    destination_id=destination_id,
                ).to_dict(),
            })
        for target in sorted(state.characters.values(), key=lambda item: item.id):
            if (
                target.id == actor.id
                or not target.active
                or not target.alive
                or target.location_id != actor.location_id
            ):
                continue
            commands.append({
                "command": "observe_character",
                "label": f"Observe {target.name}",
                "intent": ActionIntent(
                    "observe",
                    actor.id,
                    target_id=target.id,
                ).to_dict(),
            })
            if "hostile" in target.tags or "hostile" in actor.tags:
                commands.extend([
                    {
                        "command": "attack",
                        "label": f"Attack {target.name}",
                        "intent": ActionIntent(
                            "attack",
                            actor.id,
                            target_id=target.id,
                        ).to_dict(),
                    },
                    {
                        "command": "heavy_attack",
                        "label": f"Heavy attack {target.name}",
                        "intent": ActionIntent(
                            "heavy_attack",
                            actor.id,
                            target_id=target.id,
                        ).to_dict(),
                    },
                    {
                        "command": "block",
                        "label": "Block",
                        "intent": ActionIntent("block", actor.id).to_dict(),
                    },
                    {
                        "command": "dodge",
                        "label": "Dodge",
                        "intent": ActionIntent("dodge", actor.id).to_dict(),
                    },
                ])
        for node in sorted(state.resource_nodes.values(), key=lambda item: item.id):
            if node.location_id != actor.location_id or node.quantity <= 0:
                continue
            commands.append({
                "command": "gather",
                "label": f"Gather {node.resource_kind}",
                "intent": ActionIntent(
                    "gather",
                    actor.id,
                    parameters={"resource_node_id": node.id},
                ).to_dict(),
            })
        return commands

    def submit_player_intention(self, command):
        intent = self._intent_from_command(command)
        if intent.actor_id != self.engine.state.player_id:
            raise ValueError("frontend can only submit player intentions")
        before_digest = self.engine.simulator.state_digest(self.engine.state)
        result = self.runtime.intent_turn(intent)
        return self._turn_export(result, before_digest)

    def _intent_from_command(self, command):
        if isinstance(command, ActionIntent):
            return command
        if isinstance(command, str):
            return self.engine.interpreter.interpret(command, self.engine.state)
        if not isinstance(command, dict):
            raise TypeError("command must be text, dict, or ActionIntent")
        if "intent" in command:
            return ActionIntent.from_dict(command["intent"])
        return ActionIntent(
            command.get("action") or command.get("command"),
            self.engine.state.player_id,
            target_id=command.get("target_id"),
            destination_id=command.get("destination_id"),
            distance=command.get("distance"),
            raw_text=command.get("raw_text", ""),
            parameters=dict(command.get("parameters") or {}),
        )

    def _turn_export(self, runtime_turn, before_digest):
        results = [
            ("player", runtime_turn.player_result),
            *[("npc", result) for result in runtime_turn.npc_results],
            *[("world", result) for result in runtime_turn.world_results],
        ]
        return {
            "schema": "twin_realms.frontend.turn.v1",
            "accepted": runtime_turn.player_result.event.accepted,
            "before_state_digest": before_digest,
            "after_state_digest": self.engine.simulator.state_digest(
                self.engine.state,
            ),
            "events": [
                self._event_hook(source, result)
                for source, result in results
            ],
            "world_state": self.export_world_state(),
        }

    def _event_hook(self, source, result):
        event = result.event
        return {
            "source": source,
            "event_id": event.id,
            "turn": event.turn,
            "actor_id": event.actor_id,
            "target_id": event.target_id,
            "event_type": event.event_type,
            "accepted": event.accepted,
            "reason": event.reason,
            "intent": deepcopy(event.intent),
            "animation": self._animation_hook(event),
            "message": self._event_message(result),
            "combat": self._combat_payload(event),
            "facts": deepcopy(event.facts),
        }

    def _entity_export(self, actor_id):
        state = self.engine.state
        actor = state.characters[actor_id]
        return {
            "id": actor.id,
            "name": actor.name,
            "location_id": actor.location_id,
            "position": self._offset_position(
                self._location_position(actor.location_id),
                actor.id,
            ),
            "alive": actor.alive,
            "active": actor.active,
            "health": actor.health,
            "max_health": actor.max_health,
            "stamina": actor.stamina,
            "max_stamina": actor.max_stamina,
            "tags": list(actor.tags),
            "faction_id": actor.faction_id,
            "is_player": actor.id == state.player_id,
        }

    def _location_position(self, location_id):
        state = self.engine.state
        ordered = sorted(state.locations)
        index = ordered.index(location_id)
        width = max(1, int(len(ordered) ** 0.5))
        return {
            "x": float((index % width) * 12),
            "y": 0.0,
            "z": float((index // width) * 12),
        }

    @staticmethod
    def _offset_position(base, entity_id):
        offset = sum(ord(char) for char in entity_id) % 7
        return {
            "x": base["x"] + float(offset - 3),
            "y": base["y"],
            "z": base["z"] + float((offset % 3) - 1),
        }

    @staticmethod
    def _event_message(result):
        facts = result.event.facts or {}
        return facts.get("combat_log") or result.narrative

    @staticmethod
    def _combat_payload(event):
        if event.event_type not in {"attack_resolved", "blocked", "dodged"}:
            return None
        facts = event.facts or {}
        return {
            "action": facts.get("action_name") or event.intent.get("action"),
            "damage": facts.get("damage", 0),
            "missed": facts.get("missed", False),
            "target_alive": facts.get("target_alive"),
            "target_health_after": facts.get("target_health_after"),
            "stamina_spent": facts.get("stamina_spent", 0),
            "log": facts.get("combat_log"),
        }

    @staticmethod
    def _animation_hook(event):
        if not event.accepted:
            return "reject"
        action = event.intent.get("action")
        if event.event_type == "moved":
            return "move"
        if action in {"attack", "heavy_attack", "block", "dodge", "rest"}:
            return action
        if event.event_type == "resource_gathered":
            return "gather"
        if event.event_type == "world_tick_resolved":
            return "world_tick"
        return event.event_type
