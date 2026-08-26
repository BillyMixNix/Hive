from __future__ import annotations

from .human_trial import CausalWorld, HumanTrial, Interaction


PILOT_WORLD_2 = CausalWorld(
    world_id="pilot-02",
    bias=-2,
    main={
        "Aster": 1,
        "Brim": 3,
        "Cinder": 2,
        "Dusk": -2,
        "Ember": 1,
        "Flux": 0,
    },
    interactions=(
        Interaction(("Aster", "Cinder"), 3),
        Interaction(("Brim", "Dusk"), -5),
        Interaction(("Ember", "Flux"), -3),
        Interaction(("Cinder", "Dusk", "Flux"), 4),
    ),
)


PILOT_TRIAL_2 = HumanTrial(
    trial_id="K0-N1-002",
    world=PILOT_WORLD_2,
    condition="structured",
    test_states=(
        {"Aster": 1, "Brim": 0, "Cinder": 1, "Dusk": 0, "Ember": 0, "Flux": 0},
        {"Aster": 0, "Brim": 1, "Cinder": 0, "Dusk": 1, "Ember": 0, "Flux": 0},
        {"Aster": 0, "Brim": 0, "Cinder": 0, "Dusk": 0, "Ember": 1, "Flux": 1},
        {"Aster": 0, "Brim": 0, "Cinder": 1, "Dusk": 1, "Ember": 0, "Flux": 1},
        {"Aster": 0, "Brim": 1, "Cinder": 1, "Dusk": 0, "Ember": 1, "Flux": 0},
        {"Aster": 1, "Brim": 0, "Cinder": 0, "Dusk": 1, "Ember": 1, "Flux": 0},
        {"Aster": 1, "Brim": 1, "Cinder": 1, "Dusk": 1, "Ember": 0, "Flux": 0},
        {"Aster": 1, "Brim": 0, "Cinder": 1, "Dusk": 1, "Ember": 1, "Flux": 1},
    ),
)
