"""Write new recovery documentation only, never edit archived artifacts."""
from snapshot import *

def main():
 s=json.loads((OUT/'MANIFEST-SUMMARY.json').read_bytes());t=json.loads((OUT/'SOURCE-AND-TESTS.json').read_bytes());a=json.loads((OUT/'INTEGRITY-AUDIT.json').read_bytes())
 assert a['passed']
 counts=t['historical_pytest_counts']
 reasons='\n'.join(f'| `{k}` | {v:,} |' for k,v in sorted(s['excluded_reasons'].items()))
 text=f'''# Workshop source recovery — 2026-10-06

This is a byte-preserving archival recovery. No Hive source was edited, no tests or experiments were rerun, no model was called, and no candidate was promoted. Original reports and frozen evidence retain their original bytes and classifications. The snapshot is additive; inherited repository files are unchanged.

## Roots and Git provenance

- Original workspace: `{WORKSPACE}`.
- Current source: `workspace/HIVE-THINKING-POLICY-001/repaired-workshop/` in this archive.
- Original workspace/current-source Git commit and branch: **none — not a Git repository**.
- Separate nearby backlog checkout: `f65eebd0d1bcbab4e4ecd151f371b987191bf749`, branch `main`, clean at inspection. It is not provenance for the current unversioned Workshop source.
- Destination: `BillyMixNix/Hive`, new branch `recovery/workshop-source-20261006` only.
- New branch parent: `9a4c6436899e24f9bdee216d837c490ffc5d69ca` (existing recovery staging lineage). PR #36 and its branch are not updated.
- Remote main observed before recovery: `f6f0f8dbf998be53199ec9fe32c77eb9b52bc585`.
- All source roots and their original absolute paths: [SOURCE-ROOTS.json](SOURCE-ROOTS.json). Git status, tracked/untracked/ignored lists where Git exists, including generated fixture repositories: [GIT-STATE.json](GIT-STATE.json). Non-repository files are explicitly inventoried as unversioned.

## Deterministic identities

- Original workspace tree SHA-256: `{s['roots']['workspace']['sha256']}`.
- Full inventory manifest SHA-256 (uncompressed JSONL bytes): `{s['manifest_sha256']}`.
- Included source/evidence tree SHA-256: `{s['included_tree_sha256']}`.
- Latest historical source freeze hash: `{t['freeze_source_hash_claim']}`. Its historical algorithm differs from the archival tree algorithm; the per-file comparison is in SOURCE-AND-TESTS.json.
- Inventoried files across all selected roots: {s['all_files']:,}; included: {s['included_files']:,}; excluded: {s['excluded_files']:,}.
- Included source/evidence bytes: {s['included_bytes']:,}.

The archival tree hash is SHA-256 of compact UTF-8 sorted-key JSON mapping relative paths to `{{sha256,bytes,type}}`. Link hashes cover the link target string, not dereferenced content. JSONL manifests are sorted by archive path. The archive does not claim to preserve NTFS ACLs, creation times, empty directories, or Git executable bits for originally unversioned Windows files.

Full manifests and per-file exclusion reasons are provided as deterministic gzip JSONL files when size requires compression; MANIFEST-SUMMARY.json identifies their storage names and hashes. Original bytes are never redacted or rewritten: a secret-bearing file is excluded as a whole.

## Exclusions

| Reason | Files |
|---|---:|
{reasons}

Excluded classes include `.env`/credential files, private application state/databases, Git internals, caches, downloaded dependencies and NFRT intermediate files, model weights, generated build/compiled outputs, regression scratch, and opaque archives. The approved attestation, provenance, recipes, manifests and dependency identities remain where available. Gradle wrapper bootstrap JARs are retained as checked-in build tooling, not candidate compilation output. Exact exclusions are in EXCLUDED-FILES.jsonl (or its `.gz` storage form). Content scanning and manual review results are recorded separately without credential values.

## Tests available; none run during recovery

- Current Workshop: {t['test_module_count']} Python files under tests, {t['test_function_definitions']} statically identified test-function definitions. Parameterization means this is not a collected-case count.
- Preserved latest regression XML: {counts['passed']} passed, {counts['skipped']} skipped, {counts['failures']} failures, {counts['errors']} errors. These are **historical results**, not a new validation claim.
- Qualified measurement-harness tests and their historical reports are preserved.
- Frozen J001–J004 acceptance sources and task definitions are archived under `external/historical-work/HIVE-FACTORIAL-001/`.
- Frozen M3.2 baseline includes Java/Gradle source, wrapper configuration/bootstrap and {len(t['baseline_java_test_sources'])} Java files under src/test.
- Static inventory and hashes: [SOURCE-AND-TESTS.json](SOURCE-AND-TESTS.json).

## Source completeness and remaining gaps

| Area | Recovery status |
|---|---|
| FACTORIAL-002 | Original controller, frozen study metadata and non-secret run evidence recovered under external/historical-work/HIVE-FACTORIAL-002. |
| TRANSITION-003 | Source and evidence recovered under workspace/hive-transition-003 (original case preserved). |
| 003R1 | HIVE-FACTORIAL-003R1 source and evidence recovered. No separate directory named HIVE-TRANSITION-003R1 was located; that distinct identifier is unverified. |
| TRANSITION-004 / 004B / 004C / 005 | Original source copies, reports, verifier/attestation code and non-secret evidence recovered. |
| Java/Gradle verification | Frozen baseline, acceptance sources, Java-edit apparatus, verifier recipes and controller code recovered. Docker/JDK/model binaries, downloaded Gradle dependencies and NFRT cache payloads are deliberately excluded. |
| Decomposition | Current planner normalization, ownership, dispatch and replanning implementation is in workshop/hive.py and hive_protocol.py. No separate decomposition module is required by this located implementation. |
| Promotion / apply | Current explicit-human apply guards, stale/scope/integrity checks and reviewer policy recovered. A separately named promotion-bundle exporter was not located; its existence/completeness cannot be asserted. The inherited older grow/kernel/promotion.py is lineage evidence, not a substitute. |
| Reviewer/provider policy | hive_review.py, providers.py, thinking_policy.py and profiles, their tests, and preserved policy reports recovered. |

No located current frozen source file may be silently missing: SOURCE-AND-TESTS.json lists every expected freeze file and any mismatch. Historical absolute paths are intentionally unchanged. SOURCE-ROOTS.json supplies relocation mapping; no configuration was rewritten for portability. This is source/evidence recovery, **not a self-contained offline runtime backup**. Reconstructing the runtime requires the separately managed pinned images, tools, dependencies, model weights and attested cache contents.

The archive contains hidden acceptance sources and historical candidate evidence. It is not a model workspace or model context. Future experiments must isolate their designated baseline/task context using the preserved policies.

## Preservation audit

Rehashed {a['files_rehashed']:,} original files and {a['copies_rehashed']:,} included copies. Original additions/removals/hash changes: zero. Copy hash mismatches: zero. See [INTEGRITY-AUDIT.json](INTEGRITY-AUDIT.json). Source files were not imported or executed.

Git stores recovered bytes without clean filters or line-ending conversion. For a byte-identical checkout use `git -c core.autocrlf=false clone ...` or extract Git blobs/archive without text conversion. Recovery tooling is included separately; it is not part of Hive production source.

## Push boundary

Only `refs/heads/recovery/workshop-source-20261006` is authorized for this operation. No force push, no changes to main, PR #36 or existing experiment branches, and no production application/promotion. This report is prepared before pushing; the resulting commit and remote verification are reported by the recovery operation.
'''
 (OUT/'README.md').write_text(text,encoding='utf-8',newline='\n')
 (OUT/'PRE-PUSH-REPORT.md').write_text(text.replace('# Workshop source recovery — 2026-10-06','# Pre-push recovery report — 2026-10-06',1),encoding='utf-8',newline='\n')
 print('Reports written')

if __name__=='__main__':main()
