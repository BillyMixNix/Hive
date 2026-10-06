package dev.atmcompanion.activity;

import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

public final class ActivityDiffService {
    private ActivityDiffService() {}

    public static List<ActivityEvent> diff(String timestamp, Map<String, Long> before, Map<String, Long> after) {
        if (before == null || after == null) throw new IllegalArgumentException("Both before and after maps must be provided");
        validateRegistryIds(before.keySet());
        validateRegistryIds(after.keySet());
        List<ActivityEvent> events = new ArrayList<>();
        Set<String> commonIds = new HashSet<>(before.keySet());
        commonIds.retainAll(after.keySet());
        for (String id : commonIds) {
            long delta = after.get(id) - before.get(id);
            if (delta > 0) events.add(createEvent(timestamp, id, delta, ActivityEvent.Type.ITEM_GAINED));
            else if (delta < 0) events.add(createEvent(timestamp, id, Math.abs(delta), ActivityEvent.Type.ITEM_LOST));
        }
        for (String id : before.keySet()) if (!commonIds.contains(id)) events.add(createEvent(timestamp, id, before.get(id), ActivityEvent.Type.ITEM_LOST));
        for (String id : after.keySet()) if (!commonIds.contains(id)) events.add(createEvent(timestamp, id, after.get(id), ActivityEvent.Type.ITEM_GAINED));
        events.sort((a, b) -> a.registryIds().get(0).compareTo(b.registryIds().get(0)));
        return Collections.unmodifiableList(events);
    }

    private static void validateRegistryIds(Collection<String> ids) {
        for (String id : ids) {
            if (id == null || id.length() > ActivityEvent.MAX_REGISTRY_ID_LENGTH || !id.matches("[a-z0-9_.-]+:[a-z0-9/._-]+")) {
                throw new IllegalArgumentException("Invalid registry ID: " + id);
            }
        }
    }

    private static ActivityEvent createEvent(String timestamp, String id, long quantity, ActivityEvent.Type type) {
        if (quantity < 1 || quantity > ActivityEvent.MAX_QUANTITY) throw new IllegalArgumentException("Quantity out of range: " + quantity);
        return new ActivityEvent(ActivityEvent.SCHEMA_VERSION, timestamp, type, List.of(id), quantity, ActivityEvent.Source.SNAPSHOT_DIFF);
    }
}
