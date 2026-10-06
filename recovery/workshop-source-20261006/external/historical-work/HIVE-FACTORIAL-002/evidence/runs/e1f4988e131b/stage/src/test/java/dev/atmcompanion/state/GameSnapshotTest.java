package dev.atmcompanion.state;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.stream.IntStream;

import static org.junit.jupiter.api.Assertions.*;

class GameSnapshotTest {
    @Test
    void collectionsAreDefensiveCopies() {
        var mutableItems = new ArrayList<GameSnapshot.Item>();
        mutableItems.add(new GameSnapshot.Item("minecraft:diamond", 7, 0, false));
        var inventory = new GameSnapshot.Inventory(mutableItems, 41, false);
        mutableItems.clear();
        assertEquals(1, inventory.stacks().size());
        assertThrows(UnsupportedOperationException.class, () -> inventory.stacks().clear());

        var snapshot = SnapshotFixtures.empty();
        var mutableCapabilities = new LinkedHashMap<>(snapshot.capabilities());
        var copied = SnapshotFixtures.withCapabilities(snapshot, mutableCapabilities);
        mutableCapabilities.clear();
        assertFalse(copied.capabilities().isEmpty());
        assertThrows(UnsupportedOperationException.class, () -> copied.capabilities().clear());
    }

    @Test
    void capabilityCannotContradictUnderlyingObservation() {
        var snapshot = SnapshotFixtures.empty();
        var capabilities = new LinkedHashMap<>(snapshot.capabilities());
        capabilities.put("inventory", new Capability(CapabilityStatus.UNAVAILABLE, "Not inspected"));
        assertThrows(IllegalArgumentException.class, () -> SnapshotFixtures.withCapabilities(snapshot, capabilities));
        capabilities.remove("inventory");
        assertThrows(IllegalArgumentException.class, () -> SnapshotFixtures.withCapabilities(snapshot, capabilities));
    }

    @Test
    void registryIdMustRemainNamespacedAndOccupiedStackMustHavePositiveCount() {
        assertEquals("example_mod:path/to.item-name", new GameSnapshot.Item("example_mod:path/to.item-name", 1, 0, false).item());
        for (String invalid : List.of("iron_ingot", "Minecraft:diamond", "minecraft:", "minecraft:with space")) {
            assertThrows(IllegalArgumentException.class, () -> new GameSnapshot.Item(invalid, 1, 0, false));
        }
        assertThrows(IllegalArgumentException.class, () -> new GameSnapshot.Item("minecraft:air", 0, 0, false));
        assertThrows(IllegalArgumentException.class, () -> new GameSnapshot.Item("minecraft:diamond", 1, -1, false));
    }

    @Test
    void inventoryModAndAdvancementCollectionsAreBounded() {
        var items = IntStream.range(0, GameSnapshot.MAX_INVENTORY_SLOTS + 1)
                .mapToObj(slot -> new GameSnapshot.Item("minecraft:stone", 64, slot, false)).toList();
        assertThrows(IllegalArgumentException.class, () -> new GameSnapshot.Inventory(items, items.size(), false));

        var mods = IntStream.range(0, GameSnapshot.MAX_MODS + 1)
                .mapToObj(i -> new GameSnapshot.Mod("mod" + i, "1.0")).toList();
        assertThrows(IllegalArgumentException.class, () -> new GameSnapshot.Modpack(mods, mods.size(), false));

        var advancements = IntStream.range(0, GameSnapshot.MAX_ADVANCEMENTS + 1)
                .mapToObj(i -> new GameSnapshot.Advancement("example:advancement_" + i, false, 0, 1)).toList();
        assertThrows(IllegalArgumentException.class, () -> new GameSnapshot.Progression(
                advancements.size(), 0, advancements.size(), false, advancements, false));
    }

    @Test
    void advancementCountsMustDescribeTheScannedDefinitions() {
        assertThrows(IllegalArgumentException.class, () -> new GameSnapshot.Progression(5, 2, 2, false, List.of(), true));
        assertThrows(IllegalArgumentException.class, () -> new GameSnapshot.Progression(
                GameSnapshot.MAX_ADVANCEMENTS_SCANNED + 1, 0, GameSnapshot.MAX_ADVANCEMENTS_SCANNED + 1, true, List.of(), true));
        assertThrows(IllegalArgumentException.class, () -> new GameSnapshot.Advancement("minecraft:story/root", false, 2, 1));
    }

    @Test
    void nonfiniteValuesCannotProduceInvalidJsonNumbers() {
        assertThrows(IllegalArgumentException.class, () -> new GameSnapshot.Player(Float.NaN, 20, 20, 2, 0, "survival"));
        assertThrows(IllegalArgumentException.class, () -> new GameSnapshot.Player(20, Float.POSITIVE_INFINITY, 20, 2, 0, "survival"));
        assertThrows(IllegalArgumentException.class, () -> new GameSnapshot.Location("minecraft:overworld", "minecraft:plains", Double.NaN, 64, 0));
    }
}
