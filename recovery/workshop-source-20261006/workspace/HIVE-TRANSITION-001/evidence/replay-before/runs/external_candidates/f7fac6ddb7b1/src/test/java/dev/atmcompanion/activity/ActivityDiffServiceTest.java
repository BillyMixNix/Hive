package dev.atmcompanion.activity;

import org.junit.jupiter.api.Test;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

class ActivityDiffServiceTest {
    private static final String T = "2026-09-23T12:34:56.123456789Z";

    @Test void increaseAndDecreaseUsePositiveDeltas() {
        var before = Map.of("minecraft:diamond", 5L, "minecraft:iron_ingot", 2L);
        var after = Map.of("minecraft:diamond", 2L, "minecraft:iron_ingot", 5L);
        var events = ActivityDiffService.diff(T, before, after);
        assertEquals(List.of("minecraft:diamond"), events.get(0).registryIds());
        assertEquals(ActivityEvent.Type.ITEM_LOST, events.get(0).type());
        assertEquals(3L, events.get(0).quantity());
        assertEquals(ActivityEvent.Type.ITEM_GAINED, events.get(1).type());
        assertEquals(3L, events.get(1).quantity());
    }

    @Test void unchangedAndKnownEmptyProduceNoEvents() {
        assertTrue(ActivityDiffService.diff(T, Map.of("minecraft:diamond", 1L), Map.of("minecraft:diamond", 1L)).isEmpty());
        assertTrue(ActivityDiffService.diff(T, Map.of(), Map.of()).isEmpty());
    }

    @Test void unknownAndMalformedInputsAreRejected() {
        assertThrows(RuntimeException.class, () -> ActivityDiffService.diff(T, null, Map.of()));
        assertThrows(RuntimeException.class, () -> ActivityDiffService.diff(T, Map.of("minecraft:bad id", 1L), Map.of()));
        assertThrows(RuntimeException.class, () -> ActivityDiffService.diff(T, Map.of("minecraft:diamond", -1L), Map.of()));
    }

    @Test void outputIsImmutableAndInputMapsAreNotRetained() {
        var before = new HashMap<>(Map.of("minecraft:diamond", 1L));
        var events = ActivityDiffService.diff(T, before, Map.of("minecraft:diamond", 2L));
        before.put("minecraft:diamond", 99L);
        assertEquals(1L, events.get(0).quantity());
        assertThrows(UnsupportedOperationException.class, () -> events.add(null));
    }
}
