# M3 verification — ATM Companion 0.3.0

## Scope and environment

Target **All the Mods 10 8.2 / Minecraft 1.21.1 / NeoForge 21.1.251 / Java 21**. Verified on Windows 11 x64 with Microsoft OpenJDK **21.0.7+6-LTS**, Gradle wrapper **9.2.1**, ModDevGradle **2.0.147**, official Mojang mappings and JUnit **5.11.4**. The core and quest harnesses use at most 2 GiB each, sequentially. Optional API/runtime dependencies: FTB Quests **2101.1.36**, FTB Library **2101.1.36**, FTB Teams **2101.1.11**, Architectury **13.0.11**.

The development project continues M1/M2. Existing regression assertions were retained. M2's ready-crafting fixture now explicitly places a crafting table because M3 observes that prerequisite; reload fixtures wait for staged publication. No user world, launcher mods directory or existing goals/inventory were edited in this M3 pass. Earlier M1/M2 user-world success is historical evidence only.

## Exact commands and completed results

From `ATM-Companion/`, with `JAVA_HOME` set to the Java 21 JDK and `GRADLE_USER_HOME` set to the existing dependency cache:

```powershell
.\gradlew.bat clean build runGameTestServer runQuestTestServer packTestJar --console=plain
python tools/collect-m3-evidence.py
python tools/package-m3-release.py
```

The final clean Gradle invocation completed **BUILD SUCCESSFUL in 1m 29s** on September 22, 2026 local time (September 23 UTC). It compiled the production mod and runtime-test sources and produced `build/libs/ATM-Companion-0.3.0.jar`.

| Gate | Evidence / result |
| --- | --- |
| Clean compilation and JAR | Passed, exact pinned environment above |
| Unit regressions and new M3 tests | **119 tests across 17 suites; 0 failed, 0 errors, 0 skipped** |
| NeoForge logical-server load/core integration | **23 required GameTests passed**, 5.967 s reported test execution |
| Optional FTB present | **2 required GameTests passed**, 1.868 s reported test execution |
| Optional FTB absent | Core runtime starts without FTB; absent quest command remains unavailable rather than empty-known |
| Independent adversarial review | Passed for the core scope; see `M3-ADVERSARIAL-REVIEW.md` |
| Isolated ATM10 production server-pack probe | **Passed** using the shipped production JAR and official loader; scope below |

The suite collector verifies test totals and both runtime success markers before copying evidence. `evidence-m3/` contains sanitized final logs, all JUnit XML results, suite totals, synthetic live-state/plan/quest JSON, reload evidence and the diagnosed failed fixture log. No real-world inventory or user profile is collected for release evidence.

## What the tests establish

All 93 prior unit regressions remain, with 26 M3 tests. New coverage includes mixed manufactured tag members, root route budget fairness, exact per-position batch allocations and one-operation selection, plus a 2,744-case independent allocation oracle. It tests malformed/provenance-missing inputs, unknown observations, sparse grid fit, locks/reach/unlocks, occupied input, full output, campfire state, ambiguous cooking matches, fuel separation, `BurnTime - 1`, one ignition and one operation from a larger batch. Missing allocation provenance produces unknown execution; a proven shortage produces blocked execution. Prior serialization, optional integrations, empty inventory, registry identity, cycles, duplicated resource accounting, bounded graph/output and persistence tests remain.

The 23 core GameTests include the original 14 plus nine M3 tests. They exercise actual vanilla recipe classes/metadata, sparse shaped dimensions, runtime fuel hooks, station slots/timers, component-sensitive compatibility, bounded scans without forced chunk loads, shared inspection caps, stale/off-thread rejection, timeout semantics, observer nonmutation and a real cooking plan. New recipe-replacement tests restore the disposable manager in `finally`, verify same-count invalidation and cancel/replacement publication, and reject oversized furnace outputs. Real datapack reload tests replace tag/recipe facts and check that old published data stays immutable. Commands, JSON exports and actual SavedData disk round trips remain covered.

Station semantic fixtures use an injected fixed clock so machine speed cannot randomly hide the fact under test. Separate tests exercise production budget expiration and shared operation caps. The normal production constructors use real `System.nanoTime`. A fixed-clock fixture's measured runtime is not proof that a production 10 ms observation always completes.

FTB tests use the real pinned optional mods and disposable quest/team fixtures, including progress and availability changes. They do not certify every quest/custom task in ATM10. FakePlayer advancement and quest limitations stay explicit.

## Measured harness behavior

These are observed single-run samples, not a latency benchmark or an SLA.

| Measurement | Final clean run |
| --- | --- |
| Core initial index | 1,294 definitions, 842 output items, 291 unknown/nonfixed outputs, 371 unsupported dependency models |
| Core staged construction | 102 ms active work, 1,265 ms elapsed, 25 slices, 6 ms largest initial slice |
| Two real reload publications | 47/22 ms active, 85/52 ms elapsed, 19 slices each, 19/3 ms largest slice |
| FTB harness initial index | 1,298 definitions, 846 outputs, 113 ms active, 1,062 ms elapsed, 26 slices |
| Synthetic broad-tag pressure | 4,001 definitions; 199,941 retained alternatives and 399,946 identities; 876 explicitly unsupported after limits |
| Largest synthetic slice | **15 ms** in this run; an earlier successful validation observed **40 ms** despite a cooperative 5 ms target |
| Live pickaxe service request | 0.797 ms material stage, 2.462 ms execution stage, 3.419 ms total |
| Cooking fixture service request | 32.215 ms material stage, 22.796 ms fixed-clock execution stage, 64.274 ms total |

The cooking fixture used an actual cobblestone-to-stone recipe, a furnace, and one unreserved coal item whose runtime hook returned 1,600 ticks. It observed 4,913 loaded scan positions, one detailed station and 71 recipe predicates. Full material ownership and one-operation fuel are separate in `cooking-plan.json`. `/goal` left quest context explicitly unrequested. The larger first-call timing illustrates warmup/measurement variability; no universal command-latency guarantee is made.

## Diagnosed failed experiments

1. Initial sandbox build setup tried to download Gradle before compilation because it did not use the populated dependency cache. Running with explicit `GRADLE_USER_HOME` and the local Java 21 JDK resolved it. This was not a Java source failure.
2. The first clean 23-test runtime run passed 22 tests and failed a **new test assumption** that bundles were disabled. NeoForge's GameTest world enabled that feature. The fixture now checks actual enabled-feature behavior. The corrected full suite passed; `feature-fixture-failure.log` preserves the failure. The disabled-output rejection branch is source-reviewed and compiled but **not runtime-exercised** by this all-features world.
3. Adversarial source review found potential stale same-count recipe-table facts, spectator/dead-player feasibility, and missing disabled/oversized output checks. These were fixed and tested where the harness permits. See the independent review for the exact boundaries.
4. A final semantic review separated unavailable ingredient-allocation evidence from known missing inputs. A new focused regression raised the unit total to 119, and the entire clean build/core/FTB sequence passed again on the release source.

## Isolated ATM10 8.2 probe

The official `ServerFiles-8.2.zip` is prepared in the separate sibling `runtime-m3-atm10/`, not in a launcher instance. It contains 464 official server mod JARs. Archive SHA-256: `8f1ef6e6969924bc18a7194782ea9266f7a0bde41141dd94776b5225316d3278`. It is excluded from the release.

```powershell
.\gradlew.bat runPackTestServer --console=plain
```

This first development-loader attempt failed **before any probe ran**: Formations 1.0.4's development initialization attempted to load a client `Screen` class on the dedicated server. Gradle nevertheless returned success, which was not accepted as runtime evidence. Inspection of the installed Formations bytecode identified an `FMLEnvironment.production` guard without a matching side guard. NeoForge also disables its GameTest annotation harness in production. No pack mod was removed or patched to make the test pass.

The exact included NeoForge installer was then run with `java -Xmx1G -jar neoforge-21.1.251-installer.jar --installServer` in the isolated directory. It reported successful installation. A separate, explicitly enabled test-only lifecycle probe was packaged with `packTestJar`. It requires both JVM property `atm_companion.packSmoke=true` and the regular marker file `M3-DISPOSABLE-PROBE`, checks the dedicated server directory, and stops that server after writing a terminal result. This code is excluded from the production Companion JAR.

The final production run used the official 464 server mod JARs plus the Companion and probe JARs, official pack scripts/config/datapacks, a fresh `m3-probe-world` flat world, localhost-only binding, whitelist, two-chunk view/simulation distance, and a 4 GiB maximum heap. No user save, account/session or launcher installation was used. From the isolated runtime directory, with `JAVA_HOME` pointing to the recorded JDK:

```powershell
& "$env:JAVA_HOME/bin/java.exe" '-Xms512m' '-Xmx4G' '-Datm_companion.packSmoke=true' '@libraries/net/neoforged/neoforge/21.1.251/win_args.txt' 'nogui'
```

The production launch target was **forgeserver**, not a development target. It loaded **503 mod entries**, including Companion 0.3.0. All 174 KubeJS server scripts loaded with zero reported script errors/warnings. FTB loaded 66 chapters and 4,790 quests; this is a pack-load count, not verification of their individual progress rules. The probe wrote `terminalStatus: passed`, logged its successful completion, and the server saved and stopped normally with process exit 0. Evidence is in `evidence-m3/atm10-production-smoke.json` and the sanitized production/dev-failure/installer logs.

The actual tested production JAR SHA-256 is `f46efec3f9f235e6c9626febfc6897f87c7c27d5b26db9d62dc5da764defa2e8`; the collector verifies byte equality with the release build.

| Actual-pack measurement | Observed result |
| --- | --- |
| Runtime recipe definitions | **95,229**, all visited |
| Retained index | **50,000** definitions, **40,020** output items |
| Explicitly unknown / unsupported | 4,499 unknown/nonfixed outputs; 14,662 unsupported dependency models |
| Ingredient retention | 200,000 alternatives / 400,000 identities; limits reached and reported |
| Staged work | **811 slices**, **1,663 ms active**, approximately **55.6 s elapsed**, largest slice **71 ms** |
| Shallow station scan | 3,514/4,913 positions within the real observation budget; correctly reported partial |
| Empty-inventory pickaxe plan | 258 nodes; 56.811 ms total; unsupported repair-preview route |
| Empty-inventory glass plan | 268 nodes; 22.422 ms total; blocked on Create framed glass |
| Empty-inventory stone plan | 391 nodes; 27.532 ms total; blocked on Ice and Fire frozen stone |

These three plans had zero invented ownership, unknown/blocked execution, visible search/index limits and no implicit quest scan. They establish compatibility and bounded truthfulness, **not strategic usefulness**. In particular, repair/conversion routes can be poor suggestions when nothing is owned. Gathering/acquisition alternatives and better route ranking remain a concrete next engineering priority. The full-pack probe did not demonstrate positive station readiness, real-user quest progress, GUI interaction or actual crafting; those are covered only where stated in the separate core fixtures or remain for playtesting.

## Not verified and limitations

- M3 has not been installed into or played in the user's real ATM10 world. No GUI/client render, multiplayer join, modded claim permission or protected-base interaction was tested for M3.
- A ready material path is not a promise of executable crafting. Only one next operation is observed; later stations, energy, fluids, fuel and recipe unlock dependencies remain unresolved.
- Overlapping crafting selection requires checking the output preview. Cooking ambiguity becomes unknown. Modded workstation subclasses and machine APIs are unsupported.
- One new fuel item plus current heat is modeled. Fuel queues/remainders, existing station jobs and station-output ownership are excluded. Stations never enlarge the material inventory.
- Search, recipe/ingredient retention, scan radius, deep inspections and predicate budgets can truncate coverage. Cooperative timing is not preemptive; slow hooks can exceed the nominal slice.
- Recipe table replacement and normal reloads invalidate knowledge. Mutation inside an existing recipe object without table replacement/reload is not detected.
- Storage networks, equipment/nested inventory planning, automatic actions, LLMs and network transmission remain absent.

The release JAR excludes test mods, fixtures, optional dependencies and pack binaries. The ZIP includes source, documentation and sanitized evidence only. Packaging validates metadata, ZIP CRCs, duplicate entries, forbidden cache/world directories, and exact JAR bytes; sibling `SHA256SUMS-M3.txt` records artifact hashes.
