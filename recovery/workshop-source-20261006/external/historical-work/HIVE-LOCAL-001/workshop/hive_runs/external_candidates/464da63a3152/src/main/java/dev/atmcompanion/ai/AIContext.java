package dev.atmcompanion.ai;

import java.util.Map;

/** Future allowlisted context only. No exporter, external client, credentials, or automatic raw-state conversion exists in M1. */
public record AIContext(int schemaVersion, Map<String, String> explicitlySelectedFacts) {
    public AIContext { explicitlySelectedFacts = Map.copyOf(explicitlySelectedFacts); }
}
