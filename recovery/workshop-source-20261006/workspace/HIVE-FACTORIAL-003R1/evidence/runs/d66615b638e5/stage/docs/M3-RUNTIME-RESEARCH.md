# M3 runtime API research

Researched on 22 September 2026 (host-local date). Target: ATM10 8.2, Minecraft 1.21.1, NeoForge 21.1.251, Java 21. This document records source evidence and an isolated-runtime proposal. It does not certify an M3 build, test result, or full-pack runtime run; those results belong in the milestone verification report.

## Exact source evidence

The primary local source is the generated, official-mapping Minecraft/NeoForge archive `build/moddev/artifacts/neoforge-21.1.251-sources.jar`, produced by the pinned ModDevGradle build. Its SHA-256 at inspection was `859748956c6bdd0b58c76f2d0ba153d888a761cba7422e7fe354e40f462f9a64`. NeoForm is `1.21.1-20240808.144430`. The entries and methods below were read directly from this archive; they are not assumptions copied from another Minecraft release.

| Archive entry, under `net/minecraft/` | Relevant members and evidence |
| --- | --- |
| `world/item/crafting/Recipe.java`, `ShapedRecipe.java`, `ShapelessRecipe.java` | `canCraftInDimensions`; shaped width/height, shapeless ingredient-slot count |
| `world/inventory/RecipeCraftingHolder.java` | `setRecipeUsed(Level, ServerPlayer, RecipeHolder)` checks special recipe, limited-crafting rule and player recipe-book membership before mutating the holder |
| `world/item/crafting/AbstractCookingRecipe.java` | `matches(SingleRecipeInput, Level)`, `assemble`, `getCookingTime`, `getType` |
| `world/item/crafting/RecipeManager.java` | `byKey`, `getRecipes`, `getRecipeFor`, and `createCheck` with private `lastRecipe` preference |
| `world/level/block/entity/AbstractFurnaceBlockEntity.java` | Inventory slots 0/1/2, `serverTick`, `saveAdditional`, `getBurnDuration`, `canBurn` |
| `world/level/block/entity/BlastFurnaceBlockEntity.java`, `SmokerBlockEntity.java` | Recipe-type-specific constructors; each divides superclass fuel duration by two |
| `world/level/block/entity/CampfireBlockEntity.java` | Four slots; public `getItems`; per-slot cooking/cooling loops and timer serialization |
| `world/level/block/CampfireBlock.java` | `LIT`, `WATERLOGGED`, server ticker selection, extinguishing and food placement |
| `world/level/block/entity/BlockEntity.java` | Public final `saveCustomOnly`, `saveWithoutMetadata`, `collectComponents` |
| `world/level/block/entity/BaseContainerBlockEntity.java`, `world/LockCode.java` | Lock component collection and pure `unlocksWith`; `canOpen` can send a message and sound |
| `world/entity/player/Player.java` | `blockInteractionRange` reads the current attribute; `canInteractWithBlock` measures eye-to-block-AABB distance |
| `server/level/ServerChunkCache.java`, `world/level/chunk/LevelChunk.java` | `getChunkNow` is a server-thread non-loading lookup; direct block-entity map access avoids pending-NBT promotion |
| `server/level/ServerLevel.java`, `server/network/ServerGamePacketListenerImpl.java`, `server/level/ServerPlayerGameMode.java` | Vanilla spawn/border checks, packet reach tolerance, then the cancellable NeoForge block-interaction event |

Production observation lives in `src/main/java/dev/atmcompanion/execution/StationService.java`; its detached DTO is `ExecutionContext.java`. Both are independent of client-only classes. The exact local source/API signatures have been compiled by the root build; milestone-level verification remains separate.

## Crafting observations

Only exact standard shaped/shapeless recipe classes with supported, fixed normalized requirements are eligible. Runtime `canCraftInDimensions(2, 2)` and `(3, 3)` determine grid fit. Ingredient count alone does not establish shaped-recipe dimensions. A crafting table need is not inferred from output identity or an assumed vanilla recipe.

The unlock observation follows the vanilla predicate: a recipe is not blocked by this rule when limited crafting is disabled, the recipe is special, or the player's recipe book contains the holder. The observer reads those facts directly. It does not call `setRecipeUsed`, grant recipes, open menus, construct crafting output slots, or award advancements. Modded recipe/interaction restrictions remain outside this predicate.

`CraftingMenu.slotChangedCraftingGrid` and campfire completion both suppress outputs whose item is disabled by the world's feature flags. The observer therefore checks the supported fixed result with `isItemEnabled(enabledFeatures())` before publishing crafting/campfire operation facts. A dead or spectator player receives an unavailable operation rather than a positive assessment. These guards were added during adversarial source review; their regression results belong in the verification report.

Crafting-grid fit preserves sparse shaped patterns: `ShapedRecipe.canCraftInDimensions` compares the actual pattern width and height. Two occupied ingredients separated across a three-wide pattern do not become a 2x2 recipe. The decoder trims external empty rows/columns, but internal gaps remain. Overlapping crafting recipes remain a distinct boundary: the real menu can use a preferred recipe supplied by recipe-book placement, while manual arrangement can resolve another matching recipe. Grid fit and ingredient availability alone do not verify that output selection; the player must inspect the result preview.

## Furnace, blast furnace and smoker

The public inventory API supplies slot 0 input, slot 1 fuel and slot 2 output. Item registry IDs, counts and component-presence flags are copied into DTOs; internal `ItemStack` objects are not serialized or mutated. `AbstractFurnaceBlock.LIT` provides the observed block-state flag.

Remaining burn time and cooking progress are not public fields in this release. `BlockEntity.saveCustomOnly(registryAccess)` calls the exact vanilla `saveAdditional` implementation and returns a new in-memory tag. The furnace writes `BurnTime`, `CookTime` and `CookTimeTotal` as integer tags. The reader requires the exact tag types, accepts nonnegative values, and exports only these three numbers. Missing/wrong-type/negative fields produce unavailable timing, never default zero. A new empty furnace may validly have a zero total cooking time.

`saveCustomOnly` is preferable to `saveWithoutMetadata`: the latter additionally encodes block-entity components. Neither method saves files or changes blocks. However, serialization still visits the furnace's inventory, attachments, custom data and `RecipesUsed` history internally. Only the numeric whitelist is retained; raw NBT, lock strings, custom names, attachments and history never enter the DTO. This is a bounded number of serialization calls, not a preemptible hard runtime limit.

Fuel duration is obtained from the actual stack through NeoForge `getBurnTime(recipeType)`, rather than a hardcoded fuel table:

| Station | Recipe type | Effective duration of one newly ignited fuel item |
| --- | --- | --- |
| Furnace | `RecipeType.SMELTING` | Reported burn time |
| Blast furnace | `RecipeType.BLASTING` | Reported burn time divided by two, integer division |
| Smoker | `RecipeType.SMOKING` | Reported burn time divided by two, integer division |

The recipe's `getCookingTime()` is authoritative; a generic assumed 200/100-tick duration is not used. Runtime fuel hooks can fail or have unsupported results, which must remain unavailable. Fuel remainder handling is not a source of free extra fuel.

### Remaining heat has an off-by-one boundary

At the beginning of `serverTick`, an already positive `litTime` is decremented. Processing subsequently requires the remaining value to be positive. Therefore an observed existing `BurnTime` of B can contribute at most `max(0, B - 1)` processing ticks toward a fresh operation. B=1 supplies zero further processing ticks. Newly ignited fuel is assigned its full duration later in that same tick and immediately processes, so new fuel of duration N supplies N ticks, not N-1.

M3 evaluates one prospective player-funded operation. An occupied station input is not owned by the player merely because it is nearby; its current progress cannot reduce the planned operation's fuel cost. The assessor conservatively asks the player to inspect/finish an existing input job before loading a new one. Existing output must be component-compatible and have capacity. Equality of registry IDs does not establish stack compatibility. The observer additionally rejects an assembled result larger than the result/container stack capacity, including an empty output slot. This is deliberately stricter than vanilla's empty-output branch, which does not check that malformed oversized case.

Player fuel observations retain source slots. The chosen cooking input is reserved first in its actual slot, then remaining material-path reservations are distributed by item ID across the other slots. This prevents a component variant selected as input from simultaneously becoming fuel. Station fuel compatibility uses `ItemStack.isSameItemSameComponents`, not translated names or ID-only equality. Nearby station contents are never added to the player's material inventory.

## Campfire and soul campfire

Both exact vanilla blocks use `CampfireBlockEntity`. Public `getItems()` returns four live slots, which the observer copies without modification. `LIT` and `WATERLOGGED` are explicit block-state observations. A lit campfire supplies heat without consuming per-operation fuel. Waterlogging normally extinguishes it; the DTO preserves both flags instead of inventing an ignition or drainage capability.

`saveAdditional` writes `CookingTimes` and `CookingTotalTimes` as integer arrays of length four. The typed reader rejects any other types, lengths or negative elements. There is no furnace burn timer for campfires. Each occupied slot advances one tick while lit; while unlit, positive progress cools by two ticks per tick. Empty slots can retain old timing values, so those values do not establish an active job.

Each free slot can hold one newly placed item. Results are dropped into the world rather than accumulated in an output slot. Existing occupied slots and their progress are not credited to the new planned operation. The observer does not call `placeFood`, light or extinguish blocks, consume fuel, or collect dropped output. It also avoids `getCookableRecipe`, which combines free-slot checks with the station's mutable recipe cache.

## Recipe selection ambiguity

The furnace and campfire `RecipeManager.CachedCheck` hold a private previously selected recipe ID. A matching cached recipe takes precedence over a fresh recipe-manager iteration. Thus a new `getRecipeFor` query need not reveal the exact current station selection when multiple recipes match the same input.

The observer tests runtime recipe predicates for the selected player input and cooking type within a shared cap. A unique matching recipe is observed only when that inspection completes with exactly one match. Two matches establish ambiguity; interrupted inspection, failed predicates or missing input remain unknown. `RecipesUsed` is past history, not proof of the active recipe. Unsupported custom recipe outputs are not flattened into fixed results.

## Discovery and request lifetime

Production defaults are a radius-eight cube (at most 4,913 block positions), nearest 32 station records, eight deeper compatible-station inspections, 4,096 input/recipe predicate attempts, and a cooperative ten-millisecond request budget. Candidate evaluations share one request-local session and these budgets; they do not each restart a full scan. Chebyshev shells prioritize nearby observations when time expires, and retained records sort by squared distance then coordinates.

Only already available chunks are inspected through `getChunkSource().getChunkNow`. The observer reads block states from those chunks and existing block entities through `getBlockEntities().get(pos)`. It does not use `getBlockEntity(CHECK)`, which can promote pending NBT into a live block entity, and never requests chunk loading. Missing/uninitialized/replaced block entities remain unavailable. Exact vanilla block IDs and expected block-entity classes are required.

Coverage reports distinguish loaded, unloaded, scanned, omitted and retained records. No observed station means none in the inspected scope, not none in the world. A budget or output cap prevents a complete-absence claim. A single fuel hook, recipe predicate or serialization call cannot be interrupted by the cooperative clock; cold class loading or a slow mod hook can exceed ten milliseconds. A clock injectable into the service supports deterministic budget tests without changing production limits.

All collection happens on the logical server thread. A session rejects reuse after a world/dimension change, tick change, recipe-manager replacement or main-inventory change. Only detached DTOs leave the request; live chunk/block-entity references are not persisted or exported.

## Access is not a universal permission result

`player.canInteractWithBlock(pos, 0.0)` gives a conservative distance observation based on the current interaction-range attribute. The real incoming-use packet path permits an extra 1.0 block tolerance; this is not treated as ordinary player reach. Distance does not establish line of sight, navigation, or safety.

`ServerLevel.mayInteract` checks spawn protection and world-border bounds only. For furnace-family locks, `collectComponents().getOrDefault(DataComponents.LOCK, LockCode.NO_LOCK).unlocksWith(mainHand)` evaluates the lock without calling `canOpen`; the latter can send chat and a sound. Lock contents are not exposed. Spectator lock bypass does not make a player capable of performing cooking work.

Actual use later posts NeoForge's cancellable `RightClickBlock` event. The observer never posts a simulated interaction to probe permission because listeners can have side effects. Claim mods, other protection, use-item hooks and custom interaction restrictions remain explicitly unverified. Passing the observed checks means the represented prerequisites are met; it is not an execution guarantee.

## Isolated ATM10 runtime feasibility: read-only investigation

At inspection on 2026-09-23 around 04:23 UTC (22 September locally), the host reported 15.84 GiB physical RAM, approximately 7.44 GiB free, and no `java`/`javaw` processes. This is a point-in-time resource observation, not a launch reservation. Free disk was approximately 23.8 GiB on C: and 215.24 GiB on D:.

The installed instance `D:\curseforge\Instances\All the Mods 10 - ATM10` has a manifest identifying ATM10 8.2, Minecraft 1.21.1 and NeoForge 21.1.251. Its 492 mod JARs total 1,420,834,951 bytes. It also contains `config`, `defaultconfigs`, KubeJS startup/server/data resources and pack datapack directories. Copying just JARs would not reproduce its recipe environment. The instance is a client installation; its local loader library directory contains client/universal artifacts, not an inspected ready-to-run dedicated installation.

The existing `run-gametest` and `run-questtest` directories are disposable development worlds with two-GiB heap settings. The former loads Companion plus its core test harness; the latter adds the pinned FTB dependencies. The generated arguments select `forgeserverdev` and GameTest system properties. Neither directory is a full ATM10 environment. Existing tests intentionally replace recipes or create fixture progress; running the whole suite inside a full pack would not by itself prove correctness against untouched ATM10 recipe data.

The official exact-version [ServerFiles-8.2.zip, CurseForge file 8945094](https://www.curseforge.com/minecraft/modpacks/all-the-mods-10/files/8945094) is available and listed as 1.1 GB. It is the preferred server-side dependency/configuration source. The [official ATM server guide](https://allthemods.github.io/alltheguides/help/server/) specifies a Java version appropriate to the pack, recommends at least six GiB allocated RAM for most ATM packs, and describes launching the extracted distribution through its supplied server script.

### Proposed smallest controlled full-pack run

This procedure is a recommendation, not an action performed by this research task:

1. Use the fresh workspace directory `runtime-m3-atm10`, prepared below, or a separately named test directory. Do not point a working directory, world path, junction or writable configuration link at the installed client instance. Use the official 8.2 server distribution and a new world; no player saves, accounts, maps or backups are needed.
2. Preserve the distribution's server mod set, scripts, configs and datapacks. Add exactly the current production Companion JAR plus, if automated player-state checks are needed, a separate narrowly scoped smoke-test mod. Never include fixture/test code in the release JAR.
3. Use the installed Java 21 executable and the supplied `startserver.bat`/generated NeoForge `run.bat`. The inspected distribution includes the pinned installer and the startup script described below. If loader installation is required, the installer command shape is `java -jar neoforge-21.1.251-installer.jar --installServer`; after successful installation the supplied script launches `java @user_jvm_args.txt @libraries/net/neoforged/neoforge/21.1.251/win_args.txt nogui`.
4. For a single smoke process, a proposed starting heap is `-Xms2G -Xmx6G`, with `server-ip=127.0.0.1`, an unused local port, `enable-rcon=false`, a fresh `level-name`, and low view/simulation distances. These are test settings, not production recommendations. Follow normal server EULA setup. Do not run a client or concurrent Gradle/GameTest JVM during the memory-constrained full-pack launch.
5. The smoke check should retain actual ATM10 recipes/tags/configuration, record successful loader/startup/index creation, and evaluate a bounded synthetic player/station fixture against the real selected recipes. Verify commands and detached output, then stop the isolated process cleanly. Merely reaching server startup does not verify player commands or execution observations.

A six-GiB heap leaves only about 1.4 GiB of the observed free memory for JVM native memory and other growth, so this is borderline rather than guaranteed feasible. A four-GiB exploratory heap leaves more host headroom but is below the official general server recommendation; out-of-memory or prolonged garbage collection would be a resource-limit result, not proof of a Companion defect. The existing `forgeserverdev` harness is a real dedicated development target, but adding full pack files to it would establish development-runtime compatibility rather than packaged production-server compatibility. No explicit development-environment condition was found by a narrow search of the installed KubeJS JavaScript, which does not prove all mods behave identically in development mode.

Actual startup may require more memory, additional dependencies, or server-pack-specific adjustments. A new lightweight/flat test world can reduce world-generation work but must be labeled as such. If the full pack cannot boot within available resources, retain that failure evidence and continue to distinguish pinned NeoForge/FTB harness success from full ATM10 runtime verification.

The initial investigation was read-only except for this document. Subsequent authorization allowed preparation of the official server archive under the separate workspace directory `runtime-m3-atm10`; preparation status is recorded below. No server/client process was launched and no live world, instance file or UI was modified by this research agent.

### Authorized archive preparation completed

The exact official server distribution was downloaded from `https://mediafilez.forgecdn.net/files/8945/94/ServerFiles-8.2.zip`, corroborated by the publisher's CurseForge file page linked above. The download completed in approximately 167.5 seconds and contains 1,218,983,508 bytes. Its locally computed SHA-256 is `8f1ef6e6969924bc18a7194782ea9266f7a0bde41141dd94776b5225316d3278` (an integrity fingerprint, not an independently publisher-signed checksum).

Before extraction, all 2,519 archive paths were checked for absolute paths, drive/stream separators, workspace escape, symbolic links and case-insensitive collisions. Extraction completed exclusively under the workspace's `runtime-m3-atm10`. The extracted distribution totals 1,405,419,118 uncompressed bytes and contains 464 server mod JARs, pack configs/KubeJS assets and `neoforge-21.1.251-installer.jar`. This differs from the client instance's 492 JARs, confirming that blindly reusing its entire mod folder would not reproduce the published server distribution.

`startserver.bat` was read before any execution. It pins NeoForge 21.1.251, uses the included installer (or that exact artifact from the official NeoForge Maven), and supports three environment variables:

- `ATM10_JAVA`: full Java executable path.
- `ATM10_INSTALL_ONLY=true`: install dependencies and generate defaults, then exit before server startup.
- `ATM10_RESTART=false`: prevent its default automatic-restart loop.

The supplied `user_jvm_args.txt` defaults to `-Xms4G -Xmx8G` with `AlwaysPreTouch` and G1 options. Those defaults exceed the resource allowance discussed above and should be overridden only for this disposable directory before an eventual launch. At the initial handoff, no installer or startup script had been executed by the research agent and no `libraries` directory was present. Subsequent authorized installation is recorded below.

An explicit preparation command for the lead to run later from the isolated directory is:

```powershell
$env:ATM10_JAVA = 'C:\Users\billy\AppData\Roaming\PrismLauncher\java\java-runtime-delta\bin\java.exe'
$env:ATM10_INSTALL_ONLY = 'true'
$env:ATM10_RESTART = 'false'
& .\startserver.bat
```

Confirm the generated `libraries/net/neoforged/neoforge/21.1.251/win_args.txt` and installer success rather than treating existence of a partial `libraries` directory as successful installation. After memory/configuration/EULA preparation and dependency installation, a single-run launch can bypass the restart wrapper:

```powershell
& $env:ATM10_JAVA '@user_jvm_args.txt' '@libraries/net/neoforged/neoforge/21.1.251/win_args.txt' 'nogui'
```

The quotes intentionally pass Java argument-file tokens literally in PowerShell. The chosen isolated directory and all downloaded pack binaries/configuration remain outside the Companion source/release bundle. Preparation is not runtime verification.

The lead initially selected a separate NeoForge GameTest development-server source set using these official files, a fresh test world, `-Xms512M -Xmx4G`, and a narrow pack-specific smoke probe. That approach avoids executing or editing the distribution's startup scripts. Such a run would establish isolated full-pack **development-server** compatibility, not packaged production-server or human-client verification. The initial snapshot is preserved in `runtime-m3-atm10/SOURCE-PROVENANCE.json`. At the 04:35:54 UTC handoff, free physical memory was about 6.90 GiB with zero Java processes, and no world, loader libraries, or EULA file had been created in the isolated directory.

### Development-loader failure and production-loader preparation

The lead's first full-pack development launch failed before world creation or smoke-test execution. Workspace log `m3-atm10-smoke.log` records `FormationsDev.initDevTools(FormationsDev.java:40)` attempting to load `net.minecraft.client.gui.screens.Screen` on `DEDICATED_SERVER`. Although the Gradle task exited successfully, this is a failed runtime attempt, not a passing test.

The exact published `formations-1.0.4-neoforge-mc1.21.jar` was inspected with the installed Java 21 `javap -c -p`. Its `Formations` constructor calls `FormationsDev.initDevTools()` when `supermartijn642corelib` is loaded and `FMLEnvironment.production` is false. That branch does not test the physical side. A later, separate `Dist.CLIENT` check correctly protects `FormationsClient`, but does not protect the development-tools branch. The observed stack trace enters that exact branch. The appropriate next experiment is the official production loader; changing, removing, or patching Formations would change the target pack.

The pinned NeoForge source independently establishes that simply moving GameTest properties to a production launch cannot run the same annotation-based probe: `GameTestHooks.isGametestEnabled()` and `isGametestServer()` both require `!FMLLoader.isProduction()`. A production smoke probe therefore needs a separate test-only entry point, such as an explicitly enabled bounded server-tick listener with output evidence and controlled shutdown. It must remain outside the production Companion JAR and must not pretend to be a GameTest run.

After explicit authorization, the research agent verified the included installer's SHA-256 against the archive preparation record and invoked only the exact pinned official installer, with a one-GiB maximum heap, from `runtime-m3-atm10`:

```powershell
& 'C:\Users\billy\AppData\Roaming\PrismLauncher\java\java-runtime-delta\bin\java.exe' `
  -Xmx1G -jar '.\neoforge-21.1.251-installer.jar' --installServer
```

Installer output is retained separately in workspace log `m3-atm10-installer.log`. This installer action does not launch Minecraft, accept its EULA, or touch the user's installed instance or world. The preparation history is recorded in `runtime-m3-atm10/RUNTIME-PREPARATION.json`; the original `SOURCE-PROVENANCE.json` remains an unchanged snapshot of the earlier archive handoff.

The installer completed with exit code 0 and the explicit message `The server installed successfully`. Its generated `libraries/net/neoforged/neoforge/21.1.251/win_args.txt` selects `forgeserver`, NeoForge 21.1.251, Minecraft 1.21.1, FML 4.0.44 and NeoForm 20240808.144430. The argument file's SHA-256 is `ed6770c51ccff1ab5c2cde47297c1c471aa6c75a42e4d445f855d432cd1f4ea2`; the generated NeoForge server JAR is 5,675,634 bytes. At installation handoff, the directory contained neither `eula.txt` nor `world`, no Java process remained, and approximately 7.26 GiB physical memory was free. These are preparation checks, not server-load verification.

For the lead's separately authorized production smoke experiment, use the generated production argument file with the chosen test-only probe property and explicit `-Xms512m -Xmx4G` rather than the supplied eight-GiB defaults or any generated development-harness classpath. Root is responsible for isolated world/network settings, EULA setup, adding the separate probe JAR, launching, collecting actual smoke evidence, and stopping that disposable server. No Formations or other pack mod was removed or patched to obtain the production-loader preparation.
