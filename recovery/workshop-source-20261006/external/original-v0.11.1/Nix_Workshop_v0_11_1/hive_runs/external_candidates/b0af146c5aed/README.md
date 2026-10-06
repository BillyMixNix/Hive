# ATM Companion — Milestone 3

ATM Companion reads your current game state, builds a bounded material plan for an item goal, and checks observed vanilla conditions for **one next operation**. It preserves M1 snapshots and M2 recipe knowledge, persistent goals and optional FTB team quest observations. It does not autocraft, move items, change quests, or send game state to an external service. There is no LLM or API key.

Target: **All the Mods 10 8.2 · Minecraft 1.21.1 · NeoForge 21.1.251 · 64-bit Java 21**. Companion version **0.3.2**, mod ID `atm_companion`.

**Validation:** clean build, **130 unit tests, 26 core NeoForge tests and 3 FTB tests passed**. In the user's actual ATM10 world, `/quests` and `/next` succeeded with quest collection at **29 ms and 24 ms**, and recipe indexing recovered automatically. See [the M3.2 playtest](docs/M3.2-REAL-PLAYTEST.md) and [VERIFICATION.md](VERIFICATION.md) for scope and limits. Historical [M3.1 evidence](docs/M3.1-REAL-PLAYTEST.md) is preserved.

M3.2 addresses quest command timeouts by querying only the fresh quest counts and five options needed by `/quests` and `/next`, avoiding thousands of unused task titles. It also removes repeated ID formatting/regex compilation and separates cheap integration readiness from full scans. Each request reads current team state; the cooperative 250 ms limit remains and includes final DTO validation. Detailed debug scans remain separate and may still exceed that budget on a cold large book. M3.1 startup recipe-index recovery is preserved. See [M3-ARCHITECTURE.md](M3-ARCHITECTURE.md) for behavior and limits.

The prior 0.3.0 isolated production-server probe exposed 95,229 recipe definitions, retained 50,000 and took about 56 seconds to publish. That probe did not include player login and missed this bug. Those historical measurements are not a 0.3.1 full-pack test. Empty-inventory plans can still select unhelpful repair/conversion routes; strategic acquisition advice remains limited.

## Install and try it

1. Close the instance. Replace the previous Companion JAR in `mods/` with **ATM-Companion-M3.2.jar**. Keep only one Companion version installed; do not install the source ZIP.
2. Start ATM10, enter a world and run `/companion`.
3. Run `/companion knowledge`. Indexing progresses while the server/world ticks; a large pack may take tens of seconds. Wait for a completed generation before recipe planning.
4. Try `/companion stations`, then `/companion goal minecraft:diamond_pickaxe`. Refresh with `/companion goal` after changing materials or moving near a station.

For multiplayer, Companion must run on the authoritative server. Installing it on both ends remains the recommended experimental deployment. A client-only installation cannot inspect a remote server. Core features require no optional integrations; supported FTB dependencies are not bundled.

## Commands

| Command | Behavior |
| --- | --- |
| `/companion state` | Live health, hunger, XP, location, equipment, inventory and advancement summary |
| `/companion capabilities` | Available, unavailable and unintegrated observations, with reasons |
| `/companion mods [page]` | Loaded runtime mod IDs/versions, 12 per page |
| `/companion knowledge` | Index progress or completed generation, coverage, timings and recipe types |
| `/companion recipe <namespace:item>` | Up to three routes/previews and one-operation material availability |
| `/companion stations [page]` | Nearby supported vanilla stations, five per page, with scan coverage and distance |
| `/companion goal <namespace:item> [quantity]` | Save an item goal and plan; default quantity 1, maximum 4,096 |
| `/companion goal` | Recalculate the saved goal from current inventory and observations |
| `/companion goal clear` | Remove your saved goal |
| `/companion quests` | Current FTB team counts and up to five available incomplete quests |
| `/companion next` | Explain the selected next action and include a quest option when observed |
| `/companion debug snapshot` | M1 structured raw-state JSON |
| `/companion debug plan` | Material plan, execution observations, alternatives, quest context and bounded graph |
| `/companion debug recipes <namespace:item>` | Retained normalized routes, coverage and generation |
| `/companion debug quests [page]` | Eight quests per JSON page, with chapters, tasks and progress |

Commands inspect their invoking player; the console can display help. Snapshot commands share a one-second cooldown, recipe lookup has five seconds, and knowledge/stations/planning/quest commands share two seconds. Goal clearing is immediate. **`/companion goal` does not scan quests**; `/companion next`, `/companion quests` and appropriate debug commands request quest context separately.

Debug commands require operator level 2. They replace `latest-snapshot.json`, `latest-plan.json`, `latest-recipes.json`, or `latest-quests.json` under **the server's** `config/atm_companion/`. Each export is capped at 256 KiB UTF-8; oversized reports are refused before replacing the previous export. These are shared latest files, not downloads to multiplayer clients. Snapshots include your location and inventory, so review them before sharing.

## Materials and one next operation

Material statuses remain `already_owned`, `materials_ready`, `blocked`, `unsupported` and `search_limited`. **`materials_ready` describes the selected material path, not the ability to execute the entire chain.** Separate execution statuses are `not_needed`, `observed_conditions_met`, `blocked` and `unknown`.

M3 supports exact vanilla shaped/shapeless crafting, furnace smelting, blast-furnace blasting, smoker cooking and campfire cooking. Pack recipes using those classes are discovered from the running game. Crafting checks grid fit and the actual limited-crafting unlock rule. A 3×3 recipe needs an observed table within reach; possessing a table item alone does not establish access. **Check the crafting output preview before taking it:** selection among overlapping crafting recipes remains unverified.

Cooking checks a matching live input, positive duration and a unique runtime recipe match. Furnace observations include occupied input/output slots, compatible output space, existing heat and type-specific fuel. Campfires need a lit, dry station with a free slot; their output drops into the world and recovery is not guaranteed.

The assessed input must come from the exact ingredient members selected by the material plan. Fuel cannot spend items reserved for later material steps. Furnace feasibility models current heat plus **at most one additional fuel item/ignition**. Shorter fuel sequences, queued remainders and full-chain fuel scheduling remain unknown; a stack of short-burning items is not automatically treated as sufficient. Existing station input blocks assessment of a newly loaded operation.

`observed_conditions_met` means the inspected vanilla conditions for one operation are satisfied at that snapshot. Modded claims, interaction hooks, line of sight, safe navigation and future operations remain unverified. Stations and their contents are observations, not player-owned material resources. Companion performs no interaction.

## Recipe knowledge and planning

The running recipe manager, registries and tags supply facts; ATM10 ingredient trees are not hardcoded. The index preserves original tags and alternatives as **OR choices**. Unknown custom classes, machine recipes, fluids, custom ingredient predicates, dynamic output and nondefault output components remain unsupported where their semantics are unknown. An output preview is not guaranteed production; an empty tag never becomes a barrier requirement.

Each path shares a virtual inventory, so ten iron cannot satisfy two six-iron branches without a shortage of two. Batch surplus is hypothetical and may satisfy later requirements, but never becomes observed ownership. Only main inventory slots 0–35 count. Equipment, offhand, backpacks, Curios, nested containers and storage networks are excluded. Crafting remainders/byproducts are not credited; productive loops and temporarily spending reserved goal items are not solved.

Tag requirements can use mixed members, including bounded paths that manufacture different members. Exact quantities are recorded per ingredient position. Candidate branches keep separate ledgers; the planner never edits the actual inventory.

Root recipe routes receive separate shares of a global search budget, and beam selection preserves distinct root routes before extra ingredient variants. Defaults are depth 10, 768 expansions, six routes per output, six preferred alternatives and six retained candidates. Very small custom budgets may not admit every root; any bounded search can miss a better path.

Material search prefers fewer issues, fewer missing units, shallower paths, fewer steps and greater use of original inventory, with stable tie-breaking. After execution inspection, final ranking uses issue count, missing units, execution status, depth, path length and a stable path tie-breaker. Alternatives include concrete missing-material/blocker excerpts and next actions. This is a deterministic heuristic over available facts, not strategic advice or a proof of optimality. Missing/unknown routes never establish that no route exists.

## Performance and coverage

Recipe indexing is a finite lifecycle job at server startup and completed datapack reload, including `/reload`. A login that leaves recipe data unchanged does not rebuild it. If a mod replaces the recipe manager/table or changes its count, stale facts become unavailable immediately and a fresh generation is built after 20 unchanged server ticks. Work runs in cooperative **5 ms server-tick slices**, with operation caps for selection, normalization and lookup construction. Completed generations publish atomically; old facts are unavailable during replacement. Recipe-manager/table replacement, including same-count replacement, invalidates stale knowledge. Arbitrary mutation inside an existing third-party recipe object is outside this freshness guarantee.

The index visits at most 100,000 definitions and retains at most 50,000, with 200,000 retained alternatives and 400,000 retained identities. Supported inexpensive models receive priority. Time slicing changes completion latency rather than discarding more recipes on a slow reload. `/companion knowledge` separates elapsed build time, active work, slice count and observed maximum slice duration. Partial output/ingredient coverage remains explicit.

Station requests scan only a **radius-eight cube of already-loaded positions**, retaining the nearest 32 stations. A planning request shares one cooperative **10 ms** observation budget across all candidates, at most eight detailed station inspections and 4,096 recipe predicates. Cooking uniqueness may traverse recipe-manager metadata within that budget; insufficient coverage returns unknown. No chunks are loaded for inspection. There is no continuous world scanner.

All live APIs run on the logical server thread. Cooperative budgets cannot interrupt one mod API call, fuel hook, serialization call or JVM pause. Later candidates may receive less observation evidence after the shared budget is consumed. A paused singleplayer world also pauses index progress.

## Optional FTB Quests

Supported environment: **FTB Quests 2101.1.36**, **FTB Library 2101.1.36**, **FTB Teams 2101.1.11** and **Architectury 13.0.11**, matching the inspected ATM10 8.2 instance. Other FTB Quests versions report unavailable until verified; absence is `not_integrated`. Core features continue functioning.

Observations include chapter/quest IDs, server-resolved titles, visibility, dependency references, task types/progress and current-player **team** completion/start state. Queries use existing progress and never create teams, submit tasks or claim rewards. Missing team data is unavailable, not zero completion.

Available quests must have visible chapters/quests, an unlocked team, FTB task-start permission and incomplete status. Ordering is ascending unsigned quest ID, not strategic value or quest-book layout. Completed repeatable quests are excluded; cross-chapter quest-link visibility is not modeled. Dependency edges do not invent an AND rule, and item-task references are not exact crafting requirements. Quest observation has its own cooperative 250 ms budget and bounded record counts.

Quest capability reporting checks supported APIs, the current team and existing progression only. Its detail explicitly states that the quest book and progress details were not collected. An available capability therefore indicates readiness, not that a subsequent full-book request is guaranteed to fit its time/size limits. Full scans remain fresh and log aggregate phase timings without player IDs, quest titles or progress contents.

`/companion quests` and `/companion next` inspect all bounded quest visibility/completion/start flags but resolve titles only for the first five available quests. Their overview explicitly omits task details and dependency edges; omitted graph data is marked unavailable. `/companion debug plan` and `/companion debug quests` retain full detailed observations. FTB's cold title initialization can still exhaust the full-scan budget; a timeout returns unavailable/null, never partial data labeled complete. No live progress snapshot is cached.

## State and privacy

M1 snapshot schema 1 remains: health, hunger/saturation, XP, mode, biome/dimension/coordinates, inventory/equipment, runtime mods and advancements. Advancement counts include recipe unlocks; synthetic FakePlayers have unavailable persistent advancement state. Equipment overlaps snapshot inventory and must not be counted twice. Loaded mods do not independently identify a pack version.

Available-empty data differs from unavailable/null data. Raw state, knowledge, plans, execution observations and future `AIContext` remain separate. Reports omit player names/UUIDs, credentials, server addresses, unrelated chat and filesystem contents. Goals internally use player UUIDs in world SavedData, excluded from exports. No network telemetry, external AI calls or automatic uploads are implemented.

## Build and test

Set `JAVA_HOME` to a Java 21 JDK and run from the directory containing `gradlew.bat`:

```powershell
.\gradlew.bat clean build runGameTestServer runQuestTestServer --console=plain
```

Linux/macOS: `sh ./gradlew` with the same arguments. Gradle **9.2.1**, ModDevGradle **2.0.147**, NeoForge **21.1.251** and official Mojang mappings are pinned. Initial builds download normal dependencies. The production output is `build/libs/ATM-Companion-0.3.2.jar`.

Core and FTB GameTests use separate harnesses; only the latter loads optional FTB/Architectury artifacts. Test source sets and fixtures are excluded from the production JAR. Read [VERIFICATION.md](VERIFICATION.md) for the actual gate results and their scope; compiling or passing an isolated harness does not establish a real ATM10 playtest.

## Troubleshooting and playtest

- **Unknown command:** confirm the authoritative server loaded `atm_companion` 0.3.2 and only one Companion JAR is installed.
- **Index building/recovering:** keep the world running and inspect `/companion knowledge`. Startup/reload does not immediately expose a completed index. Login-triggered recipe replacement recovers automatically; keep singleplayer unpaused. Recovery has a finite retry/change limit and reports failure if the source never settles.
- **Index failed/unavailable:** inspect the server diagnostic. A completed `/reload` schedules a fresh generation; failed work never reuses stale facts.
- **Materials ready, operation blocked/unknown:** inspect station access, unlocks, input/output occupancy, selected fuel and coverage. Check the crafting preview; modded permissions remain unverified.
- **Cooking unknown:** overlapping recipes, incomplete uniqueness checks, occupied input, short fuel sequences or exhausted inspection budgets may prevent a conclusion.
- **Unsupported recipe or limited search:** preserve its type/serializer and operator export. The retained path does not prove optimality or impossibility.
- **FTB unavailable:** inspect its version/team/API/budget reason. Unavailable observations never mean no quests.
- **Export failure:** check server write permission, disk space and size diagnostics. Files are stored on that server.

For an M3 playtest, compare the same goal away from and near a vanilla station; remove and restore fuel; test an occupied output slot; compare mixed tag allocations with the recipe viewer; and watch index progress across `/reload`. Refresh after each change. Capture `/companion knowledge` and an operator plan export when reporting discrepancies. Companion should explain what it observed and what remains unknown, while leaving every action to you.
