package dev.atmcompanion.activity;

import com.google.gson.Gson;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class ActivityEventTest {
    private static final String TIMESTAMP = "2026-09-23T12:34:56.123456789Z";

    @Test
    void validatesAndCopiesTheEvent() {
        List<String> ids = new ArrayList<>(List.of("minecraft:diamond", "mekanism:ingot_osmium"));
        ActivityEvent event = new ActivityEvent(1, TIMESTAMP, ActivityEvent.Type.ITEM_GAINED, ids, 4L,
                ActivityEvent.Source.GAME_EVENT);
        ids.clear();
        assertEquals(List.of("minecraft:diamond", "mekanism:ingot_osmium"), event.registryIds());
        assertThrows(UnsupportedOperationException.class, () -> event.registryIds().add("minecraft:stick"));
    }

    @Test
    void rejectsInvalidBoundsAndPreservesUnknownQuantity() {
        assertDoesNotThrow(() -> new ActivityEvent(1, TIMESTAMP, ActivityEvent.Type.ITEM_GAINED,
                List.of(), null, ActivityEvent.Source.MANUAL));
        assertThrows(RuntimeException.class, () -> new ActivityEvent(1, TIMESTAMP, ActivityEvent.Type.ITEM_GAINED,
                List.of(), 0L, ActivityEvent.Source.MANUAL));
        assertThrows(RuntimeException.class, () -> new ActivityEvent(1, TIMESTAMP, ActivityEvent.Type.ITEM_GAINED,
                List.of(), ActivityEvent.MAX_QUANTITY + 1, ActivityEvent.Source.MANUAL));
        assertThrows(RuntimeException.class, () -> new ActivityEvent(1, "not-an-instant", ActivityEvent.Type.ITEM_GAINED,
                List.of(), null, ActivityEvent.Source.MANUAL));
    }

    @Test
    void gsonRoundTripRunsConstructorValidation() {
        Gson gson = new Gson();
        ActivityEvent original = new ActivityEvent(1, TIMESTAMP, ActivityEvent.Type.ITEM_CRAFTED,
                List.of("minecraft:diamond_pickaxe"), 1L, ActivityEvent.Source.SNAPSHOT_DIFF);
        assertEquals(original, gson.fromJson(gson.toJson(original), ActivityEvent.class));
        String invalid = gson.toJson(original).replace("\"quantity\":1", "\"quantity\":0");
        assertThrows(RuntimeException.class, () -> gson.fromJson(invalid, ActivityEvent.class));
    }
}
