# Exact verifier environment acquisition

001B sealed the currently usable host environment in `recovery/rc1-closure/environment/ENVIRONMENT_MANIFEST.json`: image ID `sha256:b71e6beae584a3bba27e6fe782a27ef971b481b1dff7226bc57f28626843ad26`, Temurin 21.0.12.1+1 inside that image, Gradle 9.2.1, pinned modding dependencies, and 4,866 selected cache files totaling 1,438,483,301 bytes. The prior fresh-root copy verified every selected file and its provenance. That is relocation of approved bytes, not independent acquisition.

For 001C a separate empty temporary acquisition root downloaded **only** `https://services.gradle.org/distributions/gradle-9.2.1-bin.zip`. The versioned URL redirected through the Gradle v9.2.1 GitHub release asset; HTTP 200 returned 135,535,598 bytes in 81.822 seconds. SHA-256 was `72f44c9f8ebcb1af43838f45ee5c4aa9c5444898b3468ab3f4af7b6076c5bc3f`, byte-identical to the frozen wrapper distribution ZIP identity. The sanitized acquisition record is preserved in `recovery/rc1-replay/gradle-acquisition.json`. The transient signed redirect query and ZIP binary are not committed. No model or task content was sent.

| Artifact | Acquisition classification | Exactness result |
| --- | --- | --- |
| Gradle 9.2.1 distribution ZIP | INDEPENDENTLY_REACQUIRABLE | BYTE_IDENTICAL SHA-256; extracted 314-file wrapper tree not independently requalified |
| Exact verifier image and Temurin JDK | HOST_LOCAL_ONLY for exact image ID | Dockerfile overlay chain uses a local parent, mutable base tag and unpinned apt/pip inputs; exact independent rebuild unproven |
| Gradle `modules-2` cache, 635 files | HOST_LOCAL_ONLY as sealed inventory | Hash-verified relocation only |
| NFRT artifacts/assets, 3,895 files | HOST_LOCAL_ONLY as sealed inventory | 3,894 recorded URLs, one binarypatcher fat JAR without URL; mutable launcher manifest exists; no complete independent fetch |
| NFRT intermediate results, 22 files / ten nodes | HOST_LOCAL_ONLY | Reconstructability from exact immutable inputs unproven |
| Approved NFRT attestation/provenance | Recovered host-authored manifests | Hash-bound; payload files still host-local |
| Host Python runtime and required installed packages | HOST_LOCAL_ONLY, byte-attested for bounded replay | `PYTHON_RUNTIME_MANIFEST.json` seals executable, runtime DLL, stdlib/DLL trees, installed file inventories, exact import-path tail, startup hooks and startup environment; entry path must be inside the checkout and user-site is rejected. No independent wheel reacquisition |
| Minecraft/modding distributions | Mixed upstream URLs; redistribution/license status unverified | Do not commit binaries or claim clean-machine reproducibility |

No substituted image, cache file or functionally equivalent binary is accepted as byte-identical. The exact environment cannot presently be reacquired on a clean machine. This supports a narrower host-bound replay only, with every selected cache hash, exact cache layout, Python runtime identity and the actual container launch image bound before model execution. Portable readiness remains **NO**.
