from __future__ import annotations

import re

from .models import ActionIntent, WorldState


class IntentInterpreter:
    """Converts player language into a constrained action proposal."""

    _DISTANCE_RE = re.compile(r"(\d+)\s*(?:m|meter|meters)\b", re.IGNORECASE)
    _CONTROL_LANGUAGE = (
        "ignore previous rules",
        "system override",
        "rewrite the event log",
        "do not validate",
        "bypass validation",
        "override the simulator",
    )

    def interpret(self, text, state: WorldState, actor_id=None):
        actor_id = actor_id or state.player_id
        lowered = " ".join(text.lower().split())
        target_id = self._match_character(lowered, state, exclude=actor_id)
        destination_id = self._match_location(lowered, state)
        distance_match = self._DISTANCE_RE.search(lowered)
        distance = int(distance_match.group(1)) if distance_match else None
        item_id = self._match_item(lowered, state)
        skill_id = self._match_registry(lowered, state.flags.get("skills", []))
        job_id = self._match_registry(lowered, state.flags.get("jobs", []))
        recipe_id = self._match_registry(
            lowered,
            state.flags.get("recipes", {}).keys(),
        )
        resource_node_id = self._match_resource(lowered, state)

        if any(marker in lowered for marker in self._CONTROL_LANGUAGE):
            return ActionIntent(
                "unknown",
                actor_id,
                raw_text=text,
                confidence=0.0,
                parameters={"rejected_control_language": True},
            )

        if any(term in lowered for term in ("drop", "discard", "leave")):
            return ActionIntent(
                "drop",
                actor_id,
                raw_text=text,
                parameters={"item_id": item_id},
            )
        if any(term in lowered for term in ("unequip", "remove armor", "sheathe")):
            slot = "main_hand" if any(term in lowered for term in ("sword", "bow", "weapon")) else "body"
            return ActionIntent(
                "unequip",
                actor_id,
                raw_text=text,
                parameters={"slot": slot},
            )
        if any(term in lowered for term in ("equip", "wear", "wield")):
            return ActionIntent(
                "equip",
                actor_id,
                raw_text=text,
                parameters={"item_id": item_id},
            )
        if any(term in lowered for term in ("train", "practice")):
            return ActionIntent(
                "train",
                actor_id,
                raw_text=text,
                parameters={"skill_id": skill_id},
            )
        if any(term in lowered for term in ("work", "job", "labor")):
            return ActionIntent(
                "work",
                actor_id,
                raw_text=text,
                parameters={"job_id": job_id},
            )
        if any(term in lowered for term in ("gather", "harvest", "mine", "fish")):
            return ActionIntent(
                "gather",
                actor_id,
                raw_text=text,
                parameters={"resource_node_id": resource_node_id},
            )
        if any(term in lowered for term in ("craft", "forge", "brew", "build")):
            return ActionIntent(
                "craft",
                actor_id,
                raw_text=text,
                parameters={"recipe_id": recipe_id},
            )
        if any(term in lowered for term in ("buy", "purchase", "trade")):
            return ActionIntent(
                "trade",
                actor_id,
                target_id=target_id,
                raw_text=text,
                parameters={"item_id": item_id},
            )
        if any(term in lowered for term in ("follow schedule", "go to work", "go home")):
            return ActionIntent("follow_schedule", actor_id, raw_text=text)
        if any(term in lowered for term in ("steal", "pickpocket")):
            return ActionIntent(
                "steal",
                actor_id,
                target_id=target_id,
                raw_text=text,
                parameters={"item_id": item_id},
            )
        if any(term in lowered for term in ("pick up", "pickup", "take")) and item_id:
            return ActionIntent(
                "pickup",
                actor_id,
                raw_text=text,
                parameters={"item_id": item_id},
            )
        if any(term in lowered for term in ("fold space", "space fold", "blink", "teleport")):
            return ActionIntent(
                "space_fold",
                actor_id,
                target_id=target_id,
                destination_id=destination_id,
                distance=distance or 5,
                raw_text=text,
            )
        if "heavy attack" in lowered or any(term in lowered for term in ("power attack", "strong attack")):
            return ActionIntent("heavy_attack", actor_id, target_id=target_id, raw_text=text)
        if any(term in lowered for term in ("block", "guard", "defend")):
            return ActionIntent("block", actor_id, raw_text=text)
        if any(term in lowered for term in ("dodge", "evade", "sidestep")):
            return ActionIntent("dodge", actor_id, raw_text=text)
        if any(term in lowered for term in ("attack", "strike", "slash", "stab", "fight")):
            return ActionIntent("attack", actor_id, target_id=target_id, raw_text=text)
        if any(term in lowered for term in ("cultivate", "cycle qi", "advance realm")):
            return ActionIntent("cultivate", actor_id, raw_text=text)
        if any(term in lowered for term in ("rest", "recover", "meditate")):
            return ActionIntent("rest", actor_id, raw_text=text)
        if any(term in lowered for term in ("inspect", "observe", "look", "examine", "study")):
            return ActionIntent("observe", actor_id, target_id=target_id, raw_text=text)
        if any(term in lowered for term in ("talk", "ask", "speak", "greet")):
            return ActionIntent("talk", actor_id, target_id=target_id, raw_text=text)
        if destination_id:
            return ActionIntent(
                "move",
                actor_id,
                destination_id=destination_id,
                raw_text=text,
            )
        return ActionIntent(
            "unknown",
            actor_id,
            raw_text=text,
            confidence=0.0,
        )

    def _match_character(self, text, state, exclude=None):
        candidates = []
        for entity_id, character in state.characters.items():
            if entity_id == exclude or not character.active:
                continue
            name_parts = character.name.lower().split()
            names = {character.name.lower(), name_parts[-1]}
            names.update(part for part in name_parts if len(part) > 2)
            names.update(tag.replace("_", " ") for tag in character.tags)
            score = max((len(name) for name in names if name in text), default=0)
            if score:
                candidates.append((score, entity_id))
        return max(candidates, default=(0, None))[1]

    @staticmethod
    def _match_registry(text, values):
        candidates = [
            (len(value.replace("_", " ")), value)
            for value in values
            if value.replace("_", " ") in text
        ]
        return max(candidates, default=(0, None))[1]

    def _match_location(self, text, state):
        candidates = []
        for entity_id, location in state.locations.items():
            names = {location.name.lower(), location.name.lower().replace(" ", "_")}
            score = max((len(name) for name in names if name in text), default=0)
            if score:
                candidates.append((score, entity_id))
        return max(candidates, default=(0, None))[1]

    def _match_item(self, text, state):
        candidates = []
        for item_id in state.flags.get("item_ids", []):
            name = item_id.split(":", 1)[-1].replace("_", " ")
            aliases = {name, name.split()[-1]}
            score = max((len(alias) for alias in aliases if alias in text), default=0)
            if score:
                candidates.append((score, item_id))
        return max(candidates, default=(0, None))[1]

    @staticmethod
    def _match_resource(text, state):
        candidates = []
        for node_id, node in state.resource_nodes.items():
            aliases = {
                node_id.split(":", 1)[-1].replace("_", " "),
                node.resource_kind.replace("_", " "),
            }
            score = max((len(alias) for alias in aliases if alias in text), default=0)
            if score:
                candidates.append((score, node_id))
        return max(candidates, default=(0, None))[1]
