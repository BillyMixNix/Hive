package dev.atmcompanion.state;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class ObservationTest {
    @Test
    void observedEmptyInventoryRemainsKnownAndEmpty() {
        Observation<List<String>> observation = Observation.available(List.of());

        assertEquals(CapabilityStatus.AVAILABLE, observation.status());
        assertNotNull(observation.data());
        assertTrue(observation.data().isEmpty());
    }

    @Test
    void unavailableIsNotAnObservedEmptyCollection() {
        Observation<List<String>> observation = Observation.unavailable("Player is not available");

        assertEquals(CapabilityStatus.UNAVAILABLE, observation.status());
        assertNull(observation.data());
        assertEquals("Player is not available", observation.detail());
        assertNotEquals(Observation.available(List.of()), observation);
    }

    @Test
    void notIntegratedIsSeparateFromUnavailable() {
        Observation<List<String>> observation = Observation.notIntegrated("AE2 storage adapter is not implemented");

        assertEquals(CapabilityStatus.NOT_INTEGRATED, observation.status());
        assertNull(observation.data());
        assertNotEquals(Observation.unavailable("AE2 storage adapter is not implemented"), observation);
    }

    @Test
    void contradictoryObservationStatesAreRejected() {
        assertThrows(IllegalArgumentException.class, () ->
                new Observation<>(CapabilityStatus.AVAILABLE, null, "Known"));
        assertThrows(IllegalArgumentException.class, () ->
                new Observation<>(CapabilityStatus.UNAVAILABLE, List.of(), "Failed"));
        assertThrows(IllegalArgumentException.class, () ->
                new Observation<>(CapabilityStatus.NOT_INTEGRATED, List.of("minecraft:iron_ingot"), "Absent"));
    }
}
