package dev.atmcompanion.state;

import java.util.Objects;

/** Unknown data is always null; a known empty collection is a different observation. */
public record Observation<T>(CapabilityStatus status, T data, String detail) {
    public Observation {
        Objects.requireNonNull(status, "status");
        Objects.requireNonNull(detail, "detail");
        if ((status == CapabilityStatus.AVAILABLE) != (data != null)) {
            throw new IllegalArgumentException("Only available observations may contain data");
        }
    }
    public static <T> Observation<T> available(T data) {
        return new Observation<>(CapabilityStatus.AVAILABLE, Objects.requireNonNull(data), "Observed from the running server");
    }
    public static <T> Observation<T> unavailable(String reason) {
        return new Observation<>(CapabilityStatus.UNAVAILABLE, null, reason);
    }
    public static <T> Observation<T> notIntegrated(String reason) {
        return new Observation<>(CapabilityStatus.NOT_INTEGRATED, null, reason);
    }

    public <U> Observation<U> map(java.util.function.Function<? super T, ? extends U> mapper) {
        if (mapper == null || this.status != CapabilityStatus.AVAILABLE || this.data == null) {
            throw new IllegalArgumentException("Mapper cannot be null and observation must be available with non-null data");
        }
        U mappedData = mapper.apply(this.data);
        if (mappedData == null) {
            throw new IllegalArgumentException("Mapped data cannot be null");
        }
        return new Observation<>(this.status, mappedData, this.detail);
    }
        return new Observation<>(CapabilityStatus.NOT_INTEGRATED, null, reason);
    }
}
