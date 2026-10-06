# Pinned reconstruction dependency model

The JSON companion contains every native component (including command arguments), input file SHA-256, output identity and node dependency. All ten key SHA-1 values were independently recomputed. Tool coordinates are additionally bound to host-approved module bytes. Build scripts, Gradle properties, wrapper, verifier image/JDK and downloaded-input manifests remain host-pinned even where NFRT does not put them directly into a node key.

| Node | Previous nodes | Action | Native key |
|---|---|---|---|
| applyDevTransforms | copyUnpatchedClasses | ApplyDevTransformsAction | `1fb7697597d32e00b3f4c6820036207e18dd35a1` |
| binaryPatch | rename | ExternalJavaToolAction | `0397ce4e987718eba98aa47e8cfe282ddcbbb61d` |
| binaryWithNeoForge | applyDevTransforms | InjectZipContentAction | `15c9a101cab2c4626123fc498aae4071050aa518` |
| copyUnpatchedClasses | binaryPatch, rename | CopyUnpatchedClassesAction | `225df56b09fa183ed417b3752b9a6127159074ce` |
| extractServer |  | ExternalJavaToolAction | `3708c41639d60b56739a2bf9df29858932d3099a` |
| merge | stripClient, stripServer | ExternalJavaToolAction | `8503fda02cff83cf4896f8b254e4fde2d657ec61` |
| mergeMappings |  | ExternalJavaToolAction | `2100ae7c755bb34ac4545c9eeec4a90c42ad48c4` |
| rename | merge, mergeMappings | ExternalJavaToolAction | `1a893e034a07f18b78686946288be2d24ab3fcfb` |
| stripClient |  | SplitResourcesFromClassesAction | `2d7e78755d8b28f5d42c07f6d2b44b7f333acb44` |
| stripServer | extractServer | SplitResourcesFromClassesAction | `8bb3d3745bd6f4ac9d34d27c8a1809cf14c56fdd` |

The base graph comes from the exact NeoForm `config.json`; the NeoForge userdev config adds binary patching and dependency injection. `NeoFormEngine.runNode` collects input components and calls each action's `computeCacheKey`. `CacheKeyBuilder.addPath` hashes bytes; `addDataSource` hashes archive entries under a configured data path; `CacheKey.computeHashValue` hashes the sorted components. An annotation path is explanatory, not part of that key.

Pinned `ModDevArtifactsWorkflow.create` configures reconstruction before `addToSourceSet` adds its outputs to application compile/runtime classpaths. `CreateMinecraftArtifacts.createArtifacts` passes dependency coordinates, selected outputs, AT/II/Parchment files and options. `NeoFormRuntimeTask` supplies artifact-manifest files and the NFRT executable. None of the approved graph's input files or key components contains project Java sources.

This is not a claim that all Java or resources are independent in arbitrary Gradle builds. `DataFileCollections.create` automatically reads `META-INF/accesstransformer.cfg` under main resource roots if it appears. Explicit configuration can select arbitrary paths for transforms or injection, including a `.java`-named file. Such configuration must remain byte-identical, and measured reconstruction input files must not overlap the independently variable class. All resource/config additions remain conservative invalidations unless separately attested.

Parchment is disabled in the approved graph. Official and NeoForm mappings already participate in mergeMappings/rename. Enabling Parchment or changing mapping data cannot reuse this approved identity merely because the old ten filenames remain present. Candidate compilation and test source processing occur downstream; no candidate output is in these 22 dependency intermediates.
