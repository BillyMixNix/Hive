package dev.atmcompanion.activity;

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class ActivityUniqueIdsAcceptanceTest {
    private static ActivityEvent event(String id) {
        return new ActivityEvent(1, "2026-09-01T00:00:00Z", ActivityEvent.Type.ITEM_GAINED,
                List.of(id), 1L, ActivityEvent.Source.GAME_EVENT);
    }
    @Test void usesRetainedEventsOnlyAndReturnsDetachedSortedIds() {
        var history = new ActivityHistory(3);
        assertEquals(List.of(), history.uniqueRegistryIds());
        history.append(event("minecraft:evicted"));
        history.append(event("minecraft:zinc"));
        history.append(event("minecraft:apple"));
        history.append(event("minecraft:apple"));
        var ids = history.uniqueRegistryIds();
        assertEquals(List.of("minecraft:apple", "minecraft:zinc"), ids);
        assertThrows(UnsupportedOperationException.class, () -> ids.add("minecraft:stone"));
        history.clear();
        assertEquals(List.of("minecraft:apple", "minecraft:zinc"), ids);
        assertEquals(0, history.size());
    }
}
