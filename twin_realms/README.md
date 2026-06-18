# Twin Realms Simulation Slice

Twin Realms keeps world truth outside the language model:

1. `IntentInterpreter` maps player text to a constrained `ActionIntent`.
2. `WorldSimulator` validates and resolves the action deterministically.
3. `WorldEvent` records the authoritative result.
4. `NarrativeGenerator` receives only resolved facts.
5. `TwinRealmsEngine` persists snapshots and verifies them by replay.

World knowledge accumulates evidence through `WorldKnowledge`. A record has no
mechanical effect until `promote_knowledge()` is called before a run starts.

## Human Play

Start a fresh Tier 3 world with direct human control:

```powershell
.\.venv\Scripts\python.exe -m twin_realms --new --tier 3 --save saves\willow.json
```

Inside the game:

```text
look
status
inventory
actions
do 3
history
save
quit
```

You can also type natural actions such as `attack the malformed`, `move to
Willow Market`, or `talk to Elder Mara`. `actions` shows the exact currently
valid affordances; `do NUMBER` executes the selected validated intent without
language interpretation.

Resume by running the same command without `--new`.

To control the player yourself while Hive controls nearby NPCs:

```powershell
.\.venv\Scripts\python.exe -m twin_realms --new --tier 3 --mode hive_learning --npc-scope local --save saves\hive-world.json
```

If Ollama is unavailable or returns HTTP 500, use the managed local server
launcher. It starts `llama-server`, loads the existing `qwen2.5:3b` model
blob, runs the game, and stops the server when the game exits:

```powershell
powershell.exe -ExecutionPolicy Bypass -File .\scripts\play_twin_realms.ps1 -New -NpcLimit 1
```

Remove `-New` to resume the save. Increase `-NpcLimit` gradually; `0` runs
every local NPC. Use `-LlmNarration` only when model-written prose is desired.
Without it, narration remains deterministic while Hive still controls NPCs.

The direct CLI can also target any already-running OpenAI-compatible server:

```powershell
.\.venv\Scripts\python.exe -m twin_realms --tier 3 --mode hive_learning --hive-url http://127.0.0.1:11435/v1/chat/completions --hive-model qwen2.5:3b
```

Model transport failures no longer terminate play. Resolved events use
deterministic narration, NPC cognition falls back to bounded safe actions, and
the terminal reports degraded mode while saving and replay remain available.

Human control is the default. `--player-control agent` restores the autonomous
Hive-player research mode. Pass `--llm` to use Hive only for narration in
baseline mode. Simulation truth and replay never depend on the model.

In Hive modes, each scheduled NPC has a separate cognition record containing
its own visible events, observations, questions, plans, lessons, and goal.

- `--npc-scope local` runs every active NPC at the player's current location.
  This is the default playable mode.
- `--npc-scope all` runs every active NPC in the world, including remote
  actors. This is substantially more expensive.
- `--npc-limit N` caps the number of NPC minds acting each player turn.
  The default `0` applies no cap.

Use `people` in the terminal to see which nearby characters currently have an
active Hive turn. When the player talks to, attacks, trades with, or otherwise
affects an NPC, the resolved event enters that NPC's visible history before
its next decision.

Runtime modes:

```powershell
# Deterministic interpretation and simulation
.\.venv\Scripts\python.exe -m twin_realms.cli --mode baseline

# LLM intent interpretation, NPC decisions, and guarded narration
.\.venv\Scripts\python.exe -m twin_realms.cli --mode assisted

# Assisted mode plus evidence-checked knowledge proposals and promotion
.\.venv\Scripts\python.exe -m twin_realms.cli --mode adaptive

# Hive observe/investigate/plan/act cognition
.\.venv\Scripts\python.exe -m twin_realms.cli --tier 3 --mode hive --npc-limit 3

# Hive cognition plus reflection lessons
.\.venv\Scripts\python.exe -m twin_realms.cli --tier 3 --mode hive_learning --npc-limit 3
```

Complexity tiers:

```powershell
# Tier 0: original combat slice
.\.venv\Scripts\python.exe -m twin_realms.cli --tier 0

# Tier 1: peaceful village expansion and delayed malformed spawn
.\.venv\Scripts\python.exe -m twin_realms.cli --tier 1

# Tier 2: equipment, leveling, skill mastery, and jobs
.\.venv\Scripts\python.exe -m twin_realms.cli --tier 2 --mode assisted --npc-limit 3

# Tier 3: complete Willow Basin regional simulation
.\.venv\Scripts\python.exe -m twin_realms.cli --tier 3 --mode assisted --npc-limit 8
```

`npc-limit` increases model-controlled world activity gradually. Drift audits
measure replay divergence, invalid references, unavailable actors, narration
violations, action diversity, rejection rate, and repeated-action streaks.

LLM components only emit structured proposals. The simulator validates and
resolves them. Replay uses recorded intents and knowledge events and never
calls the model.

Hive cognition is stored separately in `cognition_state`. It contains actor
goals, visible events, observations, unresolved questions, plans, lesson IDs,
and phase traces. It is persisted in checkpoints but excluded from world-state
digests and deterministic replay authority.

Tier 3 provides:

- 20 persistent characters across nine connected locations
- homes, work sites, schedules, needs, currency, and relationships
- three factions with laws, treasuries, reputation, and diplomacy
- renewable herbs, timber, ore, and fishing resources
- deterministic gathering, crafting, trade, and item quality
- location-bound jobs and skill growth
- cultivation stages, progress, sanctuaries, and breakthroughs
- equipment-based attack and defense resolution
- regional rumors and world pressures that change after resolved events

All generated resources and crafted items enter the same unique-ownership
registry used by replay and invariant checking.

Run its tests with:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_twin_realms.py tests\test_twin_realms_invariants.py tests\test_twin_realms_replay.py tests\test_twin_realms_narration_guard.py tests\test_twin_realms_long_run.py -q --basetemp=.\tmp_twin_realms_tests
```

The benchmark suite covers deterministic replay, unique item ownership,
persistent witnessed-theft memories, rule enforcement, narration
contradiction fallback, checkpoint reloads, and seeded 1,000-turn chaos runs.
`test_twin_realms_ai_modes.py` covers baseline, assisted, and adaptive model
participation with reproducible fake models.
`test_twin_realms_region.py` covers the Tier 3 economy, schedules, factions,
cultivation, equipment defense, world pressures, and replay.

The first Tarrow proof is `run_tarrow_heartbeat()`: it advances the aftermath
scenario from day 1 to day 7 with world ticks only, then reports pressure
deltas, memory drift, replay consistency, and the final state digest. This is
the narrow heartbeat check for whether the village changes without the player
forcing every event.
