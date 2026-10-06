# Proposed bounded generalization

This is a design pending completed measurements and a sealed diagnosis, not an installed production policy.

The candidate generalization is a new host-pinned attestation version describing a **reviewed main Java source-set class**, rather than a list of application filenames. The class comes from the actual Gradle source-set roots in a pinned measured build. Only regular `.java` files below those roots may vary. Source additions/deletions can be admitted only if the package-addition measurement and source review establish that membership is independent too. All other repository files and their membership remain fixed.

Authorization relies on the conjunction of (1) a reviewed fixed build/plugin implementation, (2) measured reconstruction input files/options and dependency graph, (3) no intersection with the independently compiled source class, (4) immutable build/config/resources and tool/dependency bytes, (5) approved baseline priming and complete seed hashes. It does not rely on the file suffix alone, Gradle's declared inputs alone, or NFRT cache existence.

The source review examines both build scripts and pinned implementation: application compilation consumes reconstruction outputs; reconstruction has no project compilation dependency or application-source read. `DataFileCollections`' resource auto-discovery means an AT addition invalidates the attestation even without a build-script edit. Explicit transform/injection/mapping configuration can select arbitrary files, including Java-named files; a measured input overlap invalidates the proposed independent-source authorization.

The v1 format must remain supported with its original narrower semantics. A v2 manifest must have explicit source-class evidence, measured main roots, no reconstruction task prerequisites, pinned input snapshot and sealed review/model references. Ambiguous mixed v1/v2 source policies are rejected. The host pins the whole manifest; candidate code cannot assert or select these privileges.

Test Java and ordinary application resources may prove independent in individual probes. They remain fixed in this minimal repair: no generalized resource or test-source allowance is needed to address independently compiled main application sources. Resources in particular contain known reconstruction-sensitive paths. Unknown changes outside the reviewed class fail closed.

Seed generation, inventory, byte hashes, namespace checks, priming provenance, module/download hashes, image/JDK and Gradle profile checks, private-copy behavior, fresh compilation, offline mode, rerun/no-build-cache flags and acceptance remain unchanged. No task ID or application filename belongs in production authorization logic.
