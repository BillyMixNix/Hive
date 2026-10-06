package dev.atmcompanion.activity;

import org.junit.jupiter.api.Test;
import java.time.Instant;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class ActivityWindowAcceptanceTest {
    private ActivityEvent event(String timestamp, String id, long quantity) {
        return new ActivityEvent(1, timestamp, ActivityEvent.Type.ITEM_GAINED, List.of(id),
                quantity, ActivityEvent.Source.MANUAL);
    }

    @Test
    void returnsHalfOpenWindowWithMatchingSummaryWithoutMutatingHistory() {
        var history = new ActivityHistory(8);
        var before = event("2026-09-30T11:59:59Z", "minecraft:iron_ingot", 2);
        var start = event("2026-09-30T12:00:00Z", "minecraft:diamond", 3);
        var inside = event("2026-09-30T12:30:00Z", "minecraft:emerald", 4);
        var end = event("2026-10-01T00:00:00Z", "minecraft:gold_ingot", 5);
        history.append(before);
        history.append(start);
        history.append(inside);
        history.append(end);

        var window = history.between(Instant.parse("2026-09-30T12:00:00Z"), Instant.parse("2026-10-01T00:00:00Z"));
        assertEquals(List.of(start, inside), window.events());
        assertEquals(2, window.summary().eventCount());
        assertEquals(7L, window.summary().totalQuantity());
        assertThrows(UnsupportedOperationException.class, () -> window.events().clear());
        assertEquals(4, history.size());

        var empty = history.between(Instant.parse("2026-09-30T12:00:00Z"), Instant.parse("2026-09-30T12:00:00Z"));
        assertTrue(empty.events().isEmpty());
        assertEquals(0, empty.summary().eventCount());
        assertThrows(IllegalArgumentException.class,
                () -> history.between(Instant.parse("2026-10-01T00:00:00Z"), Instant.parse("2026-09-30T12:00:00Z")));
        assertThrows(IllegalArgumentException.class, () -> history.between(null, Instant.now()));
    }
}
