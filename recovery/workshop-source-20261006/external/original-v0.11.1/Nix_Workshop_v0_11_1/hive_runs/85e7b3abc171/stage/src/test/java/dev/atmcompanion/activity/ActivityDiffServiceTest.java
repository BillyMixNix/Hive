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

    @Test void invalidBeforeCountsAreRejectedAlongsideValidChanges() {
        for (Long invalid : new Long[] {null, -1L}) {
            var before = new HashMap<>(Map.of("minecraft:iron_ingot", 2L));
            before.put("minecraft:diamond", invalid);
            var after = Map.of("minecraft:diamond", 0L, "minecraft:iron_ingot", 5L);
            assertThrows(IllegalArgumentException.class,
                    () -> ActivityDiffService.diff(T, before, after),
                    "Invalid before count on a shared key: " + invalid);
            assertThrows(IllegalArgumentException.class,
                    () -> ActivityDiffService.diff(T, before, Map.of("minecraft:iron_ingot", 5L)),
                    "Invalid before count on a removed key: " + invalid);
        }
    }

    @Test void invalidAfterCountsAreRejectedAlongsideValidChanges() {
        for (Long invalid : new Long[] {null, -1L}) {
            var before = Map.of("minecraft:diamond", 0L, "minecraft:iron_ingot", 5L);
            var after = new HashMap<>(Map.of("minecraft:iron_ingot", 2L));
            after.put("minecraft:diamond", invalid);
            assertThrows(IllegalArgumentException.class,
                    () -> ActivityDiffService.diff(T, before, after),
                    "Invalid after count on a shared key: " + invalid);
            assertThrows(IllegalArgumentException.class,
                    () -> ActivityDiffService.diff(T, Map.of("minecraft:iron_ingot", 5L), after),
                    "Invalid after count on an added key: " + invalid);
        }
    }

    @Test void equalNegativeCountsAreRejectedEvenWhenTheirDeltaIsZero() {
        var negative = Map.of("minecraft:diamond", -1L);
        assertThrows(IllegalArgumentException.class,
                () -> ActivityDiffService.diff(T, negative, negative));
        var before = Map.of("minecraft:diamond", -1L, "minecraft:iron_ingot", 2L);
        var after = Map.of("minecraft:diamond", -1L, "minecraft:iron_ingot", 5L);
        assertThrows(IllegalArgumentException.class,
                () -> ActivityDiffService.diff(T, before, after));
    }

    @Test void countsAboveIntegerMaxProduceSmallPositiveAndNegativeDeltas() {
        for (long count : new long[] {(1L << 32) - 1L, Long.MAX_VALUE - 3L}) {
            var before = Map.of("minecraft:diamond", count + 3L, "minecraft:iron_ingot", count);
            var after = Map.of("minecraft:diamond", count, "minecraft:iron_ingot", count + 3L);
            var events = ActivityDiffService.diff(T, before, after);
            assertEquals(2, events.size());
            assertEquals(List.of("minecraft:diamond"), events.get(0).registryIds());
            assertEquals(ActivityEvent.Type.ITEM_LOST, events.get(0).type());
            assertEquals(3L, events.get(0).quantity());
            assertEquals(List.of("minecraft:iron_ingot"), events.get(1).registryIds());
            assertEquals(ActivityEvent.Type.ITEM_GAINED, events.get(1).type());
            assertEquals(3L, events.get(1).quantity());
            assertTrue(ActivityDiffService.diff(T, before, before).isEmpty());
        }
    }

    @Test void missingKeysUseZeroForGainsAndLosses() {
        var events = ActivityDiffService.diff(T,
                Map.of("minecraft:diamond", 4L), Map.of("minecraft:iron_ingot", 7L));
        assertEquals(2, events.size());
        assertEquals(List.of("minecraft:diamond"), events.get(0).registryIds());
        assertEquals(ActivityEvent.Type.ITEM_LOST, events.get(0).type());
        assertEquals(4L, events.get(0).quantity());
        assertEquals(List.of("minecraft:iron_ingot"), events.get(1).registryIds());
        assertEquals(ActivityEvent.Type.ITEM_GAINED, events.get(1).type());
        assertEquals(7L, events.get(1).quantity());
    }

    @Test void maximumEventQuantityIsAcceptedAndOneOverIsRejectedInBothDirections() {
        assertEquals(1_000_000L, ActivityEvent.MAX_QUANTITY);
        for (Map<String, Long> before : List.of(
                Map.<String, Long>of(),
                Map.of("minecraft:diamond", (long) Integer.MAX_VALUE + 1L))) {
            long baseline = before.getOrDefault("minecraft:diamond", 0L);
            var atLimit = Map.of("minecraft:diamond", baseline + ActivityEvent.MAX_QUANTITY);
            var gained = ActivityDiffService.diff(T, before, atLimit);
            assertEquals(1, gained.size());
            assertEquals(List.of("minecraft:diamond"), gained.get(0).registryIds());
            assertEquals(ActivityEvent.Type.ITEM_GAINED, gained.get(0).type());
            assertEquals(ActivityEvent.MAX_QUANTITY, gained.get(0).quantity());
            var lost = ActivityDiffService.diff(T, atLimit, before);
            assertEquals(1, lost.size());
            assertEquals(List.of("minecraft:diamond"), lost.get(0).registryIds());
            assertEquals(ActivityEvent.Type.ITEM_LOST, lost.get(0).type());
            assertEquals(ActivityEvent.MAX_QUANTITY, lost.get(0).quantity());
            var overLimit = Map.of("minecraft:diamond", baseline + ActivityEvent.MAX_QUANTITY + 1L);
            assertThrows(IllegalArgumentException.class,
                    () -> ActivityDiffService.diff(T, before, overLimit));
            assertThrows(IllegalArgumentException.class,
                    () -> ActivityDiffService.diff(T, overLimit, before));
        }
    }

    @Test void outputIsImmutableAndInputMapsAreNotRetained() {
        var before = new HashMap<>(Map.of("minecraft:diamond", 1L));
        var events = ActivityDiffService.diff(T, before, Map.of("minecraft:diamond", 2L));
        before.put("minecraft:diamond", 99L);
        assertEquals(1L, events.get(0).quantity());
        assertThrows(UnsupportedOperationException.class, () -> events.add(null));
    }
}
