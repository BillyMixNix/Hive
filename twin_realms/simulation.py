from __future__ import annotations

import hashlib
import json
import random

from .knowledge import WorldKnowledge
from .models import ActionIntent, WorldEvent, WorldState


class WorldSimulator:
    SPACE_FOLD_COST = 18
    SPACE_FOLD_MAX_DISTANCE = 10
    ATTACK_COST = 10
    BLOCK_COST = 6
    DODGE_COST = 8
    HEAVY_ATTACK_COST = 18
    HEAVY_ATTACK_COOLDOWN = 2
    WORK_COST = 12
    TRAIN_COST = 8
    GATHER_COST = 8
    CRAFT_COST = 12
    CULTIVATE_COST = 16

    def resolve(self, state: WorldState, intent: ActionIntent, knowledge=None):
        knowledge = knowledge or WorldKnowledge()
        next_turn = state.turn + 1
        self._regenerate_resources(state, next_turn)
        activated_entities = self._activate_due_entities(state, next_turn)
        actor = state.characters.get(intent.actor_id)
        if not actor or not actor.alive or not actor.active:
            event_type, accepted, facts, reason = (
                "action_rejected",
                False,
                {},
                "actor is unavailable",
            )
        else:
            handler = getattr(self, f"_resolve_{intent.action}", self._resolve_unknown)
            event_type, accepted, facts, reason = handler(
                state,
                intent,
                knowledge,
                next_turn,
            )
        if activated_entities:
            facts = dict(facts)
            facts["activated_entities"] = activated_entities
        state.turn = next_turn
        event = WorldEvent(
            id=f"turn:{next_turn}",
            turn=next_turn,
            event_type=event_type,
            actor_id=intent.actor_id,
            target_id=intent.target_id,
            accepted=accepted,
            facts=facts,
            reason=reason,
            intent=intent.to_dict(),
        )
        self.assert_invariants(state)
        return event

    def _resolve_space_fold(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        if "space_fold" not in actor.techniques or actor.affinity != "space":
            return "action_rejected", False, {}, "space folding is not unlocked"
        if actor.realm < 3:
            return "action_rejected", False, {}, "foundation realm is required"
        distance = intent.distance or 5
        max_distance = self.SPACE_FOLD_MAX_DISTANCE
        overreach_rule = knowledge.is_promoted("space_fold_overreach_strain")
        if knowledge.is_promoted("space_fold_extended_range") or overreach_rule:
            max_distance = 12
        if distance > max_distance:
            return "action_rejected", False, {"distance": distance}, "distance exceeds stable range"
        if actor.stamina < self.SPACE_FOLD_COST:
            return "action_rejected", False, {}, "insufficient stamina"
        if intent.target_id:
            target = state.characters.get(intent.target_id)
            if not target or not target.alive or not target.active:
                return "action_rejected", False, {}, "target is unavailable"
            if target.location_id != actor.location_id:
                return "action_rejected", False, {}, "target is not present"
        if intent.destination_id:
            if intent.destination_id not in state.locations:
                return "action_rejected", False, {}, "destination does not exist"
            actor.location_id = intent.destination_id
        actor.stamina -= self.SPACE_FOLD_COST
        strain = "strained_meridian" in actor.injuries
        overreach_strain = overreach_rule and distance > self.SPACE_FOLD_MAX_DISTANCE
        if overreach_strain and "overextended_meridian" not in actor.injuries:
            actor.injuries.append("overextended_meridian")
        stability_loss = 3 if overreach_strain else (2 if strain else 1)
        state.flags["twin_realm_stability"] = max(
            0,
            state.flags["twin_realm_stability"] - stability_loss,
        )
        facts = {
            "technique": "space_fold",
            "distance": distance,
            "stamina_spent": self.SPACE_FOLD_COST,
            "stamina_after": actor.stamina,
            "meridian_strain": strain,
            "overreach_strain": overreach_strain,
            "stability_after": state.flags["twin_realm_stability"],
        }
        if intent.target_id:
            facts["positioned_behind"] = intent.target_id
        knowledge.observe(
            "space_fold_meridian_stress",
            "Space folding while injured increases realm instability.",
            confirmed=strain,
        )
        return "space_folded", True, facts, None

    def _resolve_attack(self, state, intent, knowledge, turn):
        return self._resolve_strike(
            state,
            intent,
            turn,
            action_name="attack",
            stamina_cost=self.ATTACK_COST,
            damage_multiplier=1.0,
        )

    def _resolve_heavy_attack(self, state, intent, knowledge, turn):
        if not self._cooldown_ready(state, intent.actor_id, "heavy_attack", turn):
            return "action_rejected", False, {}, "heavy attack is cooling down"
        return self._resolve_strike(
            state,
            intent,
            turn,
            action_name="heavy_attack",
            stamina_cost=self.HEAVY_ATTACK_COST,
            damage_multiplier=1.7,
            cooldown=self.HEAVY_ATTACK_COOLDOWN,
        )

    def _resolve_block(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        if actor.stamina < self.BLOCK_COST:
            return "action_rejected", False, {}, "insufficient stamina"
        actor.stamina -= self.BLOCK_COST
        combat = self._actor_combat_state(state, actor.id)
        combat["guard"] = "block"
        combat["guard_expires_turn"] = turn + 1
        return "blocked", True, {
            "stamina_spent": self.BLOCK_COST,
            "stamina_after": actor.stamina,
            "guard": "block",
            "guard_expires_turn": turn + 1,
            "combat_log": f"{actor.name} blocks; next incoming damage is reduced.",
        }, None

    def _resolve_dodge(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        if actor.stamina < self.DODGE_COST:
            return "action_rejected", False, {}, "insufficient stamina"
        actor.stamina -= self.DODGE_COST
        combat = self._actor_combat_state(state, actor.id)
        combat["guard"] = "dodge"
        combat["guard_expires_turn"] = turn + 1
        return "dodged", True, {
            "stamina_spent": self.DODGE_COST,
            "stamina_after": actor.stamina,
            "guard": "dodge",
            "guard_expires_turn": turn + 1,
            "combat_log": f"{actor.name} prepares to dodge the next attack.",
        }, None

    def _resolve_strike(
        self,
        state,
        intent,
        turn,
        *,
        action_name,
        stamina_cost,
        damage_multiplier,
        cooldown=0,
    ):
        actor = self._actor(state, intent)
        target = state.characters.get(intent.target_id or "")
        if not target or not target.alive or not target.active:
            return "action_rejected", False, {}, "a living target is required"
        if actor.location_id != target.location_id:
            return "action_rejected", False, {}, "target is not present"
        if actor.stamina < stamina_cost:
            return "action_rejected", False, {}, "insufficient stamina"
        actor.stamina -= stamina_cost
        rng = random.Random(f"{state.seed}:{turn}:{actor.id}:{target.id}:{action_name}")
        weapon_power = self._equipment_power(state, actor, "main_hand")
        defense_power = (
            self._equipment_power(state, target, "body")
            + self._equipment_power(state, target, "off_hand")
        )
        combat_mastery = max(
            actor.skill_mastery.get("swordsmanship", 0),
            actor.skill_mastery.get("archery", 0),
        )
        base_damage = int((8 + (actor.realm * 3) + weapon_power + combat_mastery) * damage_multiplier)
        variance = rng.randint(0, 5)
        countered = "distortion_hide" in target.techniques and rng.random() < 0.25
        guard = self._consume_guard(state, target.id, turn)
        missed = False
        raw_damage = (
            max(1, (base_damage + variance) // 2)
            if countered
            else base_damage + variance
        )
        if guard == "dodge":
            missed = rng.random() < 0.65
            raw_damage = 0 if missed else max(1, raw_damage // 2)
        elif guard == "block":
            raw_damage = max(1, raw_damage // 3)
        damage = max(1, raw_damage - defense_power)
        if missed:
            damage = 0
        target.health = max(0, target.health - damage)
        if target.health == 0:
            target.alive = False
        if cooldown:
            self._set_cooldown(state, actor.id, action_name, turn + cooldown)
        game_state = self._update_game_state_after_attack(state, actor, target)
        pressure_changes = self._update_world_pressures_after_attack(
            state,
            actor,
            target,
        )
        consequence_changes = self._record_core_attack_consequences(
            state,
            actor,
            target,
            turn,
            damage,
        )
        progression = self._grant_experience(actor, 8 if target.alive else 20)
        combat_log = (
            f"{actor.name} uses {action_name.replace('_', ' ')} for {stamina_cost} stamina"
            f" against {target.name}: "
        )
        if missed:
            combat_log += "the attack misses."
        else:
            guard_text = f" through {guard}" if guard else ""
            combat_log += f"{damage} damage{guard_text}."
        return "attack_resolved", True, {
            "action_name": action_name,
            "damage": damage,
            "missed": missed,
            "countered": countered,
            "target_guard": guard,
            "target_health_after": target.health,
            "target_alive": target.alive,
            "stamina_spent": stamina_cost,
            "stamina_after": actor.stamina,
            "weapon_power": weapon_power,
            "defense_power": defense_power,
            "combat_mastery": combat_mastery,
            "cooldown_until": turn + cooldown if cooldown else None,
            "combat_log": combat_log,
            "world_pressure_changes": pressure_changes,
            "consequence_changes": consequence_changes,
            **game_state,
            **progression,
        }, None

    def _resolve_rest(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        before = actor.stamina
        actor.stamina = min(actor.max_stamina, actor.stamina + 24)
        recovered = actor.stamina - before
        self._decrease_need(actor, "fatigue", 20)
        self._increase_need(actor, "hunger", 1)
        injury_healed = None
        if actor.injuries and turn % 4 == 0:
            injury_healed = actor.injuries.pop(0)
        return "rested", True, {
            "stamina_recovered": recovered,
            "stamina_after": actor.stamina,
            "injury_healed": injury_healed,
        }, None

    def _resolve_observe(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        target = state.characters.get(intent.target_id or "")
        if target and target.active and target.location_id == actor.location_id:
            return "observed_character", True, {
                "name": target.name,
                "realm": target.realm,
                "affinity": target.affinity,
                "alive": target.alive,
                "visible_injuries": list(target.injuries),
                "tags": list(target.tags),
            }, None
        location = state.locations[actor.location_id]
        present = sorted(
            character.id
            for character in state.characters.values()
            if character.location_id == location.id
            and character.id != actor.id
            and character.alive
            and character.active
        )
        return "observed_location", True, {
            "location_id": location.id,
            "location_name": location.name,
            "present_characters": present,
            "danger": location.danger,
        }, None

    def _resolve_talk(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        target = state.characters.get(intent.target_id or "")
        if (
            not target
            or not target.alive
            or not target.active
            or target.location_id != actor.location_id
        ):
            return "action_rejected", False, {}, "conversation target is not present"
        old_trust = actor.relationships.get(target.id, 0)
        hostile = "hostile" in target.tags
        delta = -1 if hostile else 1
        actor.relationships[target.id] = max(-100, min(100, old_trust + delta))
        return "conversation_resolved", True, {
            "target_name": target.name,
            "trust_before": old_trust,
            "trust_after": actor.relationships[target.id],
            "hostile": hostile,
        }, None

    def _resolve_drop(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        item_id = intent.parameters.get("item_id")
        if not item_id or item_id not in actor.inventory:
            return "action_rejected", False, {}, "item is not carried"
        for slot, equipped_id in list(actor.equipment.items()):
            if equipped_id == item_id:
                del actor.equipment[slot]
        actor.inventory.remove(item_id)
        state.ground_items.setdefault(actor.location_id, []).append(item_id)
        return "item_dropped", True, {
            "item_id": item_id,
            "location_id": actor.location_id,
            "owner_after": None,
        }, None

    def _resolve_pickup(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        item_id = intent.parameters.get("item_id")
        ground = state.ground_items.setdefault(actor.location_id, [])
        if not item_id or item_id not in ground:
            return "action_rejected", False, {}, "item is not on the ground here"
        ground.remove(item_id)
        actor.inventory.append(item_id)
        return "item_picked_up", True, {
            "item_id": item_id,
            "location_id": actor.location_id,
            "owner_after": actor.id,
        }, None

    def _resolve_steal(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        target = state.characters.get(intent.target_id or "")
        item_id = intent.parameters.get("item_id")
        if (
            not target
            or not target.alive
            or not target.active
            or target.location_id != actor.location_id
        ):
            return "action_rejected", False, {}, "theft target is not present"
        if not item_id or item_id not in target.inventory:
            return "action_rejected", False, {}, "target does not carry that item"
        for slot, equipped_id in list(target.equipment.items()):
            if equipped_id == item_id:
                del target.equipment[slot]
        target.inventory.remove(item_id)
        actor.inventory.append(item_id)
        witnesses = sorted(
            character.id
            for character in state.characters.values()
            if character.alive
            and character.active
            and character.location_id == actor.location_id
            and character.id != actor.id
        )
        trust_changes = {}
        for witness_id in witnesses:
            witness = state.characters[witness_id]
            trust_before = witness.relationships.get(actor.id, 0)
            trust_after = max(-100, trust_before - 15)
            witness.relationships[actor.id] = trust_after
            event = (
                "player_stole_from_me"
                if (
                    state.flags.get("core_loop")
                    and witness.id == target.id
                    and actor.id == state.player_id
                )
                else "witnessed_theft"
            )
            witness.memories.append({
                "turn": turn,
                "event": event,
                "actor_id": actor.id,
                "target_id": target.id,
                "item_id": item_id,
            })
            witness.memories = witness.memories[-8:]
            trust_changes[witness_id] = {
                "before": trust_before,
                "after": trust_after,
            }
        faction_penalties = {}
        for witness_id in witnesses:
            faction_id = state.characters[witness_id].faction_id
            if not faction_id or faction_id in faction_penalties:
                continue
            before = actor.reputation.get(faction_id, 0)
            after = max(-100, before - 10)
            actor.reputation[faction_id] = after
            faction_penalties[faction_id] = {
                "before": before,
                "after": after,
            }
        if faction_penalties:
            state.flags["kingdom_alert_level"] = "medium"
        return "item_stolen", True, {
            "item_id": item_id,
            "previous_owner": target.id,
            "owner_after": actor.id,
            "witnessed_by": witnesses,
            "trust_changes": trust_changes,
            "faction_reputation_changes": faction_penalties,
            "alert_level_after": state.flags.get("kingdom_alert_level"),
        }, None

    def _resolve_move(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        destination = state.locations.get(intent.destination_id or "")
        if not destination:
            return "action_rejected", False, {}, "destination does not exist"
        origin = state.locations[actor.location_id]
        if destination.id not in origin.connections:
            return "action_rejected", False, {}, "destination is not connected"
        actor.location_id = destination.id
        return "moved", True, {
            "origin_id": origin.id,
            "destination_id": destination.id,
            "destination_name": destination.name,
        }, None

    def _resolve_equip(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        item_id = intent.parameters.get("item_id")
        item = state.items.get(item_id or "")
        if not item or item_id not in actor.inventory:
            return "action_rejected", False, {}, "item is not carried"
        if not item.slot:
            return "action_rejected", False, {}, "item cannot be equipped"
        previous = actor.equipment.get(item.slot)
        actor.equipment[item.slot] = item_id
        return "item_equipped", True, {
            "item_id": item_id,
            "slot": item.slot,
            "replaced_item_id": previous,
            "power": item.power,
        }, None

    def _resolve_unequip(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        slot = intent.parameters.get("slot")
        if not slot or slot not in actor.equipment:
            return "action_rejected", False, {}, "equipment slot is empty"
        item_id = actor.equipment.pop(slot)
        return "item_unequipped", True, {
            "item_id": item_id,
            "slot": slot,
        }, None

    def _resolve_train(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        skill_id = intent.parameters.get("skill_id")
        if skill_id not in state.flags.get("skills", []):
            return "action_rejected", False, {}, "skill is unknown"
        if actor.stamina < self.TRAIN_COST:
            return "action_rejected", False, {}, "insufficient stamina"
        actor.stamina -= self.TRAIN_COST
        before = actor.skill_mastery.get(skill_id, 0)
        actor.skill_mastery[skill_id] = min(100, before + 1)
        progression = self._grant_experience(actor, 5)
        return "skill_trained", True, {
            "skill_id": skill_id,
            "mastery_before": before,
            "mastery_after": actor.skill_mastery[skill_id],
            "stamina_after": actor.stamina,
            **progression,
        }, None

    def _resolve_work(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        job_id = intent.parameters.get("job_id")
        if job_id not in state.flags.get("jobs", []):
            return "action_rejected", False, {}, "job is unknown"
        job_sites = state.flags.get("job_sites", {}).get(job_id)
        if job_sites and actor.location_id not in job_sites:
            return "action_rejected", False, {}, "job is not available here"
        if actor.stamina < self.WORK_COST:
            return "action_rejected", False, {}, "insufficient stamina"
        actor.stamina -= self.WORK_COST
        self._increase_need(actor, "hunger", 2)
        self._increase_need(actor, "fatigue", 3)
        actor.coins += 3
        before = actor.jobs.get(job_id, 0)
        actor.jobs[job_id] = min(100, before + 1)
        related_skill = {
            "archivist": "lore",
            "blacksmith": "smithing",
            "carpenter": "carpentry",
            "disciple": "cultivation",
            "farmer": "farming",
            "fisher": "fishing",
            "guard": "leadership",
            "hunter": "foraging",
            "innkeeper": "cooking",
            "merchant": "barter",
            "miner": "mining",
            "raider": "stealth",
            "villager": "foraging",
        }.get(job_id)
        if related_skill:
            actor.skill_mastery[related_skill] = min(
                100,
                actor.skill_mastery.get(related_skill, 0) + 1,
            )
        settlement_changes = self._apply_tarrow_work_settlement_effect(
            state,
            actor,
            job_id,
            turn,
        )
        progression = self._grant_experience(actor, 10)
        return "job_worked", True, {
            "job_id": job_id,
            "job_rank_before": before,
            "job_rank_after": actor.jobs[job_id],
            "related_skill": related_skill,
            "stamina_after": actor.stamina,
            "coins_after": actor.coins,
            "settlement_changes": settlement_changes,
            **progression,
        }, None

    def _resolve_gather(self, state, intent, knowledge, turn):
        from .models import Item

        actor = self._actor(state, intent)
        node_id = intent.parameters.get("resource_node_id")
        node = state.resource_nodes.get(node_id or "")
        if not node or node.location_id != actor.location_id:
            return "action_rejected", False, {}, "resource is not present"
        if node.quantity <= 0:
            return "action_rejected", False, {}, "resource is depleted"
        if actor.stamina < self.GATHER_COST:
            return "action_rejected", False, {}, "insufficient stamina"
        actor.stamina -= self.GATHER_COST
        node.quantity -= 1
        mastery = actor.skill_mastery.get(node.required_skill or "", 0)
        quality = 1 + int(mastery >= 50)
        item_id = self._new_item_id(node.resource_kind, turn, actor.id)
        state.items[item_id] = Item(
            id=item_id,
            name=node.resource_kind.replace("_", " ").title(),
            kind=node.resource_kind,
            tags=["resource"],
            quality=quality,
            value=2 * quality,
        )
        actor.inventory.append(item_id)
        state.flags["item_ids"] = sorted(state.items)
        if node.required_skill:
            actor.skill_mastery[node.required_skill] = min(100, mastery + 1)
        self._increase_need(actor, "hunger", 2)
        self._increase_need(actor, "fatigue", 2)
        event_changes = self._resolve_core_gather_events(
            state,
            actor,
            node,
            turn,
        )
        return "resource_gathered", True, {
            "resource_node_id": node.id,
            "resource_kind": node.resource_kind,
            "item_id": item_id,
            "quantity_after": node.quantity,
            "quality": quality,
            "stamina_after": actor.stamina,
            "event_changes": event_changes,
        }, None

    def _resolve_craft(self, state, intent, knowledge, turn):
        from .models import Item

        actor = self._actor(state, intent)
        recipe_id = intent.parameters.get("recipe_id")
        recipe = state.flags.get("recipes", {}).get(recipe_id or "")
        if not recipe:
            return "action_rejected", False, {}, "recipe is unknown"
        if actor.stamina < self.CRAFT_COST:
            return "action_rejected", False, {}, "insufficient stamina"
        skill_id = recipe["skill"]
        mastery = actor.skill_mastery.get(skill_id, 0)
        if mastery < int(recipe.get("min_mastery", 0)):
            return "action_rejected", False, {}, "skill mastery is too low"
        consumed = []
        for kind, required in recipe.get("inputs", {}).items():
            matches = sorted(
                item_id for item_id in actor.inventory
                if state.items[item_id].kind == kind
            )
            if len(matches) < required:
                return "action_rejected", False, {}, "required materials are missing"
            consumed.extend(matches[:required])
        for item_id in consumed:
            actor.inventory.remove(item_id)
            del state.items[item_id]
        actor.stamina -= self.CRAFT_COST
        quality = min(5, 1 + mastery // 25)
        item_id = self._new_item_id(recipe_id, turn, actor.id)
        state.items[item_id] = Item(
            id=item_id,
            name=recipe_id.replace("_", " ").title(),
            kind=recipe["output_kind"],
            slot=recipe.get("slot"),
            power=int(recipe.get("power", 0)) + quality - 1,
            skill=skill_id,
            tags=list(recipe.get("tags", [])),
            quality=quality,
            value=int(recipe.get("value", 1)) * quality,
            crafted_by=actor.id,
        )
        actor.inventory.append(item_id)
        state.flags["item_ids"] = sorted(state.items)
        actor.skill_mastery[skill_id] = min(100, mastery + 2)
        self._increase_need(actor, "fatigue", 3)
        progression = self._grant_experience(actor, 12)
        return "item_crafted", True, {
            "recipe_id": recipe_id,
            "item_id": item_id,
            "consumed_item_ids": consumed,
            "quality": quality,
            "stamina_after": actor.stamina,
            **progression,
        }, None

    def _resolve_trade(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        target = state.characters.get(intent.target_id or "")
        item_id = intent.parameters.get("item_id")
        if (
            not target
            or not target.alive
            or not target.active
            or target.location_id != actor.location_id
        ):
            return "action_rejected", False, {}, "merchant is not present"
        if "merchant" not in target.tags:
            return "action_rejected", False, {}, "target is not a merchant"
        if item_id not in target.inventory:
            return "action_rejected", False, {}, "merchant does not carry that item"
        price = state.items[item_id].value
        if actor.coins < price:
            return "action_rejected", False, {}, "insufficient coins"
        actor.coins -= price
        target.coins += price
        target.inventory.remove(item_id)
        actor.inventory.append(item_id)
        faction_id = target.faction_id or ""
        actor.reputation[faction_id] = min(
            100,
            actor.reputation.get(faction_id, 0) + 1,
        )
        return "item_traded", True, {
            "item_id": item_id,
            "price": price,
            "buyer_coins_after": actor.coins,
            "seller_coins_after": target.coins,
            "faction_id": target.faction_id,
        }, None

    def _resolve_cultivate(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        if actor.stamina < self.CULTIVATE_COST:
            return "action_rejected", False, {}, "insufficient stamina"
        location = state.locations[actor.location_id]
        gain = 4 if "cultivation_site" in location.tags else 2
        actor.stamina -= self.CULTIVATE_COST
        before_stage = actor.cultivation_stage
        actor.cultivation_progress += gain
        stages = state.flags.get("cultivation_stages", ["body"])
        stage_index = stages.index(actor.cultivation_stage)
        threshold = (stage_index + 1) * 100
        breakthrough = False
        if (
            actor.cultivation_progress >= threshold
            and stage_index + 1 < len(stages)
        ):
            actor.cultivation_progress -= threshold
            actor.cultivation_stage = stages[stage_index + 1]
            actor.realm += 1
            actor.max_health += 10
            actor.max_stamina += 10
            actor.health = actor.max_health
            breakthrough = True
        actor.skill_mastery["cultivation"] = min(
            100,
            actor.skill_mastery.get("cultivation", 0) + 1,
        )
        self._increase_need(actor, "fatigue", 2)
        return "cultivation_advanced", True, {
            "stage_before": before_stage,
            "stage_after": actor.cultivation_stage,
            "progress_after": actor.cultivation_progress,
            "progress_gained": gain,
            "breakthrough": breakthrough,
            "realm_after": actor.realm,
            "stamina_after": actor.stamina,
        }, None

    def _resolve_follow_schedule(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        period = self._day_period(state, turn)
        destination_id = actor.schedule.get(period)
        if not destination_id:
            return "action_rejected", False, {}, "no scheduled destination"
        if destination_id == actor.location_id:
            return "schedule_followed", True, {
                "period": period,
                "destination_id": destination_id,
                "moved": False,
            }, None
        next_location_id = self._next_step(
            state,
            actor.location_id,
            destination_id,
        )
        if not next_location_id:
            return "action_rejected", False, {}, "scheduled destination is unreachable"
        origin_id = actor.location_id
        actor.location_id = next_location_id
        return "schedule_followed", True, {
            "period": period,
            "origin_id": origin_id,
            "destination_id": destination_id,
            "location_after": next_location_id,
            "moved": True,
        }, None

    def _resolve_wait(self, state, intent, knowledge, turn):
        actor = self._actor(state, intent)
        self._increase_need(actor, "hunger", 1)
        return "waited", True, {}, None

    def _resolve_world_tick(self, state, intent, knowledge, turn):
        previous_day = int(state.flags.get("current_day", 1))
        current_day = max(
            previous_day,
            1 + ((turn - 1) // int(state.flags.get("day_length", 24))),
        )
        state.flags["current_day"] = current_day
        village_changes = self._advance_village_pressures(state, turn)
        memory_changes = self._record_pressure_memories(state, turn)
        npc_updates = self._advance_core_npcs(state, turn)
        emergent_changes = self._advance_core_events(state, turn)
        settlement_changes = self._advance_tarrow_settlement(state, turn)
        return "world_tick_resolved", True, {
            "day": current_day,
            "period": self._day_period(state, turn),
            "village_pressure_changes": village_changes,
            "memory_events": memory_changes,
            "npc_updates": npc_updates,
            "emergent_event_changes": emergent_changes,
            "settlement_changes": settlement_changes,
        }, None

    def _resolve_unknown(self, state, intent, knowledge, turn):
        return "action_rejected", False, {}, "intent could not be interpreted"

    def _actor(self, state, intent):
        actor = state.characters.get(intent.actor_id)
        if not actor or not actor.alive or not actor.active:
            raise ValueError("actor must exist and be alive")
        return actor

    @staticmethod
    def _activate_due_entities(state, turn):
        activated = []
        for character in state.characters.values():
            if (
                not character.active
                and character.alive
                and character.spawn_turn is not None
                and turn >= character.spawn_turn
            ):
                character.active = True
                activated.append(character.id)
        return sorted(activated)

    @staticmethod
    def _regenerate_resources(state, turn):
        for node in state.resource_nodes.values():
            elapsed = turn - node.last_regen_turn
            if elapsed < node.regen_interval or node.quantity >= node.capacity:
                continue
            regenerated = elapsed // node.regen_interval
            node.quantity = min(node.capacity, node.quantity + regenerated)
            node.last_regen_turn += regenerated * node.regen_interval

    @staticmethod
    def _new_item_id(kind, turn, actor_id):
        actor_slug = actor_id.split(":", 1)[-1]
        return f"item:{kind}:{turn}:{actor_slug}"

    @staticmethod
    def _increase_need(actor, need, amount):
        if actor.needs:
            actor.needs[need] = min(100, actor.needs.get(need, 0) + amount)

    @staticmethod
    def _decrease_need(actor, need, amount):
        if actor.needs:
            actor.needs[need] = max(0, actor.needs.get(need, 0) - amount)

    @staticmethod
    def _day_period(state, turn):
        hour = turn % int(state.flags.get("day_length", 24))
        if hour < 6:
            return "night"
        if hour < 9:
            return "dawn"
        if hour < 18:
            return "day"
        return "dusk"

    @staticmethod
    def _next_step(state, origin_id, destination_id):
        if origin_id == destination_id:
            return origin_id
        queue = [(origin_id, None)]
        visited = {origin_id}
        while queue:
            location_id, first_step = queue.pop(0)
            for connected_id in sorted(
                state.locations[location_id].connections
            ):
                if connected_id in visited:
                    continue
                step = first_step or connected_id
                if connected_id == destination_id:
                    return step
                visited.add(connected_id)
                queue.append((connected_id, step))
        return None

    @classmethod
    def _advance_core_npcs(cls, state, turn):
        if not state.flags.get("core_loop"):
            return []
        period = cls._day_period(state, turn)
        updates = []
        for character in sorted(state.characters.values(), key=lambda actor: actor.id):
            if (
                character.id == state.player_id
                or not character.alive
                or not character.active
                or "hostile" in character.tags
                or not character.schedule
            ):
                continue
            origin_id = character.location_id
            cls._increase_need(character, "hunger", 1)
            cls._increase_need(character, "fatigue", 1)
            task = None
            destination_id = None
            danger_id = cls._local_hostile_id(state, character.location_id)
            if cls._should_avoid_player(state, character):
                destination_id = character.home_location_id
                task = "avoid_player"
            elif danger_id:
                destination_id = character.home_location_id
                task = "respond_to_danger"
                cls._decrease_need(character, "safety", 20)
            elif cls._should_rest(character, period):
                destination_id = character.home_location_id or character.schedule.get(period)
                task = "rest"
            else:
                destination_id = character.schedule.get(period)
                task = "follow_schedule"
            moved = False
            if destination_id and destination_id != character.location_id:
                next_location_id = cls._next_step(
                    state,
                    character.location_id,
                    destination_id,
                )
                if next_location_id:
                    character.location_id = next_location_id
                    moved = character.location_id != origin_id
            if not moved and task == "follow_schedule":
                job = cls._active_job_at_location(state, character)
                if job and period in {"dawn", "day"}:
                    task = "work"
                    cls._increase_need(character, "fatigue", 2)
                    cls._increase_need(character, "hunger", 1)
                    character.skill_mastery[job] = min(
                        100,
                        character.skill_mastery.get(job, 0) + 1,
                    )
            if task == "rest" and character.location_id == character.home_location_id:
                cls._decrease_need(character, "fatigue", 8)
                cls._increase_need(character, "safety", 5)
            updates.append({
                "actor_id": character.id,
                "period": period,
                "task": task,
                "origin_id": origin_id,
                "destination_id": destination_id,
                "location_after": character.location_id,
                "moved": moved,
                "danger_id": danger_id,
                "needs": dict(character.needs),
            })
        return updates

    @staticmethod
    def _local_hostile_id(state, location_id):
        for character in sorted(state.characters.values(), key=lambda actor: actor.id):
            if (
                character.active
                and character.alive
                and character.location_id == location_id
                and "hostile" in character.tags
            ):
                return character.id
        return None

    @staticmethod
    def _should_rest(character, period):
        return (
            period == "night"
            or character.needs.get("fatigue", 0) >= 70
            or character.needs.get("hunger", 0) >= 85
        )

    @staticmethod
    def _active_job_at_location(state, character):
        job_sites = state.flags.get("job_sites") or {}
        for job in sorted(character.jobs):
            if character.location_id in job_sites.get(job, []):
                return job
        return None

    @staticmethod
    def _should_avoid_player(state, character):
        player = state.characters[state.player_id]
        if character.location_id != player.location_id:
            return False
        if character.relationships.get(player.id, 0) < 0:
            return True
        return any(
            memory.get("actor_id") == player.id
            and memory.get("event") in {
                "player_harmed_me",
                "player_killed_ally",
                "player_stole_from_me",
                "witnessed_theft",
            }
            for memory in character.memories
        )

    @classmethod
    def _advance_core_events(cls, state, turn):
        if not state.flags.get("core_loop"):
            return []
        changes = []
        events = state.flags.setdefault("emergent_events", {})
        pressures = state.flags.setdefault("world_pressures", {})
        supply_event = events.get("core_supply_shortage")
        if turn >= 2 and not supply_event:
            supply_event = {
                "event_id": "core_supply_shortage",
                "kind": "resource_shortage",
                "status": "active",
                "trigger_turn": turn,
                "deadline_turn": turn + 4,
                "requester_id": "char:worker",
                "location_id": "loc:camp",
                "resource_node_id": "resource:field_supplies",
                "requested_item_kind": "supplies",
            }
            events["core_supply_shortage"] = supply_event
            pressure = pressures.get("camp_supply_shortage")
            if pressure:
                pressure["severity"] = max(int(pressure.get("severity", 0)), 35)
            cls._append_core_rumor(
                state,
                {
                    "turn": turn,
                    "event": "worker_requests_supply_help",
                    "subject_id": "char:worker",
                    "origin_location_id": "loc:camp",
                    "confidence": 0.9,
                },
            )
            worker = state.characters.get("char:worker")
            if worker and worker.alive:
                cls._append_memory(worker, {
                    "turn": turn,
                    "event": "requested_supply_help",
                    "resource_kind": "supplies",
                    "deadline_turn": supply_event["deadline_turn"],
                })
            changes.append({
                "event_id": "core_supply_shortage",
                "change": "triggered",
                "kind": "resource_shortage",
                "requester_id": "char:worker",
                "deadline_turn": supply_event["deadline_turn"],
            })
            cls._record_core_event_history(
                state,
                turn,
                "core_supply_shortage",
                "triggered",
            )
        danger_event = events.get("field_danger_tracks")
        if turn >= 4 and not danger_event:
            danger_event = {
                "event_id": "field_danger_tracks",
                "kind": "danger",
                "status": "active",
                "trigger_turn": turn,
                "location_id": "loc:field",
            }
            events["field_danger_tracks"] = danger_event
            field = state.locations.get("loc:field")
            if field:
                field.danger = max(field.danger, 1)
            pressure = pressures.get("field_danger")
            if pressure:
                pressure["severity"] = max(int(pressure.get("severity", 0)), 30)
            cls._append_core_rumor(
                state,
                {
                    "turn": turn,
                    "event": "tracks_seen_near_field",
                    "subject_id": "char:hostile",
                    "origin_location_id": "loc:field",
                    "confidence": 0.65,
                },
            )
            changes.append({
                "event_id": "field_danger_tracks",
                "change": "triggered",
                "kind": "danger",
                "location_id": "loc:field",
            })
            cls._record_core_event_history(
                state,
                turn,
                "field_danger_tracks",
                "triggered",
            )
        supply_event = events.get("core_supply_shortage")
        if (
            supply_event
            and supply_event.get("status") == "active"
            and turn >= int(supply_event.get("deadline_turn", 0))
        ):
            supply_event["status"] = "ignored"
            supply_event["resolved_turn"] = turn
            pressure = pressures.get("camp_supply_shortage")
            if pressure:
                pressure["severity"] = min(
                    100,
                    int(pressure.get("severity", 0)) + 35,
                )
            worker = state.characters.get("char:worker")
            if worker and worker.alive:
                worker.health = max(1, worker.health - 5)
                cls._append_memory(worker, {
                    "turn": turn,
                    "event": "supply_shortage_ignored",
                    "event_id": "core_supply_shortage",
                })
            changes.append({
                "event_id": "core_supply_shortage",
                "change": "ignored",
                "kind": "consequence",
                "pressure_after": (
                    pressures.get("camp_supply_shortage") or {}
                ).get("severity"),
            })
            cls._record_core_event_history(
                state,
                turn,
                "core_supply_shortage",
                "ignored",
            )
        return changes

    @classmethod
    def _resolve_core_gather_events(cls, state, actor, node, turn):
        if not state.flags.get("core_loop") or actor.id != state.player_id:
            return []
        events = state.flags.get("emergent_events") or {}
        supply_event = events.get("core_supply_shortage")
        if (
            node.id != "resource:field_supplies"
            or not supply_event
            or supply_event.get("status") != "active"
        ):
            return []
        supply_event["status"] = "resolved"
        supply_event["resolved_turn"] = turn
        supply_event["resolved_by"] = actor.id
        pressures = state.flags.get("world_pressures") or {}
        pressure = pressures.get("camp_supply_shortage")
        if pressure:
            pressure["severity"] = max(0, int(pressure.get("severity", 0)) - 25)
        worker = state.characters.get("char:worker")
        if worker and worker.alive:
            cls._append_memory(worker, {
                "turn": turn,
                "event": "player_answered_supply_request",
                "actor_id": actor.id,
                "event_id": "core_supply_shortage",
            })
            before = worker.relationships.get(actor.id, 0)
            worker.relationships[actor.id] = min(100, before + 10)
        cls._append_core_rumor(
            state,
            {
                "turn": turn,
                "event": "supplies_recovered",
                "subject_id": actor.id,
                "origin_location_id": actor.location_id,
                "confidence": 0.85,
            },
        )
        cls._record_core_event_history(
            state,
            turn,
            "core_supply_shortage",
            "resolved",
        )
        return [{
            "event_id": "core_supply_shortage",
            "change": "resolved",
            "kind": "player_intervention",
            "pressure_after": (pressure or {}).get("severity"),
        }]

    @staticmethod
    def _append_core_rumor(state, rumor):
        rumors = state.flags.setdefault("rumors", [])
        key = (
            rumor.get("event"),
            rumor.get("subject_id"),
            rumor.get("origin_location_id"),
        )
        if any(
            (
                existing.get("event"),
                existing.get("subject_id"),
                existing.get("origin_location_id"),
            ) == key
            for existing in rumors
        ):
            return
        rumors.append(rumor)
        state.flags["rumors"] = rumors[-8:]

    @staticmethod
    def _record_core_event_history(state, turn, event_id, change):
        history = state.flags.setdefault("event_history", [])
        history.append({
            "turn": turn,
            "event_id": event_id,
            "change": change,
        })
        state.flags["event_history"] = history[-16:]

    @staticmethod
    def _update_world_pressures_after_attack(state, actor, target):
        if target.alive:
            return {}
        pressures = state.flags.get("world_pressures", {})
        changes = {}
        if target.id == "char:malformed" and "malformed_corruption" in pressures:
            pressure = pressures["malformed_corruption"]
            before = pressure["severity"]
            pressure["severity"] = 0
            changes["malformed_corruption"] = {
                "before": before,
                "after": 0,
            }
        if "bandit" in target.tags and "hollow_hand_raids" in pressures:
            pressure = pressures["hollow_hand_raids"]
            before = pressure["severity"]
            pressure["severity"] = max(0, before - 8)
            changes["hollow_hand_raids"] = {
                "before": before,
                "after": pressure["severity"],
            }
        if (
            actor.faction_id == "faction:hollow_hand"
            and target.faction_id == "faction:willow_council"
            and "hollow_hand_raids" in pressures
        ):
            pressure = pressures["hollow_hand_raids"]
            before = pressure["severity"]
            pressure["severity"] = min(100, before + 5)
            changes["hollow_hand_raids"] = {
                "before": before,
                "after": pressure["severity"],
            }
        return changes

    @classmethod
    def _record_core_attack_consequences(cls, state, actor, target, turn, damage):
        if not state.flags.get("core_loop") or actor.id != state.player_id:
            return {}
        if damage <= 0:
            return {}
        memory_events = []
        relationship_changes = {}
        faction_reputation_changes = {}

        if "hostile" in target.tags and not target.alive:
            event = "player_removed_hostile"
            beneficiaries = [
                character
                for character in state.characters.values()
                if (
                    character.active
                    and character.alive
                    and character.id != actor.id
                    and "hostile" not in character.tags
                )
            ]
            for beneficiary in beneficiaries:
                cls._append_memory(
                    beneficiary,
                    {
                        "turn": turn,
                        "event": event,
                        "actor_id": actor.id,
                        "target_id": target.id,
                    },
                )
                memory_events.append({
                    "actor_id": beneficiary.id,
                    "event": event,
                })
                before = beneficiary.relationships.get(actor.id, 0)
                after = min(100, before + 15)
                beneficiary.relationships[actor.id] = after
                relationship_changes[beneficiary.id] = {
                    "before": before,
                    "after": after,
                }
            faction_ids = sorted({
                beneficiary.faction_id
                for beneficiary in beneficiaries
                if beneficiary.faction_id
            })
            for faction_id in faction_ids:
                before = actor.reputation.get(faction_id, 0)
                after = min(100, before + 10)
                actor.reputation[faction_id] = after
                faction_reputation_changes[faction_id] = {
                    "before": before,
                    "after": after,
                }
        elif "hostile" not in target.tags:
            event = "player_killed_npc" if not target.alive else "player_harmed_me"
            cls._append_memory(
                target,
                {
                    "turn": turn,
                    "event": event,
                    "actor_id": actor.id,
                    "target_id": target.id,
                    "damage": damage,
                },
            )
            memory_events.append({
                "actor_id": target.id,
                "event": event,
            })
            before = target.relationships.get(actor.id, 0)
            penalty = 50 if not target.alive else 20
            after = max(-100, before - penalty)
            target.relationships[actor.id] = after
            relationship_changes[target.id] = {
                "before": before,
                "after": after,
            }
            if target.faction_id:
                before = actor.reputation.get(target.faction_id, 0)
                penalty = 35 if not target.alive else 15
                after = max(-100, before - penalty)
                actor.reputation[target.faction_id] = after
                faction_reputation_changes[target.faction_id] = {
                    "before": before,
                    "after": after,
                }
        if not memory_events and not relationship_changes and not faction_reputation_changes:
            return {}
        return {
            "memory_events": memory_events,
            "relationship_changes": relationship_changes,
            "faction_reputation_changes": faction_reputation_changes,
        }

    @staticmethod
    def _append_memory(character, memory):
        character.memories.append(memory)
        character.memories = character.memories[-8:]

    @staticmethod
    def _update_game_state_after_attack(state, actor, target):
        if not state.flags.get("core_loop"):
            return {}
        if target.alive:
            return {
                "game_over": bool(state.flags.get("game_over")),
                "victory": bool(state.flags.get("victory")),
                "defeat": bool(state.flags.get("defeat")),
            }
        if target.id == state.player_id:
            state.flags["game_over"] = True
            state.flags["defeat"] = True
            state.flags["victory"] = False
        elif actor.id == state.player_id and "hostile" in target.tags:
            living_hostiles = [
                character
                for character in state.characters.values()
                if character.active and character.alive and "hostile" in character.tags
            ]
            if not living_hostiles:
                state.flags["game_over"] = True
                state.flags["victory"] = True
                state.flags["defeat"] = False
        return {
            "game_over": bool(state.flags.get("game_over")),
            "victory": bool(state.flags.get("victory")),
            "defeat": bool(state.flags.get("defeat")),
        }

    @staticmethod
    def _actor_combat_state(state, actor_id):
        combat_state = state.flags.setdefault("combat_state", {})
        return combat_state.setdefault(actor_id, {})

    @classmethod
    def _cooldown_ready(cls, state, actor_id, action, turn):
        combat = (state.flags.get("combat_state") or {}).get(actor_id, {})
        cooldowns = combat.get("cooldowns", {})
        return int(cooldowns.get(action, 0)) < turn

    @classmethod
    def _set_cooldown(cls, state, actor_id, action, ready_after_turn):
        combat = cls._actor_combat_state(state, actor_id)
        cooldowns = combat.setdefault("cooldowns", {})
        cooldowns[action] = int(ready_after_turn)

    @classmethod
    def _consume_guard(cls, state, actor_id, turn):
        combat = cls._actor_combat_state(state, actor_id)
        guard = combat.get("guard")
        expires = int(combat.get("guard_expires_turn", -1))
        combat.pop("guard", None)
        combat.pop("guard_expires_turn", None)
        if expires < turn:
            return None
        return guard

    @classmethod
    def _advance_tarrow_settlement(cls, state, turn):
        if state.flags.get("scenario_id") != "tarrow_aftermath":
            return []
        settlements = state.flags.get("settlements") or {}
        settlement = settlements.get("settlement:tarrow")
        if not settlement:
            return []
        before = cls._settlement_snapshot(settlement)
        pressures = state.flags.get("village_pressures") or {}
        food = int(pressures.get("food", settlement.get("resources", {}).get("food", 0)))
        medicine = int(pressures.get("medicine", settlement.get("resources", {}).get("medicine", 0)))
        fear = int(pressures.get("fear", 0))
        rumors = int(pressures.get("malformed_rumors", 0))
        trust = int(pressures.get("trust_in_ren", 0))
        guards = [
            state.characters[actor_id]
            for actor_id in settlement.get("guards", [])
            if actor_id in state.characters
            and state.characters[actor_id].alive
            and state.characters[actor_id].active
        ]
        civilians = [
            state.characters[actor_id]
            for actor_id in settlement.get("civilians", [])
            if actor_id in state.characters
            and state.characters[actor_id].alive
            and state.characters[actor_id].active
        ]
        guard_score = min(100, len(guards) * 8 + trust // 2)
        hostility = max(fear, rumors)
        safety = max(0, min(100, guard_score + medicine // 3 - hostility // 2))
        prosperity = max(0, min(100, (food + medicine) // 2 - fear // 4))
        fled = 0
        if food < 25:
            fled += 3
        if fear > 82:
            fled += 3
        if food < 15:
            fled += 5
        wounded = 2 + (2 if medicine < 25 else 0) + (1 if fear > 80 else 0)
        population = settlement.setdefault("population", {})
        population["guard"] = len(guards)
        population["civilian"] = len(civilians)
        population["dead"] = max(int(population.get("dead", 1)), 1)
        population["fled"] = max(int(population.get("fled", 0)), fled)
        population["wounded"] = min(len(civilians), wounded)
        population["present"] = max(
            0,
            len(guards) + len(civilians) - int(population.get("fled", 0)),
        )
        population["total"] = (
            population["present"]
            + int(population.get("fled", 0))
            + int(population.get("dead", 0))
        )
        resources = settlement.setdefault("resources", {})
        resources["food"] = food
        resources["medicine"] = medicine
        resources["coin"] = state.factions["faction:tarrow_village"].treasury
        settlement["defense_level"] = guard_score
        settlement["hostility_level"] = hostility
        settlement["safety_level"] = safety
        settlement["prosperity"] = prosperity
        if population["present"] <= 8:
            settlement["status"] = "abandoned"
        elif safety >= 55 and prosperity >= 35:
            settlement["status"] = "improved"
        elif guard_score >= 55:
            settlement["status"] = "defended"
        elif prosperity < 25:
            settlement["status"] = "poor"
        else:
            settlement["status"] = "strained"
        locations = settlement.setdefault("location_states", {})
        locations["loc:shrine_road"] = (
            "restored"
            if rumors < 55 and trust >= 55
            else "damaged"
        )
        locations["loc:low_fields"] = (
            "abandoned"
            if food < 18
            else ("poor" if food < 32 else "working")
        )
        locations["loc:healer_hut"] = (
            "poor"
            if medicine < 25
            else ("restored" if medicine >= 40 else "strained")
        )
        locations["loc:watch_post"] = (
            "defended"
            if guard_score >= 50
            else ("damaged" if fear > 80 else "strained")
        )
        locations["loc:tarrow_square"] = (
            "abandoned"
            if settlement["status"] == "abandoned"
            else ("improved" if settlement["status"] == "improved" else "strained")
        )
        shops = settlement.setdefault("shops", {})
        if "blacksmith" in shops:
            shops["blacksmith"]["status"] = (
                "closed" if settlement["status"] == "abandoned" else "open"
            )
        if "healer" in shops:
            shops["healer"]["status"] = (
                "strained" if medicine < 35 else "open"
            )
        workplaces = settlement.setdefault("workplaces", {})
        if "fields" in workplaces:
            workplaces["fields"]["status"] = locations["loc:low_fields"]
        if "watch" in workplaces:
            workplaces["watch"]["status"] = locations["loc:watch_post"]
        changes = cls._settlement_changes(before, cls._settlement_snapshot(settlement))
        if changes:
            cls._record_settlement_history(settlement, turn, changes)
        return changes

    @classmethod
    def _apply_tarrow_work_settlement_effect(cls, state, actor, job_id, turn):
        if state.flags.get("scenario_id") != "tarrow_aftermath":
            return []
        settlement = (state.flags.get("settlements") or {}).get("settlement:tarrow")
        if not settlement:
            return []
        changes = []
        locations = settlement.setdefault("location_states", {})
        if job_id == "carpenter":
            damaged = next(
                (
                    location_id
                    for location_id, status in sorted(locations.items())
                    if status == "damaged"
                ),
                None,
            )
            if damaged:
                before = locations[damaged]
                locations[damaged] = "restored"
                settlement["prosperity"] = min(
                    100,
                    int(settlement.get("prosperity", 0)) + 5,
                )
                changes.append({
                    "field": f"location_states.{damaged}",
                    "before": before,
                    "after": "restored",
                })
        elif job_id in {"guard", "warden"}:
            before = int(settlement.get("defense_level", 0))
            settlement["defense_level"] = min(100, before + 3)
            settlement["safety_level"] = min(
                100,
                int(settlement.get("safety_level", 0)) + 2,
            )
            changes.append({
                "field": "defense_level",
                "before": before,
                "after": settlement["defense_level"],
            })
        if changes:
            cls._record_settlement_history(settlement, turn, changes, actor.id)
        return changes

    @staticmethod
    def _settlement_snapshot(settlement):
        return {
            "status": settlement.get("status"),
            "resources": dict(settlement.get("resources") or {}),
            "safety_level": settlement.get("safety_level"),
            "hostility_level": settlement.get("hostility_level"),
            "defense_level": settlement.get("defense_level"),
            "prosperity": settlement.get("prosperity"),
            "population": dict(settlement.get("population") or {}),
            "location_states": dict(settlement.get("location_states") or {}),
            "shops": {
                key: value.get("status")
                for key, value in (settlement.get("shops") or {}).items()
            },
            "workplaces": {
                key: value.get("status")
                for key, value in (settlement.get("workplaces") or {}).items()
            },
        }

    @staticmethod
    def _settlement_changes(before, after):
        changes = []
        for field in ("status", "safety_level", "hostility_level", "defense_level", "prosperity"):
            if before.get(field) != after.get(field):
                changes.append({
                    "field": field,
                    "before": before.get(field),
                    "after": after.get(field),
                })
        for group in ("resources", "population", "location_states", "shops", "workplaces"):
            keys = sorted(set(before.get(group, {})) | set(after.get(group, {})))
            for key in keys:
                old = before.get(group, {}).get(key)
                new = after.get(group, {}).get(key)
                if old != new:
                    changes.append({
                        "field": f"{group}.{key}",
                        "before": old,
                        "after": new,
                    })
        return changes

    @staticmethod
    def _record_settlement_history(settlement, turn, changes, actor_id=None):
        history = settlement.setdefault("history", [])
        for change in changes:
            entry = {
                "turn": turn,
                "field": change["field"],
                "before": change.get("before"),
                "after": change.get("after"),
            }
            if actor_id:
                entry["actor_id"] = actor_id
            history.append(entry)
        settlement["history"] = history[-24:]

    @staticmethod
    def _advance_village_pressures(state, turn):
        pressures = state.flags.get("village_pressures")
        if not pressures:
            return {}
        before = dict(pressures)
        grain = state.resource_nodes.get("resource:tarrow_grain")
        medicine = state.resource_nodes.get("resource:bitterleaf")
        grain_level = grain.quantity if grain else 5
        medicine_level = medicine.quantity if medicine else 5
        pressures["food"] = max(0, min(100, pressures["food"] + grain_level - 5))
        pressures["medicine"] = max(
            0,
            min(100, pressures["medicine"] + medicine_level - 4),
        )
        if pressures["food"] < 35:
            pressures["fear"] = min(100, pressures["fear"] + 2)
        elif pressures["food"] > 50:
            pressures["fear"] = max(0, pressures["fear"] - 1)
        if pressures["medicine"] < 30:
            pressures["fear"] = min(100, pressures["fear"] + 1)
        if turn % 24 == 0:
            pressures["malformed_rumors"] = max(
                0,
                pressures["malformed_rumors"] - 2,
            )
            if pressures["fear"] > 75:
                pressures["trust_in_ren"] = min(
                    100,
                    pressures["trust_in_ren"] + 1,
                )
        world_pressure = state.flags.get("world_pressures", {}).get(
            "resource_crisis"
        )
        if world_pressure:
            world_pressure["severity"] = max(
                0,
                min(100, 100 - pressures["food"]),
            )
        aftermath = state.flags.get("world_pressures", {}).get(
            "malformed_aftermath"
        )
        if aftermath:
            aftermath["severity"] = pressures["malformed_rumors"]
        return {
            key: {"before": before[key], "after": value}
            for key, value in pressures.items()
            if before.get(key) != value
        }

    @staticmethod
    def _record_pressure_memories(state, turn):
        if state.flags.get("scenario_id") != "tarrow_aftermath":
            return []
        pressures = state.flags.get("village_pressures", {})
        if not pressures:
            return []
        recorded = []
        if turn % 24 != 0:
            return recorded
        day = state.flags.get("current_day", 1)
        event = None
        if pressures.get("food", 100) < 25:
            event = "ration_lines_grow_longer"
        elif pressures.get("fear", 0) > 78:
            event = "night_watch_doubles"
        elif pressures.get("malformed_rumors", 0) < 55:
            event = "rumors_begin_to_thin"
        if not event:
            return recorded
        for character in state.characters.values():
            if (
                not character.alive
                or not character.active
                or "fidelity:0" in character.tags
            ):
                continue
            memory = {
                "turn": turn,
                "event": event,
                "day": day,
            }
            character.memories.append(memory)
            character.memories = character.memories[-8:]
            recorded.append(character.id)
        return sorted(recorded)

    @staticmethod
    def _equipment_power(state, character, slot):
        item_id = character.equipment.get(slot)
        item = state.items.get(item_id or "")
        return item.power if item else 0

    @staticmethod
    def _grant_experience(character, amount):
        before_level = character.level
        character.experience += amount
        while character.experience >= character.level * 100:
            character.experience -= character.level * 100
            character.level += 1
            character.max_health += 5
            character.max_stamina += 5
            character.health = min(character.max_health, character.health + 5)
            character.stamina = min(character.max_stamina, character.stamina + 5)
        return {
            "experience_gained": amount,
            "experience_after": character.experience,
            "level_before": before_level,
            "level_after": character.level,
        }

    @staticmethod
    def assert_invariants(state):
        if state.player_id not in state.characters:
            raise AssertionError("player is missing")
        if not 0 <= int(state.flags.get("twin_realm_stability", 0)) <= 100:
            raise AssertionError("realm stability is out of bounds")
        for key, character in state.characters.items():
            if key != character.id:
                raise AssertionError("character key and id disagree")
            if character.location_id not in state.locations:
                raise AssertionError(f"{character.id} has an invalid location")
            if not 0 <= character.stamina <= character.max_stamina:
                raise AssertionError(f"{character.id} has invalid stamina")
            if not 0 <= character.health <= character.max_health:
                raise AssertionError(f"{character.id} has invalid health")
            if character.alive != (character.health > 0):
                raise AssertionError(f"{character.id} has inconsistent life state")
            if character.level < 1 or character.experience < 0:
                raise AssertionError(f"{character.id} has invalid progression")
            if character.coins < 0:
                raise AssertionError(f"{character.id} has invalid currency")
            if any(not 0 <= value <= 100 for value in character.needs.values()):
                raise AssertionError(f"{character.id} has invalid needs")
            if any(
                not -100 <= value <= 100
                for value in character.reputation.values()
            ):
                raise AssertionError(f"{character.id} has invalid reputation")
            if character.faction_id and character.faction_id not in state.factions:
                raise AssertionError(f"{character.id} has invalid faction")
            if (
                character.home_location_id
                and character.home_location_id not in state.locations
            ):
                raise AssertionError(f"{character.id} has invalid home")
            if any(
                location_id not in state.locations
                for location_id in character.schedule.values()
            ):
                raise AssertionError(f"{character.id} has invalid schedule")
            if any(not 0 <= value <= 100 for value in character.skill_mastery.values()):
                raise AssertionError(f"{character.id} has invalid skill mastery")
            if any(not 0 <= value <= 100 for value in character.jobs.values()):
                raise AssertionError(f"{character.id} has invalid job rank")
            for slot, item_id in character.equipment.items():
                item = state.items.get(item_id)
                if item_id not in character.inventory:
                    raise AssertionError(f"{character.id} equipped an unowned item")
                if not item or item.slot != slot:
                    raise AssertionError(f"{character.id} has invalid equipment slot")
            if any(not -100 <= trust <= 100 for trust in character.relationships.values()):
                raise AssertionError(f"{character.id} has relationship trust out of bounds")
            for memory in character.memories:
                if not isinstance(memory, dict) or not memory.get("event"):
                    raise AssertionError(f"{character.id} has malformed memory")
                if not 0 < int(memory.get("turn", 0)) <= state.turn:
                    raise AssertionError(f"{character.id} has memory outside world history")
        for key, location in state.locations.items():
            if key != location.id:
                raise AssertionError("location key and id disagree")
            for connection in location.connections:
                if connection not in state.locations:
                    raise AssertionError(f"{location.id} has an invalid connection")
                if location.id not in state.locations[connection].connections:
                    raise AssertionError(
                        f"{location.id} has a one-way connection to {connection}"
                    )
        for key, faction in state.factions.items():
            if key != faction.id or faction.headquarters_id not in state.locations:
                raise AssertionError("faction registry is invalid")
            if faction.treasury < 0:
                raise AssertionError(f"{faction.id} has invalid treasury")
            if any(
                other_id not in state.factions or not -100 <= relation <= 100
                for other_id, relation in faction.relations.items()
            ):
                raise AssertionError(f"{faction.id} has invalid relations")
        for key, node in state.resource_nodes.items():
            if key != node.id or node.location_id not in state.locations:
                raise AssertionError("resource registry is invalid")
            if not 0 <= node.quantity <= node.capacity:
                raise AssertionError(f"{node.id} has invalid quantity")
        for pressure_id, pressure in state.flags.get(
            "world_pressures", {}
        ).items():
            if not 0 <= int(pressure.get("severity", -1)) <= 100:
                raise AssertionError(f"{pressure_id} has invalid severity")
            if any(
                location_id not in state.locations
                for location_id in pressure.get("affected_locations", [])
            ):
                raise AssertionError(f"{pressure_id} has invalid locations")
        known_items = set(state.flags.get("item_ids", []))
        if known_items != set(state.items):
            raise AssertionError("item catalog and item registry disagree")
        item_locations = {}
        for character in state.characters.values():
            for item_id in character.inventory:
                item_locations.setdefault(item_id, []).append(f"inventory:{character.id}")
        for location_id, items in state.ground_items.items():
            if location_id not in state.locations:
                raise AssertionError(f"ground items have invalid location {location_id}")
            for item_id in items:
                item_locations.setdefault(item_id, []).append(f"ground:{location_id}")
        if set(item_locations) != known_items:
            missing = sorted(known_items - set(item_locations))
            unknown = sorted(set(item_locations) - known_items)
            raise AssertionError(f"item registry mismatch: missing={missing}, unknown={unknown}")
        duplicates = {
            item_id: holders
            for item_id, holders in item_locations.items()
            if len(holders) != 1
        }
        if duplicates:
            raise AssertionError(f"items must have exactly one location: {duplicates}")
        return True

    @staticmethod
    def state_digest(state):
        payload = json.dumps(state.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
