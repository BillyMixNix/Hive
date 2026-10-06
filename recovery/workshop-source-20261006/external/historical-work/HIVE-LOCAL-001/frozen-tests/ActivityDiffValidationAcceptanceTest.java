package dev.atmcompanion.activity;

import org.junit.jupiter.api.Test;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

class ActivityDiffValidationAcceptanceTest {
    private static final String T = "2026-09-30T12:00:00Z";

    @Test
    void validatesAllValuesBeforeDiffAndPreservesLongPrecision() {
        String id = "minecraft:diamond";
        assertThrows(IllegalArgumentException.class,
                () -> ActivityDiffService.diff(T, Map.of(id, -4L), Map.of(id, -4L)));

        var nullValue = new HashMap<String, Long>();
        nullValue.put(id, null);
        assertThrows(IllegalArgumentException.class,
                () -> ActivityDiffService.diff(T, nullValue, Map.of(id, 1L)));
        assertThrows(IllegalArgumentException.class,
                () -> ActivityDiffService.diff(T, Map.of(id, 1L), Map.of(id, -1L)));

        var delta = ActivityDiffService.diff(T,
                Map.of(id, 3_000_000_000L), Map.of(id, 3_000_000_007L));
        assertEquals(1, delta.size());
        assertEquals(ActivityEvent.Type.ITEM_GAINED, delta.getFirst().type());
        assertEquals(7L, delta.getFirst().quantity());

        var removed = ActivityDiffService.diff(T, Map.of(id, 7L), Map.of());
        assertEquals(1, removed.size());
        assertEquals(ActivityEvent.Type.ITEM_LOST, removed.getFirst().type());
        assertEquals(7L, removed.getFirst().quantity());
        var added = ActivityDiffService.diff(T, Map.of(), Map.of(id, 8L));
        assertEquals(1, added.size());
        assertEquals(ActivityEvent.Type.ITEM_GAINED, added.getFirst().type());
        assertEquals(8L, added.getFirst().quantity());

        assertThrows(IllegalArgumentException.class,
                () -> ActivityDiffService.diff(T, Map.of(id, 0L),
                        Map.of(id, ActivityEvent.MAX_QUANTITY + 1)));
    }
}
