package dev.atmcompanion.activity;

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class ActivityEventWithSourceAcceptanceTest {
    @Test void changesOnlySourceAndRejectsNull() {
        var original = new ActivityEvent(1, "2026-09-01T00:00:00Z", ActivityEvent.Type.ITEM_GAINED,
                List.of("minecraft:stone"), 3L, ActivityEvent.Source.GAME_EVENT);
        var changed = original.withSource(ActivityEvent.Source.MANUAL);
        assertNotSame(original, changed);
        assertEquals(original.schemaVersion(), changed.schemaVersion());
        assertEquals(original.timestamp(), changed.timestamp());
        assertEquals(original.type(), changed.type());
        assertEquals(original.registryIds(), changed.registryIds());
        assertEquals(original.quantity(), changed.quantity());
        assertEquals(ActivityEvent.Source.MANUAL, changed.source());
        assertEquals(ActivityEvent.Source.GAME_EVENT, original.source());
        assertThrows(IllegalArgumentException.class, () -> original.withSource(null));
    }
}
