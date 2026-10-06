# Independent adversarial review

**Gate F: PASS within the documented Milestone 1 scope.** Final review completed 2026-09-22 after repairs, the successful clean build, all 37 unit tests, and all eight required dedicated-server GameTests. No blocking correctness issue remains in the reviewed implementation. This verdict does not claim actual ATM10 compatibility or a human-client playtest.

Reviewed by the research/verification agent, independently of the production implementation and test authors. This reviewer did not edit production code or run concurrent Gradle builds.

## Scope

- Authoritative player, inventory, equipment, location, advancement and loaded-mod extraction.
- Unknown-versus-empty capability semantics and JSON boundaries.
- Registry identity, recipe alternatives, tags, custom ingredients, component sensitivity and overlapping inventory allocation.
- Dedicated-server class safety, server-thread access, optional-adapter linkage/failure isolation, command permissions, throttling and bounded output.
- Production JAR contents, build/test evidence, and statements about actual ATM10 verification.

## Findings and repairs

### Blocking defect found and repaired: empty-tag display placeholders

The initial recipe implementation used `Ingredient.getItems()` as a factual list of ingredients. NeoForge adds a barrier display stack for an empty tag, so this could falsely expose `minecraft:barrier` as a real requirement. Display-oriented ingredient APIs are not automatically a faithful requirement representation.

The repair reads original `ItemValue`/`TagValue` entries, preserves source tag IDs, and expands registry tag members within fixed limits. Custom ingredients are classified unsupported before reading vanilla values. Empty tags now make overall requirement availability explicitly unavailable, including mixed empty-tag/item cases; visual placeholders never become known ingredient alternatives. The actual-server regression is `emptyTagsNeverInventBarrierRequirements`.

### Wording correction: loaded mods are process-scoped

The initial command header called the result “server mods.” On an integrated singleplayer server, `ModList` also contains physical-client-only mods. The header now says “Loaded runtime mods.” Presence remains separate from integration state: installed AE2 does not imply storage was inspected.

### Runtime defect found and repaired: dummy fake-player advancements

The first dedicated GameTest run passed seven of eight tests but failed advancement completion after an award. Investigation found that NeoForge `FakePlayer` substitutes dummy advancement methods, so querying those methods could report synthetic zero progress as known state. Production now returns unavailable advancement data for `isFakePlayer()` entities. The positive completion test uses the official GameTest helper's real `ServerPlayer` and actual `PlayerAdvancements`; the fake-player snapshot test separately asserts unavailable progression. This failure is retained in the verification history rather than hidden.

## Source review conclusions

Every populated snapshot section reads actual server/registry/loader APIs. No ATM10 resource counts, recipe requirements, pack name, or progression states are substituted from research data. Observation constructors prevent unavailable/not-integrated data from becoming an empty known collection; snapshot constructors cross-check the corresponding capability status.

Production contains no client-only imports, optional-mod imports, reflection integration hacks, background world readers, tick-based scans, network client, credentials, or LLM invocation. Snapshot capture and recipe inspection require the owning server thread. Equipment is an overlapping view of inventory, not additional ownership. Advancement counts explicitly include recipe unlocks and carry truncation information.

Recipe sufficiency means only a supported ordinary crafting recipe's ingredient multiset can be allocated from main inventory slots 0–35. It does not establish overall craftability, recipe unlock, crafting-table access, output components, machine prerequisites, fluid/chemical requirements, or storage contents. Unsupported classes and custom ingredients remain unavailable. Allocation is tested against an independent exhaustive oracle rather than only implementation-shaped examples.

Commands return private feedback, cap line lengths, paginate mods, and throttle snapshot/recipe work. Debug export requires permission level 2 and replaces one fixed server-local file. It performs bounded JSON serialization before writing, uses a temporary file and atomic replacement where supported, and reports/logs failures. Optional adapter factories are called only after their required mod is loaded; runtime/linkage failures become unavailable diagnostics without suppressing healthy adapters.

## Evidence independently inspected

- Final successful command: `gradlew.bat clean build runGameTestServer --console=plain`.
- Final JUnit XML independently summed: **37 tests, zero failures, zero errors, zero skipped**.
- Final sanitized log: physical-server launch with Minecraft **1.21.1**, NeoForge **21.1.251**, Microsoft OpenJDK **21.0.7+6-LTS**; the production mod was recognized and initialized; **all eight required GameTests passed**; Gradle reported `BUILD SUCCESSFUL` with all 13 tasks executed.
- Earlier build/runtime failures were inspected and are disclosed in `VERIFICATION.md`, including the fake-player advancement defect. The successful clean rerun follows those repairs.
- Real-server-player evidence JSON parsed independently: schema 1; advancement status available; **1,400 scanned, one completed, 1,399 incomplete**, with 256 details and explicit entry truncation. These are fixture-world facts, not ATM10 or the user's player.
- Fake-player evidence JSON independently confirms known inventory/equipment and **unavailable, null progression**, rather than invented incomplete advancements.
- Final production JAR listing: 38 entries, only production classes and mod metadata; no GameTest classes, synthetic datapacks, Minecraft classes, Gson bundle, optional-mod binaries, or account data.
- Final production JAR SHA-256 independently calculated: `9814bfea0e37ecc131002ec22f388f6727ceb0488c4ff349a2e5a28a70da4bef`.
- Production metadata: Minecraft `[1.21.1]`, NeoForge `[21.1.251,21.2)`, JavaFML `[4,)`.
- Final `README.md`, `VERIFICATION.md`, and `ARCHITECTURE.md` reviewed against production sources and observed evidence. They distinguish development-loader verification from packaged-JAR deployment and actual ATM10 gameplay. The release script's source allowlist and JAR identity/integrity checks were reviewed; final ZIP creation belongs to the release step.

## Nonblocking boundaries

- Cooperative 100 ms advancement/recipe scan budgets are checked between entries; they cannot preempt a third-party method that itself blocks. Collection/count caps, the 2,048-criteria advancement guard, and command throttles bound normal work, not arbitrary broken mod code.
- Snapshot JSON parsing is a debug/test utility that enforces documented invariants and size, not a full required-field schema validator for hostile input. There is no runtime JSON import path. A future importer must reject omitted primitive fields rather than accepting Gson defaults.
- Detailed optional integrations, nested inventories, accessory slots, machine state, power, nearby environment, goals, and planning are absent by design.
- Real ATM10, a human player client, integrated-client startup, remote multiplayer, and a deployed packaged-JAR launch require separate evidence; a development GameTest server must not be described as an ATM10 playtest.
