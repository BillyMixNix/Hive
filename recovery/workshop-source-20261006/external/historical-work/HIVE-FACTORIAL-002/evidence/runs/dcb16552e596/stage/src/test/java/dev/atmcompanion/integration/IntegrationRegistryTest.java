package dev.atmcompanion.integration;

import dev.atmcompanion.state.Capability;
import dev.atmcompanion.state.CapabilityStatus;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.junit.jupiter.api.Assertions.*;

class IntegrationRegistryTest {
    @Test
    void absentModDoesNotConstructOrLoadItsAdapter() {
        var constructed = new AtomicBoolean();
        var registry = new IntegrationRegistry(mod -> false, message -> fail(message));
        registry.register("ae2_storage", "ae2", () -> {
            constructed.set(true);
            throw new AssertionError("Absent adapter must never load");
        });

        var result = registry.inspect();

        assertFalse(constructed.get());
        assertEquals(CapabilityStatus.UNAVAILABLE, result.get("ae2_storage").status());
        assertTrue(result.get("ae2_storage").detail().contains("absent"));
    }

    @Test
    void runtimeAndLinkageFailuresDoNotHideHealthyIntegrations() {
        var diagnostics = new ArrayList<String>();
        var registry = new IntegrationRegistry(mod -> true, diagnostics::add);
        registry.register("runtime_failure", "example", () -> { throw new IllegalStateException("Unsupported API version"); });
        registry.register("linkage_failure", "example", () -> { throw new NoClassDefFoundError("OptionalApiClass"); });
        registry.register("healthy", "example", () -> adapter("healthy"));

        var result = registry.inspect();

        assertEquals(CapabilityStatus.UNAVAILABLE, result.get("runtime_failure").status());
        assertEquals(CapabilityStatus.UNAVAILABLE, result.get("linkage_failure").status());
        assertEquals(CapabilityStatus.AVAILABLE, result.get("healthy").status());
        assertEquals(2, diagnostics.size());
        assertTrue(diagnostics.stream().anyMatch(line -> line.contains("runtime_failure") && line.contains("Unsupported API version")));
        assertTrue(diagnostics.stream().anyMatch(line -> line.contains("linkage_failure") && line.contains("NoClassDefFoundError")));
    }

    @Test
    void unsupportedAdapterIsNotAskedForState() {
        var registry = new IntegrationRegistry(mod -> true, message -> fail(message));
        registry.register("quests", "ftbquests", () -> new Integration() {
            @Override public boolean isAvailable() { return false; }
            @Override public Map<String, Capability> capabilities() { throw new AssertionError("Unsupported adapter inspected"); }
        });

        assertEquals(CapabilityStatus.UNAVAILABLE, registry.inspect().get("quests").status());
    }

    @Test
    void absentCapabilityIsUnknownRatherThanAvailable() {
        var registry = new IntegrationRegistry(mod -> true, message -> fail(message));
        registry.register("quests", "ftbquests", () -> adapter("different_capability"));

        assertEquals(CapabilityStatus.UNAVAILABLE, registry.inspect().get("quests").status());
    }

    @Test
    void failureInsideCapabilityInspectionIsContainedAndLogged() {
        var diagnostics = new ArrayList<String>();
        var registry = new IntegrationRegistry(mod -> true, diagnostics::add);
        registry.register("quests", "ftbquests", () -> new Integration() {
            @Override public boolean isAvailable() { return true; }
            @Override public Map<String, Capability> capabilities() { throw new UnsupportedOperationException("API changed"); }
        });

        assertEquals(CapabilityStatus.UNAVAILABLE, registry.inspect().get("quests").status());
        assertEquals(1, diagnostics.size());
    }

    @Test
    void registrationsAreBoundedAndDuplicateCapabilitiesAreRejected() {
        var registry = new IntegrationRegistry(mod -> true, message -> {});
        registry.register("first", "example", () -> adapter("first"));
        assertThrows(IllegalArgumentException.class, () -> registry.register("first", "other", () -> adapter("first")));
        for (int i = 1; i < 32; i++) {
            String key = "capability" + i;
            registry.register(key, "example", () -> adapter(key));
        }
        assertThrows(IllegalArgumentException.class, () -> registry.register("overflow", "example", () -> adapter("overflow")));
        assertEquals(32, registry.inspect().size());
        assertThrows(UnsupportedOperationException.class, () -> registry.inspect().clear());
    }

    private static Integration adapter(String capability) {
        return new Integration() {
            @Override public boolean isAvailable() { return true; }
            @Override public Map<String, Capability> capabilities() {
                return Map.of(capability, new Capability(CapabilityStatus.AVAILABLE, "Observed by test adapter"));
            }
        };
    }
}
