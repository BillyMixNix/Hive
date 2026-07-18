from __future__ import annotations

import json
import time

from .models import WorldEvent, WorldState


class NarrativeGuard:
    """Detects direct outcome claims that contradict a resolved event."""

    _SUCCESS_TERMS = (
        "succeeds",
        "successfully",
        "teleports",
        "strikes true",
        "lands the blow",
        "kills",
        "slays",
    )
    _DEATH_TERMS = (
        " kill ",
        " kills ",
        " killed ",
        " slay ",
        " slays ",
        " slain ",
        " is dead",
        " dies",
    )
    _HIT_TERMS = (
        " hit ",
        " hits ",
        " strike ",
        " strikes ",
        " wound ",
        " wounds ",
        " cut ",
        " cuts ",
        " kill ",
        " kills ",
        " slay ",
        " slays ",
    )

    def validate(self, event: WorldEvent, text: str):
        normalized = f" {' '.join(text.lower().split())} "
        violations = []
        if not event.accepted and any(term in normalized for term in self._SUCCESS_TERMS):
            violations.append("rejected_action_described_as_success")
        if event.event_type == "attack_resolved":
            if event.facts.get("missed") and any(term in normalized for term in self._HIT_TERMS):
                violations.append("miss_described_as_hit")
            if event.facts.get("target_alive") and any(
                term in normalized for term in self._DEATH_TERMS
            ):
                violations.append("living_target_described_as_dead")
        if event.event_type == "item_dropped":
            if "still holds" in normalized or "keeps hold" in normalized:
                violations.append("dropped_item_described_as_held")
        return violations


class NarrativeGenerator:
    """Renders resolved facts. It never receives mutable simulation authority."""

    def __init__(self, llm=None, guard=None, transport_cooldown=30):
        self.llm = llm
        self.guard = guard or NarrativeGuard()
        self.last_guard_violations = []
        self.guard_violation_count = 0
        self.llm_failure_count = 0
        self.last_llm_error = None
        self.transport_cooldown = transport_cooldown
        self._retry_after = 0.0

    @classmethod
    def using_hive(cls, role="default"):
        from hive_llm import ask_hive

        return cls(llm=lambda prompt: ask_hive(prompt, role=role))

    def render(self, event: WorldEvent, state: WorldState):
        if self.llm:
            if time.monotonic() < self._retry_after:
                self.last_guard_violations = []
                return self._fallback(event, state)
            try:
                generated = self.llm(self.build_prompt(event, state))
            except Exception as exc:
                self.llm_failure_count += 1
                self.last_llm_error = str(exc)
                self._retry_after = (
                    time.monotonic() + self.transport_cooldown
                )
                self.last_guard_violations = []
                return self._fallback(event, state)
            self.last_guard_violations = self.guard.validate(event, generated)
            if not self.last_guard_violations:
                return generated
            self.guard_violation_count += len(self.last_guard_violations)
            return self._fallback(event, state)
        self.last_guard_violations = []
        return self._fallback(event, state)

    def build_prompt(self, event, state):
        actor = state.characters[event.actor_id]
        target = state.characters.get(event.target_id or "")
        packet = {
            "turn": event.turn,
            "event_id": event.id,
            "accepted": event.accepted,
            "event_type": event.event_type,
            "actor": actor.name,
            "target": target.name if target else None,
            "resolved_facts": event.facts,
            "reason": event.reason,
        }
        return (
            "Write 1-3 sentences of cultivation fantasy prose using only the "
            "resolved facts below. Do not add outcomes, objects, people, injuries, "
            "or state changes. If the action was rejected, describe the failed "
            "attempt without making it succeed.\n\n"
            + json.dumps(packet, sort_keys=True)
        )

    def _fallback(self, event, state):
        actor = state.characters[event.actor_id].name
        target = state.characters.get(event.target_id or "")
        target_name = target.name if target else "the target"
        facts = event.facts
        if not event.accepted:
            return f"{actor}'s attempt fails: {event.reason}."
        if event.event_type == "space_folded":
            strain = " Meridian strain answers the effort." if facts["meridian_strain"] else ""
            position = (
                f", placing them behind {target_name}"
                if event.target_id
                else ""
            )
            return (
                f"Distance folds around {actor}{position}. "
                f"The technique consumes {facts['stamina_spent']} stamina.{strain}"
            )
        if event.event_type == "attack_resolved":
            if facts.get("combat_log"):
                ending = " The target falls." if not facts["target_alive"] else ""
                return facts["combat_log"] + ending
            if facts.get("missed"):
                return f"{actor}'s attack misses {target_name}."
            ending = " The target falls." if not facts["target_alive"] else ""
            return f"{actor} strikes {target_name} for {facts['damage']} damage.{ending}"
        if event.event_type == "blocked":
            return facts.get("combat_log") or f"{actor} raises a guard."
        if event.event_type == "dodged":
            return facts.get("combat_log") or f"{actor} prepares to dodge."
        if event.event_type == "rested":
            return f"{actor} steadies their breath and recovers {facts['stamina_recovered']} stamina."
        if event.event_type == "observed_character":
            return (
                f"{actor} studies {facts['name']}: realm {facts['realm']}, "
                f"affinity {facts['affinity']}."
            )
        if event.event_type == "observed_location":
            return f"{actor} surveys {facts['location_name']} and finds danger level {facts['danger']}."
        if event.event_type == "conversation_resolved":
            return f"{actor} speaks with {facts['target_name']}; trust shifts to {facts['trust_after']}."
        if event.event_type == "moved":
            return f"{actor} travels to {facts['destination_name']}."
        if event.event_type == "item_dropped":
            return f"{actor} leaves {facts['item_id']} at their current location."
        if event.event_type == "item_picked_up":
            return f"{actor} picks up {facts['item_id']}."
        if event.event_type == "item_stolen":
            return (
                f"{actor} takes {facts['item_id']} from {target_name}. "
                f"{len(facts['witnessed_by'])} witnesses remember the theft."
            )
        if event.event_type == "item_equipped":
            return f"{actor} equips {facts['item_id']} in the {facts['slot']} slot."
        if event.event_type == "item_unequipped":
            return f"{actor} unequips {facts['item_id']}."
        if event.event_type == "skill_trained":
            return (
                f"{actor} trains {facts['skill_id']} to mastery "
                f"{facts['mastery_after']}."
            )
        if event.event_type == "job_worked":
            return (
                f"{actor} works as a {facts['job_id']} and reaches job rank "
                f"{facts['job_rank_after']}."
            )
        if event.event_type == "resource_gathered":
            return (
                f"{actor} gathers {facts['resource_kind']}; "
                f"{facts['quantity_after']} remain."
            )
        if event.event_type == "item_crafted":
            return (
                f"{actor} crafts {facts['item_id']} at quality "
                f"{facts['quality']}."
            )
        if event.event_type == "item_traded":
            return (
                f"{actor} buys {facts['item_id']} for {facts['price']} coins."
            )
        if event.event_type == "cultivation_advanced":
            ending = " A breakthrough follows." if facts["breakthrough"] else ""
            return (
                f"{actor} advances {facts['progress_gained']} cultivation "
                f"progress in the {facts['stage_after']} stage.{ending}"
            )
        if event.event_type == "schedule_followed":
            if facts["moved"]:
                return (
                    f"{actor} follows their schedule toward "
                    f"{facts['destination_id']}, reaching "
                    f"{facts['location_after']}."
                )
            return f"{actor} remains at their scheduled location."
        if event.event_type == "waited":
            return f"{actor} waits and watches."
        if event.event_type == "world_tick_resolved":
            changes = facts.get("village_pressure_changes", {})
            return (
                f"Day {facts['day']} settles over the village; "
                f"{len(changes)} pressures shift."
            )
        return f"Turn {event.turn} resolves as {event.event_type}."
