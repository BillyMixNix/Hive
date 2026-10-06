package dev.atmcompanion.activity;

import java.time.Instant;
import java.util.List;
import java.util.Objects;

public record ActivityEvent(int schemaVersion, String timestamp, Type type,
                           List<String> registryIds, Long quantity, Source source) {
    public static final int SCHEMA_VERSION = 1;
    public static final int MAX_REGISTRY_IDS = 16;
    public static final int MAX_REGISTRY_ID_LENGTH = 256;
    public static final int MAX_TIMESTAMP_LENGTH = 64;
    public static final long MAX_QUANTITY = 1_000_000L;

    public ActivityEvent {
        if (schemaVersion != SCHEMA_VERSION) throw new IllegalArgumentException("Unsupported schema version " + schemaVersion);
        if (timestamp == null) throw new NullPointerException("timestamp must be non-null");
        if (timestamp.length() > MAX_TIMESTAMP_LENGTH) throw new IllegalArgumentException("timestamp too long: " + timestamp.length());
        Instant.parse(Objects.requireNonNull(timestamp));
        if (type == null) throw new NullPointerException("type must be non-null");
        if (registryIds == null) throw new NullPointerException("registryIds must be non-null");
        if (registryIds.size() > MAX_REGISTRY_IDS) throw new IllegalArgumentException("registryIds exceeds max size: " + registryIds.size());
        for (String id : registryIds) {
            if (id == null) throw new NullPointerException("registryIds contains null");
            if (id.length() > MAX_REGISTRY_ID_LENGTH) throw new IllegalArgumentException("registryId too long: " + id.length());
            if (!id.matches("[a-z0-9_.-]+:[a-z0-9/._-]+")) throw new IllegalArgumentException("Invalid registry ID: " + id);
        }
        if (source == null) throw new NullPointerException("source must be non-null");
        registryIds = List.copyOf(registryIds);
        if (quantity != null) {
            if (quantity < 1 || quantity > MAX_QUANTITY) {
                throw new IllegalArgumentException("quantity out of range: " + quantity);
            }
        }
    }

    public enum Type { ITEM_GAINED, ITEM_LOST, ITEM_CRAFTED, BLOCK_BROKEN, DIMENSION_CHANGED }

    public enum Source { GAME_EVENT, SNAPSHOT_DIFF, MANUAL }
}
