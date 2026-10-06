package dev.atmcompanion.activity;

import org.junit.jupiter.api.Test;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

class ActivityHistorySummaryAcceptanceTest {
    private ActivityEvent event(ActivityEvent.Type type, Long quantity, String id) {
        return new ActivityEvent(1, "2026-09-30T12:00:00Z", type, List.of(id),
                quantity, ActivityEvent.Source.MANUAL);
    }

    @Test
    void historySummaryContainsPerTypeQuantitiesAndIsADetachedImmutableSnapshot() {
        var history = new ActivityHistory(4);
        history.append(event(ActivityEvent.Type.ITEM_GAINED, 3L, "minecraft:diamond"));
        history.append(event(ActivityEvent.Type.ITEM_LOST, 1L, "minecraft:iron_ingot"));
        history.append(event(ActivityEvent.Type.DIMENSION_CHANGED, null, "minecraft:stone"));

        var summary = history.summary();
        assertEquals(3, summary.eventCount());
        assertEquals(4L, summary.totalQuantity());
        assertEquals(3L, summary.quantitiesByType().get(ActivityEvent.Type.ITEM_GAINED));
        assertEquals(1L, summary.quantitiesByType().get(ActivityEvent.Type.ITEM_LOST));
        assertEquals(0L, summary.quantitiesByType().get(ActivityEvent.Type.DIMENSION_CHANGED));
        for (var type : ActivityEvent.Type.values()) {
            assertNotNull(summary.counts().get(type));
            assertNotNull(summary.quantitiesByType().get(type));
        }
        assertThrows(UnsupportedOperationException.class, () -> summary.quantitiesByType().clear());

        history.append(event(ActivityEvent.Type.ITEM_GAINED, 8L, "minecraft:emerald"));
        assertEquals(3, summary.eventCount());
        assertEquals(4L, summary.totalQuantity());

        var legacyConstructor = new ActivitySummary(0, 0L, Map.of());
        assertTrue(legacyConstructor.counts().isEmpty());
    }
}
