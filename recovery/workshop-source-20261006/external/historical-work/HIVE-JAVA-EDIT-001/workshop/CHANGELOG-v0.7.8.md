# Nix Workshop v0.7.8

## Bounded Worker Observation Loop

- Added a bounded worker `observe` protocol with a maximum of six requests per worker/run.
- Added deterministic, read-only `search_text`, `list_symbols`, `read_symbol`, `read_file_excerpt`, and `find_similar_code` operations.
- Kept observation/read authority separate from exact planned write ownership and strict edit validation.
- Added bounded observation trajectory records to Hive run artifacts without persisting unbounded prompts or source dumps.
- Added small planner-owned shared interface contracts and explicit teammate-dependency guidance.
- Preserved structural repair, replanning, staged verification, reviewer approval, rollback, and provider/budget behavior.
- Added adversarial coverage for budget exhaustion, path safety, read-only behavior, scope enforcement, structural repair, and shared contracts.
