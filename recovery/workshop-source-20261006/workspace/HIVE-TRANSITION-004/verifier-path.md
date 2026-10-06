# Actual verifier path and wall-time boundaries

This trace was recorded before observability edits. Paths refer to the isolated copy of the byte-identical TRANSITION-003 source.

```text
workshop/hive.py::_run_build_impl.run_worker
  _prepare_agent_edits -> snapshot -> _write_pending_edits
  asyncio.to_thread(targeted_verify, stage, role, pending paths)
    targeted_verify -> _external_verification_guard
      workshop/hive_verifier.py::targeted_verify_isolated(timeout=240)
        run_isolated
          inspect Gradle wrapper / profile; validate frozen manifest
          resolve approved wrapper/modules caches
          docker image inspect [8-second subprocess budget]
          mkdtemp -> copy_external_verification_input (sanitized source + frozen test)
          validate/hash approved NeoForm input inventory; prepare mounts/payload
          subprocess.run(docker run ..., timeout=240) [OUTER DEADLINE STARTS HERE]
            image entrypoint verification/runner.py::main
              verification/jvm_runner.py::run_jvm_profile
                copy source -> /work/candidate
                validate frozen test bytes, required class/cases, full-task policy
                copy approved wrapper distribution -> private Gradle home
                hash/copy approved NeoForm assets/artifacts into private tmpfs
                construct fixed Java environment
                _bounded_process(java -version, timeout=15)
                snapshot source/runtime hashes -> remove generated build outputs
                _bounded_process(Gradle test --tests <frozen class>, timeout=240)
                  Popen -> two pipe-drain threads -> process.wait
                collect/parse bounded JUnit XML; require exact cases and no failures/skips
                check network-attempt signatures and source immutability
                return report -> runner prints final JSON -> container exits
          parse report, combine exit status with pass flag, revalidate cache
          on outer timeout: discard partial capture -> docker rm -f -> fail
          finally remove sanitized temporary source
    return checks
  on failure restore exact pending file bytes -> bounded correction
  reject repeated proposal -> skip full gate -> reviewer -> rejected run
```

Substantial time can be spent before the outer 240-second timer: host wrapper/cache validation, full asset hashing, source copying, Docker image inspection. Substantial time inside it includes container startup, source and wrapper copying, roughly 914 MB of manifested NeoForm input verification/copy (per historical accepted evidence), Java startup, Gradle startup/configuration, offline artifact reconstruction, compilation, test process execution/shutdown, XML and source hashing. The code alone does not assign durations to these phases.

`--offline`, `--network none`, two CPUs, 448 PIDs, 4 GiB RAM/no extra swap, max two Gradle workers and 768 MiB Gradle heap are unchanged controls. Module resolution can still perform local work; offline mode is not evidence that it was fast. Container/Java limits do not prove absence of host contention.

There are nested 240-second deadlines. The outer deadline includes setup; the inner starts at Gradle invocation. This explains why an outer timeout can erase the inner report, but does not by itself prove the budget is inadequate or a runtime defect.

Observability will label actual function boundaries, process/output observations and task log markers. A Gradle `> Task` line will be labeled a marker, not invented as a precise start/end event. Container and host monotonic clocks must remain separate clock domains. Output and events are diagnostic data, never acceptance evidence by themselves.
