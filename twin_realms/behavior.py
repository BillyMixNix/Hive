from __future__ import annotations

from collections import Counter
from copy import deepcopy

from .models import ActionIntent


PROGRESSION_EVENTS = {
    "item_equipped",
    "item_picked_up",
    "job_worked",
    "skill_trained",
}


def analyze_agent_behavior(engine):
    """Replay recorded events while measuring player behavior against pre-state."""

    state = deepcopy(engine.initial_state)
    knowledge = deepcopy(engine.initial_knowledge)
    player_id = state.player_id
    player_actions = 0
    first_threat_player_turn = None
    first_threat_world_turn = None
    death_world_turn = None
    death_player_turn = None
    pre_death_player_events = []
    hostile_action_mix = Counter()
    progression = {
        "before_threat": _progression_bucket(),
        "after_threat": _progression_bucket(),
    }

    for recorded in engine.events:
        actor = state.characters.get(recorded.actor_id)
        player = state.characters[player_id]
        active_hostiles = _active_hostiles(player_id, state)
        visible_hostiles = _visible_hostiles(player_id, state)
        is_player_event = recorded.actor_id == player_id
        if is_player_event:
            player_actions += 1
            if active_hostiles and first_threat_player_turn is None:
                first_threat_player_turn = player_actions
                first_threat_world_turn = recorded.turn
            if death_world_turn is None:
                pre_death_player_events.append(recorded)
            if visible_hostiles:
                hostile_action_mix[recorded.intent.get("action", "unknown")] += 1
            phase = (
                "after_threat"
                if first_threat_player_turn is not None
                else "before_threat"
            )
            if recorded.accepted and recorded.event_type in PROGRESSION_EVENTS:
                bucket = progression[phase]
                bucket["accepted_events"] += 1
                bucket["experience_gained"] += recorded.facts.get(
                    "experience_gained", 0
                )
                bucket["event_counts"][recorded.event_type] += 1

        intent = ActionIntent.from_dict(recorded.intent)
        actual = engine.simulator.resolve(state, intent, knowledge)
        if actual.to_dict() != recorded.to_dict():
            raise AssertionError(
                f"behavior replay diverged at turn {recorded.turn}"
            )

        if (
            death_world_turn is None
            and recorded.target_id == player_id
            and recorded.facts.get("target_alive") is False
        ):
            death_world_turn = recorded.turn
            death_player_turn = player_actions

    final_player = state.characters[player_id]
    terminal_rejections = sum(
        event.actor_id == player_id
        and not event.accepted
        and event.reason == "actor is unavailable"
        for event in engine.events
    )
    rejected_pre_death = sum(
        not event.accepted for event in pre_death_player_events
    )
    for bucket in progression.values():
        bucket["event_counts"] = dict(sorted(bucket["event_counts"].items()))
    return {
        "invalid_reference_rejections": _invalid_reference_rejections(engine),
        "pre_death_accepted_rate": (
            (len(pre_death_player_events) - rejected_pre_death)
            / len(pre_death_player_events)
            if pre_death_player_events
            else None
        ),
        "pre_death_player_events": len(pre_death_player_events),
        "survival_turns": {
            "player_turns": (
                death_player_turn if death_player_turn is not None
                else player_actions
            ),
            "world_turns": (
                death_world_turn if death_world_turn is not None
                else state.turn
            ),
            "survived_benchmark": final_player.alive,
        },
        "threat_onset": {
            "player_turn": first_threat_player_turn,
            "world_turn": first_threat_world_turn,
        },
        "progression": progression,
        "hostile_present_action_mix": dict(sorted(hostile_action_mix.items())),
        "terminal_state_rejections": terminal_rejections,
        "replay_consistent": engine.verify_replay(),
        "final_player": {
            "alive": final_player.alive,
            "level": final_player.level,
            "experience": final_player.experience,
            "health": final_player.health,
            "stamina": final_player.stamina,
            "equipment": dict(final_player.equipment),
            "skills": dict(final_player.skill_mastery),
            "jobs": dict(final_player.jobs),
        },
    }


def _progression_bucket():
    return {
        "accepted_events": 0,
        "experience_gained": 0,
        "event_counts": Counter(),
    }


def _visible_hostiles(actor_id, state):
    actor = state.characters[actor_id]
    if not actor.alive or not actor.active:
        return []
    return [
        hostile_id
        for hostile_id in _active_hostiles(actor_id, state)
        if state.characters[hostile_id].location_id == actor.location_id
    ]


def _active_hostiles(actor_id, state):
    actor = state.characters[actor_id]
    if not actor.alive or not actor.active:
        return []
    return [
        character.id
        for character in state.characters.values()
        if character.id != actor_id
        and character.active
        and character.alive
        and (
            "hostile" in character.tags
            or "hostile" in actor.tags
        )
    ]


def _invalid_reference_rejections(engine):
    terms = (
        "target is not present",
        "target is unavailable",
        "living target is required",
        "destination does not exist",
        "destination is not connected",
        "item is not carried",
        "item is not on the ground here",
        "conversation target is not present",
        "theft target is not present",
        "target does not carry that item",
    )
    return sum(
        not event.accepted and event.reason in terms
        for event in engine.events
    )
