# M3 independent adversarial review

Status: **the final core source passes independent review, 119 unit tests, 23 core NeoForge GameTests, two real-FTB GameTests, and a separately verified production-loader smoke probe against the official ATM10 8.2 server pack. No remaining blocking production issue was found within those bounded scopes.** The smoke probe establishes loading, knowledge extraction and truthful empty-inventory planning, not strategic advice quality or positive execution of a pack recipe. No M3 actual ATM10 graphical-client or survival-world playtest has been performed. Earlier M2 full-pack results do not verify M3.

The test/verifier agent wrote the independent unit and runtime regressions and this report, but no production implementation. Review covered the deterministic planner, per-operation input selection, live vanilla station observation, execution assessment, staged recipe indexing and invalidation, planning service, and command output. Tests operate only in disposable headless worlds. No M3 test touches the user's CurseForge instance or survival world.

## Correctness findings and resolutions

1. **Mixed manufactured tag members.** The earlier planner could combine already-owned alternatives, but manufactured the remaining grouped demand through one preferred item. Two units from `{A,B}`, with only enough resources to manufacture one A and one B, could incorrectly appear blocked. The revised bounded search explores mixed manufacturing and records exact member counts per ingredient position. An independent regression requires the feasible mixed result and verifies that upstream raw inputs are not mislabeled as the direct recipe ingredients.
2. **An expensive first route could exhaust the shared search budget.** Root alternatives now receive independent shares of the same global node budget, and retained candidates preserve root-route diversity. A regression places an expensive branch before a later route whose input is already owned, requires the latter to survive, and preserves the 768-node limit. This improves fairness; it does not establish optimal planning.
3. **Whole-batch allocations did not identify an actual next operation.** Detached steps now record per-position member quantities across the selected batch. The pure selector validates that provenance and chooses one currently owned operation using only those selected members. It rejects malformed counts, mismatched recipe/output identity, unavailable inventory, and excessive search. A separate 2,744-case feasibility oracle checks overlapping selected-member sets without duplicating the implementation's algorithm.
4. **Recipe count alone cannot detect stale knowledge.** A recipe table can be replaced with the same count and IDs but different definitions. Runtime knowledge now checks the pinned RecipeManager's immutable definition-table identity, in addition to manager identity and count, before serving or advancing a job. An isolated fixture replaces the table, requires stale/pending knowledge to become unavailable, tests cancellation and publication of only the new generation, then restores the original table and rebuilds in `finally`.
5. **Station sessions needed stronger freshness checks.** A session now requires the same logical server thread, ServerLevel identity, recipe manager, game tick, and unchanged main-inventory stacks. The runtime fixture rejects same-tick inventory mutation and off-thread access. A session is command-local, not a cache retained across ticks.
6. **Spectators, dead players, disabled feature outputs, and oversized results could create false readiness.** The research agent identified and corrected these guards. Runtime fixtures require dead/spectator operations to stay unavailable and a 65-item stone smelting result to fail even when the output slot is empty. The feature fixture asserts behavior against the real world's flags. Its first run incorrectly assumed the Bundle feature was disabled; NeoForge's GameTest world enables it, so 22 other tests passed and this new fixture failed. The correction respects the actual enabled flag. The disabled-output branch is source-reviewed but is not runtime-exercised by this all-features harness; no reflection or feature-state modification is used.
7. **Fuel must not consume reserved materials.** The live service protects the actual selected cooking-input stack and all original inventory reserved by the material path. It reads actual runtime burn hooks and component-sensitive fuel-slot compatibility. Tests cover a physically present but entirely reserved fuel item, incompatible component-slot evidence, existing station heat, one new fuel ignition, and many short-burning items that do not satisfy the supported one-ignition model.
8. **Unavailable allocation evidence was being called a known material shortage.** A final root review distinguished `available`, `missing`, `unavailable` and `limited` input-selection results. Only a validated capacity deficit or exhausted complete allocation search becomes execution `blocked`; missing/malformed provenance remains `unknown`. A focused test passes present inventory with absent provenance, then valid provenance with absent inventory, and requires the different outcomes. Contradictory status flags are rejected. The prior absent-input fixture now explicitly denotes `missing`, preserving its original assertion.

## Verification design

The final frozen suite passes 119 unit tests, 23 core NeoForge GameTests, and the two existing real-FTB GameTests. All 93 earlier unit assertions and 14 earlier core scenarios retain their meaning. Version assertions advance only where the actual schema advances. The existing two FTB scenarios continue to exercise published APIs, real quest/task models, and current team semantics.

The new pure tests cover shape/duration metadata, immutable execution observations, unknown-versus-empty semantics, one-operation provenance, station/unlock/access gates, blocked input/output, the next-tick heat decrement, fuel reservations, uncertainty in recipe predicates, campfire conditions, candidate ranking, and already-owned goals. The M1 allocation and M2 planner oracles remain intact.

The nine new core runtime scenarios exercise:

- Actual sparse 1x3/3x1 and 2x2 shaped recipes, shapeless grid fits, and a nondefault cooking duration.
- Real player inventory, furnace slots, runtime fuel hooks, typed timer extraction, incompatible/full output, reserved fuel, and observation without inventory or furnace mutation.
- A shared eight-station deep-inspection budget across repeated candidate captures.
- Unloaded nearby chunks remaining unknown without forcing a chunk load.
- Same-tick inventory staleness, off-thread rejection, cooperative timeout, and malformed timer types.
- Dead and spectator operation rejection.
- Identical recipe facts and lookups across one-nanosecond slices, ordinary slices, and reversed input order; building results are unavailable.
- Same-count definition replacement, job cancellation, output-capacity/feature guards, and cleanup of the temporary recipe table.
- End-to-end PlanningService selection of the real cobblestone-to-stone recipe, a real furnace and coal, exact one-operation inputs, no default quest observation, timing fields, unchanged inventories, and bounded non-operator `/companion stations` output.

Semantic station fixtures inject a fixed clock into the same production service so JVM warm-up does not randomly hide required evidence. A separate advancing-clock fixture proves timeout behavior. Production still uses its real cooperative ten-millisecond budget. The end-to-end fixture exports `evidence/m3-cooking-plan.json`; these coordinates and inventories belong to its disposable test world.

## Source review conclusions

Material feasibility and observed execution conditions remain separate. Main inventory is the only owned material source. Nearby station contents are observed but never added to the player's resource ledger. A selected material path is hypothetical until its prerequisites are satisfied; an assessed first operation does not certify the whole path.

Grid dimensions, recipe unlock checks, cooking duration, input predicates, unique runtime recipe matching, result-stack compatibility, fuel hooks, vanilla reach/interaction checks, and lock checks come from the pinned Minecraft/NeoForge APIs. The observer recognizes exact supported vanilla blocks and recipe classes. Unsupported custom machines or predicates do not fall back to a vanilla assumption.

Furnace assessment requires an empty input slot and compatible result space. It discounts existing burn time by the next tick, then allows at most one additional fuel ignition. Existing occupied work is not taken over or treated as owned output. A campfire requires a matching unique recipe, a lit dry block and a free slot; its result is explicitly described as dropping into the world. No command moves items, fuels a machine, crafts, walks, changes a world block, or starts automation.

Recipe work is staged across server ticks, with bounded counts per phase and cooperative time slices. Commands do not rebuild the index. Building, failed and stale generations are unavailable; canceled jobs cannot publish over a newer generation. Detaching and publishing immutable DTOs avoids background access to live world objects. Full-pack source volume and individual mod callbacks can still exceed a desired wall-clock slice.

Default material/execution planning no longer automatically runs a quest scan. Explicit quest-aware commands retain the separate bounded integration. Stage timings distinguish material search, execution observation and optional quest work. Existing goals remain private world SavedData; debug exports remain bounded server-local files. No external AI, credentials, networking client or automatic state transmission has been added.

## Remaining limits and acceptance scope

- `observed_conditions_met` is conditional advice for one operation, not a guarantee that interaction will succeed. Modded claims/hooks, line of sight, safe travel, GUI access and later changes remain explicitly unverified.
- Overlapping crafting recipes are not resolved by a live crafting-grid simulation. The user must check the output preview before crafting; execution observations explicitly retain this uncertainty. Cooking does perform the bounded uniqueness check for its actual input and type.
- The local scan is a radius-eight cube, considers loaded chunks only, retains 32 nearby stations, deeply inspects at most eight, and shares at most 4,096 recipe predicate calls and one cooperative time budget across the request. A partial scan cannot prove no station exists.
- Only exact supported vanilla crafting/cooking execution is modeled. AE2/Mekanism machines, energy networks, storage ownership, fluids and full machine automation remain unavailable.
- One-ignition fuel support intentionally does not schedule a sequence of short-burning items, container remainders, byproducts, or fuel for a whole dependency chain. Station output is never credited as player-owned.
- Bounded material search, recipe retention and alternative limits can miss feasible or better paths. Unindexed output routes remain unknown, and recipe tags are OR alternatives, not jointly required item lists.
- Arbitrary mutation inside an existing recipe object without replacing its table is not detected by the pinned O(1) freshness check. Supported reload/table replacement is detected.
- Unit and headless tests do not establish M3 full-pack responsiveness or a graphical-client experience. Any later ATM10 test must use a separate disposable instance/world or a closed-world copy, never the user's active survival world.

## Independently inspected core evidence

The verifier inspected the final `m3-verification-final.log` and all 17 current JUnit XML reports: 119 tests, zero failures and zero errors. The clean combined run includes `clean build runGameTestServer runQuestTestServer packTestJar --console=plain`; the log ends `BUILD SUCCESSFUL in 1m 29s`, with all 21 tasks executed. Core runtime completed 23/23 tests in 5.967 seconds; optional FTB runtime completed 2/2 in 1.868 seconds. The earlier feature-fixture failure is retained separately as `m3-feature-fixture-failure.log` and is explained above. The prior 118-test pass is retained as `m3-verification-before-input-status.log`; it is not substituted for this final run.

Core startup indexed 1,294 definitions across 842 outputs in 25 slices: 102 active ms, 1,265 elapsed ms and a measured maximum six-ms slice. The two 600-definition scheduling fixtures produced identical facts using 1,805 tiny slices and ten normal slices. The retained budget regression still passed with 4,001 definitions, 199,941 alternatives and 399,946 identities in both source orders; those runs measured maximum slices of 15 and nine ms. One actual reload measured a 19-ms slice, demonstrating why the five-ms target is explicitly cooperative rather than a hard maximum. The two actual datapack reloads published new generations; the separate replacement/cancellation fixture advanced generations without exposing stale definitions.

The verifier also inspected `run-gametest/evidence/m3-cooking-plan.json`: schema 2, one owned cobblestone, no missing materials, the actual `minecraft:stone` smelting route, one operation with `observed_conditions_met`, one coal reservation with 1,600 runtime burn ticks, real empty furnace slots and compatible output, and an explicitly unrequested quest context. The observation scanned 4,913 loaded positions, inspected one furnace and evaluated 71 predicates. The fixture independently checks that observation and planning did not change the player inventory or furnace. No furnace operation was automatically executed.

These measurements are from Minecraft 1.21.1 / NeoForge 21.1.251 with Companion 0.3.0 in disposable headless worlds. The optional FTB run loaded Quests 2101.1.36, Library 2101.1.36, Teams 2101.1.11 and Architectury 13.0.11. They are not full-pack performance estimates.

## Optional full-pack probe

`src/packtest` contains a separate development-only `atm_companion_packtests` mod, excluded from normal core tests and the production JAR. Its single test waits for the actual pack's staged index, then checks manager/source counts, schema, retention limits, bounded shallow station observation and actual-pack plans for three registered vanilla goals. The disposable player's inventory is empty: no route, ownership, execution readiness or quest observation is invented to make the probe pass. Detailed statuses may legitimately be blocked, unsupported or search-limited. A bounded summary writes to `evidence/m3-atm10-smoke.json` without copying pack recipes or modifying the recipe manager.

The first optional development-loader attempt failed during pack mod construction, before the probe ran. `m3-atm10-smoke.log` identifies Formations 1.0.4's `FormationsDev.initDevTools` attempting to load client `Screen` on `DEDICATED_SERVER`. No smoke JSON was produced. The Gradle process nevertheless ended `BUILD SUCCESSFUL`; that exit status is **not** treated as runtime verification. This is separate from the earlier feature-flag fixture correction.

The verifier inspected the generated `build/moddev/packTestServerRunVmArgs.txt` and `packTestServerRunProgramArgs.txt`. The development launch uses `forgeserverdev` plus:

```text
-Dneoforge.enableGameTest=true
-Dneoforge.gameTestServer=true
-Dneoforge.enabledGameTestNamespaces=atm_companion_packtests
```

Those flags cannot simply be copied to a production server launch. The pinned NeoForge 21.1.251 `GameTestHooks` source explicitly gates both `isGametestEnabled()` and `isGametestServer()` behind `!FMLLoader.isProduction()`. Production therefore disables the annotation harness regardless of these properties.

The separate test mod now provides `ProductionPackProbe`. It registers only in a production loader when JVM property `atm_companion.packSmoke=true` and a regular, non-symlink `M3-DISPOSABLE-PROBE` marker exist in the server directory. Before each action and shutdown, it rechecks the property, marker, dedicated-server state and exact server-directory match. It waits at most 6,000 server ticks for ready knowledge, writes `evidence/m3-atm10-production-smoke.json` with explicit `terminalStatus`, then calls `halt(false)` only while those guards remain true. Neither this test mod nor its automatic shutdown belongs in the production Companion JAR. A missing guard performs no probe work or shutdown.

For the separate disposable server only, after the official installer and both test/Companion JARs are in place, the production launch pattern is:

```powershell
# Current directory must be the disposable server root; never an active player instance.
New-Item -ItemType File -Path M3-DISPOSABLE-PROBE -Force
& $Java21 '-Xms512m' '-Xmx4G' '-Datm_companion.packSmoke=true' '@libraries/net/neoforged/neoforge/21.1.251/win_args.txt' '--nogui'
```

`$Java21` denotes the selected Java 21 executable. The official generated argument file supplies the production launch target. The development GameTest flags are intentionally absent. Process exit alone is insufficient: verification requires a freshly written JSON with `terminalStatus: passed`, the corresponding terminal log, actual mod/recipe counts, and no pre-probe loading failure.

### Independently verified production retry

The verifier read the freshly written 5,794-byte `runtime-m3-atm10/evidence/m3-atm10-production-smoke.json`, timestamp `2026-09-23T04:54:35.933579400Z`, and matched it to `m3-atm10-production.log`. The log records explicit probe enablement, Companion 0.3.0 initialization, `PASSED; terminal evidence written`, normal server shutdown and all dimensions saved. The JSON reports `terminalStatus: passed`, Minecraft 1.21.1 and **503 loaded runtime mods**. The source-provenance record identifies the official ATM10 **8.2** server pack; no live user instance files supplied this environment. This retry used the normal production loader, preserving Formations and the other pack mods.

Generation 1 visited all **95,229** recipe definitions and retained **50,000**, covering **40,020** output items. It retained **200,000 alternatives / 400,000 identities**, with **4,499 unknown/nonfixed outputs**, **14,662 unsupported dependencies**, and four outputs whose route lists were truncated. `indexComplete` is correctly false. Coverage names the definition limit, unknown outputs, unsupported dependencies, ingredient-retention budget and per-output route limit. The job took **811 slices, 1,663 active ms and 55,595 elapsed ms**, with a **71-ms maximum measured slice**. The statistics field measured 55,594 ms at its adjacent capture; neither value is a hard timing guarantee. These observations confirm that individual work can exceed the cooperative five-ms target.

The real-clock nearby scan exhausted its time budget after **3,514 / 4,913** loaded positions, finding no station in that inspected portion. It reports `budgetExceeded: true`; zero observed stations is not a claim that the complete neighborhood has none. No positive full-pack station readiness is established by this probe.

All three empty-inventory plans retained zero owned resources, stayed below 768 nodes, and omitted the unrequested quest scan. They also expose the current heuristic's usability limits:

| Goal | Result | Selected explanation | Expanded nodes | End-to-end time |
| --- | --- | --- | ---: | ---: |
| Diamond pickaxe | Materials unsupported; execution unknown | Inspect the opaque Aether pickaxe-repair preview | 258 | 56.8107 ms |
| Glass | Materials/execution blocked | Obtain Create framed glass for the selected smelting route | 268 | 22.4223 ms |
| Stone | Materials/execution blocked | Obtain Ice and Fire frozen stone for the selected furnace route | 391 | 27.5322 ms |

Each plan marks search truncation and partial index knowledge. These are truthful bounded search results, but the routes are not good general acquisition advice. The probe intentionally does not force a vanilla answer or weaken uncertainty merely to obtain a green result. Better acquisition modeling and candidate ranking remain future work. This result is a successful **server-pack compatibility smoke**, not a claim of optimal planning, full recipe coverage, graphical UI testing, positive pack-specific machine execution, or an actual player-world playtest.
