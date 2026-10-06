package dev.atmcompanion.integration;

import dev.atmcompanion.state.Capability;
import dev.atmcompanion.state.CapabilityStatus;
import org.junit.jupiter.api.Test;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;
import static org.junit.jupiter.api.Assertions.*;

class IntegrationSelectedAcceptanceTest {
    @Test void skipsUnselectedFactoriesAndRejectsBadRequestsBeforeInspection() {
        var inspected = new AtomicInteger();
        var registry = new IntegrationRegistry(mod -> { inspected.incrementAndGet(); return true; }, message -> fail(message));
        registry.register("selected", "example", () -> new Integration() {
            public boolean isAvailable() { return true; }
            public Map<String, Capability> capabilities() {
                return Map.of("selected", new Capability(CapabilityStatus.AVAILABLE, "observed"));
            }
        });
        registry.register("skipped", "example", () -> { throw new AssertionError("unselected factory executed"); });
        assertThrows(IllegalArgumentException.class, () -> registry.inspectSelected(Set.of("unknown")));
        assertThrows(IllegalArgumentException.class, () -> registry.inspectSelected(null));
        var withNull = new java.util.HashSet<String>();
        withNull.add("selected");
        withNull.add(null);
        assertThrows(IllegalArgumentException.class, () -> registry.inspectSelected(withNull));
        assertEquals(0, inspected.get());
        var selected = registry.inspectSelected(Set.of("selected"));
        assertEquals(Set.of("selected"), selected.keySet());
        assertEquals(CapabilityStatus.AVAILABLE, selected.get("selected").status());
        assertEquals(1, inspected.get());
        assertThrows(UnsupportedOperationException.class, () -> selected.clear());
    }
}
