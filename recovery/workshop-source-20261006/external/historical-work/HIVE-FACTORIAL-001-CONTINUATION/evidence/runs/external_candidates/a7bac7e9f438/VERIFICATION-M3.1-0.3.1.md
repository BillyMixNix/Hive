# M3.1 hotfix verification — ATM Companion 0.3.1

## Scope and environment

Target: **ATM10 8.2 / Minecraft 1.21.1 / NeoForge 21.1.251 / Java 21**. Windows x64, Microsoft OpenJDK **21.0.7+6-LTS**, Gradle **9.2.1**, ModDevGradle **2.0.147**, official Mojang mappings, JUnit **5.11.4**. Optional integration versions remain FTB Quests/Library **2101.1.36**, FTB Teams **2101.1.11**, Architectury **13.0.11**.

This patch addresses the actual user-reported 0.3.0 startup failure. The screenshot and read-only client log showed a failed generation after its first selection slice; goal/debug-plan queries then threw `IllegalStateException`. Inspection of the installed Ars Unification **1.2.21** bytecode established that its first player-sync handler replaces the recipe table at LOWEST event priority. Companion previously treated that expected replacement as permanently fatal. See [the diagnosis](docs/M3.1-STARTUP-RECIPE-RESEARCH.md).

During the hotfix build, only the workspace source and disposable harnesses were changed. In a subsequent user-authorized playtest, ATM10 was saved and closed through its UI, the existing JAR was backed up, the checksum-verified 0.3.1 JAR was installed, and the same world was reopened. The requested goal was set through the normal command. No crafting, item transfer, quest completion or direct world-file edit was performed. See [the focused actual-instance record](docs/M3.1-REAL-PLAYTEST.md).

## Exact commands

From `ATM-Companion/`, with `JAVA_HOME` selecting the installed Java 21 JDK and `GRADLE_USER_HOME` selecting its populated cache:

```powershell
.\gradlew.bat compileJava test '-Dorg.gradle.jvmargs=-Xmx512m' --console=plain
.\gradlew.bat clean build runGameTestServer runQuestTestServer packTestJar '-Dorg.gradle.jvmargs=-Xmx512m' -PtestServerHeap=1G --console=plain
python tools/collect-m31-evidence.py
python tools/package-m31-release.py
```

The smaller heaps reduce contention with the user's open game. Test servers run sequentially in separate disposable worlds. `packTestJar` compiles the optional full-pack probe; it does not execute a full ATM10 test and is excluded from the release JAR.

## Results

The targeted compile/unit invocation completed **BUILD SUCCESSFUL in 56 s** and executed all 119 unit tests. The final clean build completed **BUILD SUCCESSFUL in 4 min 2 s**, exit code 0, on September 22, 2026 local time. Its `test` task reused those valid Gradle-cached results; both NeoForge runtime servers executed afresh.

| Gate | Result |
| --- | --- |
| Clean compilation and production JAR | Passed; `build/libs/ATM-Companion-0.3.1.jar` |
| Unit regressions | **119 tests, 17 suites, 0 failures/errors/skips** |
| NeoForge core/FTB-absent runtime | **26 required GameTests passed**, including all three new recovery scenarios |
| FTB-present runtime | **2 required GameTests passed** with pinned real optional mods |
| Independent adversarial review | No blocking issue found; conclusions and coverage limits in the separate review |
| Actual graphical ATM10 0.3.1 playtest | **Startup recovery and already-owned goal/next verified**; FTB query exceeded its time budget twice |

The compiler emitted one deprecation warning for the test-only `makeMockServerPlayerInLevel` fixture helper. The production mod has no dependency on that helper. Runtime warnings about 0.3.0 → 0.3.1 reflect upgrading the disposable test-world metadata; both suites passed. No production or regression failures occurred in this hotfix run.

The evidence collector validates success markers, mod version and unit totals. `evidence-m31/` includes the executed unit log, final clean log, JUnit XML, suite summary and synthetic snapshot/recipe/plan/quest exports. Test classes, full-pack probe code, Minecraft installations, modpack binaries and caches are excluded from the production JAR/release bundle as applicable.

## What the recovery tests establish

Three additional NeoForge GameTests use actual `RecipeManager.replaceRecipes`, the real event bus, LOWEST-priority sync listeners and native server ticks. They verify:

- First-player sync followed by a same-count table replacement during an incomplete index, and eventual publication of the changed ingredient facts without `/reload`.
- New-count replacement after a completed generation; the held old DTO remains immutable and is never served as current knowledge.
- Ten successive replacements reset stabilization; repeated same-tick queries cannot hasten recovery or allocate new generations.
- Global null-player sync followed by a late LOWEST replacement also recovers.
- Eight interrupted automatic build starts stop at the documented cap and remain failed across additional ticks.
- A continuously changing table stops waiting after 1,200 actual server ticks, rather than waiting indefinitely.
- Real recipe command dispatch gives bounded, useful recovery guidance; terminal failure gives log/reload guidance without claiming that waiting will fix it.

The previous stale-index/cancellation test retains its stale-data rejection assertions but expects `recovering` instead of permanent `failed` for a recoverable table replacement. Prior M1/M2/M3 tests are preserved, including allocation, cycles, limits, optional-mod absence, goal persistence, reload, actual vanilla station/fuel observations and output bounds.

The core harness has no FTB Quests installed. The separate quest harness loads the pinned real optional mods with synthetic quest/team fixtures. Neither certifies every ATM10 recipe or quest.

## Recovery behavior and review limits

Freshness guards run before and after each index slice and before serving knowledge. A replaced manager/table or changed count clears stale state immediately. Automatic rebuilding begins after 20 unchanged server ticks; successful publication resets recovery budgets. Recovery is limited to eight unsuccessful starts and 1,200 ticks per continuous stabilization wait. Actual extraction/inspection exceptions remain terminal and logged. Commands do not perform indexing work.

Independent review: [M3.1-ADVERSARIAL-REVIEW.md](M3.1-ADVERSARIAL-REVIEW.md). Reentrant/mid-slice replacement guards and unrelated extraction-error paths are source-reviewed, not individually fault-injected. In-place mutation inside an existing third-party recipe object remains outside the identity/count guard. Cooperative slice limits cannot interrupt one slow mod callback.

## Measured harness behavior

Single-run measurements, not full-pack benchmarks or latency guarantees:

| Measurement | Observed value |
| --- | --- |
| Core initial index | 1,294 definitions; 842 outputs; 123 ms active, 1,832 ms elapsed, 29 slices, 5 ms maximum slice |
| Login-replacement recovery index | 1,294 definitions; 44 ms active, 158 ms elapsed, 19 slices after stabilization |
| Subsequent new-count/noisy/reload recoveries | 1,295 definitions; 31–37 ms active, 62–81 ms elapsed, 19 slices |
| FTB initial index | 1,298 definitions; 846 outputs; 185 ms active, 2,246 ms elapsed, 38 slices, 15 ms maximum slice |
| Continuous-change cutoff | 1,200 actual server ticks; 1,201 observed changes; zero automatic build starts |
| Interrupted-build cutoff | Exactly eight automatic starts; remained failed across 45 additional ticks |

The GameTest server accelerates ticks, so the 1,200-tick fixture does not take one minute of wall time. Recovery index timings start at fresh-job creation and exclude its preceding 20-tick stabilization interval. The cooperative five-millisecond target can be exceeded by one callback or a JVM pause, as the observed 15 ms FTB slice illustrates. Planner logic is unchanged; no new full-pack planner latency claim is made.

## Actual ATM10 playtest and remaining limits

**A focused actual ATM10 8.2 graphical-client playtest was subsequently completed at the user's request.** Actual Ars Unification first-login processing replaced the table; Companion invalidated generation 1, automatically rebuilt generation 2 and published 50,000 of 97,050 definitions across 39,992 output IDs. No manual `/reload` was used. Build time was 87,286 ms elapsed / 4,963 ms active across 1,135 slices; the maximum observed slice was 204 ms, demonstrating the remaining cooperative-budget limitation.

`/companion knowledge` returned the completed index. `/companion goal minecraft:diamond_pickaxe` and `/companion next` returned `already_owned` / `not_needed`, because the requested item was already in the inspected main inventory. This does **not** validate a nontrivial recipe-dependency path in that world. Both next-action attempts reported FTB quest data unavailable after exceeding the 250 ms collection budget. No quest availability or recommendation was established. The bounded record contains no raw world snapshot, player identity or coordinates.

The 0.3.0 isolated official production-server probe remains historical evidence only: 503 mod entries, 95,229 recipes, 50,000 retained, 811 slices, 1,663 ms active and 55,595 ms elapsed. It had no real player login, so it did not exercise the late-modification path. Its original records are preserved under `evidence-m3/` and [VERIFICATION-M3-0.3.0.md](VERIFICATION-M3-0.3.0.md); they do not certify this hotfix. Current results are stored separately under `evidence-m31/`.

Recipe/planner coverage is otherwise unchanged. Custom machines, power, fluid semantics, external storage and modded access permissions remain unsupported. Empty-inventory heuristic paths can prefer unhelpful repair/conversion routes; this patch repairs knowledge availability, not strategic acquisition ranking.

## Repeatable focused check

Close the instance, replace the old Companion JAR with **ATM-Companion-M3.1.jar**, and keep only one version. Re-enter the same world and leave it unpaused. `/companion knowledge` may show building or recovering before a completed generation; large packs can take tens of seconds. It should not remain failed because the table changed during login. Then retry `/companion goal minecraft:diamond_pickaxe`, `/companion next`, and (with operator permission) `/companion debug plan`. Compare `/companion stations` near the same vanilla workstations. Report the knowledge status and a plan export if another failure appears.
