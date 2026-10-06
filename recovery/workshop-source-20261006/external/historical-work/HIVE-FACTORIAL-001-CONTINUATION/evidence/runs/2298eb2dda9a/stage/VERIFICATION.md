# M3.2 verification — ATM Companion 0.3.2

## Environment

Target: **ATM10 8.2 / Minecraft 1.21.1 / NeoForge 21.1.251 / Java 21**. Windows x64. Builds/disposable servers used Microsoft OpenJDK **21.0.7+6-LTS**, Gradle **9.2.1**, ModDevGradle **2.0.147**, Mojang mappings and JUnit **5.11.4**. The graphical instance uses Adoptium **21.0.9+10-LTS**. Optional integration: FTB Quests/Library **2101.1.36**, Teams **2101.1.11**, Architectury **13.0.11**.

Ordinary `/quests` and `/next` now request fresh counts and five options without collecting thousands of unused task titles. Full debug observations remain separate. No progress cache, increased deadline, network telemetry or AI service was added. Existing recipe recovery and planning are preserved.

## Exact commands

From `ATM-Companion/`, using the Java 21 JDK and populated Gradle cache:

```powershell
.\gradlew.bat clean build runGameTestServer runQuestTestServer packTestJar '-Dorg.gradle.jvmargs=-Xmx512m' --console=plain
.\gradlew.bat runQuestTestServer -PquestProfile '-Dorg.gradle.jvmargs=-Xmx512m' --console=plain
python tools/collect-m32-evidence.py
python tools/package-m32-release.py
```

The profiling invocation was an earlier diagnostic experiment, not the final success gate. Its local JFR recording is excluded from the release.

The official pack was tested in separate `runtime-m3-atm10/`, replacing only the production Companion and test-only probe JARs between runs:

```powershell
& "$env:JAVA_HOME\bin\java.exe" '-Xms512m' '-Xmx4G' '-Datm_companion.questSmoke=true' '@libraries/net/neoforged/neoforge/21.1.251/win_args.txt' 'nogui'
```

This runs actual NeoForge production mode with official server-pack files, a synthetic logged-in player/team, a loopback-only dedicated server and a disposable world. Explicit property, marker, production-mode, dedicated-server and directory guards protect both probing and automatic shutdown. No launcher save is opened by the probe. `packTestJar` alone only compiles it. Test/probe classes and optional dependencies are excluded from the production JAR.

## Results

Final clean run: **BUILD SUCCESSFUL in 2 min 22 s**, exit 0, September 22, 2026 local time.

| Gate | Result |
| --- | --- |
| Clean compilation | Passed; `build/libs/ATM-Companion-0.3.2.jar` |
| Unit regressions | **130 tests, 19 suites, 0 failures/errors/skips** |
| NeoForge core, FTB absent | **26 required GameTests passed**, 13.11 s test execution |
| Real pinned FTB integration | **3 required GameTests passed**, 7.205 s test execution |
| Official ATM10 production server pack | 503 mods loaded; four of four overview requests available |
| Independent adversarial review | No blocking issue; [review](M3.2-ADVERSARIAL-REVIEW.md) |
| User's graphical ATM10 world | See [focused playtest record](docs/M3.2-REAL-PLAYTEST.md) |

The final clean run reused valid Gradle-cached unit results; revised unit sources executed in the preceding run. Both runtime harnesses ran afresh. Full-pack-tested and final-built production JARs have the same SHA-256: `393a37838bcaf9b962722b62e11df87e0ff1a6e64c0ed325cddd6a8223e21287`.

## Measured performance

Single-machine observations, not latency guarantees. The 250 ms deadline is cooperative and cannot interrupt one FTB callback, logging, GC or a JVM pause. Caller elapsed time may exceed it.

| Observation | Result / elapsed |
| --- | --- |
| Old 0.3.1, official book | Three timeouts: 255.7 / 250.3 / 250.1 ms; fourth incorrectly escaped the final budget check and returned available at 267.8 ms |
| New overview, official book | **92.2061 / 25.5552 / 43.6577 / 23.4683 ms**, all available |
| New full detail, official book | Three timeouts: 251.2 / 250.5 / 250.3 ms, then complete at **134.3676 ms** |
| Generated scale fixture overview | Cold **36.712 ms** before any full observation; all six summary samples available |
| Scale readiness probe | **0.0817 ms**, explicitly not a full observation |

The official book has **66 chapters, 4,790 quests, 6,024 tasks and 5,231 dependency references**. Overview counts agreed with the successful full snapshot in the same run. Synthetic team completion changed naturally between baseline and patched logins; those counts are not compared across versions or described as user progress.

The generated fixture adds 4,790 quests, 66 chapters and 9,580 item tasks via public FTB APIs, with dependency chains of at most eight quests. The final harness also contained 30 prior small-fixture quests. Its first overview must succeed, match full-snapshot counts and first-five IDs/titles, and immediately reflect partial progress, completion, team lock/unlock, title replacement and definition deletion. Temporary scale chapters are removed afterward; original 10 chapters/30 quests remain.

Full-detail requests separately record bounded attempts, require null data on unavailable results and require a complete fresh observation. After FTB definition-cache invalidation, at most four same-tick test attempts are permitted; production commands do not automatically retry full scans. Prior small-book full-detail assertions remain, including current-team changes and absent/unmapped players.

Scale serialization was measured separately: **6,911,411 bytes / 361.4682 ms**. This is a disposable diagnostic, not a production export. Exports remain paginated/bounded at 256 KiB; oversized reports are refused.

## Failed experiments and corrections

- An initial invocation misspelled the quest task as `runQuestGameTestServer`; the real task is `runQuestTestServer`.
- A preexisting core test attempted planning before staged startup indexing finished. Its fixture now waits at most 400 ticks for actual publication, preserving its original assertions.
- Formatting/regex optimizations alone failed the cold full-book scale test and a profiled repeat. Source inspection found costly lazy FTB title resolution; the small JFR sample did not establish its exact share of time.
- The final design uses a distinct overview for normal commands. The new scale test was revised to test that explicit contract, while retaining truthful full-debug timeout handling. A full-detail assertion after clearing FTB caches was corrected to verify bounded unavailable/null results followed by complete fresh data. No deadline was increased.

Excerpts are preserved in `evidence-m32/failed-experiments.log`. The new overview DTO, lazy optional gates, fixed-width IDs, unavailable graph semantics, same-tick progress freshness and existing M1/M2/M3 regressions are covered.

## Limits and release contents

**Cold full debug exports can still time out.** A retry reads current facts rather than a cached progress snapshot. Overview omits tasks/dependencies explicitly; its planning graph marks those details unavailable. Existing limits remain for custom task semantics, completed repeatable quests, cross-chapter links, strategic quest ranking, modded machines and storage. This hotfix does not claim a new broad recipe, deep-goal or multiplayer playtest. Historical recipe recovery evidence is preserved in [M3.1 verification](VERIFICATION-M3.1-0.3.1.md).

`evidence-m32/` contains sanitized logs, JUnit XML, bounded fixture aggregates, baseline/patched official-book measurements and source provenance. Releases exclude JFR files, caches, installations, full quest books, user saves, credentials and modpack binaries. The previous installed JAR is backed up outside the bundle. `SHA256SUMS-M3.2.txt` covers the release JAR and ZIP.
