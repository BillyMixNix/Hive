package dev.atmcompanion.activity;

import org.junit.jupiter.api.Test;
import java.util.HashMap;
import java.util.Map;
import static org.junit.jupiter.api.Assertions.*;

class ActivityTrackerTest {
    private static final String T = "2026-09-23T12:34:56Z";

    @Test void firstObservationIsBaselineAndSecondProducesDiff() {
        var tracker = new ActivityTracker();
        assertTrue(tracker.observe("p1", T, Map.of("minecraft:diamond", 2L)).isEmpty());
        var events = tracker.observe("p1", T, Map.of("minecraft:diamond", 5L));
        assertEquals(1, events.size());
        assertEquals(3L, events.get(0).quantity());
        assertEquals(ActivityEvent.Type.ITEM_GAINED, events.get(0).type());
    }

    @Test void successfulObservationAdvancesBaselineAndForgetResetsIt() {
        var tracker = new ActivityTracker();
        tracker.observe("p1", T, Map.of("minecraft:iron_ingot", 1L));
        assertTrue(tracker.observe("p1", T, Map.of("minecraft:iron_ingot", 1L)).isEmpty());
        tracker.forget("p1");
        assertTrue(tracker.observe("p1", T, Map.of("minecraft:iron_ingot", 9L)).isEmpty());
        assertEquals(1, tracker.trackedPlayers());
    }

    @Test void copiesInputAndRejectsNullsAndOverflow() {
        var tracker = new ActivityTracker();
        var inventory = new HashMap<>(Map.of("minecraft:diamond", 1L));
        tracker.observe("p1", T, inventory);
        inventory.put("minecraft:diamond", 99L);
        assertTrue(tracker.observe("p1", T, Map.of("minecraft:diamond", 1L)).isEmpty());
        assertThrows(RuntimeException.class, () -> tracker.observe(null, T, Map.of()));
        assertThrows(RuntimeException.class, () -> tracker.observe("p2", null, Map.of()));
        assertThrows(RuntimeException.class, () -> tracker.observe("p2", T, null));
        for (int i = 2; i <= 64; i++) tracker.observe("p" + i, T, Map.of());
        assertThrows(RuntimeException.class, () -> tracker.observe("p65", T, Map.of()));
    }
}
