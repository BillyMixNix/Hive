# Pre-edit diagnosis — source-class attestation limitation

**Diagnosis: the one-file allowance is narrower than the reconstruction dependency boundary established for the pinned build.** This is a host attestation-policy limitation, not evidence that other application source changes require Minecraft reconstruction.

The completed offline input-only probes show equal captured reconstruction properties, 131 artifact identities/content hashes, runtime executable input, optional input collections, task dependency graph and output selection for all ordinary main-Java changes, all four authorized task scopes, an unrelated Java file and a new application package/class. The pinned build scripts and plugin/runtime implementation do not read application Java source during reconstruction. `createMinecraftArtifacts` has no project compilation prerequisite. Its outputs become application compilation dependencies, in that direction only.

The positive evidence is stronger than suffix matching: the full build/configuration is fixed and reviewed; the main Java root is measured; native input files and archive components are independently identified/hashed; no root/input overlap exists; every other repository byte and the tool/download identities stay bound. A new build with source-reading logic requires a new attestation. It cannot inherit this authorization from directory names alone.

## SAFE_INDEPENDENT_VARIATION

Regular `.java` source contents and membership under the **attested, measured main Java source roots of this fixed build**, subject to unchanged non-Java files/build logic and no reconstruction-input overlap. This includes multiple files and package additions. Compilation and all tests remain fresh, so syntactically invalid or incorrect source can pass dependency compatibility but must still fail compilation/acceptance. Dependency compatibility is not candidate correctness.

## RECONSTRUCTION_RELEVANT

Dependency coordinates/content, NeoForge/NeoForm data and binary patches, ModDevGradle/NFRT implementation, mappings and reconstruction options, selected output graph, access transformers (including resource auto-discovery), explicit interface injection, Parchment settings/data, Java/toolchain/image and Gradle wrapper/profile. Changing AT, interface injection, Parchment or a binary output option changed measured inputs. The unavailable changed NeoForge artifact, if unresolved offline, is unknown rather than an equal-input result. All such changes invalidate reuse.

## CONSERVATIVELY_UNKNOWN / fixed by this repair

Test source, non-main source sets, application resources, unknown repository additions, arbitrary configuration/build-script edits and properties stay fixed. The particular harmless test/resource/comment/property/dependency probes can leave the reconstruction snapshot unchanged; that does not authorize arbitrary variation in these classes. Main resource roots contain an automatically discovered AT path. Source-reading build logic or a Java-named transform is possible in other configurations. Restricting this repair to reviewed main-source variation is deliberate.

## Smallest justified repair

Add a versioned, host-pinned source-class attestation while retaining v1's exact narrow semantics. The new manifest records measured main roots and reviewed independence, normalized reconstruction inputs and sealed evidence hashes. Reject overlapping reconstruction inputs, missing/ambiguous proof and mixed policies. Compare the full candidate inventory after excluding only qualifying regular main `.java` source files. Every other path/hash must still match. Keep seed provenance, every seed/module/download hash, image/profile bindings, private copy, contamination checks, fresh compilation and gates untouched. No benchmark task/file names enter policy logic.

## Competing explanation and falsification

Equal declared task inputs alone might miss an undeclared source read. The pinned build/plugin source review and absence of a compilation prerequisite address that possibility; no universal theorem about Gradle is claimed. A reproducible change of the reviewed main source class that changes reconstruction inputs/node keys, a hidden source-consuming build action, a qualifying path also selected as transform/mapping data, tool bytes not bound by approved manifests, candidate outputs in the seed, or any shared writable intermediate path would falsify applicability. New source/addition real controls must still show ten hits, fresh main/test compilation, actual frozen decisions and source immutability before readiness can be declared.

This diagnosis is sealed before production edits. No task inference, factorial or promotion occurred. The earlier factorial remains invalid and all historical results remain unchanged.
