package dev.atmcompanion.activity;

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class ActivityHistoryRecentLimitAcceptanceTest {
    private ActivityEvent event(String path) {
        return new ActivityEvent(1, "2026-09-30T12:00:00Z", ActivityEvent.Type.ITEM_GAINED,
                List.of(path), 1L, ActivityEvent.Source.MANUAL);
    }

    @Test
    void returnsNewestBoundedSliceInOrderWithoutChangingHistory() {
        var history = new ActivityHistory(3);
        history.append(event("minecraft:a"));
        history.append(event("minecraft:b"));
        history.append(event("minecraft:c"));
        history.append(event("minecraft:d"));

        var expected = List.of(event("minecraft:c"), event("minecraft:d"));
        var result = history.recent(2);
        assertEquals(expected, result);
        assertEquals(List.of(event("minecraft:b"), event("minecraft:c"), event("minecraft:d")), history.recent());
        assertEquals(3, history.size());
        assertThrows(UnsupportedOperationException.class, () -> result.clear());
        assertThrows(IllegalArgumentException.class, () -> history.recent(0));
        assertThrows(IllegalArgumentException.class, () -> history.recent(4));
    }
}
