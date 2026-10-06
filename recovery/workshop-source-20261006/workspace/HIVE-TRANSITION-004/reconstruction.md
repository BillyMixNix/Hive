# TRANSITION-003 targeted-verifier reconstruction

Run **45ad10e6dd49**, preserved without edits. This reconstruction predates instrumentation changes. It separates recorded observations from reconstruction from the byte-verified executable source. A historical full argv/environment/process trace does **not** exist; unknown fields remain unknown.

## Observed

- [Applied diff](evidence/transition-003/applied-stage/first-applied.patch) and [file](evidence/transition-003/applied-stage/first-applied-SnapshotFormatter.java): only `src/main/java/dev/atmcompanion/state/SnapshotFormatter.java`. Applied SHA-256 `a3219f4e0b65847123f6cebc150dbe1a026690bf9887062c25c2941747fef242`; baseline file `5322a76cc496bdef8c6c5fb3d70ccd11004b076d6246cb7202874ca261255b98`.
- [Observation](evidence/transition-003/applied-stage/observation.json) at **2026-10-05 14:57:47.3258675Z** records the modified stage while container **hive-verify-4993c0baef72** was alive. This proves edit execution, not compilation/test execution.
- [Calls](evidence/transition-003/calls.json): initial backend finished approximately 14:53:32.632478Z (start plus recorded duration); targeted correction began **14:58:23.811728Z**. The interval is about 291.18 seconds, including host preflight, verification and cleanup. It is not a measured 291-second Gradle run. Exact Docker-launch/timeout timestamps are absent.
- [Run](evidence/transition-003/run.json): one targeted repair whose diagnostic has only `isolated_verifier=false`, `Isolated verification timed out after 240s.` Correction repeated the exact original proposal and was rejected. Final full gate was skipped, changed_files=[], applied=false, no frozen acceptance result. The stage file was restored, independently checked in TRANSITION-003.
- Frozen metadata pins image `nix-workshop-verifier:0.11.1-jvm21-extroot-002d-tmpfscopy`, ID `sha256:b71e6beae584a3bba27e6fe782a27ef971b481b1dff7226bc57f28626843ad26`, Gradle **9.2.1**, JUnit class **dev.atmcompanion.state.SnapshotFormatterUnicodeAcceptanceTest**, exactly **3 cases**, frozen source hash `80c1ced02955971cc827aed4e983d9407b919f47cc3af20f457f3a0f0098f159`.
- Post-hoc read-only inspection of that same image found its `runner.py` and `jvm_runner.py` byte-identical to preserved source. [Java observation](evidence/image/java-version.json): Temurin **21.0.12.1+1**. This is strong image-identity evidence, not a historical log proving Java was reached during the timed-out run.

## Reconstructed from preserved code, not historical phase observations

`hive.targeted_verify` passes the stage, empty changed-test selector, external_root=true, frozen JUnit artifact manifest, pinned JVM profile and baseline hash to `hive_verifier.targeted_verify_isolated`. That wrapper calls `run_isolated(..., mode='targeted', timeout=240)`.

The historical Docker argv shape is:

```text
docker run --name hive-verify-4993c0baef72 --rm
 --network none --read-only --cap-drop ALL --security-opt no-new-privileges
 --pids-limit 448 --memory 4g --memory-swap 4g --cpus 2
 --tmpfs /work:rw,nosuid,nodev,size=4g,mode=1777
 --tmpfs /tmp:rw,nosuid,nodev,size=128m,mode=1777
 --mount type=bind,source=<unrecorded sanitized temporary source>,target=/source,readonly
 <fixed environment and approved read-only cache mounts below>
 nix-workshop-verifier:0.11.1-jvm21-extroot-002d-tmpfscopy jvm-targeted <pinned JSON profile>
```

The sanitized temp directory was generated as `hive-verifier-input-*`; its exact absolute path and Docker executable resolution were not saved. The original stage was `HIVE-TRANSITION-003/evidence/live-diagnostic/runs/45ad10e6dd49/stage`. Host copying inserts the frozen test from its immutable artifact; container `shutil.copytree` materializes `/source` into `/work/candidate`.

Approved cache is the frozen `e5a7c314b902` cache identified in TRANSITION-003 preflight. Its `caches/modules-2` mounts to `/approved-gradle-cache/modules-2`; `wrapper/dists/gradle-9.2.1-bin` to the same suffix under `/approved-gradle-cache/wrapper/dists`; NeoForm `assets`/`artifacts` to `/approved-gradle-cache/neoformruntime/{assets,artifacts}`; its frozen manifest to `/tmp/hive-external-build-inputs.manifest.json`. All mounts are read-only. Wrapper and manifest-verified native inputs are then copied into disposable `/work/gradle-user-home`; module dependencies remain a shared read-only cache. These potentially substantial operations precede Java/Gradle.

Explicit Docker environment: HOME=/tmp/home, TMPDIR=/tmp, PYTHONDONTWRITEBYTECODE=1, JAVA_HOME=/opt/java/openjdk, GRADLE_USER_HOME=/work/gradle-user-home, GRADLE_RO_DEP_CACHE=/approved-gradle-cache, fixed JDK/system PATH, LANG=C.UTF-8, CI=true. Image defaults also include PYTHONUNBUFFERED=1, LC_ALL=en_US.UTF-8 and the pinned Java version. Host Docker-client environment is inherited and was not snapshotted; secrets/unrelated variables are not reconstructed or logged. No host environment is forwarded wholesale into Java.

Host `subprocess.run` specifies no cwd, so it inherits the invoking Python cwd; no historical cwd record independently confirms it. Image has no WORKDIR; entrypoint is `python3 /opt/verifier/runner.py`. Inner Java cwd is explicitly `/work/candidate`, with a constructed environment: JAVA_HOME, private GRADLE_USER_HOME, read-only cache root, HOME=/work/home, TMPDIR=/work/tmp, fixed PATH, LANG=C.UTF-8, CI=true.

Intended Java version command: `/opt/java/openjdk/bin/java -version`, timeout 15. Intended targeted argv:

```text
/opt/java/openjdk/bin/java -Djava.io.tmpdir=/work/tmp -classpath
 gradle/wrapper/gradle-wrapper.jar org.gradle.wrapper.GradleWrapperMain
 --no-daemon --offline --console=plain --max-workers=2 --rerun-tasks
 --no-build-cache -Dorg.gradle.jvmargs=-Xmx768m
 test --tests dev.atmcompanion.state.SnapshotFormatterUnicodeAcceptanceTest
```

No changed-file-based test reduction occurs: the fixed frozen class is the selector. `--no-daemon` requests no persistent daemon; a single-use JVM may still be forked to honor JVM settings. That occurred in historical independent accepted evidence but is not established for this timeout. Full gate would run `clean build runGameTestServer runQuestTestServer packTestJar` only after acceptance; it was never invoked here.

## Timeout, output, cleanup and rollback

Host `hive_verifier.run_isolated`: `subprocess.run(command, capture_output=True, text=True, timeout=240)`. Python kills/waits for its Docker CLI child when this expires. The handler catches `TimeoutExpired` **without binding the exception**, discarding its partial stdout/stderr, invokes `docker rm -f <exact name>` with timeout 10, ignores the removal result, rechecks approved-cache integrity and returns failure. `finally` removes sanitized input with `shutil.rmtree(..., ignore_errors=True)`. Complete container/descendant termination and cleanup success were not recorded.

Inside the container, `_bounded_process` drains both Java pipes on threads into 12,000-byte tails. The JVM profile passes no output observer, so those tails are only included in the final JSON report. The outer container kill can occur before inner Gradle's own 240-second timeout because container setup consumes outer time. `_bounded_process` kills only its direct process on inner timeout, waits without a bound, and joins readers for up to five seconds each; surviving descendants are not directly checked. This is a possible gap, not an established cause of the historical timeout.

`hive._run_build_impl.run_worker` snapshots files, applies pending scoped edits, awaits `targeted_verify`, and calls `_restore_pending_edits` on failed verification. It sends one normal targeted correction and rejects an identical effective proposal before rewriting/rechecking it. Full verification is then skipped for failed prerequisites. None of the buffered/partial output can legitimately establish PASS.

The historical record cannot distinguish copy, configuration, compilation, tests or a hang. New observed replays will test those hypotheses; they cannot retroactively add missing historical timestamps.
