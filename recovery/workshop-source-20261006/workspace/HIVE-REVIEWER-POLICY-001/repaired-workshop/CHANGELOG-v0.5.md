# Nix Workshop v0.5

Built from the Desktop `Nix-Workshop-v0.4.2.zip` source.

- Promotes the real FastAPI Workshop app to version 0.5.1.
- Adds health reporting at `/api/health`.
- Adds request-timeout-independent background job primitives with explicit planning, editing, testing, repair, approval, completion, failure, and cancellation states.
- Adds `/api/jobs/{job_id}` status and `/api/jobs/{job_id}/cancel` control endpoints.
- Adds bounded, relevance-ranked context retrieval and fail-closed structured JSON repair helpers for Hive workers.
- Preserves existing workspace path validation, snapshots, ledger, approval gates, budget controls, and loopback-only main service.
- Hive Build UI polls background jobs and renders the completed Hive run, including explicit build-failed status.

## Verification

The archive suite passes 35 tests with two warnings; Python compilation and frontend JavaScript parsing also pass.
