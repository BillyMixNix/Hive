# Pre-edit diagnosis — HIVE-TRANSITION-003

**Classification: MIXED_INTERFACE_MODEL_FAILURE**

This artifact is written before any production edits. `evidence/pre-edit-seal.json` records its hash and verifies the copied production source still matches TRANSITION-002. It is not revised to fit the live result.

## Supported evidence

H1 in its strong form (no valid plan expressible) is falsified: a backend-only plan passes schema, normalization, ownership/host scope and reaches the real worker callback with zero model calls. Required facts and inactive-role instructions reached the historical model, yet both responses ignore exclusive ownership. That supports a model-compliance component.

A narrower H1 is supported: the generation schema admits all eight one-file ownership subsets, including four conflicting subsets that deterministic validation rejects. Both actual historical outputs pass their generation schema. Active/inactive consistency is left to prose. The three-role example and correction's rejected-role interface example plausibly reinforce unnecessary test work, but their probability effect is not established. EVAL-009 avoided this burden through predetermined children and explicit read/write separation; it is a contrast, not a controlled ablation.

The mixed diagnosis states an avoidable interface burden plus observed noncompliance. It does not assert that model quality is the general cause, that read access itself grants ownership, or that representation alone explains the behavior.

## Smallest justified repair selected before editing

For an exact host scope containing **one distinct writable file**, the normal ownership rules already imply at most one active writing role. Encode this implication in the planner generation schema with complete alternative branches: each eligible role can be the sole writer while others have canonical inactive goals and empty file/acceptance arrays; include an all-inactive branch for the existing no-change representation. The model still selects the owner and supplies its goal/criteria; the host does not pick backend or resolve conflicts by role priority. Scope/path type/filename never determines a hardcoded J001 solution.

Preserve multi-file schemas and valid multi-role execution. Preserve normal validators unchanged; duplicate or contradictory outputs supplied through any path still fail. Preserve one correction, measured 12,288 context, truncate=false, output caps, baseline/candidate isolation and all gates. Keep initial/correction text unchanged to isolate the structural intervention. Correction minimum-contract constraints, when independently required by immutable intent, must apply to every alternative rather than be dropped.

Why bounded to one-file scope: that capacity constraint is logically fixed from authority alone and directly covers the observed failure. A general per-file owner-map redesign would alter every plan/worker contract and require migration. Per-role filename heuristics would invent authority/role policy. Large ownership partitions for arbitrary multi-file scopes would expand schema exponentially. None is needed for this experiment. The remaining multi-file overlap checks stay in validation.

## Competing explanation and falsification

Pure H2 remains plausible for why this particular response failed: the original prose is clear, and a valid plan is simple. The schema language mismatch alone does not prove a statistical cause. If the fresh constrained request still yields overlap, or merely changes to another contradictory/no-work plan, record that as no verified dispatch improvement and inspect actual schema/runtime support before declaring stronger H2. If a valid owner reaches a worker, that supports this narrow structural repair but not a software-task success or reliability claim.

The exact affected transition is **planner structured generation → ownership-consistent plan validation → dispatch eligibility**. Historical invalid outputs must remain rejected; any repair that accepts them or silently drops a writer falsifies the intended containment claim. Any loss of T001 scope or T002 context protections also invalidates the repair.
