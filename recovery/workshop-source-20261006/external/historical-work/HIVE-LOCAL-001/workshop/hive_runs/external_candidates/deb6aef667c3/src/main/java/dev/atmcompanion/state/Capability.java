package dev.atmcompanion.state;

import java.util.Objects;

public record Capability(CapabilityStatus status, String detail) {
    public Capability {
        Objects.requireNonNull(status, "status");
        Objects.requireNonNull(detail, "detail");
    }
    public static Capability from(Observation<?> observation) {
        return new Capability(observation.status(), observation.detail());
    }
}
