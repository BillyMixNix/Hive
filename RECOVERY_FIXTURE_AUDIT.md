# Archived Workshop fixture provenance

The archived FACTORIAL-003R1 Workshop suite initially had 602 passed, 8 skipped, and 11 `FileNotFoundError` failures. Three unchanged test modules resolve `evidence/...` beneath their own experiment directory. FACTORIAL-003R1's frozen source was copied from NFRT-ATTESTATION-002, but its seven sibling evidence files were not copied. The FACTORIAL-003R1 `FREEZE.json` names that source origin and its source-inventory SHA-256 (`36c63c2bad271e4e2e11318a2f1b1f308c3c847b3f3155713e268e7e8b55d21b`) matches the committed source inventory. The three requesting tests are byte-identical in both experiments. These facts establish path drift and exact original fixture identity; no fixture was inferred from prose.

`RECOVERY_FIXTURE_MAP.json` records each requesting test, semantic purpose, source and destination prefix, exact SHA-256, and disposition. All seven distinct files are `EXACT_FIXTURE_IDENTITY_PROVEN_AT_OTHER_PATH`; together they account for all 11 failing test invocations:

| Missing historical fixture | SHA-256 prefix | Failing invocations |
|---|---|---:|
| `ownership-historical-replay.json` | `3b859a77` | 1 |
| `ordinal-03/planner-1.response.txt` | `12ddb25f` | 3 |
| `ordinal-03/planner-2.response.txt` | `64cba174` | 1 |
| `planner-input-fixtures/01/request.json` | `5f1fffd5` | 1 |
| `planner-input-fixtures/02/request.json` | `9d64793c` | 2 |
| `planner-input-fixtures/run.json` | `4deb228a` | 3 (one also reads the 02 request) |
| `live/01-J001-r1-qwen2.5-coder-14b-hive/run.json` | `a860c8b9` | 1 |

The [recovery-only resolver](recovery/rc1-closure/fixture_resolver.py) reads exact raw bytes from committed Git blobs at anchor `dd5db71`, validates the reviewed mapping SHA, source SHA, destination path and existing bytes, and writes only into a separate isolated test worktree. It rejects unmapped, ambiguous, missing, substituted, traversal, and symlink/junction destinations. [Materialization evidence](recovery/rc1-closure/fixture-materializations.json) records seven source/destination identities and hashes. The frozen tests, source corpus, and historical manifests were not modified. The isolated archived suite then reported **613 passed, 8 skipped, 0 failed** in 79.30 seconds.

The recovered bytes are historical test fixtures, not runtime authority and not model-visible context. The recovery harness does not rescore any factorial or transition outcome.
