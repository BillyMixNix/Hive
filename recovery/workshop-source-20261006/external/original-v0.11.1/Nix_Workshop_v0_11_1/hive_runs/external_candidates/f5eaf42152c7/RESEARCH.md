# ATM Companion M1 technical research

Research performed 2026-09-22. These are target and design findings, not claims that an ATM10 world was run. Runtime evidence belongs in VERIFICATION.md.

## Target pinned from published release evidence

| Component | Selected target | Evidence |
| --- | --- | --- |
| ATM10 | **8.2**, published September 22, 2026 | [Official CurseForge release, file 8945086](https://www.curseforge.com/minecraft/modpacks/all-the-mods-10/files/8945086) |
| Minecraft | **1.21.1** | Same release's supported game version |
| NeoForge | **21.1.251** | Same release's explicit NeoForge version; corroborated by pack changelog |
| Java | **64-bit JDK/JRE 21** | [NeoForge 1.21.1 prerequisites](https://docs.neoforged.net/docs/1.21.1/gettingstarted/) |
| Gradle wrapper | **9.2.1** | [Official 1.21.1 MDK wrapper](https://github.com/NeoForgeMDKs/MDK-1.21.1-ModDevGradle/blob/main/gradle/wrapper/gradle-wrapper.properties), observed this date |
| ModDevGradle | **2.0.147** | [Official 1.21.1 MDK build](https://github.com/NeoForgeMDKs/MDK-1.21.1-ModDevGradle/blob/main/build.gradle), observed this date |
| Mappings | Mojang official mappings through NeoForm | Use the MDK's resolved 1.21.1 development sources; Parchment is optional and unnecessary for M1 |

Freshly opening the official file list revealed 8.2; search snippets still reported 8.1. The GitHub repository has no latest GitHub Release endpoint and its available tags stopped at 2.29. Neither stale search snippets nor those tags determine the target.

The official pack repository's release-date commit is `e5e3d1d83ec6885bb9a5e9fb309fb8e9730db025` (2026-09-22T05:32:30Z). Its [8.1 to 8.2 changelog](https://github.com/AllTheMods/ATM-10/blob/e5e3d1d83ec6885bb9a5e9fb309fb8e9730db025/changelogs/CHANGELOG-ATM10-8.1-8.2.md) records NeoForge 21.1.249 → 21.1.251 and FTB Quests 2101.1.34 → 2101.1.36. This commit corroborates the published release; the published release, rather than an arbitrary future main branch, determines the selected versions.

## Actual pack integration environment

The pack's [recorded mod list at the release-date commit](https://github.com/AllTheMods/ATM-10/blob/e5e3d1d83ec6885bb9a5e9fb309fb8e9730db025/config/crash_assistant/modlist.json) contains:

| Mod ID | Recorded version |
| --- | --- |
| `ftbquests` | 2101.1.36 |
| `ftblibrary` | 2101.1.36 |
| `ftbteams` | 2101.1.11 |
| `jei` | 19.57.0.446 |
| `ae2` | 19.2.17 |
| `mekanism` | 10.7.19; jar filename 10.7.19.85 |
| `sophisticatedstorage` | 1.5.91; jar filename 1.5.91.2127 |
| `refinedstorage` | 2.0.9 |
| `mysticalagriculture` | 8.0.28 |
| `productivebees` | 1.21.1-13.13.5 |

No `emi` entry was found in that recorded list. Do not make EMI a dependency. These values are research context only: the deployed mod must report its actual process's `ModList` at runtime and never substitute this table for observation. Pack version cannot safely be inferred solely from Minecraft and loader versions.

## M1 API and truth boundaries

Use `RegisterCommandsEvent` on `NeoForge.EVENT_BUS` for server commands. Commands are rebuilt when server resources reload, so register with the event, not a one-time static dispatcher. [NeoForge source](https://github.com/neoforged/NeoForge/blob/1.21.1/src/main/java/net/neoforged/neoforge/event/RegisterCommandsEvent.java).

All player/world extraction should run on the owning server thread from a `ServerPlayer`. Do not call `Minecraft.getInstance()` or refer to `net.minecraft.client` from common classes. The integrated server in singleplayer is still a logical server; a physical-client check is not a logical-server check. Dedicated-server loading is necessary to catch accidental client class references. [NeoForge sides documentation](https://docs.neoforged.net/docs/1.21.1/concepts/sides/).

The implementation should verify these official mapped names by compilation against the selected development dependency:

| Snapshot fact | API source |
| --- | --- |
| Health / maximum health | `ServerPlayer.getHealth()`, `getMaxHealth()` |
| Hunger / saturation | `getFoodData().getFoodLevel()`, `getSaturationLevel()` |
| XP level / game mode | `experienceLevel`, `gameMode.getGameModeForPlayer()` |
| Position / dimension | `getX()/getY()/getZ()`, `serverLevel().dimension().location()` |
| Biome | `serverLevel().getBiome(blockPosition()).unwrapKey()`; absent key remains unavailable |
| Inventory | `getInventory().getContainerSize()`, `getItem(slot)`; skip empty stacks |
| Equipment | `getItemBySlot(EquipmentSlot)`; armor/offhand overlap inventory, so never sum both |
| Item registry identity | `BuiltInRegistries.ITEM.getKey(stack.getItem())` |
| Loaded mods | `ModList.get().getMods()`, each mod info's ID and version |
| Advancement definitions | `server.getAdvancements().getAllAdvancements()` |
| Player advancement progress | `player.getAdvancements().getOrStartProgress(holder).isDone()` |

Registry IDs are authoritative namespaced identities. Biomes use dynamic registry holders; use their keys rather than translated names. [Registry documentation](https://docs.neoforged.net/docs/1.21.1/concepts/registries/).

Advancement completion is per player and is distinct from FTB Quests team progress. Recipe-unlock advancements can inflate totals: identify whether a reported total includes every advancement or only display-bearing advancements. Bounded samples must carry explicit truncation; missing or failed progress is unavailable, not incomplete. `getOrStartProgress` can initialize a missing progress object, so call it only on the server thread; never award/revoke anything while observing. NeoForge exposes grant/revoke progress events for later event-driven caching. [Advancement source patch](https://github.com/neoforged/NeoForge/blob/1.21.1/patches/net/minecraft/server/PlayerAdvancements.java.patch).

## Recipe discovery spike

The server recipe manager is the source after datapacks and pack modifications load. Enumerating its holders can locate recipes whose `getResultItem(registryAccess)` advertises the requested item. That method is a recipe-book/display result, not a universal proof of a craft's actual result. `assemble(input, registryAccess)` may depend on input and custom recipe logic. A generic `getIngredients()` may be empty even when the machine requires fluids, chemicals, catalysts, energy or other context. [NeoForge recipe documentation](https://docs.neoforged.net/docs/1.21.1/resources/server/recipes/).

For M1, strictly limit exact requirement claims to supported standard recipe classes and label other types unsupported. Recipe lookup must be bounded and explicit, never every tick. Recompute or invalidate cached knowledge after reload. If limits are reached, zero matches means no matches in the inspected scope, not that no recipe exists.

`Ingredient.test(stack)` is the matching authority. Vanilla ingredients may contain items, tags or alternatives. NeoForge custom ingredients may depend on components, intersections, differences, or arbitrary predicates. Their display stacks are not necessarily a complete matching set. [NeoForge ingredient documentation](https://docs.neoforged.net/docs/1.21.1/resources/server/recipes/ingredients/).

NeoForge adds `Ingredient.isCustom()`, `isSimple()`, `getCustomIngredient()`, and `getValues()`. `getValues()` throws for custom ingredients. Standard `ItemValue.item()` and `TagValue.tag()` preserve item/tag identity and alternatives without expansion. Empty tags can produce a **barrier display placeholder**, so blindly treating `getItems()` as consumable requirements is incorrect. [Ingredient patch](https://github.com/neoforged/NeoForge/blob/1.21.1/patches/net/minecraft/world/item/crafting/Ingredient.java.patch).

Count requirements per slot, and avoid double-counting one inventory stack across overlapping alternative sets. Independent per-ingredient availability counts do not establish full craftability. Components omitted from snapshots must remain explicitly outside the represented state.

## FTB Quests M2 feasibility

Exact inspected source: [FTB Quests v2101.1.36](https://github.com/FTBTeam/FTB-Quests/tree/v2101.1.36), commit `8c53f35a97d8897c861b097f1e39f4fc3beb3a15`.

The public [FTBQuestsAPI](https://github.com/FTBTeam/FTB-Quests/blob/v2101.1.36/common/src/main/java/dev/ftb/mods/ftbquests/api/FTBQuestsAPI.java) supplies `api().getQuestFile(false)` for server data. It throws if called before initialization. Its stability statement favors the `api` package; returned quest model classes outside that package are not promised stable. A version-tested optional adapter can use direct typed calls without reflection.

The public [QuestFile interface](https://github.com/FTBTeam/FTB-Quests/blob/v2101.1.36/common/src/main/java/dev/ftb/mods/ftbquests/api/QuestFile.java) exposes chapter/quest iteration and `getTeamData(Player)`. That returns `Optional.empty()` when FTB Teams has not recognized a player yet. It may create progress data; a stricter observational adapter can resolve the team and use `getNullableTeamData(UUID)` instead. Do not treat absent team data as no completed quests.

| Desired fact | Source route / semantics |
| --- | --- |
| IDs | `QuestObjectBase.getId()` / `getCodeString()` (16-digit hexadecimal string preserves 64-bit identity) |
| Titles | `QuestObjectBase.getTitle()`; preserve text/component semantics and localization limits |
| Dependencies | `Quest.streamDependencies()`; use actual dependency semantics, including required counts and completion versus started conditions |
| Completion / started | `TeamData.isCompleted(object)`, `isStarted(object)`; explicitly team-scoped |
| Startable quests | `TeamData.canStartTasks(quest)` includes progression mode, exclusions and repeat cooldown |
| Visible chapters/quests | `Chapter.isVisible(teamData)`, `Quest.isVisible(teamData)`; do not equate visibility with readiness |
| Tasks | `Quest.getTasks()`, `Task.getType()`, `getMaxProgress()`, `TeamData.getProgress(task)` |
| Item task requirement | `ItemTask.getItemStack()`, quantity via `getMaxProgress()`, matching through its predicate; retain component/filter/consumption semantics |

Sources: [QuestObjectBase](https://github.com/FTBTeam/FTB-Quests/blob/v2101.1.36/common/src/main/java/dev/ftb/mods/ftbquests/quest/QuestObjectBase.java), [Quest](https://github.com/FTBTeam/FTB-Quests/blob/v2101.1.36/common/src/main/java/dev/ftb/mods/ftbquests/quest/Quest.java), [TeamData](https://github.com/FTBTeam/FTB-Quests/blob/v2101.1.36/common/src/main/java/dev/ftb/mods/ftbquests/quest/TeamData.java), [Chapter](https://github.com/FTBTeam/FTB-Quests/blob/v2101.1.36/common/src/main/java/dev/ftb/mods/ftbquests/quest/Chapter.java), [Task](https://github.com/FTBTeam/FTB-Quests/blob/v2101.1.36/common/src/main/java/dev/ftb/mods/ftbquests/quest/task/Task.java), [ItemTask](https://github.com/FTBTeam/FTB-Quests/blob/v2101.1.36/common/src/main/java/dev/ftb/mods/ftbquests/quest/task/ItemTask.java).

There is no single demonstrated server-side meaning of “active chapter”: the UI-selected chapter and player-selected companion goal must not be invented from quest visibility. FTB task types include energy, fluid, kill, observation and custom tasks; expose unknown types rather than flattening them into item counts. Avoid client-only GUI, icon and tooltip methods in quest classes.

## Optional adapters and recipe viewers

Design decision: a small registry of adapter descriptors can check actual loaded mod IDs and compatible versions before constructing typed implementation classes. Do not eagerly link optional-mod types from common class fields, method signatures or static initialization. Isolate each adapter failure, log a useful bounded diagnostic, and return unavailable/not-integrated with a reason. Mod presence alone never means its storage or machine state was inspected.

JEI is present and has a documented plugin/API route with compile-only API and optional runtime dependency. Its recipe display extensions can help later UI integration, but cannot replace authoritative server state or be loaded by a dedicated-server sensor. Consult the version-specific links in the [JEI getting-started index](https://github.com/mezz/JustEnoughItems/wiki/Getting-Started), which explicitly separates old Forge guides from Minecraft 1.21/1.21.1. EMI was not observed in the selected pack list; defer its adapter.

AE2, Mekanism, storage, farming and bee integrations remain research candidates, not claimed sensors. M2 should first validate actual API access in an ATM10 playtest, bound all network/storage enumeration, honor player access, and keep “not inspected” distinct from an observed empty collection.

## Strongest feasible local verification

Official MDK includes a `gameTestServer` run type. [ModDevGradle](https://github.com/neoforged/ModDevGradle#unit-testing-with-junit) also documents `neoForge.unitTest.enable()` and a NeoForge test framework `EphemeralTestServerProvider` for JUnit tests that need a Minecraft server. Prefer a real server-backed snapshot fixture to mocked Minecraft internals. Verify the selected loader loads the actual production mod, then capture inventory/equipment/advancement/location facts from a server player and exercise registered commands.

The build coordinator found Java 21 installed and no ATM10 instance in the inspected Prism locations; ATM11 is not a substitute. A NeoForge test world can verify boot and sensors but cannot validate ATM10's complete recipes, mixins, integrations or real player experience. Record these levels separately in VERIFICATION.md.

Subsequent M2 integration candidate after the reload-aware recipe index: implement and validate a **version-pinned optional FTB Quests 2101.1.36 adapter**, capturing team-scoped IDs, dependency edges, task types and completion without flattening unsupported tasks. Combine that evidence with runtime recipe knowledge before constructing a planner. The single chosen next step after the real ATM10 M1 playtest is the recipe index described in VERIFICATION.md.
