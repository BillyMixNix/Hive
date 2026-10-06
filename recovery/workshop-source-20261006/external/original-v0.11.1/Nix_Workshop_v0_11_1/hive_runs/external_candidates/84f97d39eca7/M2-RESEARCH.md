# Milestone 2 research and integration contract

Research date: 22 September 2026. The target remains ATM10 8.2, Minecraft 1.21.1, NeoForge 21.1.251, Java 21, Gradle 9.2.1, ModDevGradle 2.0.147, official Mojang mappings. The final clean build and both dedicated-server test environments passed. This document records the inspected APIs, integration contract and FTB verification boundary; retained execution evidence is under `evidence-m2/`.

## Target evidence and optional dependencies

The official [ATM10 8.2 release](https://www.curseforge.com/minecraft/modpacks/all-the-mods-10/files/8945086) and [release-date pack mod list](https://github.com/AllTheMods/ATM-10/blob/e5e3d1d83ec6885bb9a5e9fb309fb8e9730db025/config/crash_assistant/modlist.json) identify FTB Quests 2101.1.36, FTB Library 2101.1.36, FTB Teams 2101.1.11, and Architectury 13.0.11. The installed ATM10 instance was subsequently located and inspected read-only; its relevant JAR versions agree. Its quest configuration contains 66 chapter files, totaling 2,809,915 bytes. This is installation/configuration evidence, not a claim that the M2 mod has run inside ATM10.

Published Maven coordinates, verified against the publishers' POMs:

| Artifact | Exact target | Repository |
| --- | --- | --- |
| `dev.ftb.mods:ftb-quests-neoforge` | `2101.1.36` | `https://maven.ftb.dev/releases` |
| `dev.ftb.mods:ftb-library-neoforge` | `2101.1.36` | `https://maven.ftb.dev/releases` |
| `dev.ftb.mods:ftb-teams-neoforge` | `2101.1.11` | `https://maven.ftb.dev/releases` |
| `dev.architectury:architectury-neoforge` | `13.0.11` | `https://maven.architectury.dev` |

FTB Quests' [published POM](https://maven.ftb.dev/releases/dev/ftb/mods/ftb-quests-neoforge/2101.1.36/ftb-quests-neoforge-2101.1.36.pom) lists minimum selected build dependencies Architectury 13.0.8, Library 2101.1.36 and Teams 2101.1.9. We explicitly select the pack's actual versions above. These artifacts are compile-only in production and runtime dependencies only in the separate quest-test run. They are not embedded, shaded or redistributed in the companion release.

## Recipe reload lifecycle

Inspected the exact NeoForge 21.1.251 source JAR and the generated official-mapping Minecraft sources in `build/moddev/artifacts/neoforge-21.1.251-sources.jar`, rather than applying a newer Minecraft version's API.

- `MinecraftServer.reloadResources(...)` loads a new `ReloadableServerResources` and `RecipeManager`. Its final `thenAcceptAsync(..., this)` runs on the server executor, replaces the active resources, updates registry tags and calls `PlayerList.reloadResources()`.
- NeoForge's patch to `PlayerList.reloadResources()` posts `OnDatapackSyncEvent(this, null)` after the server has installed those resources. The same event also fires for an individual joining player; a non-null event player is not evidence of a new recipe generation.
- `ServerStartedEvent` is suitable for the initial controlled build. The global datapack-sync event is suitable for rebuilding after a completed reload. A manager-identity check can invalidate stale generations defensively.
- `AddReloadListenerEvent` exposes the resources being prepared, but reading `server.getRecipeManager()` at that point can still return the previous manager. It is not an after-swap notification.
- `TagsUpdatedEvent.SERVER_DATA_LOAD` explicitly allows a client-thread invocation during initial singleplayer load. It must not be treated as an unconditional logical-server-thread signal.
- Failed reloads must not publish a partially assembled index. Recipe normalization occurs on the logical server thread; only immutable DTOs may be processed away from the game thread.

NeoForge's [version-specific recipe documentation](https://docs.neoforged.net/docs/1.21.1/resources/server/recipes/) confirms the server `RecipeManager` as the authoritative source and distinguishes recipes, ingredient predicates and recipe input instances. Display result stacks from unknown recipe classes do not prove a fixed output or establish complete requirements. Runtime tags, alternatives, custom ingredients, component matching, fluid inputs and machine conditions require explicit representation or an unsupported status.

## FTB Quests APIs inspected

Sources are pinned to [FTB Quests v2101.1.36](https://github.com/FTBTeam/FTB-Quests/tree/v2101.1.36), commit `8c53f35a97d8897c861b097f1e39f4fc3beb3a15`, and [FTB Teams v2101.1.11](https://github.com/FTBTeam/FTB-Teams/tree/v2101.1.11). Raw source was retrieved directly from those official repositories when the browser renderer could not open their tag pages.

`FTBQuestsAPI.api().getQuestFile(false)` returns the server `BaseQuestFile`. The API's own documentation does not promise stability for model classes outside its `api` package. Consequently, the optional adapter supports exactly FTB Quests 2101.1.36 and reports a different version unavailable. There is no reflection or private-field access.

| Observation | API source | Meaning |
| --- | --- | --- |
| Chapters | `BaseQuestFile.getChapterGroups()`, `ChapterGroup.getChapters()` | Actual server quest definitions |
| Quests | `Chapter.getQuests()` | Actual chapter membership |
| Stable quest IDs | `QuestObjectBase.getCodeString()` | Unsigned 16-digit uppercase hexadecimal identifiers; no conversion to imprecise JSON numbers |
| Titles | `QuestObjectBase.getTitle().getString()` | Server-resolved title; up to 256 characters, with an ellipsis when clipped |
| Current team | `FTBTeamsAPI.api().getManager().getTeamForPlayer(player)` | Current party/team, not necessarily the player's personal team |
| Existing progress | `BaseQuestFile.getNullableTeamData(team.getId())` | Missing progress remains unavailable; observation never creates it |
| Completed / started | `TeamData.isCompleted(object)`, `isStarted(object)` | Recorded completion and start flags for the current team |
| Task progress | `TeamData.getProgress(task)`, `Task.getMaxProgress()` | Actual numeric progress and target, without interpreting unknown task semantics |
| Dependencies | `Quest.streamDependencies()` | ID/type references, including non-quest dependency objects |
| Dependency evaluation | `TeamData.areDependenciesComplete(quest)` | FTB's authoritative evaluation of its actual rule |
| Task startability | `TeamData.canStartTasks(quest)` | FTB progression mode, dependencies, exclusion and repeat cooldown evaluation |
| Visibility | `Quest.isVisible(teamData)`, `Chapter.isVisible(teamData)` | FTB's current-team visibility predicate; no invented active-chapter state |
| Lock state | `TeamData.isLocked()` | Explicit additional guard when listing available quests |
| Task type | `Task.getType().getTypeId()` | Namespaced registered FTB task type |
| Item task reference | Exact `ItemTask.getItemStack()` class | Configured item reference only; matching is not fully integrated |

Relevant source files: [FTBQuestsAPI](https://github.com/FTBTeam/FTB-Quests/blob/v2101.1.36/common/src/main/java/dev/ftb/mods/ftbquests/api/FTBQuestsAPI.java), [BaseQuestFile](https://github.com/FTBTeam/FTB-Quests/blob/v2101.1.36/common/src/main/java/dev/ftb/mods/ftbquests/quest/BaseQuestFile.java), [Quest](https://github.com/FTBTeam/FTB-Quests/blob/v2101.1.36/common/src/main/java/dev/ftb/mods/ftbquests/quest/Quest.java), [TeamData](https://github.com/FTBTeam/FTB-Quests/blob/v2101.1.36/common/src/main/java/dev/ftb/mods/ftbquests/quest/TeamData.java), [ItemTask](https://github.com/FTBTeam/FTB-Quests/blob/v2101.1.36/common/src/main/java/dev/ftb/mods/ftbquests/quest/task/ItemTask.java), [TeamManager](https://github.com/FTBTeam/FTB-Teams/blob/v2101.1.11/common/src/main/java/dev/ftb/mods/ftbteams/api/TeamManager.java).

### Semantics that must remain explicit

The dependency-mode field has no public getter. It can represent all-completed, any-completed, started-state checks, or minimum-count rules. The actual installed pack includes `one_completed`, `one_started` and flexible progression. Exporting every dependency edge as an all-of crafting prerequisite would be wrong. The DTO keeps the edges, marks `dependencyRule` unavailable, and exports FTB's evaluated `dependenciesSatisfied` and `canStartTasks` booleans. Flexible progression can allow tasks to start even with unmet dependencies; the two booleans are intentionally distinct.

Likewise, an ItemTask can use filters, component policies, consumption settings and submission rules. The DTO's `itemReference` can identify a configured item and whether its stack has a component patch, but `requirementRule` remains unavailable. An item-reference graph edge is a reference, not proof that exactly that plain item satisfies the task. Unknown/custom task types retain type IDs, progress and explicit unknown requirements. No display alternatives are flattened into fixed requirements.

`availableQuestIds` has a precise, deliberately modest definition: containing chapter visible, quest visible, team unlocked, FTB says tasks can start, and not already completed. It is sorted by ID, not ranked by desirability. The chapter visibility predicate matters because a chapter can be always-invisible independently of its quests. Quest-link placement across other chapters is not integrated. Completed repeatable quests are excluded from this list; the `repeatable` and `canStartTasks` fields remain available for future repeat-aware planning. Titles use the server's locale/fallback behavior, not a claim about an individual client's translation.

The DTO exports no player UUID, team UUID, team name, account data, server address, chat history, credentials or unrelated filesystem contents. Scope is the literal `current_player_ftb_team`. Quest IDs are game-content identifiers. No quest data is transmitted to an external service.

## Optional integration and bounds

`OptionalQuestAccess<P>` is a pure injectable version/availability gate. Its adapter factory is not called when FTB is absent or unsupported. `QuestService` has no FTB types in its public signatures; the typed adapter is instantiated lazily only behind that gate. Runtime exceptions, linkage failures and third-party recursion overflow are converted to unavailable observations with logged diagnostics. A missing mod is `not_integrated`; unsupported, not-ready or broken APIs are `unavailable`; an observed empty quest book is `available` with empty collections.

Every actual query asserts the logical server thread. It resolves the current team on each explicit request; no player/world reference or old team snapshot is cached. Synthetic players are not treated as having persistent quest progress. Production never calls `getOrCreateTeamData`, `setProgress`, rewards or completion mutation APIs.

Extraction has bounds of 256 chapter groups, 256 chapters, 8,192 quests, 64 tasks per quest, 256 dependencies per quest, 16,384 total tasks and 32,768 total dependency references. A cooperative 250 ms collection budget is checked between operations. A single upstream API call cannot be preempted safely on the server thread. Exceeding a structural or time bound returns an unavailable observation; a truncated quest book is never presented as complete. Titles are capped at 256 characters. Output serialization has its own export bound in the main command layer.

## Runtime verification design

The separate `questtest` source set and `runQuestTestServer` run load the published optional binaries above. Its fixture uses the real server quest file, `Chapter`, `Quest`, `ItemTask`, FTB Teams manager, logged-in mock ServerPlayer and team progression APIs. The tests exercise partial task progress, completion, blocked/unlocked quests, a real `one_completed` rule, explicit unknown requirement semantics, deterministic IDs, team locking and current-party resolution. A separate wrong-version gate fixture verifies that the adapter factory is not entered. The ordinary GameTest run keeps optional binaries absent, so it independently exercises safe core loading without FTB.

Fixtures mutate only the disposable test server's quest book and team progress. They do not read or modify the user's ATM10 world. The first FTB run exposed a harness limitation: Mojang's logged-in mock player does not negotiate NeoForge mod payloads, so FTB's normal progress-update packet was rejected. Configuring it after login was also too late on a repeat run: the now-populated quest book sent its translation table during login. The fixture therefore follows Mojang's embedded connection pattern and calls NeoForge 21.1.251's purpose-built `NetworkRegistry.configureMockConnection` GameTest API **before** `PlayerList.placeNewPlayer`. This models a compatible NeoForge connection without disabling production packet checks; it does not verify a real graphical client. Test source sets and their structures are excluded from the release JAR. See VERIFICATION.md and retained test evidence for the actual outcomes, including failed experiments and their repairs. A successful small integration fixture does not prove all ATM10 quests, addon task types or the full 492-mod pack have been exercised.

Once packets were enabled, the next run also caught an invalid synthetic profile name: `quest-mock-player` has 17 characters, exceeding Minecraft/FTB's 16-character player-name codec limit. Fixture names now use valid short names, and the test repairs only its own previous invalid profile via FTB's public model setters so the retained disposable world can be tested again. No real player or production data is changed by this test-only migration.

## Verified outcome

The final clean build completed successfully on 22 September 2026 with **87 unit tests, 13 core NeoForge GameTests and both FTB integration GameTests passing**. The FTB test batch completed in 2.223 seconds using the exact published versions listed above. Its retained world contained two synthetic chapters and six synthetic quests, including a previous-run fixture; this explicitly exercised login with an already-populated quest book. The generated [quest evidence](evidence-m2/ftb-quests-fixture.json) contains current-team observations and two available incomplete quest IDs, without player/team identities.

Verified through actual FTB APIs: unresolved team remaining unknown, real partial progress, completion, dependency unlocking, the `one_completed` dependency operator, locked-team availability, deterministic quest order and switching to the current party team. The core runtime suite independently verified loading without FTB, and the injectable wrong-version fixture verified that the version gate never invokes its adapter factory; no incompatible FTB binary was installed. Item-reference and dependency-rule limitations remain explicit in the output. The [final execution log](evidence-m2/verification-final.log) reports both runtime suites passing and `BUILD SUCCESSFUL`.

This is a real NeoForge dedicated test environment with the published FTB binaries and synthetic content. M2 has **not** been run in the user's full ATM10 instance, and the complete installed quest book's performance, addon task types, cross-chapter quest-link behavior and a graphical client remain unverified. The runtime adapter's collection limits and unknown semantics remain necessary for that playtest.
