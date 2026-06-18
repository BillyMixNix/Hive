from __future__ import annotations

from pathlib import Path

from .agent_loop import AffordanceBuilder


class TerminalPlayer:
    """Human-facing terminal loop over validated Twin Realms actions."""

    def __init__(
        self,
        runtime,
        *,
        save_path="twin_realms_save.json",
        input_fn=input,
        output_fn=print,
        affordances=None,
    ):
        self.runtime = runtime
        self.save_path = Path(save_path)
        self.input_fn = input_fn
        self.output_fn = output_fn
        self.affordances = affordances or AffordanceBuilder()
        self._numbered_actions = []
        self._reported_narration_failures = 0
        self._reported_npc_transport_failures = 0

    @property
    def engine(self):
        return self.runtime.engine

    def run(self):
        self.output_fn("Twin Realms")
        self.output_fn("Type 'help' for commands. Free text performs an action.")
        self.output_fn(self.describe_location())
        while True:
            try:
                text = self.input_fn("> ").strip()
            except (EOFError, KeyboardInterrupt):
                text = "quit"
                self.output_fn("")
            if not self.handle(text):
                break

    def handle(self, text):
        clean = " ".join(text.lower().split())
        if not clean:
            return True
        if clean in {"quit", "exit"}:
            self.save()
            self.output_fn(
                f"Saved turn {self.engine.state.turn} to {self.save_path}."
            )
            return False
        if clean in {"help", "?"}:
            self.output_fn(self.help_text())
            return True
        if clean in {"look", "where", "location"}:
            self.output_fn(self.describe_location())
            return True
        if clean in {"status", "stats"}:
            self.output_fn(self.describe_status())
            return True
        if clean in {"inventory", "items", "equipment"}:
            self.output_fn(self.describe_inventory())
            return True
        if clean in {"people", "npcs", "characters"}:
            self.output_fn(self.describe_people())
            return True
        if clean in {"village", "pressures", "rumors", "factions"}:
            self.output_fn(self.describe_village())
            return True
        if clean in {"actions", "choices"}:
            self.output_fn(self.describe_actions())
            return True
        if clean in {"history", "events"}:
            self.output_fn(self.describe_history())
            return True
        if clean == "save":
            self.save()
            self.output_fn(
                f"Saved turn {self.engine.state.turn} to {self.save_path}."
            )
            return True
        if clean.startswith("do "):
            return self._perform_numbered(clean[3:].strip())
        self._render_turn(self.runtime.turn(text))
        return True

    def save(self):
        return self.engine.save(self.save_path)

    def describe_location(self):
        state = self.engine.state
        actor = state.characters[state.player_id]
        location = state.locations[actor.location_id]
        present = [
            character.name
            for character in state.characters.values()
            if character.id != actor.id
            and character.active
            and character.alive
            and character.location_id == actor.location_id
        ]
        exits = [
            state.locations[location_id].name
            for location_id in location.connections
        ]
        ground = [
            state.items[item_id].name
            for item_id in state.ground_items.get(location.id, [])
        ]
        return "\n".join([
            f"{location.name} | danger {location.danger} | turn {state.turn}",
            f"Present: {', '.join(present) if present else 'nobody'}",
            f"Exits: {', '.join(exits) if exits else 'none'}",
            f"Ground: {', '.join(ground) if ground else 'nothing'}",
        ])

    def describe_status(self):
        state = self.engine.state
        actor = state.characters[state.player_id]
        injuries = ", ".join(actor.injuries) if actor.injuries else "none"
        return "\n".join([
            f"{actor.name} | health {actor.health}/{actor.max_health} | "
            f"stamina {actor.stamina}/{actor.max_stamina}",
            f"Realm {actor.realm} | {actor.cultivation_stage} "
            f"{actor.cultivation_progress}% | affinity {actor.affinity}",
            f"Level {actor.level} | experience {actor.experience} | "
            f"coins {actor.coins}",
            f"Injuries: {injuries}",
        ])

    def describe_inventory(self):
        state = self.engine.state
        actor = state.characters[state.player_id]
        carried = [
            f"{item_id} ({state.items[item_id].name})"
            for item_id in actor.inventory
        ]
        equipped = [
            f"{slot}: {item_id}" for slot, item_id in actor.equipment.items()
        ]
        return "\n".join([
            "Carried: " + (", ".join(carried) if carried else "nothing"),
            "Equipped: " + (", ".join(equipped) if equipped else "nothing"),
        ])

    def describe_people(self):
        state = self.engine.state
        player = state.characters[state.player_id]
        scheduled = set(self.runtime._npc_ids_for_turn())
        people = [
            character
            for character in state.characters.values()
            if character.id != player.id
            and character.active
            and character.alive
            and character.location_id == player.location_id
        ]
        if not people:
            return "Nobody else is here."
        lines = ["People here:"]
        for character in people:
            control = (
                "Hive mind active"
                if character.id in scheduled and self.runtime.npc_planner
                else "world actor"
            )
            faction = character.faction_id or "independent"
            lines.append(
                f"- {character.name} | {faction} | {control}"
            )
        return "\n".join(lines)

    def describe_village(self):
        state = self.engine.state
        pressures = state.flags.get("village_pressures") or {}
        world_pressures = state.flags.get("world_pressures") or {}
        rumors = state.flags.get("rumors") or []
        lines = [
            f"Day {state.flags.get('current_day', 1)} | turn {state.turn}",
            "Village pressures:",
        ]
        if pressures:
            lines.extend(
                f"- {key.replace('_', ' ')}: {pressures[key]}"
                for key in sorted(pressures)
            )
        else:
            lines.append("- none")
        lines.append("World pressures:")
        if world_pressures:
            for key in sorted(world_pressures):
                pressure = world_pressures[key]
                if not isinstance(pressure, dict):
                    continue
                severity = pressure.get("severity", 0)
                locations = [
                    state.locations[location_id].name
                    for location_id in pressure.get("affected_locations", [])
                    if location_id in state.locations
                ]
                location_text = ", ".join(locations) if locations else "none"
                lines.append(
                    f"- {key.replace('_', ' ')}: {severity} | {location_text}"
                )
        else:
            lines.append("- none")
        lines.append("Rumors:")
        if rumors:
            for rumor in rumors:
                subject = state.characters.get(rumor.get("subject_id", ""))
                origin = state.locations.get(rumor.get("origin_location_id", ""))
                confidence = int(float(rumor.get("confidence", 0)) * 100)
                subject_name = subject.name if subject else rumor.get("subject_id")
                origin_name = origin.name if origin else rumor.get("origin_location_id")
                lines.append(
                    f"- {subject_name} from {origin_name} | confidence {confidence}%"
                )
        else:
            lines.append("- none")
        return "\n".join(lines)

    def describe_actions(self):
        state = self.engine.state
        self._numbered_actions = self.affordances.build(
            state.player_id,
            state,
        )
        lines = ["Available actions:"]
        lines.extend(
            f"{index}. {self._humanize(option['description'])}"
            for index, option in enumerate(self._numbered_actions, start=1)
        )
        lines.append("Use 'do NUMBER' to select one exactly.")
        return "\n".join(lines)

    def _humanize(self, text):
        state = self.engine.state
        replacements = {
            **{
                entity_id: character.name
                for entity_id, character in state.characters.items()
            },
            **{
                entity_id: location.name
                for entity_id, location in state.locations.items()
            },
            **{
                entity_id: item.name
                for entity_id, item in state.items.items()
            },
            **{
                entity_id: entity_id.split(":", 1)[-1].replace("_", " ")
                for entity_id in state.resource_nodes
            },
        }
        rendered = text
        for entity_id in sorted(replacements, key=len, reverse=True):
            rendered = rendered.replace(entity_id, replacements[entity_id])
        return rendered

    def describe_history(self, limit=8):
        events = self.engine.events[-limit:]
        if not events:
            return "No resolved events yet."
        return "\n".join(
            f"{event.turn}. {event.actor_id}: {event.event_type}"
            + (f" ({event.reason})" if event.reason else "")
            for event in events
        )

    @staticmethod
    def help_text():
        return "\n".join([
            "Commands:",
            "  look       Show the current location and nearby actors.",
            "  status     Show health, stamina, realm, and progression.",
            "  inventory  Show carried and equipped items.",
            "  people     Show nearby NPCs and active Hive minds.",
            "  village    Show Tarrow pressures, world pressures, and rumors.",
            "  actions    Show exact actions currently allowed.",
            "  do NUMBER  Execute one listed action.",
            "  history    Show recent authoritative world events.",
            "  save       Save without exiting.",
            "  quit       Save and exit.",
            "You can also type actions naturally, such as:",
            "  attack the malformed",
            "  move to Willow Market",
            "  talk to Elder Mara",
            "  train swordsmanship",
        ])

    def _perform_numbered(self, raw_number):
        try:
            index = int(raw_number) - 1
        except ValueError:
            self.output_fn("Use 'do NUMBER', for example 'do 3'.")
            return True
        if not self._numbered_actions:
            self.output_fn("Use 'actions' first to refresh the current choices.")
            return True
        if not 0 <= index < len(self._numbered_actions):
            self.output_fn("That action number is not available.")
            return True
        intent = self._numbered_actions[index]["intent"]
        self._numbered_actions = []
        self._render_turn(self.runtime.intent_turn(intent))
        return True

    def _render_turn(self, result):
        self._numbered_actions = []
        self.output_fn(result.player_result.narrative)
        if not result.player_result.event.accepted:
            self.output_fn(f"Rejected: {result.player_result.event.reason}")
        for npc_result in result.npc_results:
            self.output_fn(f"[World] {npc_result.narrative}")
        self._report_degraded_mode()

    def _report_degraded_mode(self):
        narrator = self.engine.narrator
        narration_failures = getattr(
            narrator,
            "llm_failure_count",
            0,
        )
        if narration_failures > self._reported_narration_failures:
            self.output_fn(
                "[System] Hive narration is unavailable. "
                "Using deterministic resolved-event narration."
            )
            self._reported_narration_failures = narration_failures
        planner = self.runtime.npc_planner
        npc_failures = getattr(planner, "transport_failures", 0)
        if npc_failures > self._reported_npc_transport_failures:
            self.output_fn(
                "[System] Hive NPC transport is unavailable. "
                "NPC cognition is using bounded safe fallbacks; world truth, "
                "replay, and saving remain active."
            )
            self._reported_npc_transport_failures = npc_failures
