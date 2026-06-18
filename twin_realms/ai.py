from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .models import ActionIntent, WorldEvent, WorldState


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
ALLOWED_ACTIONS = {
    "attack",
    "craft",
    "cultivate",
    "drop",
    "equip",
    "follow_schedule",
    "gather",
    "move",
    "observe",
    "pickup",
    "rest",
    "space_fold",
    "steal",
    "talk",
    "trade",
    "train",
    "unequip",
    "unknown",
    "wait",
    "work",
}


def _parse_json_object(text):
    if isinstance(text, dict):
        return dict(text)
    match = _JSON_OBJECT_RE.search(str(text))
    if not match:
        raise ValueError("model response did not contain a JSON object")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("model response must be a JSON object")
    return value


@dataclass
class ProposalMetrics:
    calls: int = 0
    valid: int = 0
    invalid: int = 0
    fallbacks: int = 0

    @property
    def validity_rate(self):
        return self.valid / self.calls if self.calls else 0.0

    def to_dict(self):
        return {
            "calls": self.calls,
            "valid": self.valid,
            "invalid": self.invalid,
            "fallbacks": self.fallbacks,
            "validity_rate": self.validity_rate,
        }


class ActionProposalValidator:
    def validate(self, proposal, state: WorldState, *, actor_id, raw_text=""):
        action = str(proposal.get("action") or "unknown").strip().lower()
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"unsupported action: {action}")
        if actor_id not in state.characters or not state.characters[actor_id].alive:
            raise ValueError("actor must exist and be alive")
        if not state.characters[actor_id].active:
            raise ValueError("actor must be active")

        target_id = proposal.get("target_id")
        destination_id = proposal.get("destination_id")
        distance = proposal.get("distance")
        parameters = proposal.get("parameters") or {}
        confidence = float(proposal.get("confidence", 0.5))
        if target_id is not None and target_id not in state.characters:
            raise ValueError("target_id is not a known character")
        if destination_id is not None and destination_id not in state.locations:
            raise ValueError("destination_id is not a known location")
        if distance is not None:
            distance = int(distance)
            if distance < 0 or distance > 1000:
                raise ValueError("distance is outside proposal bounds")
        if not isinstance(parameters, dict):
            raise ValueError("parameters must be an object")
        item_id = parameters.get("item_id")
        if item_id is not None and item_id not in state.flags.get("item_ids", []):
            raise ValueError("item_id is not a known item")
        skill_id = parameters.get("skill_id")
        if skill_id is not None and skill_id not in state.flags.get("skills", []):
            raise ValueError("skill_id is not a known skill")
        job_id = parameters.get("job_id")
        if job_id is not None and job_id not in state.flags.get("jobs", []):
            raise ValueError("job_id is not a known job")
        recipe_id = parameters.get("recipe_id")
        if (
            recipe_id is not None
            and recipe_id not in state.flags.get("recipes", {})
        ):
            raise ValueError("recipe_id is not a known recipe")
        resource_node_id = parameters.get("resource_node_id")
        if (
            resource_node_id is not None
            and resource_node_id not in state.resource_nodes
        ):
            raise ValueError("resource_node_id is not a known resource")
        return ActionIntent(
            action=action,
            actor_id=actor_id,
            target_id=target_id,
            destination_id=destination_id,
            distance=distance,
            raw_text=raw_text,
            confidence=max(0.0, min(1.0, confidence)),
            parameters=parameters,
        )


class LLMIntentInterpreter:
    def __init__(self, llm, fallback=None, validator=None):
        self.llm = llm
        self.fallback = fallback
        self.validator = validator or ActionProposalValidator()
        self.metrics = ProposalMetrics()

    @classmethod
    def using_hive(cls, fallback=None, role="default"):
        from hive_llm import ask_hive

        return cls(
            lambda prompt: ask_hive(prompt, role=role),
            fallback=fallback,
        )

    def interpret(self, text, state: WorldState, actor_id=None):
        actor_id = actor_id or state.player_id
        if self.fallback and any(
            marker in " ".join(text.lower().split())
            for marker in getattr(self.fallback, "_CONTROL_LANGUAGE", ())
        ):
            return self.fallback.interpret(text, state, actor_id=actor_id)
        self.metrics.calls += 1
        try:
            proposal = _parse_json_object(self.llm(self.build_prompt(text, state, actor_id)))
            if not isinstance(proposal.get("parameters"), dict):
                proposal["parameters"] = {}
            proposal["parameters"].setdefault("proposal_source", "llm_intent")
            intent = self.validator.validate(
                proposal,
                state,
                actor_id=actor_id,
                raw_text=text,
            )
            self.metrics.valid += 1
            return intent
        except (TypeError, ValueError, json.JSONDecodeError):
            self.metrics.invalid += 1
            self.metrics.fallbacks += 1
            if self.fallback:
                return self.fallback.interpret(text, state, actor_id=actor_id)
            return ActionIntent(
                "unknown",
                actor_id,
                raw_text=text,
                confidence=0.0,
                parameters={"invalid_model_proposal": True},
            )

    def build_prompt(self, text, state, actor_id):
        actor = state.characters[actor_id]
        packet = {
            "player_input": text,
            "actor_id": actor_id,
            "actor_location": actor.location_id,
            "characters": sorted(
                character.id
                for character in state.characters.values()
                if character.active
            ),
            "locations": sorted(state.locations),
            "items": sorted(state.flags.get("item_ids", [])),
            "skills": sorted(state.flags.get("skills", [])),
            "jobs": sorted(state.flags.get("jobs", [])),
            "recipes": sorted(state.flags.get("recipes", {})),
            "resource_nodes": sorted(state.resource_nodes),
            "allowed_actions": sorted(ALLOWED_ACTIONS),
        }
        return (
            "Interpret the player input as exactly one proposed game action.\n"
            "Return exactly one JSON object and no other text.\n\n"
            "Return exactly this JSON shape:\n"
            '{"action":"ACTION","target_id":null,'
            '"destination_id":null,"distance":null,"confidence":1.0,'
            '"parameters":{}}\n\n'
            "Hard field rules:\n"
            "- Use null for an unused nullable field. Never use an empty string.\n"
            "- parameters must always be a JSON object. Never use null, a string, or a list.\n"
            "- action must be one value from allowed_actions.\n"
            "- target_id is only for a character target and must use a listed character ID.\n"
            "- destination_id is only for move destinations and must use a listed location ID.\n"
            "- distance is only for space_fold and must be a number or null.\n"
            "- For pickup, drop, or steal, put the item ID in parameters.item_id.\n"
            "- For steal, target_id is the character being stolen from.\n"
            "- Do not copy or repeat the input packet.\n"
            "- Do not resolve the action and do not alter world state.\n\n"
            "Action selection examples:\n"
            '- "Observe the malformed." -> '
            '{"action":"observe","target_id":"char:malformed",'
            '"destination_id":null,"distance":null,"confidence":1.0,'
            '"parameters":{}}\n'
            '- "Rest and recover." -> '
            '{"action":"rest","target_id":null,"destination_id":null,'
            '"distance":null,"confidence":1.0,"parameters":{}}\n'
            '- "Attack the malformed." -> '
            '{"action":"attack","target_id":"char:malformed",'
            '"destination_id":null,"distance":null,"confidence":1.0,'
            '"parameters":{}}\n'
            '- "Fold space 5m behind the malformed." -> '
            '{"action":"space_fold","target_id":"char:malformed",'
            '"destination_id":null,"distance":5,"confidence":1.0,'
            '"parameters":{}}\n'
            '- "Drop the iron sword." -> '
            '{"action":"drop","target_id":null,"destination_id":null,'
            '"distance":null,"confidence":1.0,'
            '"parameters":{"item_id":"item:iron_sword"}}\n'
            '- "Pick up the iron sword." -> '
            '{"action":"pickup","target_id":null,"destination_id":null,'
            '"distance":null,"confidence":1.0,'
            '"parameters":{"item_id":"item:iron_sword"}}\n\n'
            "Input packet:\n"
            + json.dumps(packet, sort_keys=True)
        )


class LLMNPCPlanner:
    def __init__(self, llm, validator=None):
        self.llm = llm
        self.validator = validator or ActionProposalValidator()
        self.metrics = ProposalMetrics()

    @classmethod
    def using_hive(cls, role="default"):
        from hive_llm import ask_hive

        return cls(lambda prompt: ask_hive(prompt, role=role))

    def propose(self, actor_id, state: WorldState):
        self.metrics.calls += 1
        try:
            proposal = _parse_json_object(self.llm(self.build_prompt(actor_id, state)))
            if not isinstance(proposal.get("parameters"), dict):
                proposal["parameters"] = {}
            proposal["parameters"].setdefault("proposal_source", "llm_npc")
            intent = self.validator.validate(proposal, state, actor_id=actor_id)
            self.metrics.valid += 1
            return intent
        except (TypeError, ValueError, json.JSONDecodeError):
            self.metrics.invalid += 1
            self.metrics.fallbacks += 1
            return ActionIntent(
                "wait",
                actor_id,
                confidence=0.0,
                parameters={"invalid_model_proposal": True},
            )

    def build_prompt(self, actor_id, state):
        actor = state.characters[actor_id]
        present = sorted(
            character.id
            for character in state.characters.values()
            if character.alive
            and character.active
            and character.location_id == actor.location_id
        )
        packet = {
            "actor_id": actor_id,
            "location_id": actor.location_id,
            "health": actor.health,
            "stamina": actor.stamina,
            "tags": actor.tags,
            "present_characters": present,
            "connections": state.locations[actor.location_id].connections,
            "allowed_actions": sorted(ALLOWED_ACTIONS),
        }
        return (
            "Choose exactly one NPC action from allowed_actions.\n"
            "Return exactly one action proposal JSON object and no other text.\n"
            "Do not repeat or copy the world state.\n"
            "The simulator decides whether the proposal succeeds.\n\n"
            "Return exactly this JSON shape:\n"
            '{"action":"attack","target_id":"char:player",'
            '"destination_id":null,"distance":null,"confidence":1.0,'
            '"parameters":{}}\n\n'
            "Hard field rules:\n"
            "- Use null for every unused nullable field. Never use an empty string.\n"
            "- parameters must always be a JSON object.\n"
            "- target_id is only for a listed character target.\n"
            "- destination_id is only for move and must be a listed connection.\n"
            "- distance is only for space_fold.\n"
            "- For pickup, drop, or steal, put item_id inside parameters.\n"
            "- Never include actor_id, health, stamina, tags, connections, or allowed_actions in the response.\n\n"
            "Valid attack example:\n"
            '{"action":"attack","target_id":"char:player",'
            '"destination_id":null,"distance":null,"confidence":1.0,'
            '"parameters":{}}\n'
            "Valid move example:\n"
            '{"action":"move","target_id":null,'
            '"destination_id":"loc:forest_edge","distance":null,'
            '"confidence":1.0,"parameters":{}}\n\n'
            "World state:\n"
            + json.dumps(packet, sort_keys=True)
        )


HYPOTHESIS_REGISTRY = {
    "space_fold_meridian_stress": (
        "Space folding while injured increases realm instability."
    ),
    "space_fold_extended_range": (
        "A stable space fold can reach twelve meters."
    ),
    "space_fold_overreach_strain": (
        "Space folding beyond ten meters causes meridian strain."
    ),
}


class LLMKnowledgeAgent:
    def __init__(self, llm):
        self.llm = llm
        self.metrics = ProposalMetrics()

    @classmethod
    def using_hive(cls, role="default"):
        from hive_llm import ask_hive

        return cls(lambda prompt: ask_hive(prompt, role=role))

    def propose(self, event: WorldEvent):
        self.metrics.calls += 1
        try:
            proposal = _parse_json_object(self.llm(self.build_prompt(event)))
            key = str(proposal.get("key") or "")
            if key not in HYPOTHESIS_REGISTRY:
                raise ValueError("hypothesis is not registered")
            self.metrics.valid += 1
            return {
                "key": key,
                "statement": HYPOTHESIS_REGISTRY[key],
                "confidence": max(
                    0.0,
                    min(1.0, float(proposal.get("confidence", 0.5))),
                ),
            }
        except (TypeError, ValueError, json.JSONDecodeError):
            self.metrics.invalid += 1
            return None

    def build_prompt(self, event):
        return (
            "Propose at most one registered world-knowledge hypothesis supported by "
            "this resolved event. Return JSON with key and confidence. Registered "
            f"keys: {sorted(HYPOTHESIS_REGISTRY)}. Event: "
            + json.dumps(event.to_dict(), sort_keys=True)
        )


def evaluate_hypothesis(key, event: WorldEvent):
    if key == "space_fold_meridian_stress":
        if event.event_type != "space_folded":
            return None
        return bool(event.facts.get("meridian_strain"))
    if key == "space_fold_extended_range":
        if event.intent.get("action") != "space_fold":
            return None
        distance = event.intent.get("distance") or 0
        if distance != 12:
            return None
        return bool(event.accepted)
    if key == "space_fold_overreach_strain":
        if event.intent.get("action") != "space_fold":
            return None
        distance = event.intent.get("distance") or 0
        if distance <= 10:
            return None
        return (
            event.reason == "distance exceeds stable range"
            or bool(event.facts.get("overreach_strain"))
        )
    return None
