from __future__ import annotations

from dataclasses import dataclass

from .engine import TwinRealmsEngine
from .models import ActionIntent
from .runtime import TwinRealmsRuntime
from .tarrow import build_tarrow_aftermath_world


@dataclass(frozen=True)
class TarrowScenarioReport:
    path: str
    elapsed_days: int
    start_turn: int
    end_turn: int
    start_day: int
    end_day: int
    commands: tuple[str, ...]
    accepted_commands: tuple[str, ...]
    rejected_commands: tuple[dict, ...]
    pressure_before: dict
    pressure_after: dict
    settlement_before: dict
    settlement_after: dict
    key_events: tuple[dict, ...]
    replay_consistent: bool
    state_digest: str

    @property
    def pressure_deltas(self):
        return {
            key: self.pressure_after.get(key, 0) - before
            for key, before in self.pressure_before.items()
            if self.pressure_after.get(key, before) != before
        }

    @property
    def settlement_deltas(self):
        before = self.settlement_before
        after = self.settlement_after
        deltas = {}
        for key in (
            "status",
            "safety_level",
            "hostility_level",
            "defense_level",
            "prosperity",
        ):
            if before.get(key) != after.get(key):
                deltas[key] = {
                    "before": before.get(key),
                    "after": after.get(key),
                }
        for group in ("population", "location_states", "resources"):
            changed = {}
            keys = sorted(set(before.get(group, {})) | set(after.get(group, {})))
            for key in keys:
                if before.get(group, {}).get(key) != after.get(group, {}).get(key):
                    changed[key] = {
                        "before": before.get(group, {}).get(key),
                        "after": after.get(group, {}).get(key),
                    }
            if changed:
                deltas[group] = changed
        return deltas

    def to_dict(self):
        return {
            "path": self.path,
            "elapsed_days": self.elapsed_days,
            "start_turn": self.start_turn,
            "end_turn": self.end_turn,
            "start_day": self.start_day,
            "end_day": self.end_day,
            "commands": list(self.commands),
            "accepted_commands": list(self.accepted_commands),
            "rejected_commands": list(self.rejected_commands),
            "pressure_before": dict(self.pressure_before),
            "pressure_after": dict(self.pressure_after),
            "pressure_deltas": self.pressure_deltas,
            "settlement_before": dict(self.settlement_before),
            "settlement_after": dict(self.settlement_after),
            "settlement_deltas": self.settlement_deltas,
            "key_events": list(self.key_events),
            "replay_consistent": self.replay_consistent,
            "state_digest": self.state_digest,
        }


SCENARIO_PATHS = {
    "ignore": (),
    "defend": (
        "move to Old Watch Post",
        "work guard",
        "rest",
        "work guard",
    ),
    "rebuild": (
        "work carpenter",
        "move to Low Fields",
        "work farmer",
        "rest",
        "move to Healer Hut",
        "work healer",
    ),
}


def run_tarrow_scenario(path="ignore", *, days=3, seed=17):
    """Run one deterministic vertical-slice path through Tarrow."""

    if path not in SCENARIO_PATHS:
        raise ValueError(f"unknown Tarrow scenario path: {path}")
    if days < 1:
        raise ValueError("days must be at least 1")

    engine = TwinRealmsEngine(build_tarrow_aftermath_world(seed=seed))
    runtime = TwinRealmsRuntime(engine, mode="baseline")
    state = engine.state
    start_turn = state.turn
    start_day = int(state.flags.get("current_day", 1))
    pressure_before = dict(state.flags.get("village_pressures") or {})
    settlement_before = _settlement_snapshot(state)
    key_events = []
    accepted = []
    rejected = []

    for command in SCENARIO_PATHS[path]:
        result = runtime.turn(command)
        event = result.player_result.event
        key_events.append(_event_summary(event))
        if event.accepted:
            accepted.append(command)
        else:
            rejected.append({
                "command": command,
                "reason": event.reason,
            })
        for world_result in result.world_results:
            _record_world_event(key_events, world_result.event)

    target_turn = start_turn + (days * int(state.flags.get("day_length", 24)))
    while state.turn < target_turn:
        result = engine.apply_intent(ActionIntent("world_tick", state.player_id))
        _record_world_event(key_events, result.event)

    return TarrowScenarioReport(
        path=path,
        elapsed_days=days,
        start_turn=start_turn,
        end_turn=state.turn,
        start_day=start_day,
        end_day=int(state.flags.get("current_day", start_day)),
        commands=tuple(SCENARIO_PATHS[path]),
        accepted_commands=tuple(accepted),
        rejected_commands=tuple(rejected),
        pressure_before=pressure_before,
        pressure_after=dict(state.flags.get("village_pressures") or {}),
        settlement_before=settlement_before,
        settlement_after=_settlement_snapshot(state),
        key_events=tuple(key_events),
        replay_consistent=engine.verify_replay(),
        state_digest=engine.simulator.state_digest(state),
    )


def run_tarrow_scenario_matrix(paths=None, *, days=3, seed=17):
    paths = tuple(paths or SCENARIO_PATHS)
    return {
        path: run_tarrow_scenario(path, days=days, seed=seed)
        for path in paths
    }


def _record_world_event(key_events, event):
    facts = event.facts or {}
    if (
        facts.get("village_pressure_changes")
        or facts.get("settlement_changes")
        or facts.get("memory_events")
    ):
        key_events.append(_event_summary(event))


def _event_summary(event):
    facts = event.facts or {}
    summary = {
        "turn": event.turn,
        "type": event.event_type,
        "actor_id": event.actor_id,
        "accepted": event.accepted,
    }
    if event.reason:
        summary["reason"] = event.reason
    for key in (
        "job_id",
        "destination_id",
        "village_pressure_changes",
        "settlement_changes",
        "memory_events",
    ):
        value = facts.get(key)
        if value:
            summary[key] = value
    return summary


def _settlement_snapshot(state):
    settlement = state.flags["settlements"]["settlement:tarrow"]
    return {
        "status": settlement.get("status"),
        "safety_level": settlement.get("safety_level"),
        "hostility_level": settlement.get("hostility_level"),
        "defense_level": settlement.get("defense_level"),
        "prosperity": settlement.get("prosperity"),
        "resources": dict(settlement.get("resources") or {}),
        "population": dict(settlement.get("population") or {}),
        "location_states": dict(settlement.get("location_states") or {}),
    }
