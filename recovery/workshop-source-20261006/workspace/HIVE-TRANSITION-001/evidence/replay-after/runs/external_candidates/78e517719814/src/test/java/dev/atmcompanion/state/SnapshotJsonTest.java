package dev.atmcompanion.state;

import com.google.gson.JsonParser;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;

import static org.junit.jupiter.api.Assertions.*;

class SnapshotJsonTest {
    @Test
    void populatedSnapshotRoundTripsWithoutChangingRegistryIds() {
        var snapshot = SnapshotFixtures.populated();
        var json = SnapshotJson.toJson(snapshot);
        var result = SnapshotJson.fromJson(json);

        assertEquals(snapshot, result);
        assertEquals("mekanism:ingot_osmium", result.inventory().data().stacks().get(1).item());
        assertEquals("example_mod:tools/custom_pickaxe", result.inventory().data().stacks().get(2).item());
        assertTrue(result.inventory().data().stacks().get(2).hasNonDefaultComponents());
        assertTrue(JsonParser.parseString(json).isJsonObject());
        assertTrue(json.getBytes(StandardCharsets.UTF_8).length < SnapshotJson.MAX_JSON_BYTES);
    }

    @Test
    void emptyInventoryAndInspectedEmptyEquipmentRoundTripAsAvailable() {
        var result = SnapshotJson.fromJson(SnapshotJson.toJson(SnapshotFixtures.empty()));

        assertEquals(CapabilityStatus.AVAILABLE, result.inventory().status());
        assertTrue(result.inventory().data().stacks().isEmpty());
        assertEquals(CapabilityStatus.AVAILABLE, result.equipment().status());
        assertNotNull(result.equipment().data());
        assertNull(result.equipment().data().mainHand());
    }

    @Test
    void unavailableInventorySerializesAsNullRatherThanEmptyKnownInventory() {
        var snapshot = SnapshotFixtures.unavailable();
        String json = SnapshotJson.toJson(snapshot);
        var inventory = JsonParser.parseString(json).getAsJsonObject().getAsJsonObject("inventory");

        assertEquals("unavailable", inventory.get("status").getAsString());
        assertTrue(inventory.get("data").isJsonNull());
        assertEquals(snapshot, SnapshotJson.fromJson(json));
    }

    @Test
    void nonIntegratedStatusAndCompletedVsIncompleteAdvancementsArePreserved() {
        var snapshot = SnapshotJson.fromJson(SnapshotJson.toJson(SnapshotFixtures.populated()));

        assertEquals(CapabilityStatus.NOT_INTEGRATED, snapshot.capabilities().get("quests").status());
        assertTrue(snapshot.progression().data().advancements().getFirst().completed());
        assertFalse(snapshot.progression().data().advancements().getLast().completed());
        assertEquals(1, snapshot.progression().data().completed());
        assertEquals(1, snapshot.progression().data().incomplete());
    }

    @Test
    void malformedMissingAndUnsupportedSchemaDataCannotBecomeSnapshots() {
        for (String json : new String[]{"null", "[]", "{", "{}", "{\"schemaVersion\":2}",
                SnapshotJson.toJson(SnapshotFixtures.empty()).replace("\"schemaVersion\": 1", "\"schemaVersion\": 2")}) {
            assertThrows(RuntimeException.class, () -> SnapshotJson.fromJson(json), json);
        }
    }

    @Test
    void deserializationCannotBypassObservationOrCapabilityInvariants() {
        String json = SnapshotJson.toJson(SnapshotFixtures.populated());
        var root = JsonParser.parseString(json).getAsJsonObject();
        root.getAsJsonObject("inventory").addProperty("status", "unavailable");
        assertThrows(RuntimeException.class, () -> SnapshotJson.fromJson(root.toString()));

        var contradictoryCapabilities = JsonParser.parseString(json).getAsJsonObject();
        contradictoryCapabilities.getAsJsonObject("capabilities").getAsJsonObject("inventory")
                .addProperty("status", "not_integrated");
        assertThrows(RuntimeException.class, () -> SnapshotJson.fromJson(contradictoryCapabilities.toString()));
    }

    @Test
    void serializationAndDeserializationEnforceUtf8ByteLimit() {
        String multibyte = "€".repeat(SnapshotJson.MAX_JSON_BYTES / 3 + 1);
        assertTrue(multibyte.length() < SnapshotJson.MAX_JSON_BYTES);
        assertTrue(multibyte.getBytes(StandardCharsets.UTF_8).length > SnapshotJson.MAX_JSON_BYTES);
        assertThrows(IllegalArgumentException.class, () -> SnapshotJson.fromJson(multibyte));

        var snapshot = SnapshotFixtures.empty();
        var capabilities = new LinkedHashMap<>(snapshot.capabilities());
        capabilities.put("example", new Capability(CapabilityStatus.UNAVAILABLE, multibyte));
        var oversized = SnapshotFixtures.withCapabilities(snapshot, capabilities);
        assertThrows(IllegalArgumentException.class, () -> SnapshotJson.toJson(oversized));
    }
}
