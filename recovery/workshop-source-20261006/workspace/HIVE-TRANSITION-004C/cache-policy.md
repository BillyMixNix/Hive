# NFRT dependency-intermediate policy (before production edits)

Only a host-approved, SHA-256 pinned attestation can enable reuse. A seed is not trusted because NFRT accepts its filenames or cache keys. With no configured attestation, the existing verified-download/reconstruction path remains in force. Partial configuration, a missing configured seed, corruption, additional files, or incompatibility is a verification failure; no fallback to another seed is allowed.

## Trust boundary

The attestation binds the immutable baseline identity, exact JVM verifier image (therefore JDK/tool environment), frozen Gradle profile/wrapper, the sealed priming provenance and complete priming inventory, the downloaded-input manifest, a measured reconstruction-input description, and a complete source-file inventory. Only explicitly attested existing application Java files shown not to participate in reconstruction may differ from that inventory. All other files, including build scripts, settings, properties, wrapper, resources, access transformers, mappings, interface-injection data, Parchment configuration, and source-generation configuration, must match. Additions and deletions invalidate compatibility. This is deliberately bounded reuse, not a claim about arbitrary Gradle builds.

The approved priming inventory binds all tool/dependency files used by the measured build, including ModDevGradle 2.0.147, NFRT 2.0.31, NeoForge 21.1.251, mappings and tool classpaths. The preserved TRANSITION-004B task-input capture records 131 artifact identities and content hashes, native-cache options, binary reconstruction flags, Java/tool paths and absent optional inputs. Its digest and the ten NFRT cache-key records form provenance. Changing a participating build/tool input requires a new attestation; retaining an old filename/version is insufficient.

## Permitted seed

Only the attested flat `caches/neoformruntime/intermediate_results` inventory: NFRT node-key text records and the corresponding dependency output JAR/text files. Each file must also occur with the same hash and size in the sealed priming inventory. Every file is checked before use and after copying. JAR entries must not contain the application's package namespaces. Filenames, regular-file status, bounded sizes, exact membership and hashes are validated; links/reparse points are forbidden.

## Forbidden candidate results

No application or test classes, project build output, Gradle task history, incremental compiler state, JUnit XML, verifier result JSON, previous acceptance decisions, or candidate-specific generated sources may be seeded. Approved dependency intermediates do contain Minecraft/NeoForge dependency classes; these are not application classes. The attestation's reviewed provenance, strict inventory and application-namespace check distinguish them.

## Isolation and gates

Mount the approved intermediate directory and attestation read-only. Copy only verified intermediate bytes to the fresh container's private writable NFRT directory; NFRT may touch or replace this private copy. No shared writable cache or hard links. Recheck immutable source seed integrity after execution. Downloaded-input validation remains intact. `--rerun-tasks`, `--no-build-cache`, offline mode, source integrity, frozen assertions, compilation and targeted/full commands remain unchanged. The outer targeted deadline remains 240 seconds. A seed hit has no bearing on acceptance.

## Evidence and falsification

This policy is supported by TRANSITION-004B's sealed inventory, equal baseline/candidate reconstruction inputs, source inspection and ten observed NFRT cache hits. A build that reads one of the attested mutable sources during reconstruction, an unbound reconstruction input, candidate classes in a seed, or any writable shared mount would invalidate its applicability. New build configurations need a fresh measured compatibility review, not automatic eligibility.
