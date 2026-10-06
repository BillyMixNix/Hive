package dev.atmcompanion.activity;

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class ActivitySummaryCountAcceptanceTest {
    private ActivityEvent event(ActivityEvent.Type type, long quantity) {
        return new ActivityEvent(1, "2026-09-30T12:00:00Z", type, List.of("minecraft:diamond"),
                quantity, ActivityEvent.Source.MANUAL);
    }

    @Test
    void returnsExactTypeCountsIncludingZeroAndRejectsNull() {
        var summary = ActivitySummary.from(List.of(
                event(ActivityEvent.Type.ITEM_GAINED, 2),
                event(ActivityEvent.Type.ITEM_GAINED, 1),
                event(ActivityEvent.Type.ITEM_LOST, 4)));

        assertEquals(2, summary.count(ActivityEvent.Type.ITEM_GAINED));
        assertEquals(1, summary.count(ActivityEvent.Type.ITEM_LOST));
        for (var type : ActivityEvent.Type.values()) {
            int expected = type == ActivityEvent.Type.ITEM_GAINED ? 2
                    : type == ActivityEvent.Type.ITEM_LOST ? 1 : 0;
            assertEquals(expected, summary.count(type), "count for " + type);
        }
        assertThrows(IllegalArgumentException.class, () -> summary.count(null));
    }
}
