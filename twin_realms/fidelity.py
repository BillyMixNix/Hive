from __future__ import annotations


FIDELITY_BACKGROUND = 0
FIDELITY_SCHEDULED = 1
FIDELITY_REACTIVE = 2
FIDELITY_HIVE = 3
FIDELITY_LEADER = 4

FIDELITY_LABELS = {
    FIDELITY_BACKGROUND: "background_facts",
    FIDELITY_SCHEDULED: "schedule_needs",
    FIDELITY_REACTIVE: "local_reactive_memory",
    FIDELITY_HIVE: "hive_cognition",
    FIDELITY_LEADER: "companion_or_faction_leader",
}


def set_fidelity(character, tier):
    if not 0 <= int(tier) <= 4:
        raise ValueError("fidelity tier must be between 0 and 4")
    tags = [
        tag for tag in character.tags
        if not tag.startswith("fidelity:")
    ]
    tags.append(f"fidelity:{int(tier)}")
    character.tags = tags
    return character


def get_fidelity(character):
    for tag in character.tags:
        if tag.startswith("fidelity:"):
            return int(tag.split(":", 1)[1])
    return FIDELITY_BACKGROUND


def fidelity_label(character):
    return FIDELITY_LABELS[get_fidelity(character)]
