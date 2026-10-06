package dev.atmcompanion.activity;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class ActivityCommandServiceResetTest {
    @Test
    void resetForgetsOnlyTheNamedPlayersActivityAndReturnsBoundedConfirmation() {
        LiveActivityService live = new LiveActivityService();
        ActivityCommandService commands = new ActivityCommandService(live);
        live.observe("Alex", "2026-09-24T00:00:00Z", Map.of("minecraft:stone", 1L));
        live.observe("Steve", "2026-09-24T00:00:00Z", Map.of("minecraft:dirt", 1L));

        assertEquals("Activity history reset for Alex.", commands.reset("Alex"));
        assertEquals(1, live.trackedPlayers());
    }

    @Test
    void resetRejectsBlankPlayerIdentity() {
        ActivityCommandService commands = new ActivityCommandService(new LiveActivityService());
        org.junit.jupiter.api.Assertions.assertThrows(IllegalArgumentException.class, () -> commands.reset(" "));
    }
}
