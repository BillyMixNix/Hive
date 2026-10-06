# Downloaded-input materialization

The sealed manifest covers **3,895 files / 914,224,273 bytes**: six native artifacts (89,002,943 bytes) and 3,889 assets (825,221,330 bytes). The source is an approved Windows host directory bound read-only through Docker Desktop into Linux. The destination is each container's `/work/gradle-user-home/caches/neoformruntime` on private tmpfs. It is not a shared writable cache.

`verification/jvm_runner.py:_copy_external_build_inputs` validates the pinned manifest, inventories both source directories (including link/special-file checks), checks exact membership, stats each file, creates private parent directories, and hashes SHA-256 while copying in 1 MiB chunks. Host preflight also validates hashes outside the 240-second subprocess budget; that cost must be reported separately. Container inventory, metadata operations, reads, hashes and writes are all inside the measured copy phase. The phase total alone cannot separate those costs.

TRANSITION-004B's 72.900/75.023 seconds correspond to aggregate effective rates of 12.54/12.19 MB/s (decimal units), including all metadata/hash overhead. The first 004C integration run measured 72.91 seconds for the same phase before failing closed on a Python API incompatibility in newly added seed code. It is not evidence about compilation.

A blanket read-only native-cache substitution is unsafe: the exact pinned NFRT `ArtifactManager.download` calls `BasicFileAttributeView.setTimes` on existing artifacts and converts a general IOException into a runtime failure. The intermediate CacheManager also touches key records and performs cleanup. Assets have a different access path: `AssetDownloader` creates index/object directories and `DownloadManager` hashes an existing asset index before deciding whether to write. Whether all existing asset objects can safely be exposed read-only under the full gate requires a separate proof. No such substitution is made on the basis of the copy total alone.

Sources: `evidence/build-inventory.json`; pinned NFRT sources extracted without alteration under `evidence/upstream/net/neoforged/neoform/runtime/{artifacts,downloads}`; original downloaded-input validator retained in production. Measurements and any narrowly justified subsequent intervention will be added after compiler localization.

## Direct filesystem observation

The preserved-candidate container's `/proc/self/mountinfo` reports read-only **9p / DrvFS** mounts for approved dependencies, assets, intermediates and source, and **tmpfs** for `/work`. This confirms Windows/Linux filesystem crossing, rather than merely inferring it from a Windows path (`evidence/runs/seeded-preserved/runtime-observation-early.json`). No Docker Resource Saver setting was changed.

Final replay instrumentation separates source inventory from the artifact and asset copy groups, while preserving all checks and byte copies. The baseline alone spends about 31 seconds inventorying the native source before copying; the six 89 MB artifacts then copy in about 1.3 seconds. This directly identifies substantial per-file metadata overhead. The remaining group timings include open/stat/parent creation, reads, hashes and writes; they cannot isolate SHA cost or prove that every remaining second is filesystem latency. Complete values are in `evidence/timings.json`.

No materialization optimization is installed. Both the readonly approved source and private writable destination remain necessary under the current policy; the approved dependency bytes could potentially use another strictly verified transport in a future measured change. Directly sharing a writable native cache remains forbidden. This experiment's additional repair targets the separately observed discarded incremental compiler bookkeeping.

| Final control | Complete copy phase | Source inventory | Six artifact copies | 3,889 asset copies | Aggregate throughput |
|---|---:|---:|---:|---:|---:|
| Baseline | 83.720 s | 30.854 s | 1.314 s | 51.486 s | 10.92 MB/s |
| Preserved candidate | 80.210 s | 29.819 s | 1.057 s | 49.327 s | 11.40 MB/s |

The group durations exclude initial manifest parsing and rounding/observation differences. Inventory alone is roughly 37% of the phase. Large-file artifact throughput (about 68–84 MB/s) differs markedly from the many-file asset group (about 16–17 MB/s). That supports per-file overhead as a contributor, while file-size distribution, host contention and read/hash/write costs are not independently controlled here. Hashing remains required; it was neither removed nor moved out of the container copy path.
