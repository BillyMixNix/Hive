package dev.atmcompanion.integration;

import dev.atmcompanion.state.Capability;
import dev.atmcompanion.state.CapabilityStatus;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.function.Consumer;
import java.util.function.Predicate;
import java.util.function.Supplier;

/** Factories are evaluated only after the required mod is present. No optional mod classes are referenced here. */
public final class IntegrationRegistry {
    private final Predicate<String> loadedMod;
    private final Consumer<String> diagnostics;
    private final Map<String, Registration> registrations = new LinkedHashMap<>();
    public IntegrationRegistry(Predicate<String> loadedMod, Consumer<String> diagnostics) {
        this.loadedMod = Objects.requireNonNull(loadedMod);
        this.diagnostics = Objects.requireNonNull(diagnostics);
    }
    public void register(String capability, String requiredMod, Supplier<Integration> factory) {
        if (registrations.size() >= 32) throw new IllegalArgumentException("Integration registration limit reached");
        if (registrations.putIfAbsent(Objects.requireNonNull(capability), new Registration(Objects.requireNonNull(requiredMod), Objects.requireNonNull(factory))) != null) {
            throw new IllegalArgumentException("Duplicate capability " + capability);
        }
    }
    public Map<String, Capability> inspect() {
        Map<String, Capability> result = new LinkedHashMap<>();
        registrations.forEach((capability, registration) -> {
            try {
                if (!loadedMod.test(registration.requiredMod)) {
                    result.put(capability, new Capability(CapabilityStatus.UNAVAILABLE, "Required mod is absent: " + registration.requiredMod));
                    return;
                }
                Integration adapter = registration.factory.get();
                Capability observed = adapter.isAvailable() ? adapter.capabilities().get(capability) : null;
                result.put(capability, observed == null ? new Capability(CapabilityStatus.UNAVAILABLE, "Adapter does not support the running API") : observed);
            } catch (RuntimeException | LinkageError exception) {
                diagnostics.accept("Integration " + capability + " unavailable: " + exception.getClass().getSimpleName() + ": " + exception.getMessage());
                result.put(capability, new Capability(CapabilityStatus.UNAVAILABLE, "Adapter failed: " + exception.getClass().getSimpleName() + "; see server log"));
            }
        });
        return Map.copyOf(result);
    }
    private record Registration(String requiredMod, Supplier<Integration> factory) {}
}
